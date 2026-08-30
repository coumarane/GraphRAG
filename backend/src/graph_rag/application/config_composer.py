"""Config composer: read-only current-config view + validate-and-diff preview.

No live writes, deliberately. ``get_settings()`` is a process-wide
``@lru_cache`` singleton with no cross-replica invalidation -- a "save"
button changing one pod's in-memory settings would be broken in a
multi-replica deployment by construction. The whole config surface is
already GitOps-managed (CI on ``backend/src/**`` -> ArgoCD/Harbor deploy);
a second, out-of-band mutable config path would fight that model instead of
extending it.

Instead this renders a YAML diff for the operator to copy into a PR. Git's
own merge-conflict/review process is the concurrency control here -- there
is no live mutable state to race on, so there is nothing to lock.

Parser profile *content* is intentionally read-only in this module: making
``ParsingSettings.profiles`` actually drive ingestion routing is the
plugin-architecture plan's Phase 1 scope
(see ``docs/plugin-architecture-plan.md``), not this one's.
"""

from __future__ import annotations

import difflib
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field
from pydantic import ValidationError as PydanticValidationError

from graph_rag.config.settings import ChunkingSettings, RetrievalSettings, Settings

EDITABLE_SECTIONS: tuple[str, ...] = ("chunking", "retrieval")


class CurrentConfigResponse(BaseModel):
    """Read-only snapshot of the composer's editable + reference config."""

    model_config = ConfigDict(extra="forbid")

    chunking: dict[str, Any]
    retrieval: dict[str, Any]
    parser_default_profile: str
    parser_profile_primary: str | None = None
    parser_profile_editable: bool = False


class ConfigPreviewRequest(BaseModel):
    """Proposed partial overrides for the editable sections."""

    model_config = ConfigDict(extra="forbid")

    chunking: dict[str, Any] = Field(default_factory=dict)
    retrieval: dict[str, Any] = Field(default_factory=dict)


class ConfigPreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valid: bool
    errors: list[str] = Field(default_factory=list)
    diff: str = ""
    target_file: str = "backend/config/default.yaml"


def build_current_config(settings: Settings) -> CurrentConfigResponse:
    profile = settings.parsing.profiles.get(settings.parsing.default_profile)
    return CurrentConfigResponse(
        chunking=settings.chunking.model_dump(mode="json"),
        retrieval=settings.retrieval.model_dump(mode="json"),
        parser_default_profile=settings.parsing.default_profile,
        parser_profile_primary=profile.primary if profile is not None else None,
        parser_profile_editable=False,
    )


def _validation_messages(exc: PydanticValidationError, *, section: str) -> list[str]:
    return [
        f"{section}.{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
        for error in exc.errors()
    ]


def _section_yaml(section: str, values: dict[str, Any]) -> str:
    return yaml.safe_dump({section: values}, sort_keys=False)


def preview_config_change(
    settings: Settings, request: ConfigPreviewRequest
) -> ConfigPreviewResponse:
    """Validate a proposed override and render it as a YAML diff. No writes."""
    errors: list[str] = []
    merged_chunking = {**settings.chunking.model_dump(mode="json"), **request.chunking}
    merged_retrieval = {**settings.retrieval.model_dump(mode="json"), **request.retrieval}

    try:
        ChunkingSettings(**merged_chunking)
    except PydanticValidationError as exc:
        errors.extend(_validation_messages(exc, section="chunking"))
    try:
        RetrievalSettings(**merged_retrieval)
    except PydanticValidationError as exc:
        errors.extend(_validation_messages(exc, section="retrieval"))

    if errors:
        return ConfigPreviewResponse(valid=False, errors=errors)

    diff_parts: list[str] = []
    if request.chunking:
        diff_parts.append(
            "".join(
                difflib.unified_diff(
                    _section_yaml("chunking", settings.chunking.model_dump(mode="json")).splitlines(
                        keepends=True
                    ),
                    _section_yaml("chunking", merged_chunking).splitlines(keepends=True),
                    fromfile="chunking (current)",
                    tofile="chunking (proposed)",
                )
            )
        )
    if request.retrieval:
        diff_parts.append(
            "".join(
                difflib.unified_diff(
                    _section_yaml(
                        "retrieval", settings.retrieval.model_dump(mode="json")
                    ).splitlines(keepends=True),
                    _section_yaml("retrieval", merged_retrieval).splitlines(keepends=True),
                    fromfile="retrieval (current)",
                    tofile="retrieval (proposed)",
                )
            )
        )

    return ConfigPreviewResponse(valid=True, diff="\n".join(diff_parts))
