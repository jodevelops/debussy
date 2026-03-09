"""
Tests for GET/POST /api/gpu/config endpoints.

Verifies:
  - GET /api/gpu/config returns url, masked key, model fields
  - POST /api/gpu/config updates in-memory config
  - POST with empty key keeps existing key unchanged
  - POST persists to .env file
"""

import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
    from fastapi.testclient import TestClient
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

_skip = unittest.skipUnless(
    _FASTAPI_AVAILABLE,
    "FastAPI not installed — run: pip install fastapi httpx python-multipart",
)


def _make_client(gpustack_url="", gpustack_key="", model_text="", model_vision=""):
    from kwb.api import deps
    from kwb.core.config import KWBConfig
    from kwb.core.workspace import Workspace

    deps._state["datasets"] = {}
    deps._state["report"] = None
    deps._state["workspace"] = Workspace(name="test")
    deps._config_cache = KWBConfig(
        gpustack_url=gpustack_url,
        gpustack_key=gpustack_key,
        gpustack_model_text=model_text,
        gpustack_model_vision=model_vision,
    )

    from kwb.api.app import app
    return TestClient(app)


@_skip
class TestGpuConfigGet(unittest.TestCase):

    def test_get_returns_url_and_masked_key(self):
        client = _make_client(gpustack_url="http://gpu:80", gpustack_key="sk-secret123")
        r = client.get("/api/gpu/config")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["gpustack_url"], "http://gpu:80")
        self.assertIn("gpustack_key_masked", data)
        # Key should be masked, not shown in full
        self.assertNotEqual(data["gpustack_key_masked"], "sk-secret123")
        self.assertNotIn("gpustack_key", data)  # raw key must not be returned

    def test_get_empty_config(self):
        client = _make_client()
        r = client.get("/api/gpu/config")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["gpustack_url"], "")
        self.assertEqual(data["gpustack_key_masked"], "")

    def test_get_returns_model_fields(self):
        client = _make_client(model_text="llama3", model_vision="llava")
        r = client.get("/api/gpu/config")
        data = r.json()
        self.assertEqual(data["gpustack_model_text"], "llama3")
        self.assertEqual(data["gpustack_model_vision"], "llava")


@_skip
class TestGpuConfigPost(unittest.TestCase):

    def test_post_updates_config(self):
        client = _make_client()
        r = client.post("/api/gpu/config", json={
            "gpustack_url": "http://newhost:8080",
            "gpustack_key": "sk-newkey",
            "gpustack_model_text": "mistral",
            "gpustack_model_vision": "llava",
        })
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

        # Verify in-memory config was updated
        from kwb.api import deps
        cfg = deps.get_config()
        self.assertEqual(cfg.gpustack_url, "http://newhost:8080")
        self.assertEqual(cfg.gpustack_key, "sk-newkey")
        self.assertEqual(cfg.gpustack_model_text, "mistral")
        self.assertEqual(cfg.gpustack_model_vision, "llava")

    def test_post_empty_url_clears_it(self):
        """URL and model fields can be cleared by submitting empty strings."""
        client = _make_client(gpustack_url="http://old:80", model_text="llama3")
        r = client.post("/api/gpu/config", json={
            "gpustack_url": "",
            "gpustack_key": "",
            "gpustack_model_text": "",
            "gpustack_model_vision": "",
        })
        self.assertEqual(r.json()["status"], "ok")
        from kwb.api import deps
        cfg = deps.get_config()
        self.assertEqual(cfg.gpustack_url, "")
        self.assertEqual(cfg.gpustack_model_text, "")

    def test_post_empty_key_keeps_existing(self):
        """Only the API key uses 'empty = unchanged' semantics."""
        client = _make_client(gpustack_url="http://old:80", gpustack_key="sk-existing")
        r = client.post("/api/gpu/config", json={
            "gpustack_url": "http://old:80",
            "gpustack_key": "",  # empty → keep existing key
            "gpustack_model_text": "",
            "gpustack_model_vision": "",
        })
        self.assertEqual(r.json()["status"], "ok")
        from kwb.api import deps
        self.assertEqual(deps.get_config().gpustack_key, "sk-existing")

    def test_post_persists_to_dotenv(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            env_path = Path(tmpdir) / ".env"

            from kwb.api import deps
            from kwb.core.config import KWBConfig
            from kwb.core.workspace import Workspace

            deps._state["datasets"] = {}
            deps._state["report"] = None
            deps._state["workspace"] = Workspace(name="test")
            deps._config_cache = KWBConfig(gpustack_url="", gpustack_key="")

            from kwb.api.app import app
            client = TestClient(app)

            # Patch save_to_dotenv to write to our temp path
            original_save = KWBConfig.save_to_dotenv

            def patched_save(self_cfg, path=None):
                original_save(self_cfg, path=env_path)

            with patch.object(KWBConfig, "save_to_dotenv", patched_save):
                r = client.post("/api/gpu/config", json={
                    "gpustack_url": "http://test:80",
                    "gpustack_key": "sk-testkey",
                    "gpustack_model_text": "",
                    "gpustack_model_vision": "",
                })
            self.assertEqual(r.json()["status"], "ok")
            content = env_path.read_text()
            self.assertIn("KWB_GPUSTACK_URL=http://test:80", content)
            self.assertIn("KWB_GPUSTACK_KEY=sk-testkey", content)


@_skip
class TestSaveToDotenv(unittest.TestCase):
    """Unit tests for KWBConfig.save_to_dotenv()."""

    def test_creates_new_file(self):
        from kwb.core.config import KWBConfig
        cfg = KWBConfig(gpustack_url="http://x:80", gpustack_key="key1")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            cfg.save_to_dotenv(p)
            content = p.read_text()
            self.assertIn("KWB_GPUSTACK_URL=http://x:80", content)
            self.assertIn("KWB_GPUSTACK_KEY=key1", content)

    def test_updates_existing_file(self):
        from kwb.core.config import KWBConfig
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("KWB_GPUSTACK_URL=http://old:80\nKWB_OTHER=keep\n")
            cfg = KWBConfig(gpustack_url="http://new:80", gpustack_key="newkey")
            cfg.save_to_dotenv(p)
            content = p.read_text()
            self.assertIn("KWB_GPUSTACK_URL=http://new:80", content)
            self.assertIn("KWB_OTHER=keep", content)
            self.assertNotIn("http://old:80", content)

    def test_preserves_comments(self):
        from kwb.core.config import KWBConfig
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / ".env"
            p.write_text("# GPUStack\nKWB_GPUSTACK_URL=http://old:80\n")
            cfg = KWBConfig(gpustack_url="http://new:80")
            cfg.save_to_dotenv(p)
            content = p.read_text()
            self.assertIn("# GPUStack", content)


if __name__ == "__main__":
    unittest.main()
