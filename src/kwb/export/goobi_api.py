"""Goobi REST API client utilities (F32)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class GoobiAPIConfig:
    base_url: str = ""
    api_key: str = ""
    project: str = ""
    timeout_seconds: int = 30

    @property
    def configured(self) -> bool:
        return bool(self.base_url)


class GoobiAPIError(RuntimeError):
    """Raised when Goobi API requests fail."""


class GoobiAPIClient:
    """Small JSON client with testable transport override."""

    def __init__(self, config: GoobiAPIConfig, opener=None):
        self.config = config
        self._opener = opener or urllib.request.urlopen

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        if self.config.api_key:
            headers["X-API-Key"] = self.config.api_key
        return headers

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.config.configured:
            raise GoobiAPIError("Goobi API nicht konfiguriert")

        url = self.config.base_url.rstrip("/") + "/" + path.lstrip("/")
        data = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(url=url, data=data, method=method, headers=self._headers())
        try:
            with self._opener(req, timeout=self.config.timeout_seconds) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else str(e)
            raise GoobiAPIError(f"HTTP {e.code}: {msg}") from e
        except urllib.error.URLError as e:
            raise GoobiAPIError(f"Verbindung fehlgeschlagen: {e.reason}") from e
        except json.JSONDecodeError as e:
            raise GoobiAPIError("Ungültige JSON-Antwort von Goobi API") from e

    def status(self) -> dict[str, Any]:
        """Check remote API health/capabilities endpoint."""
        return self._request("GET", "/api/status")

    def push_record_xml(self, xml: str, record_id: str = "") -> dict[str, Any]:
        payload: dict[str, Any] = {"xml": xml}
        if record_id:
            payload["record_id"] = record_id
        if self.config.project:
            payload["project"] = self.config.project
        return self._request("POST", "/api/import/record", payload)

    def push_batch_xml(self, xml: str, dataset: str = "") -> dict[str, Any]:
        payload: dict[str, Any] = {"xml": xml}
        if dataset:
            payload["dataset"] = dataset
        if self.config.project:
            payload["project"] = self.config.project
        return self._request("POST", "/api/import/batch", payload)
