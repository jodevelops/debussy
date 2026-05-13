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
from datetime import datetime, timezone
from typing import Any, Callable

from kwb.ai.provider import AIMessage, AIProvider, AIResponse
from kwb.core.utils import try_parse_json  # canonical location

logger = logging.getLogger(__name__)

# Backward-compatible alias so existing imports don't break
_try_parse_json = try_parse_json


@dataclass
class ParseFailure:
    """Record of a JSON parse failure from an LLM response."""
    record_id: str
    raw_response: str | None = None
    error_message: str | None = None

    @property
    def raw_response_preview(self) -> str:
        """First 200 chars of raw response for dashboard display."""
        if not self.raw_response:
            return ""
        return (self.raw_response[:200] + "...") if len(self.raw_response) > 200 else self.raw_response


@dataclass
class CompletionSummary:
    """Summary of completion rates and failure types for batch operations."""
    total_records: int = 0
    succeeded: int = 0
    llm_failed: int = 0
    parse_failed: int = 0
    empty_result: int = 0

    @property
    def completion_rate(self) -> float:
        """Fraction of records that produced usable results."""
        if self.total_records == 0:
            return 0.0
        return self.succeeded / self.total_records

    @property
    def completion_percentage(self) -> int:
        """Completion rate as integer percentage."""
        return round(self.completion_rate * 100)


@dataclass
class BatchResult:
    """Result of processing a single item in a batch."""
    record_id: str
    success: bool
    response: AIResponse | None = None
    parsed: dict[str, Any] | None = None
    error: str | None = None
    error_type: str | None = None
    duration_seconds: float = 0.0


@dataclass
class BatchReport:
    """Summary of a batch processing run.

    Provenance fields (provider_name, model, prompt_fn_name, started_at,
    finished_at) make different runs distinguishable. Without them, two
    BatchReports produced by different prompt functions or models look
    identical in storage.
    """
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    total_duration_seconds: float = 0.0
    results: list[BatchResult] = field(default_factory=list)
    parse_failures: list[ParseFailure] = field(default_factory=list)
    # Provenance — populated by process_batch.
    provider_name: str | None = None
    model: str | None = None
    prompt_fn_name: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    # #150: fingerprint of the resolved system prompt actually sent to the
    # model. Populated by the caller (e.g. ner_llm). See
    # kwb.ai.prompts.resolve_system_prompt.
    system_prompt_used: dict | None = None

    @property
    def success_rate(self) -> float:
        return self.succeeded / self.total if self.total > 0 else 0.0

    @property
    def avg_duration(self) -> float:
        durations = [r.duration_seconds for r in self.results if r.success]
        return sum(durations) / len(durations) if durations else 0.0


def _prompt_fn_name(fn: Callable[..., Any]) -> str:
    """Best-effort identifier for a prompt function (handles partial / lambda)."""
    name = getattr(fn, "__name__", None)
    if name and name != "<lambda>":
        return name
    inner = getattr(fn, "func", None)  # functools.partial
    if inner is not None:
        return getattr(inner, "__name__", repr(fn))
    return repr(fn)


def _provider_name(provider: AIProvider) -> str:
    """Identifier for the provider — class name is stable and readable."""
    return type(provider).__name__


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

    Exception handling philosophy:
    - Per-item failures (network, parse, provider errors) are captured into
      BatchResult and processing continues. The full exception type and
      stack trace are logged via logger.exception so curators can diagnose.
    - KeyboardInterrupt / SystemExit / BaseException are NOT caught and will
      abort the batch — that is intentional, since they signal operator or
      environment intent.

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
        BatchReport with all results and provenance metadata.
    """
    started_at = datetime.now(timezone.utc)
    report = BatchReport(
        total=len(items),
        provider_name=_provider_name(provider),
        model=model,
        prompt_fn_name=_prompt_fn_name(prompt_fn),
        started_at=started_at,
    )
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

            # Track parse failures: when response content exists but parsing failed
            if parsed is None and response.content and response.content.strip():
                report.parse_failures.append(ParseFailure(
                    record_id=record_id,
                    raw_response=response.content,
                    error_message="JSON parse failed"
                ))

            result = BatchResult(
                record_id=record_id,
                success=True,
                response=response,
                parsed=parsed,
                duration_seconds=duration,
            )
            report.succeeded += 1

        except Exception as e:
            # Per-item failure — log with full stack trace and continue.
            # KeyboardInterrupt / SystemExit are BaseException subclasses and
            # propagate, so an operator can still abort.
            duration = time.time() - item_start
            error_type = type(e).__name__
            result = BatchResult(
                record_id=record_id,
                success=False,
                error=str(e),
                error_type=error_type,
                duration_seconds=duration,
            )
            report.failed += 1
            logger.exception(
                "Batch item failed: record_id=%s error_type=%s",
                record_id, error_type,
            )

        report.results.append(result)

        if on_progress:
            on_progress(i + 1, len(items), result)

        if delay_seconds > 0 and i < len(items) - 1:
            time.sleep(delay_seconds)

    report.total_duration_seconds = time.time() - start_time
    report.finished_at = datetime.now(timezone.utc)
    return report
