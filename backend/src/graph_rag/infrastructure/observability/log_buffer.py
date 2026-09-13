"""In-process ring buffer of application log events for the Admin console."""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime
from threading import Lock
from typing import Any

_MAX = 4_000
_LOCK = Lock()
_EVENTS: deque[dict[str, Any]] = deque(maxlen=_MAX)


def record_log_event(event: dict[str, Any]) -> None:
    payload = dict(event)
    payload.setdefault("timestamp", datetime.now(UTC).isoformat())
    with _LOCK:
        _EVENTS.append(payload)


def clear_log_events() -> None:
    with _LOCK:
        _EVENTS.clear()


def query_log_events(
    *,
    query: str | None = None,
    level: str | None = None,
    logger_name: str | None = None,
    correlation_id: str | None = None,
    document_id: str | None = None,
    pod: str | None = None,
    from_ts: str | None = None,
    until: str | None = None,
    limit: int = 100,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    with _LOCK:
        items = list(_EVENTS)
    counts = {"ERROR": 0, "INFO": 0, "WARNING": 0, "DEBUG": 0}
    for item in items:
        key = str(item.get("level") or "INFO").upper()
        if key in counts:
            counts[key] += 1
        elif key in {"ERR", "FATAL", "CRITICAL"}:
            counts["ERROR"] += 1
        elif key in {"WARN"}:
            counts["WARNING"] += 1
    filtered = items
    if query:
        needle = query.lower()
        filtered = [
            item
            for item in filtered
            if needle in str(item.get("event") or "").lower()
            or needle in str(item.get("logger") or "").lower()
            or needle in str(item.get("message") or "").lower()
        ]
    if level and level.upper() not in {"ALL", "ALL LEVELS", ""}:
        want = level.upper()
        filtered = [item for item in filtered if str(item.get("level") or "").upper() == want]
    if logger_name:
        filtered = [item for item in filtered if str(item.get("logger") or "") == logger_name]
    if correlation_id:
        filtered = [
            item for item in filtered if str(item.get("correlation_id") or "") == correlation_id
        ]
    if document_id:
        filtered = [item for item in filtered if str(item.get("document_id") or "") == document_id]
    if pod:
        filtered = [
            item for item in filtered if str(item.get("pod") or item.get("service") or "") == pod
        ]
    start = _parse_ts(from_ts)
    end = _parse_ts(until)
    if start is not None or end is not None:
        kept: list[dict[str, Any]] = []
        for item in filtered:
            stamp = _parse_ts(str(item.get("timestamp") or ""))
            if stamp is None:
                kept.append(item)
                continue
            if start is not None and stamp < start:
                continue
            if end is not None and stamp > end:
                continue
            kept.append(item)
        filtered = kept
    filtered = list(reversed(filtered))[: max(1, min(limit, 500))]
    return filtered, counts


def structlog_buffer_processor(
    _logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    level = str(event_dict.get("level") or method_name or "info").upper()
    record_log_event(
        {
            "timestamp": event_dict.get("timestamp"),
            "level": level,
            "event": event_dict.get("event"),
            "logger": event_dict.get("logger") or event_dict.get("logger_name"),
            "correlation_id": event_dict.get("correlation_id"),
            "document_id": event_dict.get("document_id"),
            "pathname": event_dict.get("pathname"),
            "func_name": event_dict.get("func_name"),
            "service": event_dict.get("service"),
            "pod": event_dict.get("pod") or event_dict.get("hostname"),
        }
    )
    return event_dict


def _parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        value = datetime.fromisoformat(text)
    except ValueError:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
