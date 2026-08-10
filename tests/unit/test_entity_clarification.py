"""Entity clarification resume helpers."""

from __future__ import annotations

from enterprise_rag.domain.conversation.context_resolver import (
    ConversationTurn,
    QueryContextResolver,
)
from enterprise_rag.domain.conversation.entity_clarification import (
    bind_entity_to_question,
    clarification_options,
    detect_clarification_resume,
    match_entity_selection,
)


def test_clarification_options_drop_wh_noise() -> None:
    options = clarification_options(
        "Which entity are you referring to: SY-KNP or Who?"
    )
    assert options == ["SY-KNP"]


def test_match_entity_selection_accepts_short_reply() -> None:
    assert match_entity_selection("SY-KNP", ["SY-KNP", "BNB"]) == "SY-KNP"
    assert match_entity_selection("the SY-KNP one", ["SY-KNP", "BNB"]) == "SY-KNP"
    assert match_entity_selection("Tell me about INCI names", ["SY-KNP"]) is None


def test_detect_clarification_resume_replays_pending_map_question() -> None:
    pending = "How many red pins are on the contracted farmer map?"
    resume = detect_clarification_resume(
        question="SY-KNP",
        conversation_history=[
            {"role": "user", "content": pending},
            {
                "role": "assistant",
                "content": "Which entity are you referring to: SY-KNP or Who?",
            },
        ],
    )
    assert resume is not None
    assert resume.pending_question == pending
    assert resume.selected_entity == "SY-KNP"
    bound = bind_entity_to_question(resume.pending_question, resume.selected_entity)
    assert "SY-KNP" in bound
    assert "red pins" in bound.casefold()


def test_detect_clarification_resume_ignores_unrelated_short_reply() -> None:
    resume = detect_clarification_resume(
        question="yes",
        conversation_history=[
            {"role": "user", "content": "Is SY-KNP cationic?"},
            {"role": "assistant", "content": "Yes, according to the slide [C1]."},
        ],
    )
    assert resume is None


def test_wh_words_are_not_extracted_as_entities() -> None:
    resolver = QueryContextResolver()
    entities = resolver._extract_entities(
        "Who manufactures SY-KNP and What about MIC values?"
    )
    fold = {item.casefold() for item in entities}
    assert "who" not in fold
    assert "what" not in fold
    assert any("sy-knp" in item.casefold() for item in entities)


def test_pronoun_followup_does_not_clarify_with_wh_noise() -> None:
    resolver = QueryContextResolver()
    resolved = resolver.resolve(
        "How many red pins are on the map?",
        [
            ConversationTurn(role="user", content="Who manufactures SY-KNP?"),
            ConversationTurn(
                role="assistant",
                content="According to the presentation, SY-KNP is manufactured by …",
            ),
        ],
    )
    assert not resolved.ambiguous
    assert resolved.clarification_question is None


def test_named_entity_in_question_skips_clarification() -> None:
    resolver = QueryContextResolver()
    resolved = resolver.resolve(
        "On the contract-farming map for SY-KNP: how many pins, and does that match?",
        [
            ConversationTurn(role="user", content="Who manufactures SY-KNP?"),
            ConversationTurn(
                role="assistant",
                content="BNB CHEM appears in the presentation [C1].",
            ),
            ConversationTurn(role="user", content="Tell me about Astaxanthin-LS1"),
            ConversationTurn(
                role="assistant",
                content="Astaxanthin-LS1 is a carotenoid ingredient [C1].",
            ),
        ],
    )
    assert not resolved.ambiguous
    assert resolved.clarification_question is None
    assert any("SY-KNP" in item for item in resolved.active_entities)
