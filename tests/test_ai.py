"""
Tests for AI modules: provider, prompts, batch, semantic analysis.

All tests use MockProvider — no GPU required.
"""

import json
import os
import tempfile

from kwb.ai.provider import AIMessage
from kwb.ai.mock import MockProvider
from kwb.ai.prompts import (
    prompt_classify_subject,
    prompt_describe_image,
    prompt_normalize_term,
    prompt_ocr_analysis,
)
from kwb.ai.batch import process_batch, _try_parse_json
from kwb.analyze.semantic import classify_subjects, describe_images
from kwb.ingest.image_loader import ImageProfile, ingest_image
from kwb.core.models import DatasetProfile, FindingCategory


# ---------------------------------------------------------------------------
# Provider tests
# ---------------------------------------------------------------------------

class TestMockProvider:
    def test_basic_completion(self):
        mock = MockProvider.with_defaults()
        resp = mock.complete([AIMessage.user("Hello")])
        assert resp.content is not None
        assert resp.model == "mock-model"

    def test_classify_rule(self):
        mock = MockProvider.with_defaults()
        resp = mock.complete([AIMessage.user("Classify this subject: Minarett")])
        parsed = json.loads(resp.content)
        assert "category" in parsed
        assert parsed["confidence"] > 0

    def test_vision_rule(self):
        mock = MockProvider.with_defaults()
        msg = AIMessage.user_with_image("Describe this", "AAAA", "image/jpeg")
        resp = mock.complete([msg])
        parsed = json.loads(resp.content)
        assert "description" in parsed
        assert "objects" in parsed

    def test_call_log(self):
        mock = MockProvider.with_defaults()
        mock.complete([AIMessage.user("test 1")])
        mock.complete([AIMessage.user("test 2")])
        assert len(mock.call_log) == 2

    def test_is_available(self):
        mock = MockProvider.with_defaults()
        assert mock.is_available() is True

    def test_list_models(self):
        mock = MockProvider.with_defaults()
        models = mock.list_models()
        assert len(models) > 0


# ---------------------------------------------------------------------------
# Prompt tests
# ---------------------------------------------------------------------------

class TestPrompts:
    def test_classify_subject_structure(self):
        msgs = prompt_classify_subject("Minarett; Stadtmauer")
        assert len(msgs) == 2
        assert msgs[0].role == "system"
        assert msgs[1].role == "user"
        assert "Minarett" in msgs[1].content

    def test_classify_with_context(self):
        msgs = prompt_classify_subject("Berge", context="Record dcb-001")
        assert "dcb-001" in msgs[1].content

    def test_describe_image_structure(self):
        msgs = prompt_describe_image(additional_context="test.jpg")
        assert len(msgs) == 2
        assert "JSON" in msgs[0].content

    def test_normalize_term(self):
        msgs = prompt_normalize_term("minarett", field_name="Architecture")
        assert "minarett" in msgs[1].content
        assert "Architecture" in msgs[1].content

    def test_ocr_analysis(self):
        msgs = prompt_ocr_analysis()
        assert len(msgs) == 2
        assert "transcription" in msgs[1].content


# ---------------------------------------------------------------------------
# Batch tests
# ---------------------------------------------------------------------------

class TestBatch:
    def test_basic_batch(self):
        mock = MockProvider.with_defaults()
        items = [
            {"record_id": "r1", "text": "Classify: Minarett"},
            {"record_id": "r2", "text": "Classify: Kirche"},
            {"record_id": "r3", "text": "Classify: Moschee"},
        ]

        def prompt_fn(item):
            return [AIMessage.user(item["text"])]

        report = process_batch(mock, items, prompt_fn)
        assert report.total == 3
        assert report.succeeded == 3
        assert report.failed == 0
        assert report.success_rate == 1.0

    def test_progress_callback(self):
        mock = MockProvider.with_defaults()
        progress_log = []

        def on_progress(current, total, result):
            progress_log.append((current, total, result.success))

        items = [{"record_id": f"r{i}"} for i in range(5)]
        report = process_batch(
            mock, items,
            prompt_fn=lambda item: [AIMessage.user("test")],
            on_progress=on_progress,
        )
        assert len(progress_log) == 5
        assert progress_log[-1][0] == 5

    def test_json_parsing(self):
        assert _try_parse_json('{"key": "value"}') == {"key": "value"}
        assert _try_parse_json('```json\n{"key": "value"}\n```') == {"key": "value"}
        assert _try_parse_json("not json") is None

    def test_batch_report_provenance_populated(self):
        """AI-BUG-02: BatchReport must record provider/model/prompt_fn so two
        runs are distinguishable."""
        mock = MockProvider.with_defaults()
        items = [{"record_id": "r1", "text": "Classify: Minarett"}]

        def my_prompt(item):
            return [AIMessage.user(item["text"])]

        report = process_batch(mock, items, my_prompt, model="mock-x")

        assert report.provider_name == "MockProvider"
        assert report.model == "mock-x"
        assert report.prompt_fn_name == "my_prompt"
        assert report.started_at is not None
        assert report.finished_at is not None
        assert report.finished_at >= report.started_at

    def test_batch_report_provenance_distinguishes_runs(self):
        """Two runs with different prompt functions produce distinguishable
        BatchReports."""
        mock = MockProvider.with_defaults()
        items = [{"record_id": "r1"}]

        def prompt_a(item):
            return [AIMessage.user("a")]

        def prompt_b(item):
            return [AIMessage.user("b")]

        rep_a = process_batch(mock, items, prompt_a, model="m1")
        rep_b = process_batch(mock, items, prompt_b, model="m2")

        assert rep_a.prompt_fn_name != rep_b.prompt_fn_name
        assert rep_a.model != rep_b.model

    def test_batch_failure_captures_exception_type(self):
        """AI-BUG-01: per-item failures must record error_type, not just
        the message — so curators can triage timeouts vs parse errors."""
        from kwb.ai.provider import ProviderConfig

        class FailingProvider(MockProvider):
            def complete(self, messages, model=None, **kwargs):
                raise ConnectionError("simulated network failure")

        provider = FailingProvider(ProviderConfig(base_url="mock://x"))
        items = [{"record_id": "r1"}, {"record_id": "r2"}]
        report = process_batch(
            provider, items, prompt_fn=lambda i: [AIMessage.user("test")]
        )

        assert report.failed == 2
        assert report.succeeded == 0
        for r in report.results:
            assert r.success is False
            assert r.error_type == "ConnectionError"
            assert "simulated network failure" in r.error

    def test_batch_continues_on_per_item_failure(self):
        """AI-BUG-01: a single failing item must not abort the batch."""
        from kwb.ai.provider import AIResponse, ProviderConfig

        class FlakyProvider(MockProvider):
            def __init__(self):
                super().__init__(ProviderConfig(base_url="mock://x"))
                self.calls = 0

            def complete(self, messages, model=None, **kwargs):
                self.calls += 1
                if self.calls == 2:
                    raise ValueError("flaky on second call")
                return AIResponse(
                    content='{"ok": true}',
                    model=model or "mock-model",
                    usage={},
                )

        provider = FlakyProvider()
        items = [{"record_id": f"r{i}"} for i in range(3)]
        report = process_batch(
            provider, items, prompt_fn=lambda i: [AIMessage.user("test")]
        )

        assert report.total == 3
        assert report.succeeded == 2
        assert report.failed == 1
        assert report.results[1].error_type == "ValueError"

    def test_batch_keyboard_interrupt_propagates(self):
        """AI-BUG-01: KeyboardInterrupt is BaseException, must NOT be caught.
        Operators must always be able to abort."""
        import pytest
        from kwb.ai.provider import ProviderConfig

        class AbortingProvider(MockProvider):
            def complete(self, messages, model=None, **kwargs):
                raise KeyboardInterrupt()

        provider = AbortingProvider(ProviderConfig(base_url="mock://x"))
        items = [{"record_id": "r1"}]

        with pytest.raises(KeyboardInterrupt):
            process_batch(
                provider, items, prompt_fn=lambda i: [AIMessage.user("test")]
            )

    def test_batch_parse_failure_tracking(self):
        """EXT-BUG-02: JSON parse failures must be tracked and visible."""
        from kwb.ai.provider import AIResponse, ProviderConfig

        class BadJsonProvider(MockProvider):
            def complete(self, messages, model=None, **kwargs):
                return AIResponse(
                    content="not valid json at all",
                    model=model or "mock-model",
                    usage={},
                )

        provider = BadJsonProvider(ProviderConfig(base_url="mock://x"))
        items = [
            {"record_id": "r1"},
            {"record_id": "r2"},
            {"record_id": "r3"},
        ]
        report = process_batch(
            provider, items, prompt_fn=lambda i: [AIMessage.user("test")]
        )

        assert report.total == 3
        assert report.succeeded == 3  # LLM calls succeeded
        assert len(report.parse_failures) == 3  # But parsing failed
        assert all(pf.raw_response == "not valid json at all" for pf in report.parse_failures)
        assert all(pf.error_message == "JSON parse failed" for pf in report.parse_failures)


# ---------------------------------------------------------------------------
# Image loader tests
# ---------------------------------------------------------------------------

class TestImageLoader:
    def test_ingest_jpeg(self):
        """Create a minimal valid JPEG and ingest it."""
        # Minimal JPEG: SOI + APP0 + minimal content + EOI
        # This is the smallest valid JPEG possible
        jpeg_bytes = bytes([
            0xFF, 0xD8,  # SOI
            0xFF, 0xE0,  # APP0
            0x00, 0x10,  # Length: 16
            0x4A, 0x46, 0x49, 0x46, 0x00,  # "JFIF\0"
            0x01, 0x01,  # Version
            0x00,        # Units
            0x00, 0x01,  # X density
            0x00, 0x01,  # Y density
            0x00, 0x00,  # Thumbnail
            0xFF, 0xC0,  # SOF0
            0x00, 0x0B,  # Length: 11
            0x08,        # Precision
            0x00, 0x01,  # Height: 1
            0x00, 0x01,  # Width: 1
            0x01,        # Components: 1
            0x01, 0x11, 0x00,  # Component info
            0xFF, 0xD9,  # EOI
        ])

        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
            f.write(jpeg_bytes)
            tmp_path = f.name

        try:
            profile = ingest_image(tmp_path)
            assert profile.mime_type == "image/jpeg"
            assert profile.file_size_bytes > 0
            assert profile.hash_sha256 != ""
            assert profile.base64_data != ""
            assert profile.width == 1
            assert profile.height == 1
        finally:
            os.unlink(tmp_path)

    def test_ingest_png(self):
        """Create a minimal valid PNG and ingest it."""
        import struct
        import zlib

        def _make_chunk(chunk_type, data):
            chunk = chunk_type + data
            return struct.pack(">I", len(data)) + chunk + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)

        ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 0, 0, 0, 0)
        raw_data = zlib.compress(b"\x00\x00")  # filter byte + 1 pixel

        png = b"\x89PNG\r\n\x1a\n"
        png += _make_chunk(b"IHDR", ihdr_data)
        png += _make_chunk(b"IDAT", raw_data)
        png += _make_chunk(b"IEND", b"")

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(png)
            tmp_path = f.name

        try:
            profile = ingest_image(tmp_path)
            assert profile.mime_type == "image/png"
            assert profile.width == 1
            assert profile.height == 1
        finally:
            os.unlink(tmp_path)


# ---------------------------------------------------------------------------
# Semantic analysis integration test
# ---------------------------------------------------------------------------

class TestSemanticAnalysis:
    def test_classify_subjects_with_mock(self):
        """Run subject classification on synthetic data with mock provider."""
        import pandas as pd

        df = pd.DataFrame({
            "record_id": ["r1", "r2", "r3"],
            "subject_extract_original": ["Minarett; Stadtmauer", "Berge; Gletscher", ""],
        })
        profile = DatasetProfile(
            source_path="test.csv",
            source_name="test",
            row_count=3,
            column_count=2,
            columns=[],
            id_column="record_id",
        )

        mock = MockProvider.with_defaults()
        findings, batch_report = classify_subjects(
            df, profile, mock,
            subject_column="subject_extract_original",
        )

        # Should have processed 2 records (3rd is empty)
        assert batch_report.total == 2
        assert batch_report.succeeded == 2
        assert len(findings) > 0

    def test_classify_missing_column(self):
        """Should produce a finding when column doesn't exist."""
        import pandas as pd

        df = pd.DataFrame({"record_id": ["r1"], "other": ["data"]})
        profile = DatasetProfile(
            source_path="test.csv", source_name="test",
            row_count=1, column_count=2, columns=[], id_column="record_id",
        )

        mock = MockProvider.with_defaults()
        findings, _ = classify_subjects(
            df, profile, mock,
            subject_column="nonexistent_column",
        )
        assert any(f.category == FindingCategory.SCHEMA_MISMATCH for f in findings)

    def test_describe_images_with_mock(self):
        """Run image description on mock image profiles."""
        mock = MockProvider.with_defaults()
        images = [
            ImageProfile(
                path="/fake/img1.jpg", filename="img1.jpg",
                file_size_bytes=1000, mime_type="image/jpeg",
                base64_data="AAAA",
            ),
            ImageProfile(
                path="/fake/img2.jpg", filename="img2.jpg",
                file_size_bytes=2000, mime_type="image/jpeg",
                base64_data="BBBB",
            ),
        ]

        findings, batch_report = describe_images(images, mock)
        assert batch_report.total == 2
        assert batch_report.succeeded == 2
