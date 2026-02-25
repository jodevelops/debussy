"""
GPUStack provider — connects to a local GPUStack instance.

GPUStack exposes an OpenAI-compatible API at /v1/chat/completions.
This provider also works with any OpenAI-compatible endpoint
(vLLM, LocalAI, text-generation-webui, etc.).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from kwb.ai.provider import AIMessage, AIProvider, AIResponse, ProviderConfig

logger = logging.getLogger(__name__)


def _message_to_dict(msg: AIMessage) -> dict[str, Any]:
    """Convert AIMessage to OpenAI API format.
    
    Handles both text-only and multimodal (vision) messages.
    For vision: content must be a list of content parts, not a string.
    """
    if isinstance(msg.content, str):
        return {"role": msg.role, "content": msg.content}
    
    # Multimodal message — content is a list of parts
    # Ensure format matches OpenAI vision API spec
    parts = []
    for item in msg.content:
        if item.get("type") == "text":
            parts.append({"type": "text", "text": item["text"]})
        elif item.get("type") == "image_url":
            parts.append({
                "type": "image_url",
                "image_url": {"url": item["image_url"]["url"]},
            })
    return {"role": msg.role, "content": parts}


class GPUStackProvider(AIProvider):
    """
    Provider for GPUStack and any OpenAI-compatible API.

    Config example:
        ProviderConfig(
            base_url="http://localhost:80",
            api_key="your-gpustack-key",
            default_model="qwen2.5-7b-instruct",
        )
    """

    def complete(
        self,
        messages: list[AIMessage],
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AIResponse:
        model = model or self.config.default_model
        url = f"{self.config.base_url.rstrip('/')}/v1/chat/completions"

        payload = {
            "model": model,
            "messages": [_message_to_dict(m) for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs,
        }

        headers = {
            "Content-Type": "application/json",
        }
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        data = json.dumps(payload).encode("utf-8")
        req = Request(url, data=data, headers=headers, method="POST")

        last_error = None
        for attempt in range(1, self.config.max_retries + 1):
            try:
                with urlopen(req, timeout=self.config.timeout_seconds) as resp:
                    result = json.loads(resp.read().decode("utf-8"))

                choice = result["choices"][0]
                return AIResponse(
                    content=choice["message"]["content"],
                    model=result.get("model", model),
                    usage=result.get("usage", {}),
                    raw=result,
                )

            except HTTPError as e:
                last_error = e
                body = e.read().decode("utf-8", errors="replace")
                logger.warning(f"Attempt {attempt}/{self.config.max_retries} failed: HTTP {e.code} — {body[:200]}")
                if e.code == 429:  # Rate limited
                    time.sleep(2 ** attempt)
                elif e.code >= 500:  # Server error — retry
                    time.sleep(1)
                else:
                    raise  # Client error — don't retry

            except (URLError, TimeoutError) as e:
                last_error = e
                logger.warning(f"Attempt {attempt}/{self.config.max_retries} failed: {e}")
                time.sleep(1)

        raise ConnectionError(
            f"Failed after {self.config.max_retries} attempts: {last_error}"
        )

    def is_available(self) -> bool:
        """Ping the models endpoint."""
        url = f"{self.config.base_url.rstrip('/')}/v1/models"
        headers = {}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=5) as resp:
                return resp.status == 200
        except Exception:
            return False

    def list_models(self) -> list[str]:
        """List available models from GPUStack."""
        url = f"{self.config.base_url.rstrip('/')}/v1/models"
        headers = {}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        try:
            req = Request(url, headers=headers)
            with urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return [m["id"] for m in result.get("data", [])]
        except Exception as e:
            logger.error(f"Failed to list models: {e}")
            return []
