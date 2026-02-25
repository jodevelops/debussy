"""
Mock AI provider for testing.

Returns deterministic responses based on configurable rules.
This means every analyze/enrich module can be tested without a GPU.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from kwb.ai.provider import AIMessage, AIProvider, AIResponse, ProviderConfig


class MockProvider(AIProvider):
    """
    Deterministic mock provider for testing.

    Usage:
        mock = MockProvider.with_defaults()
        response = mock.complete([AIMessage.user("Classify: Minarett")])
        # Returns a predictable JSON classification

    Custom responses:
        mock = MockProvider.with_rules([
            (lambda msgs: "error" in msgs[-1].content.lower(), "ERROR RESPONSE"),
            (lambda msgs: True, '{"category": "default"}'),
        ])
    """

    def __init__(
        self,
        config: ProviderConfig | None = None,
        rules: list[tuple[Callable[[list[AIMessage]], bool], str]] | None = None,
        default_response: str = '{"status": "ok"}',
    ):
        super().__init__(config or ProviderConfig(base_url="mock://localhost"))
        self.rules = rules or []
        self.default_response = default_response
        self.call_log: list[dict[str, Any]] = []

    def complete(
        self,
        messages: list[AIMessage],
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> AIResponse:
        # Log the call for test assertions
        self.call_log.append({
            "messages": messages,
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "kwargs": kwargs,
        })

        # Find matching rule
        for predicate, response in self.rules:
            if predicate(messages):
                return AIResponse(
                    content=response,
                    model=model or "mock-model",
                    usage={"prompt_tokens": 10, "completion_tokens": 20},
                )

        return AIResponse(
            content=self.default_response,
            model=model or "mock-model",
            usage={"prompt_tokens": 10, "completion_tokens": 20},
        )

    def is_available(self) -> bool:
        return True

    def list_models(self) -> list[str]:
        return ["mock-model", "mock-vision-model"]

    @staticmethod
    def with_defaults() -> "MockProvider":
        """Create a mock that returns realistic GLAM responses."""
        def _classify_rule(msgs: list[AIMessage]) -> bool:
            last = msgs[-1].content if isinstance(msgs[-1].content, str) else ""
            return "classif" in last.lower() or "klassif" in last.lower()

        def _describe_rule(msgs: list[AIMessage]) -> bool:
            last = msgs[-1].content if isinstance(msgs[-1].content, str) else ""
            return "descri" in last.lower() or "beschreib" in last.lower()

        def _is_vision(msgs: list[AIMessage]) -> bool:
            last = msgs[-1]
            return isinstance(last.content, list)

        classify_response = json.dumps({
            "category": "Architecture_Infrastructure",
            "confidence": 0.85,
            "reasoning": "Contains architectural terms (Minarett, Stadtmauer)",
            "suggested_terms": ["Minarett", "Stadtmauer", "Islamische Architektur"],
        })

        describe_response = json.dumps({
            "description": "Historische Schwarzweiss-Fotografie einer befestigten Stadt mit Minarett und Stadtmauer in einer Wüstenlandschaft.",
            "objects": ["Minarett", "Stadtmauer", "Wüste", "Gebäude"],
            "confidence": 0.80,
        })

        vision_response = json.dumps({
            "description": "Fotografische Aufnahme einer Landschaft mit Bergen und Vegetation.",
            "objects": ["Berge", "Vegetation", "Himmel"],
            "text_detected": "",
            "confidence": 0.75,
        })

        return MockProvider(
            rules=[
                (_is_vision, vision_response),
                (_classify_rule, classify_response),
                (_describe_rule, describe_response),
            ],
            default_response=json.dumps({"status": "ok", "result": "no specific rule matched"}),
        )
