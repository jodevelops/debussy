"""
Tests für offene Issues aus dem Testbericht (TEST-04, TEST-05, TEST-06).

TEST-04: Image Integration Test  — Upload → Thumbnail → Analyse
TEST-05: GPUStack Provider       — vollständig mit gemockten HTTP-Aufrufen
TEST-06: MockProvider Fehlerszenarien — ungültiges JSON, leere Antworten,
         Batch-Fehlertoleranz
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# ---------------------------------------------------------------------------
# Minimal JPEG für Tests (SOI + APP0 + SOF0 + EOI, 1×1 Pixel)
# ---------------------------------------------------------------------------
_JPEG_1PX = bytes([
    0xFF, 0xD8,                                    # SOI
    0xFF, 0xE0, 0x00, 0x10,                        # APP0 marker + length
    0x4A, 0x46, 0x49, 0x46, 0x00,                  # "JFIF\0"
    0x01, 0x01, 0x00,                              # version + units
    0x00, 0x01, 0x00, 0x01,                        # X/Y density
    0x00, 0x00,                                    # thumbnail
    0xFF, 0xC0, 0x00, 0x0B,                        # SOF0 + length
    0x08,                                          # precision
    0x00, 0x01, 0x00, 0x01,                        # height=1, width=1
    0x01, 0x01, 0x11, 0x00,                        # 1 component
    0xFF, 0xD9,                                    # EOI
])


# ---------------------------------------------------------------------------
# Conditional FastAPI import
# ---------------------------------------------------------------------------
try:
    from fastapi.testclient import TestClient
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

_skip_fastapi = unittest.skipUnless(_FASTAPI_AVAILABLE, "FastAPI not installed")


def _make_client():
    """Frischer TestClient mit MockProvider und leerem State."""
    from kwb.api import deps
    from kwb.core.workspace import Workspace
    from kwb.ai.mock import MockProvider
    from kwb.api.routes import ai as ai_routes

    deps._state["datasets"] = {}
    deps._state["report"] = None
    deps._state["workspace"] = Workspace(name="test")
    deps._config_cache = None
    deps._prov_override = MockProvider.with_defaults()
    ai_routes._uploaded_images.clear()

    from kwb.api.app import app
    return TestClient(app)


# ===========================================================================
# TEST-04: Image Integration — Upload → Thumbnail → Analyse
# ===========================================================================

@_skip_fastapi
class TestImageIntegration(unittest.TestCase):
    """
    Vollständiger Bild-Workflow:
      1. Bild hochladen (/api/images/upload)
      2. Thumbnail abrufen (/api/images/{id}/data)
      3. Analyse starten (/api/images/analyze)
      4. Ergebnis im Listen-Endpoint sichtbar (/api/images)
    """

    def setUp(self):
        self.client = _make_client()

    def _upload(self, name: str = "test.jpg") -> str:
        r = self.client.post(
            "/api/images/upload",
            files=[("files", (name, io.BytesIO(_JPEG_1PX), "image/jpeg"))],
        )
        self.assertEqual(r.status_code, 200, r.text)
        imgs = r.json()["images"]
        self.assertEqual(len(imgs), 1)
        return imgs[0]["id"]

    def test_upload_returns_id_and_filename(self):
        r = self.client.post(
            "/api/images/upload",
            files=[("files", ("foto.jpg", io.BytesIO(_JPEG_1PX), "image/jpeg"))],
        )
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["uploaded"], 1)
        img = data["images"][0]
        self.assertIn("id", img)
        self.assertIn("filename", img)
        self.assertTrue(img["id"].startswith("img_"))

    def test_thumbnail_served_after_upload(self):
        """Nach dem Upload muss /api/images/{id}/data Binärdaten liefern."""
        img_id = self._upload("thumb_test.jpg")
        r = self.client.get(f"/api/images/{img_id}/data")
        self.assertEqual(r.status_code, 200)
        # Antwort muss Bytes enthalten (kein JSON-Fehler)
        self.assertGreater(len(r.content), 0)
        # Content-Type muss image/... sein
        ct = r.headers.get("content-type", "")
        self.assertIn("image", ct, f"Unexpected Content-Type: {ct}")

    def test_thumbnail_unknown_id_returns_404(self):
        r = self.client.get("/api/images/img_9999_does_not_exist/data")
        self.assertEqual(r.status_code, 404)

    def test_analyze_single_image(self):
        """Upload → Analyse: Ergebnis enthält id und result."""
        img_id = self._upload("analyze_me.jpg")
        r = self.client.post("/api/images/analyze", json={"image_ids": [img_id]})
        self.assertEqual(r.status_code, 200, r.text)
        data = r.json()
        self.assertIn("results", data)
        self.assertEqual(len(data["results"]), 1)
        result = data["results"][0]
        self.assertEqual(result["id"], img_id)
        self.assertIn("result", result)

    def test_analyze_multiple_images(self):
        ids = [self._upload(f"img{i}.jpg") for i in range(3)]
        r = self.client.post("/api/images/analyze", json={"image_ids": ids})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()["results"]), 3)

    def test_analyze_unknown_id_returns_error_entry_not_500(self):
        """Unbekannte ID im Analyse-Request → Fehler im Ergebnis, kein HTTP-500."""
        r = self.client.post("/api/images/analyze", json={"image_ids": ["img_9999_fake"]})
        # Endpoint muss 200 oder 4xx zurückgeben, nicht 500
        self.assertNotEqual(r.status_code, 500)
        if r.status_code == 200:
            result = r.json()["results"][0]
            self.assertIn("error", result)

    def test_images_list_shows_analyzed_flag(self):
        """Nach der Analyse zeigt /api/images analyzed=true."""
        img_id = self._upload("listed.jpg")
        # Vor Analyse: analyzed sollte False sein
        r_before = self.client.get("/api/images")
        self.assertEqual(r_before.status_code, 200)
        imgs_before = {i["id"]: i for i in r_before.json()["images"]}
        self.assertFalse(imgs_before[img_id].get("analyzed", False))

        # Analyse starten
        self.client.post("/api/images/analyze", json={"image_ids": [img_id]})

        # Nach Analyse: analyzed sollte True sein
        r_after = self.client.get("/api/images")
        imgs_after = {i["id"]: i for i in r_after.json()["images"]}
        self.assertTrue(imgs_after[img_id].get("analyzed", False))

    def test_full_workflow_upload_thumbnail_analyze(self):
        """Vollständiger Workflow in einem Test: Upload → Thumbnail → Analyse."""
        # 1. Upload
        r_upload = self.client.post(
            "/api/images/upload",
            files=[("files", ("workflow.jpg", io.BytesIO(_JPEG_1PX), "image/jpeg"))],
        )
        self.assertEqual(r_upload.status_code, 200)
        img_id = r_upload.json()["images"][0]["id"]

        # 2. Thumbnail
        r_thumb = self.client.get(f"/api/images/{img_id}/data")
        self.assertEqual(r_thumb.status_code, 200)
        self.assertGreater(len(r_thumb.content), 0)

        # 3. Analyse
        r_analyze = self.client.post("/api/images/analyze", json={"image_ids": [img_id]})
        self.assertEqual(r_analyze.status_code, 200)
        result = r_analyze.json()["results"][0]
        self.assertEqual(result["id"], img_id)
        self.assertNotIn("error", result)


# ===========================================================================
# TEST-05: GPUStack Provider — vollständig mit gemockten HTTP-Aufrufen
# ===========================================================================

class TestGPUStackProvider(unittest.TestCase):
    """
    GPUStackProvider wird mit gemocktem urllib.request.urlopen getestet.
    Kein echter HTTP-Aufruf — deterministisch und offline.
    """

    def _make_provider(self, base_url: str = "http://fake-gpustack:80"):
        from kwb.ai.gpustack import GPUStackProvider
        from kwb.ai.provider import ProviderConfig
        cfg = ProviderConfig(
            base_url=base_url,
            api_key="test-key",
            default_model="llama3-8b",
            max_retries=2,
            timeout_seconds=5,
        )
        return GPUStackProvider(cfg)

    def _mock_http_response(self, body: bytes, status: int = 200):
        """Erstellt ein Mock-Response-Objekt, das urlopen zurückgibt."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = body
        mock_resp.status = status
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        return mock_resp

    @patch("kwb.ai.gpustack.urlopen")
    def test_complete_returns_ai_response(self, mock_urlopen):
        """complete() parst die OpenAI-kompatible JSON-Antwort korrekt."""
        fake_body = json.dumps({
            "choices": [{"message": {"content": '{"category": "Architektur"}'}}],
            "model": "llama3-8b",
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }).encode()
        mock_urlopen.return_value = self._mock_http_response(fake_body)

        from kwb.ai.provider import AIMessage
        prov = self._make_provider()
        resp = prov.complete([AIMessage.user("Klassifiziere: Minarett")])

        self.assertEqual(resp.model, "llama3-8b")
        self.assertIn("Architektur", resp.content)
        self.assertEqual(resp.usage["prompt_tokens"], 10)

    @patch("kwb.ai.gpustack.urlopen")
    def test_complete_sends_authorization_header(self, mock_urlopen):
        """complete() setzt Authorization-Header wenn api_key gesetzt."""
        fake_body = json.dumps({
            "choices": [{"message": {"content": "ok"}}],
            "model": "llama3-8b",
            "usage": {},
        }).encode()
        mock_urlopen.return_value = self._mock_http_response(fake_body)

        from kwb.ai.provider import AIMessage
        prov = self._make_provider()
        prov.complete([AIMessage.user("test")])

        # Den Request-Aufruf auslesen
        call_args = mock_urlopen.call_args
        req = call_args[0][0]
        self.assertIn("Authorization", req.headers)
        self.assertTrue(req.headers["Authorization"].startswith("Bearer"))

    @patch("kwb.ai.gpustack.urlopen")
    def test_complete_model_override(self, mock_urlopen):
        """complete() verwendet übergebenes model, nicht config.default_model."""
        fake_body = json.dumps({
            "choices": [{"message": {"content": "resp"}}],
            "model": "qwen-72b",
            "usage": {},
        }).encode()
        mock_urlopen.return_value = self._mock_http_response(fake_body)

        from kwb.ai.provider import AIMessage
        prov = self._make_provider()
        resp = prov.complete([AIMessage.user("test")], model="qwen-72b")
        self.assertEqual(resp.model, "qwen-72b")

    @patch("kwb.ai.gpustack.urlopen")
    def test_is_available_true_on_200(self, mock_urlopen):
        """is_available() gibt True zurück wenn /v1/models antwortet."""
        mock_urlopen.return_value = self._mock_http_response(b'{"data":[]}', 200)
        prov = self._make_provider()
        self.assertTrue(prov.is_available())

    @patch("kwb.ai.gpustack.urlopen")
    def test_is_available_false_on_connection_error(self, mock_urlopen):
        """is_available() gibt False zurück bei Netzwerkfehler."""
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("connection refused")
        prov = self._make_provider()
        self.assertFalse(prov.is_available())

    @patch("kwb.ai.gpustack.urlopen")
    def test_list_models_parses_response(self, mock_urlopen):
        """list_models() gibt die Modell-IDs aus der API zurück."""
        body = json.dumps({"data": [{"id": "llama3-8b"}, {"id": "qwen-72b"}]}).encode()
        mock_urlopen.return_value = self._mock_http_response(body)
        prov = self._make_provider()
        models = prov.list_models()
        self.assertIn("llama3-8b", models)
        self.assertIn("qwen-72b", models)

    @patch("kwb.ai.gpustack.urlopen")
    def test_list_models_empty_on_error(self, mock_urlopen):
        """list_models() gibt leere Liste bei Netzwerkfehler zurück."""
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("timeout")
        prov = self._make_provider()
        self.assertEqual(prov.list_models(), [])

    @patch("kwb.ai.gpustack.urlopen")
    @patch("kwb.ai.gpustack.time.sleep")  # sleep unterdrücken
    def test_complete_retries_on_500(self, mock_sleep, mock_urlopen):
        """complete() wiederholt den Request bei HTTP 500."""
        from urllib.error import HTTPError

        success_body = json.dumps({
            "choices": [{"message": {"content": "ok"}}],
            "model": "llama3-8b", "usage": {},
        }).encode()

        # Erster Aufruf: 500, zweiter: Erfolg
        error_500 = HTTPError(url=None, code=500, msg="Internal", hdrs=None, fp=io.BytesIO(b""))
        error_500.read = lambda: b""
        mock_urlopen.side_effect = [error_500, self._mock_http_response(success_body)]

        from kwb.ai.provider import AIMessage
        prov = self._make_provider()
        resp = prov.complete([AIMessage.user("test")])
        self.assertEqual(resp.content, "ok")
        self.assertEqual(mock_urlopen.call_count, 2)

    @patch("kwb.ai.gpustack.urlopen")
    @patch("kwb.ai.gpustack.time.sleep")
    def test_complete_raises_after_all_retries_exhausted(self, mock_sleep, mock_urlopen):
        """complete() wirft ConnectionError wenn alle Versuche scheitern."""
        from urllib.error import URLError
        mock_urlopen.side_effect = URLError("connection refused")

        from kwb.ai.provider import AIMessage
        prov = self._make_provider()
        with self.assertRaises(ConnectionError):
            prov.complete([AIMessage.user("test")])

    @patch("kwb.ai.gpustack.urlopen")
    @patch("kwb.ai.gpustack.time.sleep")
    def test_complete_raises_immediately_on_4xx(self, mock_sleep, mock_urlopen):
        """complete() wiederholt nicht bei 4xx (außer 429)."""
        from urllib.error import HTTPError
        err = HTTPError(url=None, code=400, msg="Bad Request", hdrs=None, fp=io.BytesIO(b""))
        err.read = lambda: b"bad request"
        mock_urlopen.side_effect = err

        from kwb.ai.provider import AIMessage
        prov = self._make_provider()
        with self.assertRaises(HTTPError):
            prov.complete([AIMessage.user("test")])
        # Kein Retry bei 4xx
        self.assertEqual(mock_urlopen.call_count, 1)

    @patch("kwb.ai.gpustack.urlopen")
    @patch("kwb.ai.gpustack.time.sleep")
    def test_complete_retries_on_429_rate_limit(self, mock_sleep, mock_urlopen):
        """complete() wiederholt bei HTTP 429 (Rate Limit) mit Backoff."""
        from urllib.error import HTTPError
        success_body = json.dumps({
            "choices": [{"message": {"content": "ok after retry"}}],
            "model": "llama3-8b", "usage": {},
        }).encode()

        err_429 = HTTPError(url=None, code=429, msg="Too Many Requests", hdrs=None, fp=io.BytesIO(b""))
        err_429.read = lambda: b""
        mock_urlopen.side_effect = [err_429, self._mock_http_response(success_body)]

        from kwb.ai.provider import AIMessage
        prov = self._make_provider()
        resp = prov.complete([AIMessage.user("test")])
        self.assertEqual(resp.content, "ok after retry")
        mock_sleep.assert_called()  # Backoff-Sleep wurde aufgerufen

    @patch("kwb.ai.gpustack.urlopen")
    def test_complete_with_vision_message(self, mock_urlopen):
        """complete() übergibt Multipart-Content korrekt für Vision-Anfragen."""
        fake_body = json.dumps({
            "choices": [{"message": {"content": '{"description": "Berglandschaft"}'}}],
            "model": "llava-13b", "usage": {},
        }).encode()
        mock_urlopen.return_value = self._mock_http_response(fake_body)

        from kwb.ai.provider import AIMessage
        prov = self._make_provider()
        msg = AIMessage.user_with_image("Beschreibe dieses Bild", "AAAA==", "image/jpeg")
        resp = prov.complete([msg])
        self.assertIn("Berglandschaft", resp.content)


# ===========================================================================
# TEST-06: MockProvider Fehlerszenarien
# ===========================================================================

class TestMockProviderErrorScenarios(unittest.TestCase):
    """
    Fehlerszenarien im MockProvider und im Batch-Prozessor:
    - Ungültiges JSON als Antwort
    - Leere Antwort
    - Provider-Exception während Batch
    - Batch-Fehlertoleranz (Verarbeitung läuft weiter trotz Einzelfehlern)
    """

    def test_invalid_json_response_parsed_as_none(self):
        """_try_parse_json gibt None zurück bei ungültigem JSON."""
        from kwb.core.utils import try_parse_json
        self.assertIsNone(try_parse_json("das ist kein JSON"))
        self.assertIsNone(try_parse_json(""))
        self.assertIsNone(try_parse_json(None))
        self.assertIsNone(try_parse_json("{unclosed"))

    def test_valid_json_response_parsed_correctly(self):
        """_try_parse_json parst gültiges JSON korrekt."""
        from kwb.core.utils import try_parse_json
        result = try_parse_json('{"key": "value", "num": 42}')
        self.assertEqual(result, {"key": "value", "num": 42})

    def test_json_in_code_block_extracted(self):
        """_try_parse_json extrahiert JSON aus Markdown-Code-Block."""
        from kwb.core.utils import try_parse_json
        wrapped = '```json\n{"category": "Architektur"}\n```'
        result = try_parse_json(wrapped)
        self.assertIsNotNone(result)
        self.assertEqual(result["category"], "Architektur")

    def test_mock_provider_with_invalid_json_response(self):
        """MockProvider kann so konfiguriert werden, dass es ungültiges JSON liefert."""
        from kwb.ai.mock import MockProvider
        from kwb.ai.provider import AIMessage
        mock = MockProvider(default_response="KEIN_JSON_HIER")
        resp = mock.complete([AIMessage.user("test")])
        self.assertEqual(resp.content, "KEIN_JSON_HIER")

    def test_mock_provider_with_empty_response(self):
        """MockProvider mit leerem Default-Response."""
        from kwb.ai.mock import MockProvider
        from kwb.ai.provider import AIMessage
        mock = MockProvider(default_response="")
        resp = mock.complete([AIMessage.user("test")])
        self.assertEqual(resp.content, "")

    def test_batch_continues_after_invalid_json(self):
        """
        Batch-Verarbeitung läuft weiter auch wenn einzelne Antworten
        kein gültiges JSON enthalten. success=True, parsed=None.
        """
        from kwb.ai.mock import MockProvider
        from kwb.ai.provider import AIMessage
        from kwb.ai.batch import process_batch

        mock = MockProvider(default_response="KEIN_JSON")
        items = [{"record_id": f"r{i}"} for i in range(3)]
        report = process_batch(
            mock, items,
            prompt_fn=lambda item: [AIMessage.user("test")],
        )
        self.assertEqual(report.total, 3)
        self.assertEqual(report.succeeded, 3)   # Erfolg trotz unparsebarem JSON
        self.assertEqual(report.failed, 0)
        for r in report.results:
            self.assertTrue(r.success)
            self.assertIsNone(r.parsed)          # parsed=None wenn JSON fehlt

    def test_batch_counts_failed_when_provider_raises(self):
        """Batch zählt failed korrekt wenn Provider eine Exception wirft."""
        from kwb.ai.provider import AIMessage, AIProvider, AIResponse, ProviderConfig
        from kwb.ai.batch import process_batch

        class FailingProvider(AIProvider):
            def __init__(self):
                super().__init__(ProviderConfig(base_url="mock://fail"))
            def complete(self, messages, **kwargs):
                raise RuntimeError("Simulated network error")
            def is_available(self): return False
            def list_models(self): return []

        items = [{"record_id": f"r{i}"} for i in range(4)]
        report = process_batch(
            FailingProvider(), items,
            prompt_fn=lambda item: [AIMessage.user("test")],
        )
        self.assertEqual(report.total, 4)
        self.assertEqual(report.failed, 4)
        self.assertEqual(report.succeeded, 0)
        self.assertEqual(report.success_rate, 0.0)

    def test_batch_partial_failure_tolerance(self):
        """Batch toleriert Einzelfehler — erfolgreiche Records werden gezählt."""
        from kwb.ai.provider import AIMessage, AIProvider, AIResponse, ProviderConfig
        from kwb.ai.batch import process_batch
        import json

        call_count = {"n": 0}

        class PartiallyFailingProvider(AIProvider):
            def __init__(self):
                super().__init__(ProviderConfig(base_url="mock://partial"))
            def complete(self, messages, **kwargs):
                call_count["n"] += 1
                if call_count["n"] % 2 == 0:   # jeder zweite Aufruf schlägt fehl
                    raise RuntimeError("Simulated failure")
                return AIResponse(
                    content=json.dumps({"ok": True}),
                    model="mock",
                    usage={},
                )
            def is_available(self): return True
            def list_models(self): return ["mock"]

        items = [{"record_id": f"r{i}"} for i in range(6)]
        report = process_batch(
            PartiallyFailingProvider(), items,
            prompt_fn=lambda item: [AIMessage.user("test")],
        )
        self.assertEqual(report.total, 6)
        self.assertEqual(report.succeeded, 3)
        self.assertEqual(report.failed, 3)
        self.assertAlmostEqual(report.success_rate, 0.5)

    def test_batch_with_empty_items_list(self):
        """Batch mit leerer Item-Liste gibt leeren Report zurück."""
        from kwb.ai.mock import MockProvider
        from kwb.ai.provider import AIMessage
        from kwb.ai.batch import process_batch

        mock = MockProvider.with_defaults()
        report = process_batch(mock, [], prompt_fn=lambda item: [AIMessage.user("test")])
        self.assertEqual(report.total, 0)
        self.assertEqual(report.succeeded, 0)
        self.assertEqual(report.success_rate, 0.0)

    def test_mock_provider_call_log_records_all_calls(self):
        """MockProvider.call_log enthält alle Aufrufe mit korrekten Modell-Infos."""
        from kwb.ai.mock import MockProvider
        from kwb.ai.provider import AIMessage
        mock = MockProvider.with_defaults()

        mock.complete([AIMessage.user("eins")], model="model-A")
        mock.complete([AIMessage.user("zwei")], model="model-B")
        mock.complete([AIMessage.user("drei")])

        self.assertEqual(len(mock.call_log), 3)
        self.assertEqual(mock.call_log[0]["model"], "model-A")
        self.assertEqual(mock.call_log[1]["model"], "model-B")
        self.assertEqual(mock.call_log[2]["model"], "mock-model")  # default

    def test_mock_provider_reset_clears_log(self):
        """reset_log() leert den call_log."""
        from kwb.ai.mock import MockProvider
        from kwb.ai.provider import AIMessage
        mock = MockProvider.with_defaults()
        mock.complete([AIMessage.user("test")])
        self.assertEqual(len(mock.call_log), 1)
        mock.reset_log()
        self.assertEqual(len(mock.call_log), 0)

    def test_mock_provider_rule_priority(self):
        """Rules werden in Reihenfolge geprüft — erste passende gewinnt."""
        from kwb.ai.mock import MockProvider
        from kwb.ai.provider import AIMessage

        mock = MockProvider(
            rules=[
                (lambda msgs: "alpha" in msgs[-1].content, '{"match": "alpha"}'),
                (lambda msgs: "alpha" in msgs[-1].content, '{"match": "alpha-second"}'),
            ],
            default_response='{"match": "default"}',
        )
        resp = mock.complete([AIMessage.user("alpha test")])
        self.assertEqual(json.loads(resp.content)["match"], "alpha")

        resp2 = mock.complete([AIMessage.user("beta test")])
        self.assertEqual(json.loads(resp2.content)["match"], "default")


if __name__ == "__main__":
    unittest.main()
