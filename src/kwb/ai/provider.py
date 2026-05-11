"""Abstract AI provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


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


@dataclass
class ProviderConfig:
    base_url: str
    api_key: str = ""
    default_model: str = ""
    timeout_seconds: int = 120
    max_retries: int = 3


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
