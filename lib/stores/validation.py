"""Validation layer for telemetry data.

Catches data inconsistencies and provides confidence scores.
Dashboard displays warnings to user when data quality is questionable.
"""

from dataclasses import dataclass
from typing import Generic, List, TypeVar

from .interfaces import DaySummary, ToolCallRecord

T = TypeVar("T")


@dataclass
class ValidationResult(Generic[T]):
    """Result of validating telemetry data.

    Wraps the original data with confidence score and any warnings.
    Dashboard uses this to display data quality indicators.
    """

    data: T
    warnings: List[str]
    confidence: float  # 0.0 to 1.0, where 1.0 means fully confident


def validate_day_summary(summary: DaySummary) -> ValidationResult[DaySummary]:
    """Validate a daily summary and return with confidence score.

    Checks for common data inconsistencies:
    - Tool calls without token usage
    - Invalid cache ratio values
    - Cache hits exceeding tool calls
    - Summarizations accepted exceeding offered

    Args:
        summary: The DaySummary to validate.

    Returns:
        ValidationResult with the original data, warnings, and confidence score.
    """
    warnings: List[str] = []

    if summary.tool_calls > 0 and summary.total_tokens == 0:
        warnings.append(f"Inconsistent: {summary.tool_calls} calls but 0 tokens")

    if summary.cache_ratio < 0 or summary.cache_ratio > 1.0:
        warnings.append(
            f"Invalid cache ratio: {summary.cache_ratio:.2f} (expected 0.0-1.0)"
        )

    if summary.cache_hits > summary.tool_calls:
        warnings.append(
            f"Cache hits ({summary.cache_hits}) exceed tool calls ({summary.tool_calls})"
        )

    if summary.summarizations_accepted > summary.summarizations_offered:
        warnings.append(
            f"Summarizations accepted ({summary.summarizations_accepted}) "
            f"exceeds offered ({summary.summarizations_offered})"
        )

    if summary.total_tokens == 0 and summary.tool_calls == 0:
        warnings.append("No data recorded for this day")

    confidence = max(0.0, 1.0 - (len(warnings) * 0.2))

    return ValidationResult(data=summary, warnings=warnings, confidence=confidence)


def validate_tool_call(record: ToolCallRecord) -> ValidationResult[ToolCallRecord]:
    """Validate a tool call record.

    Checks for common data inconsistencies:
    - full_requested set without summary_size
    - Negative duration
    - Zero response size on non-cache-hit
    - Unusually long duration

    Args:
        record: The ToolCallRecord to validate.

    Returns:
        ValidationResult with the original data, warnings, and confidence score.
    """
    warnings: List[str] = []

    if record.full_requested and record.summary_size is None:
        warnings.append("full_requested is set but summary_size is missing")

    if record.duration_ms < 0:
        warnings.append(f"Negative duration: {record.duration_ms}ms")

    if not record.is_cache_hit and record.response_size == 0:
        warnings.append("Non-cache-hit call has 0 response_size")

    if record.duration_ms > 60000:
        warnings.append(f"Unusually long duration: {record.duration_ms}ms")

    confidence = max(0.0, 1.0 - (len(warnings) * 0.2))

    return ValidationResult(data=record, warnings=warnings, confidence=confidence)
