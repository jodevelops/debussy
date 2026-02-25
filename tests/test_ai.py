"""
Tests for AI modules: provider, prompts, batch, semantic analysis.

All tests use MockProvider — no GPU required.
"""

import json
import os
import tempfile
from pathlib import Path

from kwb.ai.provider import AIMessage, ProviderConfig
from kwb.ai.mock import MockProvider
from kwb.ai.gpustack import GPUStackProvider
from kwb.ai.prompts import (
    prompt_classify_subject,
    prompt_describe_image,
    prompt_normalize_term,
    prompt_ocr_analysis,
)
from kwb.ai.batch import process_batch, _try_parse_json, BatchReport
from kwb.analyze.semantic import classify_subjects, describe_images
from kwb.ingest.image_loader import ImageProfile, ingest_image
from kwb.ingest.csv_loader import ingest_csv
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
        assert "Transkription" in msgs[1].content


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
        import struct, zlib

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
