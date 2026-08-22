"""Sticky conversation context: first Q/A establishes the retrieval pin.

Follow-ups stay inside that context until the user explicitly switches topic
or consents to search other documents.
"""

from __future__ import annotations

import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.domain.conversation.context_resolver import QueryContextResolver


class ActiveConversationContext(BaseModel):
    """Client/server shared handle for the pinned conversation scope."""

    model_config = ConfigDict(extra="forbid")

    label: str
    document_ids: list[UUID] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)


def normalize_title(title: str) -> str:
    text = title.strip()
    text = re.sub(r"^【[^】]+】\s*", "", text)
    if text.lower().endswith(".pdf"):
        text = text[:-4]
    return text.strip()


def match_document_ids_for_entities(
    entities: list[str],
    titles: dict[UUID, str],
) -> list[UUID]:
    """Map product-like entities onto document titles (substring, casefold)."""
    if not entities or not titles:
        return []
    matched: list[UUID] = []
    for entity in entities:
        needle = entity.casefold().strip()
        if len(needle) < 2:
            continue
        for doc_id, title in titles.items():
            hay = normalize_title(title).casefold()
            raw = title.casefold()
            if needle in hay or needle in raw or hay in needle:
                if doc_id not in matched:
                    matched.append(doc_id)
    return matched


def label_for_documents(
    document_ids: list[UUID],
    titles: dict[UUID, str],
    *,
    entities: list[str] | None = None,
) -> str:
    if entities:
        return entities[0]
    names: list[str] = []
    for doc_id in document_ids:
        title = titles.get(doc_id)
        if title:
            names.append(normalize_title(title))
        else:
            names.append(str(doc_id))
    if not names:
        return "the current conversation"
    if len(names) == 1:
        return names[0]
    return ", ".join(names)


def infer_context_entities(
    question: str,
    history: list[dict[str, str]],
    resolver: QueryContextResolver,
) -> list[str]:
    """Prefer the first user turn's entities as the conversation anchor."""
    first_user = ""
    for turn in history:
        if str(turn.get("role") or "").casefold() in {"user", "human"}:
            first_user = str(turn.get("content") or "")
            break
    seed = first_user or question
    entities = resolver._extract_entities(seed)  # noqa: SLF001 - shared heuristic
    entities = resolver._prefer_topic_entities(entities)  # noqa: SLF001
    if not entities:
        entities = resolver._prefer_topic_entities(
            resolver._extract_entities(question)  # noqa: SLF001
        )
    return entities[:3]


def dominant_document_ids_from_citations(
    citations: list[object],
    *,
    limit: int = 2,
) -> list[UUID]:
    counts: dict[UUID, int] = {}
    order: list[UUID] = []
    for item in citations:
        doc_id = getattr(item, "document_id", None)
        if doc_id is None and isinstance(item, dict):
            raw = item.get("document_id")
            try:
                doc_id = UUID(str(raw)) if raw else None
            except Exception:  # noqa: BLE001
                doc_id = None
        if doc_id is None:
            continue
        if doc_id not in counts:
            order.append(doc_id)
            counts[doc_id] = 0
        counts[doc_id] += 1
    ranked = sorted(order, key=lambda item: (-counts[item], order.index(item)))
    return ranked[:limit]
