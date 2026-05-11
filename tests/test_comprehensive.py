"""
Tests for GPUStack provider, error scenarios, and CLI.

TEST-05: GPUStack with mocked urlopen
TEST-06: MockProvider error scenarios
TEST-07: OCR test assertion fix
TEST-08: CLI tests
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from kwb.ai.provider import AIMessage, AIResponse, ProviderConfig
from kwb.ai.mock import MockProvider
from kwb.ai.gpustack import GPUStackProvider
from kwb.ai.prompts import prompt_ocr_transcription_quality


# ---------------------------------------------------------------------------
# TEST-05: GPUStack Provider with mocked HTTP
# ---------------------------------------------------------------------------

class TestGPUStackProvider(unittest.TestCase):
    """Test GPUStack provider with mocked urlopen — no real GPU needed."""

    def _make_provider(self, base_url="http://gpu.local:80", model="test-llm"):
        return GPUStackProvider(ProviderConfig(
            base_url=base_url,
            api_key="test-key-123",
            default_model=model,
        ))

    def _mock_response(self, content="Test response", model="test-llm"):
        """Create a mock urlopen response."""
        body = json.dumps({
            "choices": [{"message": {"content": content}}],
            "model": model,
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }).encode()
        mock = MagicMock()
        mock.read.return_value = body
        mock.status = 200
        mock.__enter__ = lambda s: s
        mock.__exit__ = MagicMock(return_value=False)
        return mock

    @patch("kwb.ai.gpustack.urlopen")
    def test_complete_basic(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response("Antwort vom LLM")
        prov = self._make_provider()
        resp = prov.complete([AIMessage.user("Hallo")])
        self.assertEqual(resp.content, "Antwort vom LLM")
        self.assertEqual(resp.model, "test-llm")
        mock_urlopen.assert_called_once()

    @patch("kwb.ai.gpustack.urlopen")
    def test_complete_sends_auth_header(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response()
        prov = self._make_provider()
        prov.complete([AIMessage.user("test")])

        call_args = mock_urlopen.call_args
        request = call_args[0][0]
        self.assertEqual(request.get_header("Authorization"), "Bearer test-key-123")

    @patch("kwb.ai.gpustack.urlopen")
    def test_complete_sends_correct_payload(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response()
        prov = self._make_provider()
        prov.complete(
            [AIMessage.system("Sei hilfreich"), AIMessage.user("Frage")],
            model="custom-model",
            temperature=0.5,
            max_tokens=200,
        )

        call_args = mock_urlopen.call_args
        request = call_args[0][0]
        payload = json.loads(request.data.decode())
        self.assertEqual(payload["model"], "custom-model")
        self.assertEqual(payload["temperature"], 0.5)
        self.assertEqual(payload["max_tokens"], 200)
        self.assertEqual(len(payload["messages"]), 2)
        self.assertEqual(payload["messages"][0]["role"], "system")

    @patch("kwb.ai.gpustack.urlopen")
    def test_complete_with_vision_message(self, mock_urlopen):
        mock_urlopen.return_value = self._mock_response('{"description": "Ein Bild"}')
        prov = self._make_provider()
        msg = AIMessage.user_with_image("Beschreibe", "AAAA", "image/jpeg")
        resp = prov.complete([msg])
        self.assertIn("description", resp.content)

        # Verify multipart message structure
        payload = json.loads(mock_urlopen.call_args[0][0].data.decode())
        user_msg = payload["messages"][0]
        self.assertIsInstance(user_msg["content"], list)
        self.assertEqual(user_msg["content"][0]["type"], "image_url")

    @patch("kwb.ai.gpustack.urlopen")
    def test_retry_on_server_error(self, mock_urlopen):
        from urllib.error import HTTPError
        error_resp = MagicMock()
        error_resp.read.return_value = b"Internal Server Error"
        error = HTTPError("http://gpu.local/v1/chat/completions", 500, "ISE", {}, error_resp)
        mock_urlopen.side_effect = [error, self._mock_response("Retry OK")]

        prov = self._make_provider()
        prov.config.max_retries = 2
        resp = prov.complete([AIMessage.user("test")])
        self.assertEqual(resp.content, "Retry OK")
        self.assertEqual(mock_urlopen.call_count, 2)

    @patch("kwb.ai.gpustack.urlopen")
    def test_raises_after_max_retries(self, mock_urlopen):
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("Connection refused")

        prov = self._make_provider()
        prov.config.max_retries = 2
        with self.assertRaises(ConnectionError):
            prov.complete([AIMessage.user("test")])
        self.assertEqual(mock_urlopen.call_count, 2)

    @patch("kwb.ai.gpustack.urlopen")
    def test_is_available_success(self, mock_urlopen):
        mock = MagicMock()
        mock.status = 200
        mock.__enter__ = lambda s: s
        mock.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock

        prov = self._make_provider()
        self.assertTrue(prov.is_available())

    @patch("kwb.ai.gpustack.urlopen")
    def test_is_available_failure(self, mock_urlopen):
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("refused")
        prov = self._make_provider()
        self.assertFalse(prov.is_available())

    @patch("kwb.ai.gpustack.urlopen")
    def test_list_models(self, mock_urlopen):
        body = json.dumps({"data": [
            {"id": "llama-3.1-8b"}, {"id": "qwen-vl-7b"},
        ]}).encode()
        mock = MagicMock()
        mock.read.return_value = body
        mock.__enter__ = lambda s: s
        mock.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock

        prov = self._make_provider()
        models = prov.list_models()
        self.assertEqual(models, ["llama-3.1-8b", "qwen-vl-7b"])


# ---------------------------------------------------------------------------
# TEST-06: MockProvider error scenarios
# ---------------------------------------------------------------------------

class TestMockProviderErrors(unittest.TestCase):
    """Test what happens when AI provider returns invalid/empty responses."""

    def test_invalid_json_response(self):
        """Provider returns invalid JSON — consumers should handle gracefully."""
        mock = MockProvider(default_response="This is not valid JSON at all!")
        resp = mock.complete([AIMessage.user("test")])
        self.assertEqual(resp.content, "This is not valid JSON at all!")

        # Verify batch processing handles it
        from kwb.ai.batch import _try_parse_json
        self.assertIsNone(_try_parse_json(resp.content))

    def test_empty_response(self):
        """Provider returns empty string."""
        mock = MockProvider(default_response="")
        resp = mock.complete([AIMessage.user("test")])
        self.assertEqual(resp.content, "")

    def test_partial_json_response(self):
        """Provider returns truncated JSON."""
        mock = MockProvider(default_response='{"key": "val')
        resp = mock.complete([AIMessage.user("test")])
        from kwb.ai.batch import _try_parse_json
        self.assertIsNone(_try_parse_json(resp.content))

    def test_html_error_response(self):
        """Provider returns HTML error page (common with misconfigured proxies)."""
        mock = MockProvider(default_response="<html><body>502 Bad Gateway</body></html>")
        resp = mock.complete([AIMessage.user("test")])
        from kwb.ai.batch import _try_parse_json
        self.assertIsNone(_try_parse_json(resp.content))

    def test_batch_with_mixed_errors(self):
        """Batch processing handles mix of valid and invalid responses."""
        from kwb.ai.batch import process_batch
        call_count = [0]

        def _alternating_provider():
            """Returns valid JSON on odd calls, garbage on even."""
            mock = MockProvider()

            original_complete = mock.complete.__func__

            def alternating_complete(self, messages, **kwargs):
                call_count[0] += 1
                if call_count[0] % 2 == 0:
                    return AIResponse(content="not json", model="mock")
                return AIResponse(
                    content='{"status": "ok"}', model="mock",
                    usage={"prompt_tokens": 1, "completion_tokens": 1},
                )

            import types
            mock.complete = types.MethodType(alternating_complete, mock)
            return mock

        mock = _alternating_provider()
        items = [{"id": str(i)} for i in range(4)]
        report = process_batch(
            mock, items,
            lambda item: [AIMessage.user("test")],
        )
        self.assertEqual(report.total, 4)
        # Some should have parsed=None (the non-JSON ones)
        parsed_count = sum(1 for r in report.results if r.parsed)
        unparsed_count = sum(1 for r in report.results if not r.parsed)
        self.assertGreater(parsed_count, 0)
        self.assertGreater(unparsed_count, 0)

    def test_classify_subjects_with_invalid_response(self):
        """classify_subjects handles invalid LLM responses gracefully."""
        import pandas as pd
        from kwb.analyze.semantic import classify_subjects
        from kwb.core.models import DatasetProfile

        mock = MockProvider(default_response="Ich bin kein JSON")
        df = pd.DataFrame({
            "record_id": ["r1"],
            "subject_extract_original": ["Minarett"],
        })
        profile = DatasetProfile(
            source_path="test.csv", source_name="test",
            row_count=1, column_count=2, columns=[], id_column="record_id",
        )
        # Should not raise
        findings, batch = classify_subjects(df, profile, mock)
        self.assertEqual(batch.total, 1)


# ---------------------------------------------------------------------------
# TEST-07: OCR Test Assertion
# ---------------------------------------------------------------------------

class TestOCRPrompt(unittest.TestCase):
    """Verify OCR prompt uses consistent language."""

    def test_ocr_prompt_contains_transcription(self):
        """OCR prompt should contain 'transcription' (the JSON key)."""
        msgs = prompt_ocr_transcription_quality()
        user_text = msgs[1].content
        # The prompt requests JSON with "transcription" key
        self.assertIn("transcription", user_text)

    def test_ocr_prompt_has_expected_json_keys(self):
        """OCR prompt should request specific JSON structure."""
        msgs = prompt_ocr_transcription_quality()
        user_text = msgs[1].content
        for key in ["text_found", "text_type", "language", "transcription",
                     "text_regions", "overall_confidence"]:
            self.assertIn(key, user_text, f"Missing key: {key}")


# ---------------------------------------------------------------------------
# TEST-08: CLI Tests
# ---------------------------------------------------------------------------

class TestCLI(unittest.TestCase):
    """Tests for the CLI entry point."""

    def test_cli_no_args_shows_help(self):
        """CLI with no arguments should return 0 (help shown)."""
        from kwb.cli import main
        result = main([])
        self.assertEqual(result, 0)

    def test_cli_analyze_missing_file(self):
        """CLI analyze with non-existent file should return error."""
        from kwb.cli import main
        result = main(["analyze", "/nonexistent/file.csv"])
        self.assertEqual(result, 1)

    def test_cli_analyze_real_csv(self):
        """CLI analyze with a valid CSV file should succeed."""
        from kwb.cli import main
        with tempfile.NamedTemporaryFile(
            suffix=".csv", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write("record_id,title,year\n")
            f.write("obj_001,Test Object,1920\n")
            f.write("obj_002,Another Object,1935\n")
            tmp = f.name

        try:
            result = main(["analyze", tmp])
            self.assertEqual(result, 0)
        finally:
            Path(tmp).unlink()

    def test_cli_analyze_with_output(self):
        """CLI analyze writes report to file when -o is given."""
        from kwb.cli import main
        with tempfile.NamedTemporaryFile(
            suffix=".csv", mode="w", delete=False, encoding="utf-8"
        ) as f:
            f.write("record_id,title\nobj_001,Test\n")
            csv_path = f.name

        with tempfile.NamedTemporaryFile(
            suffix=".md", delete=False
        ) as out:
            out_path = out.name

        try:
            result = main(["analyze", csv_path, "-o", out_path])
            self.assertEqual(result, 0)
            content = Path(out_path).read_text()
            self.assertIn("qualit", content.lower())  # "Datenqualitätsbericht" or similar
        finally:
            Path(csv_path).unlink()
            Path(out_path).unlink()

    def test_cli_plan(self):
        """CLI plan command should succeed with the default catalog."""
        from kwb.cli import main
        # plan command reads docs/FUNKTIONSKATALOG.md
        if not Path("docs/FUNKTIONSKATALOG.md").exists():
            self.skipTest("FUNKTIONSKATALOG.md not found")
        result = main(["plan", "--top", "3"])
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
