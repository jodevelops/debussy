"""
Mock AI provider for testing.

CHANGE: call_log now records the resolved model name so tests can
assert that the correct model was forwarded to the provider.
"""

from __future__ import annotations

import json
from typing import Any, Callable

from kwb.ai.provider import (
    AIMessage,
    AIProvider,
    AIResponse,
    PROVIDER_TYPE_MOCK,
    ProviderConfig,
)


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
        super().__init__(
            config
            or ProviderConfig(base_url="mock://localhost", provider_type=PROVIDER_TYPE_MOCK)
        )
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
            # Only match when an actual image_url part is present.
            # Previous check (isinstance(content, list)) matched any
            # multimodal-shaped message even if no image was attached (#144).
            content = msgs[-1].content
            if not isinstance(content, list):
                return False
            return any(
                isinstance(part, dict) and part.get("type") == "image_url"
                for part in content
            )

        def _classify_rule(msgs: list[AIMessage]) -> bool:
            # Inspect all text parts, not just the last message's content,
            # so a multimodal message with text "klassifiziere" still routes
            # correctly when no image is attached.
            content = msgs[-1].content
            if isinstance(content, str):
                text = content
            else:
                text = " ".join(
                    part.get("text", "") for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                )
            text_lower = text.lower()
            return "classif" in text_lower or "klassif" in text_lower

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

    @staticmethod
    def with_quality_check_responses(
        cell_issue_type: str = "semantic_misplacement",
        cell_severity: str = "warning",
        cell_confidence: float = 0.88,
    ) -> "MockProvider":
        """
        Convenience factory for LLM quality-check tests.

        Returns deterministic structured responses for cell-, column-, record-
        and dataset-level quality prompts based on keyword detection.
        """
        def _is_cell_check(msgs: list) -> bool:
            last = msgs[-1].content if isinstance(msgs[-1].content, str) else ""
            return "Zellwert" in last or "cell" in last.lower()

        def _is_column_check(msgs: list) -> bool:
            last = msgs[-1].content if isinstance(msgs[-1].content, str) else ""
            return "Feldreinheit" in last or "field_purity_score" in last

        def _is_record_check(msgs: list) -> bool:
            last = msgs[-1].content if isinstance(msgs[-1].content, str) else ""
            return "Datensatz-ID" in last or "overall_confidence" in last

        def _is_dataset_check(msgs: list) -> bool:
            last = msgs[-1].content if isinstance(msgs[-1].content, str) else ""
            return "dominant_error_families" in last or "work_package_candidates" in last

        cell_response = json.dumps({
            "value": "Kutsche",
            "field": "location_place_name",
            "issue_type": cell_issue_type,
            "severity": cell_severity,
            "confidence": cell_confidence,
            "reasoning": "Der Wert bezeichnet kein benanntes geografisches Objekt.",
            "evidence": {"expected": "Toponym", "found": "Sachbegriff"},
            "suggested_target_field": "subject_general",
            "suggested_action": "move_or_review",
            "review_required": True,
        })

        column_response = json.dumps({
            "column": "location_place_name",
            "field_purity_score": 62.0,
            "dominant_issue_types": ["semantic_misplacement", "generic"],
            "typical_problems": ["Sachbegriffe statt Ortsnamen", "generische Motivbegriffe"],
            "affected_value_examples": ["Kutsche", "Eisenbahnbrücke", "Felder"],
            "suggested_action": "Nicht-Toponyme in Subject-Feld verschieben",
            "confidence": 0.85,
            "reasoning": "Mehrere Werte sind keine benannten Orte.",
            "review_required": True,
        })

        record_response = json.dumps({
            "record_id": "obj-001",
            "severity": "warning",
            "conflicts": [
                {
                    "fields": ["date_created", "date_issued"],
                    "description": "Herausgabedatum liegt vor dem Entstehungsdatum.",
                    "confidence": 0.79,
                }
            ],
            "overall_confidence": 0.79,
            "reasoning": "Zeitliche Inkonsistenz zwischen Entstehungs- und Herausgabedatum.",
            "review_required": True,
        })

        dataset_response = json.dumps({
            "dominant_error_families": [
                "Semantische Fehlplatzierung von Sachbegriffen in Ortsfeldern"
            ],
            "at_risk_columns": ["location_place_name"],
            "issue_clusters": [
                {
                    "label": "Nicht-Toponyme in Ortsfeldern",
                    "affected_columns": ["location_place_name"],
                    "count": 12,
                    "severity": "warning",
                    "suggested_action": "In Subject-Feld verschieben",
                }
            ],
            "work_package_candidates": [
                {
                    "title": "Semantische Umsortierung generischer Nicht-Toponyme",
                    "description": "Sachbegriffe aus location_place_name in subject_general verschieben.",
                    "priority": "warning",
                    "affected_columns": ["location_place_name"],
                    "estimated_records": 12,
                    "action_type": "move_or_review",
                }
            ],
            "risk_summary": "Ortsfeld enthält systematisch fehlplatzierte Sachbegriffe.",
            "confidence": 0.87,
        })

        return MockProvider(
            rules=[
                (_is_dataset_check, dataset_response),
                (_is_record_check, record_response),
                (_is_column_check, column_response),
                (_is_cell_check, cell_response),
            ],
            default_response=cell_response,
        )
