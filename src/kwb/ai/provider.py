"""
Abstract AI provider interface.

Every AI backend (GPUStack, Ollama, OpenAI, Mock) implements this interface.
The rest of the codebase never touches HTTP directly — it talks to a Provider.

This is the single most important abstraction in the project:
- swap providers without changing analysis code
- test without a GPU
- support future backends without refactoring
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ModelCapability(str, Enum):
    """What can a model do?"""
    TEXT = "text"               # Text generation / classification
    VISION = "vision"           # Image understanding
    EMBEDDING = "embedding"     # Vector embeddings


@dataclass
class AIMessage:
    """A single message in a conversation."""
    role: str  # "system", "user", "assistant"
    content: str | list[dict[str, Any]]  # str for text, list for multimodal

    @staticmethod
    def system(text: str) -> "AIMessage":
        return AIMessage(role="system", content=text)

    @staticmethod
    def user(text: str) -> "AIMessage":
        return AIMessage(role="user", content=text)

    @staticmethod
    def user_with_image(text: str, image_base64: str, mime_type: str = "image/jpeg") -> "AIMessage":
        """Create a multimodal message with text + image."""
        return AIMessage(
            role="user",
            content=[
                {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{image_base64}"}},
                {"type": "text", "text": text},
            ],
        )


@dataclass
class AIResponse:
    """Response from an AI provider."""
    content: str
    model: str
    usage: dict[str, int] = field(default_factory=dict)  # prompt_tokens, completion_tokens
    raw: dict[str, Any] = field(default_factory=dict)     # full API response for debugging


@dataclass
class ProviderConfig:
    """Configuration for an AI provider."""
    base_url: str
    api_key: str = ""
    default_model: str = ""
    timeout_seconds: int = 120
    max_retries: int = 3


class AIProvider(ABC):
    """
    Abstract base class for all AI providers.

    Usage:
        provider = GPUStackProvider(config)
        response = provider.complete([
            AIMessage.system("You are a GLAM metadata expert."),
            AIMessage.user("Classify this subject: 'Minarett; Stadtmauer'"),
        ])
        print(response.content)
    """

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
    ) -> AIResponse:
        """Send a completion request and return the response."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Check if the provider is reachable."""
        ...

    @abstractmethod
    def list_models(self) -> list[str]:
        """List available models."""
        ...

    @property
    def name(self) -> str:
        return self.__class__.__name__
