"""Normalize ABAC attributes used for user permission management."""

from __future__ import annotations

from typing import Any, cast

from graph_rag.domain.auth.models import UserRecord, UserStatus
from graph_rag.domain.types import JsonValue

BOOL_ATTRS = ("admin", "can_ingest")
STRING_ATTRS = (
    "department",
    "country",
    "business_unit",
    "job_level",
    "cost_center",
    "employment_type",
)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "on"}
    return False


def _as_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_groups(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        parts = value.replace(";", ",").split(",")
        return [part.strip() for part in parts if part.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def _as_clearance(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_user_attributes(
    attributes: dict[str, JsonValue] | None,
    *,
    role: str,
    default_can_ingest: bool | None = None,
) -> dict[str, JsonValue]:
    """Return a sanitized attributes dict aligned with the user's role.

    Workspace ``admin`` role always sets ``attributes.admin``. Member role
    clears that flag so leftover ABAC admin grants cannot outlive a demotion.
    """
    raw = dict(attributes or {})
    normalized: dict[str, JsonValue] = {}

    for key, value in raw.items():
        if key in BOOL_ATTRS or key in STRING_ATTRS:
            continue
        if key in {"groups", "clearance_level", "admin", "can_ingest"}:
            continue
        if value is None or value == "":
            continue
        normalized[key] = value

    role_key = (role or "member").strip().casefold() or "member"
    normalized["admin"] = role_key == "admin"

    if "can_ingest" in raw:
        normalized["can_ingest"] = _as_bool(raw.get("can_ingest"))
    elif default_can_ingest is not None:
        normalized["can_ingest"] = default_can_ingest

    clearance = _as_clearance(raw.get("clearance_level"))
    if clearance is not None:
        normalized["clearance_level"] = max(0, clearance)

    groups = _as_groups(raw.get("groups"))
    if groups:
        normalized["groups"] = cast(JsonValue, groups)

    for key in STRING_ATTRS:
        text = _as_optional_str(raw.get(key))
        if text is not None:
            normalized[key] = text

    return normalized


def apply_user_permission_update(
    user: UserRecord,
    *,
    display_name: str | None = None,
    role: str | None = None,
    status: UserStatus | None = None,
    attributes: dict[str, JsonValue] | None = None,
) -> UserRecord:
    """Apply a PATCH payload onto a persisted user record."""
    next_role = (role if role is not None else user.role).strip().casefold() or "member"
    next_status = status if status is not None else user.status
    merged = dict(user.attributes)
    if attributes is not None:
        merged.update(attributes)
        for key, value in attributes.items():
            if value is None or value == "":
                merged.pop(key, None)
    next_attrs = normalize_user_attributes(merged, role=next_role)
    next_name = user.display_name if display_name is None else (display_name.strip() or None)
    return user.model_copy(
        update={
            "display_name": next_name,
            "role": next_role,
            "status": next_status,
            "is_active": next_status == UserStatus.ACTIVE,
            "attributes": next_attrs,
        }
    )
