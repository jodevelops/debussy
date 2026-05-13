"""
Tests for system-prompt fingerprint in streaming endpoints (#150 follow-up).

Codex review on PR #215 flagged that ``system_prompt_used`` was added to
the non-streaming /api/scan and /api/edtf responses but missing from
the corresponding /stream variants — which is what the dashboard uses
in practice. These tests assert the fingerprint shows up in the final
SSE ``done`` payload for both stream endpoints.
"""
from __future__ import annotations

import io
import json
import os
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

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


_SAMPLE_CSV = (
    b"record_id,title,year,subject\n"
    b"r1,Karte Bern,1923,Stadtplan\n"
    b"r2,Foto Bern,ca. 1850,Fotografie\n"
    b"r3,Plan Bern,1901,Plan\n"
)


def _client():
    from kwb.api import deps
    from kwb.core.workspace import Workspace
    deps._state["datasets"] = {}
    deps._state["report"] = None
    deps._state["workspace"] = Workspace(name="test")
    deps._config_cache = None
    from kwb.api.app import app
    from kwb.ai.mock import MockProvider
    deps._prov_override = MockProvider.with_defaults()
    return TestClient(app)


def _upload(client, name="data.csv"):
    client.post(
        "/api/analyze",
        files=[("files", (name, io.BytesIO(_SAMPLE_CSV), "text/csv"))],
    )


def _final_done(text: str) -> dict:
    """Pull the last SSE ``done`` event payload out of a stream response."""
    matches = re.findall(r"data: ({.*?})\n\n", text)
    self_test = []
    for raw in matches:
        try:
            evt = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if evt.get("type") == "done":
            self_test.append(evt)
    assert self_test, f"No done event found in stream:\n{text[:500]}"
    return self_test[-1]


@_skip_no_fastapi
class TestScanStreamFingerprint(unittest.TestCase):
    def test_scan_stream_includes_fingerprint_on_done(self):
        client = _client()
        _upload(client, "scan.csv")
        with client.stream(
            "POST",
            "/api/scan/stream",
            json={"dataset": "scan.csv", "sample_size": 2},
        ) as resp:
            self.assertEqual(resp.status_code, 200)
            text = "".join(chunk for chunk in resp.iter_text())
        done = _final_done(text)
        result = done["result"]
        self.assertIn("system_prompt_used", result)
        fp = result["system_prompt_used"]
        # When a scan actually invoked the LLM the fingerprint must be a dict
        # with a sha256. If no items reached the provider (e.g. all blank) the
        # field is null — accept either but never absent.
        self.assertTrue(fp is None or "sha256" in fp)
        if fp is not None:
            self.assertEqual(fp.get("task"), "problematic_terms")


@_skip_no_fastapi
class TestEDTFStreamFingerprint(unittest.TestCase):
    def test_edtf_stream_with_llm_includes_fingerprint(self):
        client = _client()
        _upload(client, "edtf.csv")
        with client.stream(
            "POST",
            "/api/edtf/stream",
            json={
                "dataset": "edtf.csv",
                "column": "year",
                "use_llm": True,
            },
        ) as resp:
            self.assertEqual(resp.status_code, 200)
            text = "".join(chunk for chunk in resp.iter_text())
        done = _final_done(text)
        result = done["result"]
        self.assertIn("system_prompt_used", result)

    def test_edtf_stream_without_llm_still_has_field(self):
        """Even rules-only runs should report system_prompt_used (likely null)."""
        client = _client()
        _upload(client, "edtf.csv")
        with client.stream(
            "POST",
            "/api/edtf/stream",
            json={
                "dataset": "edtf.csv",
                "column": "year",
                "use_llm": False,
            },
        ) as resp:
            text = "".join(chunk for chunk in resp.iter_text())
        done = _final_done(text)
        # Key must exist so the dashboard never crashes on a missing field
        self.assertIn("system_prompt_used", done["result"])


if __name__ == "__main__":
    unittest.main()
