"""
Batch processing for AI operations.

Handles the reality of processing 8,000+ records through a local LLM:
- Progress tracking
- Error resilience (skip failures, don't lose progress)
- Rate limiting
- Result collection with provenance
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from kwb.ai.provider import AIMessage, AIProvider, AIResponse
from kwb.core.utils import try_parse_json  # canonical location

logger = logging.getLogger(__name__)

# Backward-compatible alias so existing imports don't break
_try_parse_json = try_parse_json


@dataclass
class BatchResult:
    """Result of processing a single item in a batch."""
    record_id: str
    success: bool
    response: AIResponse | None = None
    parsed: dict[str, Any] | None = None
    error: str | None = None
    duration_seconds: float = 0.0


@dataclass
class BatchReport:
    """Summary of a batch processing run."""
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    total_duration_seconds: float = 0.0
    results: list[BatchResult] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return self.succeeded / self.total if self.total > 0 else 0.0

    @property
    def avg_duration(self) -> float:
        durations = [r.duration_seconds for r in self.results if r.success]
        return sum(durations) / len(durations) if durations else 0.0


def process_batch(
    provider: AIProvider,
    items: list[dict[str, Any]],
    prompt_fn: Callable[[dict[str, Any]], list[AIMessage]],
    id_field: str = "record_id",
    model: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 1024,
    delay_seconds: float = 0.0,
    on_progress: Callable[[int, int, BatchResult], None] | None = None,
) -> BatchReport:
    """
    Process a list of items through an AI provider.

    Args:
        provider: The AI provider to use.
        items: List of dicts, each representing one record.
        prompt_fn: Function that takes an item dict and returns messages.
        id_field: Key in each item dict for the record ID.
        model: Model to use (or provider default).
        temperature: Sampling temperature.
        max_tokens: Max response tokens.
        delay_seconds: Delay between requests (rate limiting).
        on_progress: Callback(current_index, total, result) for progress.

    Returns:
        BatchReport with all results.
    """
    report = BatchReport(total=len(items))
    start_time = time.time()

    for i, item in enumerate(items):
        record_id = item.get(id_field, f"item-{i}")
        item_start = time.time()

        try:
            messages = prompt_fn(item)
            response = provider.complete(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            parsed = try_parse_json(response.content)
            duration = time.time() - item_start

            result = BatchResult(
                record_id=record_id,
                success=True,
                response=response,
                parsed=parsed,
                duration_seconds=duration,
            )
            report.succeeded += 1

        except Exception as e:
            duration = time.time() - item_start
            result = BatchResult(
                record_id=record_id,
                success=False,
                error=str(e),
                duration_seconds=duration,
            )
            report.failed += 1
            logger.warning(f"Failed on {record_id}: {e}")

        report.results.append(result)

        if on_progress:
            on_progress(i + 1, len(items), result)

        if delay_seconds > 0 and i < len(items) - 1:
            time.sleep(delay_seconds)

    report.total_duration_seconds = time.time() - start_time
    return report
