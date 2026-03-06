"""Tests for export/goobi_api.py."""
from __future__ import annotations

import io
import json
import unittest
import urllib.error

from kwb.export.goobi_api import GoobiAPIClient, GoobiAPIConfig, GoobiAPIError


class _Resp:
    def __init__(self, payload: dict):
        self._buf = io.BytesIO(json.dumps(payload).encode("utf-8"))

    def read(self):
        return self._buf.read()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class TestGoobiAPIClient(unittest.TestCase):
    def test_status_success(self):
        cfg = GoobiAPIConfig(base_url="https://goobi.example.org", api_key="secret", project="demo")

        def opener(req, timeout=0):
            self.assertEqual(req.full_url, "https://goobi.example.org/api/status")
            self.assertEqual(req.get_method(), "GET")
            self.assertEqual(req.headers.get("X-api-key"), "secret")
            self.assertGreater(timeout, 0)
            return _Resp({"ok": True})

        c = GoobiAPIClient(cfg, opener=opener)
        out = c.status()
        self.assertTrue(out["ok"])

    def test_push_record_payload(self):
        cfg = GoobiAPIConfig(base_url="https://goobi.example.org", project="projA")

        def opener(req, timeout=0):
            body = json.loads(req.data.decode("utf-8"))
            self.assertEqual(body["record_id"], "r-1")
            self.assertEqual(body["project"], "projA")
            self.assertIn("xml", body)
            return _Resp({"imported": 1})

        c = GoobiAPIClient(cfg, opener=opener)
        out = c.push_record_xml("<goobi-import/>", record_id="r-1")
        self.assertEqual(out["imported"], 1)

    def test_not_configured(self):
        c = GoobiAPIClient(GoobiAPIConfig(base_url=""))
        with self.assertRaises(GoobiAPIError):
            c.status()

    def test_http_error_wrapped(self):
        cfg = GoobiAPIConfig(base_url="https://goobi.example.org")

        def opener(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 500, "boom", hdrs=None, fp=io.BytesIO(b"upstream"))

        c = GoobiAPIClient(cfg, opener=opener)
        with self.assertRaises(GoobiAPIError) as ex:
            c.status()
        self.assertIn("HTTP 500", str(ex.exception))


if __name__ == "__main__":
    unittest.main()
