"""Conversation title derivation, mirroring the frontend's ``titleFromQuestion``."""

from __future__ import annotations

import re

_WHITESPACE_RE = re.compile(r"\s+")


def title_from_question(question: str) -> str:
    """Derive a conversation title from its first question.

    Direct port of ``titleFromQuestion`` in ``frontend/src/lib/chatHistory.ts``
    so a conversation auto-titled server-side matches what the client would
    have produced for the same question.
    """
    cleaned = _WHITESPACE_RE.sub(" ", question).strip()
    if not cleaned:
        return "New chat"
    if len(cleaned) > 48:
        return f"{cleaned[:48].rstrip()}…"
    return cleaned
