"""Document scope expand policy tests."""

from __future__ import annotations

from uuid import uuid4

from graph_rag.domain.conversation.scope_expand import (
    answer_looks_like_abstention,
    build_scope_miss_message,
    detect_scope_expand_from_history,
    format_document_context_label,
    is_scope_expand_affirmative,
)


def test_scope_miss_message_names_context() -> None:
    msg = build_scope_miss_message("SY-KNP")
    assert "SY-KNP" in msg
    assert "conversation context" in msg.casefold()
    assert "yes" in msg.casefold()


def test_format_strips_presentation_prefix() -> None:
    doc_id = uuid4()
    label = format_document_context_label(
        [doc_id],
        {doc_id: "【Presentation】 SY-KNP.pdf"},
    )
    assert "SY-KNP" in label


def test_affirmative_and_abstention_detectors() -> None:
    assert is_scope_expand_affirmative("yes")
    assert is_scope_expand_affirmative("Yes.")
    assert not is_scope_expand_affirmative("yes please search boron")
    assert answer_looks_like_abstention(
        "There is insufficient information in the provided evidence."
    )


def test_detect_expand_replays_prior_question() -> None:
    decision = detect_scope_expand_from_history(
        question="yes",
        conversation_history=[
            {"role": "user", "content": "Who manufactures SY-KNP?"},
            {
                "role": "assistant",
                "content": (
                    "No relevant information was found within the current conversation "
                    'context (SY-KNP). Would you like me to search across other documents '
                    'in the knowledge base? Reply "Yes" to continue.'
                ),
            },
        ],
    )
    assert decision.expand
    assert decision.prior_question == "Who manufactures SY-KNP?"


def test_detect_expand_ignores_unrelated_yes() -> None:
    decision = detect_scope_expand_from_history(
        question="yes",
        conversation_history=[
            {"role": "user", "content": "Is SY-KNP cationic?"},
            {"role": "assistant", "content": "Yes, according to the slide [C1]."},
        ],
    )
    assert not decision.expand
