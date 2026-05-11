"""GPUStack provider — OpenAI-compatible API."""
from __future__ import annotations
import json
import logging
import time
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from kwb.ai.provider import (
    AIProvider,
    AIResponse,
    ProviderAuthError,
    ProviderBadRequestError,
    ProviderNetworkError,
    ProviderRateLimitError,
    ProviderServerError,
    message_to_openai_dict,
)

logger = logging.getLogger(__name__)

class GPUStackProvider(AIProvider):
    def complete(self, messages, model=None, temperature=0.0, max_tokens=1024, **kwargs):
        model = model or self.config.default_model
        url = f"{self.config.base_url.rstrip('/')}/v1/chat/completions"
        payload = {"model": model, "messages": [message_to_openai_dict(m) for m in messages],
                   "temperature": temperature, "max_tokens": max_tokens, **kwargs}
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        req = Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
        last_error = None
        last_body = ""
        for attempt in range(1, self.config.max_retries + 1):
            try:
                with urlopen(req, timeout=self.config.timeout_seconds) as resp:
                    result = json.loads(resp.read().decode())
                choice = result["choices"][0]
                return AIResponse(content=choice["message"]["content"],
                                  model=result.get("model", model),
                                  usage=result.get("usage", {}), raw=result)
            except HTTPError as e:
                last_error = e
                last_body = e.read().decode("utf-8", errors="replace")
                logger.warning(f"Attempt {attempt} HTTP {e.code}: {last_body[:200]}")
                if e.code in (401, 403):
                    raise ProviderAuthError(
                        f"GPUStack auth failed (HTTP {e.code}): check api_key — {last_body[:200]}"
                    ) from e
                if e.code == 429:
                    time.sleep(2 ** attempt)
                    continue
                elif e.code >= 500:
                    time.sleep(1)
                    continue
                else:
                    raise ProviderBadRequestError(
                        f"GPUStack bad request (HTTP {e.code}): {last_body[:200]}"
                    ) from e
            except (URLError, TimeoutError) as e:
                last_error = e; logger.warning(f"Attempt {attempt}: {e}"); time.sleep(1)
        # Retries exhausted — classify the final error so callers can triage.
        if isinstance(last_error, HTTPError):
            if last_error.code == 429:
                raise ProviderRateLimitError(
                    f"GPUStack rate limit after {self.config.max_retries} retries: {last_body[:200]}"
                ) from last_error
            raise ProviderServerError(
                f"GPUStack server error after {self.config.max_retries} retries "
                f"(HTTP {last_error.code}): {last_body[:200]}"
            ) from last_error
        raise ProviderNetworkError(
            f"GPUStack unreachable after {self.config.max_retries} attempts: {last_error}"
        ) from last_error

    def is_available(self):
        url = f"{self.config.base_url.rstrip('/')}/v1/models"
        headers = {}
        if self.config.api_key: headers["Authorization"] = f"Bearer {self.config.api_key}"
        try:
            with urlopen(Request(url, headers=headers), timeout=5) as resp:
                return resp.status == 200
        except: return False

    def list_models(self):
        url = f"{self.config.base_url.rstrip('/')}/v1/models"
        headers = {}
        if self.config.api_key: headers["Authorization"] = f"Bearer {self.config.api_key}"
        try:
            with urlopen(Request(url, headers=headers), timeout=10) as resp:
                return [m["id"] for m in json.loads(resp.read()).get("data", [])]
        except Exception as e:
            logger.error(f"Failed to list models: {e}"); return []
