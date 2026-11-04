"""Derived member-facing progress. It is not stored on the run row."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from graph_rag.domain.ingestion.stages import SUCCESSFUL_STAGE_STATUSES

_TERMINAL = {
    "completed": "ready",
    "completed_with_warnings": "ready",
    "partial": "partial",
    "failed": "failed",
    "cancelled": "cancelled",
}


def derive_progress_state(
    status: str,
    heartbeat_at: datetime | None,
    *,
    now: datetime | None = None,
    stall_after: timedelta = timedelta(seconds=120),
    created_at: datetime | None = None,
) -> str:
    """Report a stall only after the stall window with no heartbeat.

    A run that has just been accepted has no heartbeat yet. That gap is the
    worker picking up the job, not a stall. Callers that know when the run was
    created pass ``created_at`` so the window starts there. Callers that pass
    neither a heartbeat nor a creation time still report stalled.
    """
    mapped = _TERMINAL.get(status)
    if mapped is not None:
        return mapped
    current = now or datetime.now(UTC)
    stamp = heartbeat_at if heartbeat_at is not None else created_at
    if stamp is None:
        return "stalled"
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    if current - stamp >= stall_after:
        return "stalled"
    return "running"


def last_completed_stage(stages: list[object]) -> str | None:
    last: str | None = None
    for stage in stages:
        status = getattr(stage, "status", None)
        value = getattr(status, "value", status)
        if value in {item.value for item in SUCCESSFUL_STAGE_STATUSES} or value in {
            "completed",
            "completed_with_warnings",
        }:
            name = getattr(stage, "stage", None)
            last = getattr(name, "value", name)
    return None if last is None else str(last)
