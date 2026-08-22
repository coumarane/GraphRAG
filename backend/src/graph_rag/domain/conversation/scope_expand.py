"""Document-scope miss handling and expand-on-confirmation policy.

When a query is pinned to specific documents, never silently widen to the
corpus. On an in-scope miss, ask the user to confirm before searching others.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import UUID

_AFFIRMATIVE = re.compile(
    r"^\s*(yes|y|yeah|yep|sure|ok|okay|please do|go ahead|search(?:\s+all)?|"
    r"expand|broader|all documents)\s*[.!]?\s*$",
    re.IGNORECASE,
)
_ABSTENTION = re.compile(
    r"(?is)\b("
    r"insufficient(?:\s+information)?|"
    r"could not find(?:\s+enough)?|"
    r"not enough (?:retrieved )?evidence|"
    r"no (?:relevant )?(?:information|results|evidence)|"
    r"unable to (?:determine|identify|find)|"
    r"not (?:explicitly )?(?:stated|specified)|"
    r"does not (?:appear to )?contain|"
    r"cannot (?:be )?(?:definitively )?(?:answer|identified|determine|identify)|"
    r"cannot be definitively identified|"
    r"manufacturer cannot"
    r")\b"
)

AWAITING_SCOPE_EXPAND = "awaiting_scope_expand"
DOCUMENT_SCOPE_EXPANDED = "document_scope_expanded"


@dataclass(frozen=True)
class ScopeExpandDecision:
    """Whether this turn should widen document filters."""

    expand: bool
    prior_question: str | None = None


def is_scope_expand_affirmative(text: str) -> bool:
    return bool(_AFFIRMATIVE.match((text or "").strip()))


def answer_looks_like_abstention(answer: str) -> bool:
    return bool(_ABSTENTION.search(answer or ""))


def format_document_context_label(
    document_ids: list[UUID],
    titles: dict[UUID, str] | None = None,
) -> str:
    titles = titles or {}
    names: list[str] = []
    for doc_id in document_ids:
        name = (titles.get(doc_id) or "").strip()
        if not name:
            name = str(doc_id)
        # Prefer short product-ish labels from presentation titles.
        if name.lower().endswith(".pdf"):
            name = name[:-4]
        name = name.replace("【Presentation】", "").replace("【presentation】", "").strip()
        names.append(name or str(doc_id))
    if not names:
        return "the current document"
    if len(names) == 1:
        return names[0]
    return ", ".join(names)


def build_scope_miss_message(context_label: str) -> str:
    label = context_label.strip() or "the current conversation"
    return (
        f"No relevant information was found within the current conversation "
        f"context ({label}). Would you like me to search across other documents "
        f'in the knowledge base? Reply "Yes" to continue.'
    )


def detect_scope_expand_from_history(
    *,
    question: str,
    conversation_history: list[dict[str, str]],
) -> ScopeExpandDecision:
    """If the user affirms after an awaiting_scope_expand turn, expand and replay Q."""
    if not is_scope_expand_affirmative(question):
        return ScopeExpandDecision(expand=False)

    # Walk history newest-first for the last assistant turn.
    prior_user: str | None = None
    for index in range(len(conversation_history) - 1, -1, -1):
        turn = conversation_history[index]
        role = str(turn.get("role") or "").casefold()
        content = str(turn.get("content") or "")
        if role == "assistant":
            # Frontend may not send warnings; detect by message shape or marker.
            if (
                AWAITING_SCOPE_EXPAND in content
                or "reply \"yes\" to continue" in content.casefold()
                or "reply with 'yes'" in content.casefold()
                or "search across other documents" in content.casefold()
            ):
                # Find the user question immediately before this assistant turn.
                for back in range(index - 1, -1, -1):
                    prev = conversation_history[back]
                    if str(prev.get("role") or "").casefold() == "user":
                        prior_user = str(prev.get("content") or "").strip() or None
                        break
                break
        if role == "user" and prior_user is None:
            # Keep scanning; affirmative is the current question, not history.
            continue
    if prior_user and not is_scope_expand_affirmative(prior_user):
        return ScopeExpandDecision(expand=True, prior_question=prior_user)
    return ScopeExpandDecision(expand=False)
