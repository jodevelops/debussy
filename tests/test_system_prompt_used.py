"""
Tests for system-prompt override feedback (issue #150).

Covers:
  - resolve_system_prompt helper (override vs default fingerprints)
  - fingerprint_prompt (sha256, length, preview)
  - NERResult.system_prompt_used populated by ner_llm / ner_hybrid
  - scan_problematic_terms BatchReport carries the fingerprint
  - EDTF batch carries the fingerprint
  - /api/prompts/dry-run returns the resolved text + fingerprint without
    making an LLM call
"""
from __future__ import annotations

import hashlib
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from kwb.ai.mock import MockProvider
from kwb.ai.prompts import (
    fingerprint_prompt,
    resolve_system_prompt,
)


class TestResolveSystemPrompt(unittest.TestCase):
    def test_empty_override_picks_default(self):
        text, fp = resolve_system_prompt("", "DEFAULT TEXT", task="ner")
        self.assertEqual(text, "DEFAULT TEXT")
        self.assertFalse(fp["is_override"])
        self.assertEqual(fp["task"], "ner")
        self.assertEqual(fp["length"], len("DEFAULT TEXT"))

    def test_whitespace_only_override_picks_default(self):
        text, fp = resolve_system_prompt("   \n\t  ", "DEFAULT", task="edtf")
        self.assertEqual(text, "DEFAULT")
        self.assertFalse(fp["is_override"])

    def test_override_text_returned(self):
        override = "Du bist ein spezieller Kurator."
        text, fp = resolve_system_prompt(override, "DEFAULT", task="ner")
        self.assertEqual(text, override)
        self.assertTrue(fp["is_override"])
        self.assertEqual(fp["sha256"], hashlib.sha256(override.encode()).hexdigest())

    def test_fingerprint_records_default_sha(self):
        """The default's sha is always reported so the UI can compare."""
        default = "DEFAULT TEXT"
        _, fp = resolve_system_prompt("custom", default, task="ner")
        expected = hashlib.sha256(default.encode()).hexdigest()
        self.assertEqual(fp["default_sha256"], expected)
        self.assertNotEqual(fp["sha256"], fp["default_sha256"])

    def test_default_path_sha_equals_default_sha(self):
        default = "DEFAULT TEXT"
        _, fp = resolve_system_prompt("", default, task="ner")
        self.assertEqual(fp["sha256"], fp["default_sha256"])

    def test_preview_truncates_long_text(self):
        long = "x" * 1000
        fp = fingerprint_prompt(long)
        self.assertEqual(fp["length"], 1000)
        self.assertLessEqual(len(fp["preview"]), 1000)
        self.assertTrue(fp["preview"].endswith("…"))

    def test_preview_does_not_truncate_short(self):
        fp = fingerprint_prompt("kurz")
        self.assertEqual(fp["preview"], "kurz")
        self.assertFalse(fp["preview"].endswith("…"))


class TestNERSystemPromptCapture(unittest.TestCase):
    def test_ner_llm_returns_fingerprint_via_batch(self):
        from kwb.analyze.ner import ner_llm

        prov = MockProvider.with_defaults()
        ents, batch = ner_llm(
            [{"record_id": "r1", "text": "Goethe in Weimar.", "column": "title"}],
            prov,
        )
        self.assertIsNotNone(batch.system_prompt_used)
        self.assertFalse(batch.system_prompt_used["is_override"])
        self.assertEqual(batch.system_prompt_used["task"], "ner")

    def test_ner_llm_records_override(self):
        from kwb.analyze.ner import ner_llm

        prov = MockProvider.with_defaults()
        override = "Du bist ein Test-Kurator."
        _, batch = ner_llm(
            [{"record_id": "r1", "text": "Goethe", "column": "x"}],
            prov,
            system_prompt=override,
        )
        self.assertTrue(batch.system_prompt_used["is_override"])
        self.assertEqual(
            batch.system_prompt_used["sha256"],
            hashlib.sha256(override.encode()).hexdigest(),
        )

    def test_ner_hybrid_surfaces_fingerprint_on_result(self):
        import pandas as pd
        from kwb.analyze.ner import ner_hybrid

        df = pd.DataFrame({"record_id": ["r1"], "title": ["Goethe in Weimar."]})
        prov = MockProvider.with_defaults()
        result = ner_hybrid(
            df, columns=["title"], provider=prov,
            id_column="record_id", use_spacy=False, use_llm=True,
        )
        self.assertIsNotNone(result.system_prompt_used)
        self.assertEqual(result.system_prompt_used["task"], "ner")


class TestScanSystemPromptCapture(unittest.TestCase):
    def test_scan_problematic_terms_returns_fingerprint(self):
        import pandas as pd
        from kwb.analyze.ner import scan_problematic_terms

        df = pd.DataFrame({"record_id": ["r1"], "subject": ["Test"]})
        prov = MockProvider.with_defaults()
        _, batch = scan_problematic_terms(df, prov, id_column="record_id", sample_size=1)
        self.assertIsNotNone(batch.system_prompt_used)
        self.assertEqual(batch.system_prompt_used["task"], "problematic_terms")


class TestEDTFSystemPromptCapture(unittest.TestCase):
    def test_normalize_dates_llm_records_fingerprint(self):
        from kwb.enrich.edtf import _normalize_dates_llm

        prov = MockProvider.with_defaults()
        _, batch = _normalize_dates_llm(
            [{"record_id": "r1", "text": "ca. 1923"}],
            prov,
        )
        self.assertIsNotNone(batch.system_prompt_used)
        self.assertEqual(batch.system_prompt_used["task"], "edtf")


_FORCE_NO_FASTAPI = os.environ.get("KWB_FORCE_NO_FASTAPI") == "1"
try:
    if _FORCE_NO_FASTAPI:
        raise ImportError("FastAPI disabled for deterministic catalog checks")
    from fastapi.testclient import TestClient
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False

_skip_no_fastapi = unittest.skipUnless(
    _FASTAPI_AVAILABLE, "FastAPI not installed",
)


@_skip_no_fastapi
class TestDryRunEndpoint(unittest.TestCase):
    def _client(self):
        from kwb.api import deps
        from kwb.core.workspace import Workspace
        deps._state["datasets"] = {}
        deps._state["workspace"] = Workspace(name="test")
        from kwb.api.app import app
        return TestClient(app)

    def test_default_path(self):
        r = self._client().post(
            "/api/prompts/dry-run",
            json={"task": "ner", "system_prompt": ""},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["task"], "ner")
        self.assertFalse(body["fingerprint"]["is_override"])
        self.assertEqual(
            body["fingerprint"]["sha256"],
            body["fingerprint"]["default_sha256"],
        )

    def test_override_path(self):
        override = "Mein eigener Prompt."
        r = self._client().post(
            "/api/prompts/dry-run",
            json={"task": "edtf", "system_prompt": override},
        )
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["resolved"], override)
        self.assertTrue(body["fingerprint"]["is_override"])
        self.assertNotEqual(
            body["fingerprint"]["sha256"],
            body["fingerprint"]["default_sha256"],
        )

    def test_unknown_task_rejected(self):
        r = self._client().post(
            "/api/prompts/dry-run",
            json={"task": "bogus", "system_prompt": ""},
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()["status"], "error")


if __name__ == "__main__":
    unittest.main()
