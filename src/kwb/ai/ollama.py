"""
Ollama provider — connects to a local Ollama instance.

Ollama exposes an OpenAI-compatible API at /v1/chat/completions (since v0.1.24).
This provider is the recommended choice for local development without a GPU cluster.

Usage:
    1. Install: https://ollama.com
    2. Pull a model: ollama pull qwen2.5:7b
    3. Set KWB_OLLAMA_URL=http://localhost:11434 in .env

Ollama requires no API key for local use.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

from kwb.ai.provider import AIMessage, AIProvider, AIResponse, message_to_openai_dict

logger = logging.getLogger(__name__)


class OllamaProvider(AIProvider):
    """
    Provider for Ollama (local model runner).

    Ollama uses an OpenAI-compatible API so most logic is identical to
    GPUStackProvider. Key differences:
    - No API key required for local use
    - Default port is 11434 (not 80)
    - Model names use ollama format: "qwen2.5:7b", "llama3.2:3b", etc.
    - /api/tags endpoint for model listing (not /v1/models)

    Config example:
        ProviderConfig(
            base_url="http://localhost:11434",
            api_key="",  # empty for local Ollama
            default_model="qwen2.5:7b",
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
            "messages": [message_to_openai_dict(m) for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            **kwargs,
        }

        headers = {"Content-Type": "application/json"}
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
                logger.warning(f"Attempt {attempt} failed: HTTP {e.code} — {body[:200]}")
                if e.code == 429:
                    time.sleep(2 ** attempt)
                    continue
                elif e.code >= 500:
                    time.sleep(1)
                    continue
                else:
                    raise

            except (URLError, TimeoutError) as e:
                last_error = e
                logger.warning(f"Attempt {attempt} failed: {e}")
                time.sleep(1)

        raise ConnectionError(
            f"Ollama: Failed after {self.config.max_retries} attempts: {last_error}"
        )

    def is_available(self) -> bool:
        """Check if Ollama is available via /api/tags endpoint (Ollama-specific)."""
        url = f"{self.config.base_url.rstrip('/')}/api/tags"
        try:
            req = Request(url)
            with urlopen(req, timeout=5) as resp:
                if resp.status != 200:
                    return False
                result = json.loads(resp.read().decode("utf-8"))
                return "models" in result
        except Exception:
            return False

    def list_models(self) -> list[str]:
        """List available models via Ollama /api/tags endpoint."""
        url = f"{self.config.base_url.rstrip('/')}/api/tags"
        try:
            req = Request(url)
            with urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                return [m["name"] for m in result.get("models", [])]
        except Exception as e:
            logger.error(f"Ollama: Failed to list models: {e}")
            return []

    @property
    def name(self) -> str:
        return "OllamaProvider"
