"""GPUStack provider — OpenAI-compatible API."""
from __future__ import annotations
import json, logging, time
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
from kwb.ai.provider import AIMessage, AIProvider, AIResponse, ProviderConfig

logger = logging.getLogger(__name__)

def _message_to_dict(msg):
    if isinstance(msg.content, str):
        return {"role": msg.role, "content": msg.content}
    parts = []
    for item in msg.content:
        if item.get("type") == "text":
            parts.append({"type": "text", "text": item["text"]})
        elif item.get("type") == "image_url":
            parts.append({"type": "image_url", "image_url": {"url": item["image_url"]["url"]}})
    return {"role": msg.role, "content": parts}

class GPUStackProvider(AIProvider):
    def complete(self, messages, model=None, temperature=0.0, max_tokens=1024, **kwargs):
        model = model or self.config.default_model
        url = f"{self.config.base_url.rstrip('/')}/v1/chat/completions"
        payload = {"model": model, "messages": [_message_to_dict(m) for m in messages],
                   "temperature": temperature, "max_tokens": max_tokens, **kwargs}
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        req = Request(url, data=json.dumps(payload).encode(), headers=headers, method="POST")
        last_error = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                with urlopen(req, timeout=self.config.timeout_seconds) as resp:
                    result = json.loads(resp.read().decode())
                choice = result["choices"][0]
                return AIResponse(content=choice["message"]["content"],
                                  model=result.get("model", model),
                                  usage=result.get("usage", {}), raw=result)
            except HTTPError as e:
                last_error = e; body = e.read().decode("utf-8", errors="replace")
                logger.warning(f"Attempt {attempt} HTTP {e.code}: {body[:200]}")
                if e.code == 429: time.sleep(2 ** attempt)
                elif e.code >= 500: time.sleep(1)
                else: raise
            except (URLError, TimeoutError) as e:
                last_error = e; logger.warning(f"Attempt {attempt}: {e}"); time.sleep(1)
        raise ConnectionError(f"Failed after {self.config.max_retries} attempts: {last_error}")

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
