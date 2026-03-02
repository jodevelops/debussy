"""
Mock AI provider for testing.

CHANGE: call_log now records the resolved model name so tests can
assert that the correct model was forwarded to the provider.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from kwb.ai.provider import AIMessage, AIProvider, AIResponse, ProviderConfig


class MockProvider(AIProvider):
    """
    Deterministic mock provider for testing.

    call_log entries now include the final model that was used,
    enabling assertions like:
        assert mock.call_log[0]["model"] == "gpt-oss-120b"
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
        resolved_model = model or self.config.default_model or "mock-model"

        self.call_log.append({
            "messages": messages,
            "model": resolved_model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "kwargs": kwargs,
        })

        for predicate, response in self.rules:
            if predicate(messages):
                return AIResponse(
                    content=response,
                    model=resolved_model,
                    usage={"prompt_tokens": 10, "completion_tokens": 20},
                )

        return AIResponse(
            content=self.default_response,
            model=resolved_model,
            usage={"prompt_tokens": 10, "completion_tokens": 20},
        )

    def is_available(self) -> bool:
        return True

    def list_models(self) -> list[str]:
        return ["mock-model", "mock-vision-model"]

    def reset_log(self) -> None:
        """Clear call_log between test cases."""
        self.call_log = []

    @staticmethod
    def with_defaults() -> "MockProvider":
        """Create a mock that returns realistic GLAM responses."""
        def _is_vision(msgs: list[AIMessage]) -> bool:
            return isinstance(msgs[-1].content, list)

        def _classify_rule(msgs: list[AIMessage]) -> bool:
            last = msgs[-1].content if isinstance(msgs[-1].content, str) else ""
            return "classif" in last.lower() or "klassif" in last.lower()

        classify_response = json.dumps({
            "category": "Architecture_Infrastructure",
            "confidence": 0.85,
            "reasoning": "Contains architectural terms (Minarett, Stadtmauer)",
            "suggested_terms": ["Minarett", "Stadtmauer"],
        })

        describe_response = json.dumps({
            "description": "Historische Schwarzweiss-Fotografie.",
            "objects": ["Minarett", "Stadtmauer"],
            "confidence": 0.80,
        })

        vision_response = json.dumps({
            "description": "Fotografische Aufnahme einer Landschaft.",
            "objects": ["Berge", "Vegetation"],
            "text_detected": "",
            "confidence": 0.75,
        })

        return MockProvider(
            rules=[
                (_is_vision, vision_response),
                (_classify_rule, classify_response),
            ],
            default_response=describe_response,
        )

    @staticmethod
    def with_ner_response(entities: list[dict]) -> "MockProvider":
        """Convenience factory for NER tests."""
        return MockProvider(
            default_response=json.dumps({"entities": entities})
        )

    @staticmethod
    def with_edtf_response(original: str, edtf: str, confidence: float = 0.9) -> "MockProvider":
        """Convenience factory for EDTF LLM fallback tests."""
        return MockProvider(
            default_response=json.dumps({
                "original": original,
                "edtf": edtf,
                "confidence": confidence,
                "note": "llm-converted",
            })
        )
