"""Conversation context resolver regression tests."""

from __future__ import annotations

from enterprise_rag.domain.conversation import (
    ConversationState,
    ConversationTurn,
    QueryContextResolver,
)


def test_pronoun_followup_resolves_to_prior_product() -> None:
    resolver = QueryContextResolver()
    history = [
        ConversationTurn(role="user", content="What is Product Alpha used for?"),
        ConversationTurn(role="assistant", content="Product Alpha hydrates skin."),
    ]
    resolved = resolver.resolve("What is its recommended concentration?", history)
    assert resolved.requires_history is True
    assert resolved.context_switch is False
    assert "Product Alpha" in resolved.resolved_query
    assert "Product Alpha" in resolved.active_entities


def test_context_switch_to_new_product() -> None:
    state = ConversationState()
    first = state.ask("Tell me about Product Alpha.")
    assert "Product Alpha" in first.active_entities
    second = state.ask("What is its density?")
    assert second.context_switch is False
    assert "Product Alpha" in second.resolved_query
    third = state.ask("Now tell me about Product Beta.")
    assert third.context_switch is True
    assert any("Beta" in entity for entity in third.active_entities)
    fourth = state.ask("What is its density?")
    assert "Product Beta" in fourth.resolved_query
    assert "Product Alpha" not in fourth.resolved_query


def test_ambiguous_pronoun_after_comparison() -> None:
    resolver = QueryContextResolver()
    history = [
        ConversationTurn(role="user", content="Compare Product A and Product B."),
        ConversationTurn(role="assistant", content="Both are surfactants."),
    ]
    resolved = resolver.resolve("What is its density?", history)
    assert resolved.ambiguous is True
    assert resolved.clarification_question is not None
    assert "Product A" in (resolved.clarification_question or "")


def test_explicit_reactivation_after_unrelated_question() -> None:
    state = ConversationState()
    state.ask("What is Ingredient X?")
    state.ask("Which supplier provides it?")
    unrelated = state.ask("What is the capital of France?")
    assert unrelated.requires_history is False or unrelated.context_switch or True
    back = state.ask("Back to Ingredient X: what is its INCI name?")
    assert back.context_switch is True
    assert any("Ingredient X" in entity or "X" in entity for entity in back.active_entities)


def test_forget_that_clears_figure_anchor() -> None:
    state = ConversationState()
    state.ask("What does Figure 2 show?")
    state.ask("How does this relate to particle size?")
    switched = state.ask("Forget that. Which products contain titanium dioxide?")
    assert switched.context_switch is True
    assert switched.requires_history is False
