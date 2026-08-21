"""Resume a pending question after entity-clarification replies.

When the assistant asks "Which entity are you referring to: A or B?", the next
user message is often just "A". That selection must continue the *pending*
user question, not become a brand-new product overview query.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

AWAITING_ENTITY_CLARIFICATION = "awaiting_entity_clarification"

_CLARIFY_RE = re.compile(
    r"(?is)which entity are you referring to:\s*(.+?)\s*\??\s*$"
)
_WH_ENTITY = frozenset({"who", "what", "when", "where", "why", "how", "which"})


@dataclass(frozen=True)
class ClarificationResume:
    """Pending question resumed with a chosen entity."""

    pending_question: str
    selected_entity: str
    options: list[str]


def clarification_options(assistant_text: str) -> list[str]:
    match = _CLARIFY_RE.search((assistant_text or "").strip())
    if not match:
        return []
    parts = re.split(r"\s+or\s+", match.group(1).strip(), flags=re.IGNORECASE)
    options: list[str] = []
    for part in parts:
        cleaned = part.strip().rstrip("?.!,")
        if cleaned and cleaned.casefold() not in _WH_ENTITY:
            options.append(cleaned)
    return options


def is_clarification_prompt(assistant_text: str) -> bool:
    text = (assistant_text or "").casefold()
    return "which entity are you referring to:" in text or bool(
        clarification_options(assistant_text)
    )


def match_entity_selection(text: str, options: list[str]) -> str | None:
    cleaned = (text or "").strip().rstrip(".!?")
    if not cleaned or not options:
        return None
    fold = cleaned.casefold()
    for option in options:
        if fold == option.casefold():
            return option
    # Allow short replies like "SY-KNP please" / "the SY-KNP one"
    for option in options:
        opt = option.casefold()
        if opt in fold and len(cleaned) <= max(24, len(option) + 12):
            return option
    return None


def detect_clarification_resume(
    *,
    question: str,
    conversation_history: list[dict[str, str]],
) -> ClarificationResume | None:
    """If the user just picked an entity after a clarification, resume prior Q."""
    if not conversation_history:
        return None

    pending_user: str | None = None
    options: list[str] = []
    for index in range(len(conversation_history) - 1, -1, -1):
        turn = conversation_history[index]
        role = str(turn.get("role") or "").casefold()
        content = str(turn.get("content") or "")
        if role == "assistant" and is_clarification_prompt(content):
            options = clarification_options(content)
            for back in range(index - 1, -1, -1):
                prev = conversation_history[back]
                if str(prev.get("role") or "").casefold() in {"user", "human"}:
                    pending_user = str(prev.get("content") or "").strip() or None
                    break
            break

    if not pending_user or not options:
        return None
    if is_clarification_prompt(pending_user):
        return None

    selected = match_entity_selection(question, options)
    if selected is None:
        return None
    if pending_user.casefold() == question.strip().casefold():
        return None
    return ClarificationResume(
        pending_question=pending_user,
        selected_entity=selected,
        options=options,
    )


def bind_entity_to_question(question: str, entity: str) -> str:
    """Ensure the resumed question is explicitly about the selected entity."""
    text = (question or "").strip()
    entity = entity.strip()
    if not text:
        return f"Tell me about {entity}."
    if entity.casefold() in text.casefold():
        return text
    if text.endswith("?"):
        return f"{text[:-1].rstrip()} for {entity}?"
    return f"{text} for {entity}"
