"""Abstract AI provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Exception taxonomy (#149)
# ---------------------------------------------------------------------------
# Raw HTTPError / URLError leak HTTP details into business code and force
# every caller to inspect status codes to triage. The classes below let
# callers catch the specific failure mode they can handle.

class ProviderError(Exception):
    """Base class for all provider-related errors."""


class ProviderAuthError(ProviderError):
    """Authentication failed (401/403). API key wrong, missing, or revoked."""


class ProviderRateLimitError(ProviderError):
    """Rate limit hit (429) and retries were exhausted."""


class ProviderServerError(ProviderError):
    """Provider returned 5xx after all retries — provider is unhealthy."""


class ProviderNetworkError(ProviderError, ConnectionError):
    """Connection failed entirely (timeout, refused, DNS) — provider unreachable.

    Inherits from ConnectionError so existing ``except ConnectionError``
    handlers keep catching network failures.
    """


class ProviderBadRequestError(ProviderError):
    """Provider returned 4xx other than 401/403/429 — request was malformed."""


def message_to_openai_dict(msg: "AIMessage") -> dict[str, Any]:
    """Convert AIMessage to OpenAI API format.

    Handles both text-only and multimodal (text+image) messages.
    Unknown content types are silently dropped (#145).
    """
    if isinstance(msg.content, str):
        return {"role": msg.role, "content": msg.content}

    parts = []
    for item in msg.content:
        item_type = item.get("type")
        if item_type == "text":
            parts.append({"type": "text", "text": item["text"]})
        elif item_type == "image_url":
            parts.append({
                "type": "image_url",
                "image_url": {"url": item["image_url"]["url"]},
            })
        # else: unknown type, silently dropped

    return {"role": msg.role, "content": parts}


@dataclass
class AIMessage:
    role: str
    content: str | list[dict[str, Any]]

    @staticmethod
    def system(text: str) -> "AIMessage":
        return AIMessage(role="system", content=text)

    @staticmethod
    def user(text: str) -> "AIMessage":
        return AIMessage(role="user", content=text)

    @staticmethod
    def user_with_image(text: str, image_base64: str, mime_type: str = "image/jpeg") -> "AIMessage":
        return AIMessage(
            role="user",
            content=[
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_base64}"}},
                {"type": "text", "text": text},
            ],
        )


@dataclass
class AIResponse:
    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


# Discriminator values for ProviderConfig.provider_type.
# Used by factory code to dispatch to the correct provider class without
# guessing from base_url (which is fragile — Ollama and GPUStack URLs look
# similar). Keeps misconfiguration loud instead of silent (#147).
PROVIDER_TYPE_GPUSTACK = "gpustack"
PROVIDER_TYPE_OLLAMA = "ollama"
PROVIDER_TYPE_MOCK = "mock"

VALID_PROVIDER_TYPES = frozenset({
    PROVIDER_TYPE_GPUSTACK,
    PROVIDER_TYPE_OLLAMA,
    PROVIDER_TYPE_MOCK,
})


@dataclass
class ProviderConfig:
    """Configuration for an AI provider.

    The ``provider_type`` field is a discriminator that maps a config to
    a specific provider implementation. Without it, the wrong provider
    class may be instantiated against a URL it doesn't speak (e.g.,
    pointing GPUStackProvider at an Ollama endpoint), producing
    confusing wrong-API errors instead of a clear configuration error.
    """
    base_url: str
    api_key: str = ""
    default_model: str = ""
    timeout_seconds: int = 120
    max_retries: int = 3
    provider_type: str = PROVIDER_TYPE_GPUSTACK

    def __post_init__(self) -> None:
        if self.provider_type not in VALID_PROVIDER_TYPES:
            raise ValueError(
                f"Invalid provider_type {self.provider_type!r}. "
                f"Must be one of: {sorted(VALID_PROVIDER_TYPES)}"
            )


class AIProvider(ABC):
    def __init__(self, config: ProviderConfig):
        self.config = config

    @abstractmethod
    def complete(
        self,
        messages: list[AIMessage],
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AIResponse: ...

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def list_models(self) -> list[str]: ...

    @property
    def name(self) -> str:
        return self.__class__.__name__
