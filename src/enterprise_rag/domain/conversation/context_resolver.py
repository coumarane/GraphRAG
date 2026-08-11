"""Conversational query contextualization with explicit context-switch detection."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field

_PRONOUN_RE = re.compile(
    r"(?i)\b(it|its|they|them|their|this|that|these|those|which one|the former|the latter)\b"
)
_COMPARE_RE = re.compile(r"(?i)\b(compare|comparison|versus|vs\.?|between)\b")
_CONTEXT_SWITCH_RE = re.compile(
    r"(?i)\b("
    r"forget that|never mind|unrelated|different topic|"
    r"now tell me about|switching to|instead,? (?:tell|what|show)|"
    r"back to\b|regarding\b|about\b"
    r")\b"
)
_EXPLICIT_ENTITY_RE = re.compile(
    r"(?i)\b(?:tell me about|what about|now (?:about|for|tell me about)|regarding|back to)\s+(.+?)(?:\?|$|:)"
)
_PRODUCTISH_RE = re.compile(
    r"\b("
    r"[A-Z][A-Za-z0-9\-_/]*"
    r"(?:\s+(?:[A-Z][A-Za-z0-9\-_/]*|[A-Z]\b|\d+[A-Za-z0-9\-_/]*)){0,4}"
    r")\b"
)
_STOP_ENTITY = frozenset(
    {
        "What",
        "Which",
        "Where",
        "When",
        "How",
        "Why",
        "Who",
        "The",
        "This",
        "That",
        "These",
        "Those",
        "Compare",
        "Tell",
        "Show",
        "Give",
        "Please",
        "Europe",
        "France",
        "Now",
        "About",
        "Back",
        "Instead",
        "Forget",
        "User",
        "Assistant",
    }
)
_WH_ENTITY = frozenset({"who", "what", "when", "where", "why", "how", "which"})
# Datasheet / form-field labels that look product-ish but are not entities.
_FIELD_LABEL_ENTITY = frozenset(
    {
        "INCI",
        "CAS",
        "APHA",
        "HPLC",
        "HS",
        "H.S",
        "Code",
        "Classification",
        "Appearance",
        "Specification",
        "Specifications",
        "Version",
        "General",
        "Characteristics",
        "Information",
        "Item",
        "Unit",
        "Test",
        "Method",
        "Packing",
        "Export",
        "Standard",
        "Chemical",
        "Name",
        "Color",
        "Water",
        "Content",
        "Hydroxyl",
        "Value",
        "Melting",
        "Point",
        "Clear",
        "Polyethylene",
        "Glycol",
    }
)


class ConversationTurn(BaseModel):
    """One prior user/assistant turn."""

    model_config = ConfigDict(extra="forbid")

    role: str
    content: str = Field(min_length=1)


class ResolvedQueryContext(BaseModel):
    """Structured contextualization result for retrieval/generation."""

    model_config = ConfigDict(extra="forbid")

    query: str
    requires_history: bool = False
    resolved_query: str
    active_entities: list[str] = Field(default_factory=list)
    context_switch: bool = False
    ambiguous: bool = False
    clarification_question: str | None = None
    warnings: list[str] = Field(default_factory=list)


@dataclass
class QueryContextResolver:
    """Resolve follow-ups without blindly concatenating chat history."""

    max_history_turns: int = 8

    def resolve(
        self,
        query: str,
        history: list[ConversationTurn] | None = None,
        *,
        known_entities: list[str] | None = None,
    ) -> ResolvedQueryContext:
        question = query.strip()
        turns = list(history or [])[-self.max_history_turns :]
        prior_entities = self._entities_from_history(turns)
        if known_entities:
            for entity in known_entities:
                if entity not in prior_entities:
                    prior_entities.append(entity)
        prior_entities = self._prefer_topic_entities(prior_entities)

        current_entities = self._prefer_topic_entities(self._extract_entities(question))
        switch = self._is_context_switch(question, prior_entities, current_entities)
        has_pronoun = bool(_PRONOUN_RE.search(question))
        ambiguous = False
        clarification: str | None = None
        warnings: list[str] = []
        active: list[str] = []
        requires_history = False
        resolved = question

        # Prefer known active entities when history extraction is noisy.
        if known_entities and not switch:
            known = self._prefer_topic_entities(list(known_entities))
            if len(known) == 1:
                prior_entities = list(known)
            else:
                merged: list[str] = []
                for entity in [*known, *prior_entities]:
                    if entity not in merged:
                        merged.append(entity)
                prior_entities = self._prefer_topic_entities(merged)

        if switch:
            # Explicit topic change — do not inherit prior entity unless restated.
            active = current_entities[:3]
            if not active:
                # "Now tell me about Product B" already captured; otherwise keep empty.
                explicit = _EXPLICIT_ENTITY_RE.search(question)
                if explicit:
                    active = [explicit.group(1).strip().rstrip(".")]
            return ResolvedQueryContext(
                query=question,
                requires_history=False,
                resolved_query=question,
                active_entities=active,
                context_switch=True,
                ambiguous=False,
                clarification_question=None,
                warnings=warnings,
            )

        if has_pronoun or self._looks_like_followup(question):
            requires_history = True
            if len(prior_entities) == 1:
                active = prior_entities[:1]
                resolved = self._rewrite_with_entity(question, active[0])
            elif len(prior_entities) >= 2 and re.search(r"(?i)\bwhich one\b", question):
                # Comparative follow-up: keep both entities explicit.
                active = prior_entities[:2]
                resolved = (
                    f"{question.rstrip('?')} among "
                    f"{active[0]} and {active[1]}?"
                )
            elif len(prior_entities) >= 2 and has_pronoun:
                # Question already names one prior entity → no need to clarify.
                # Require word-ish boundaries so "Who" cannot match inside "how".
                named = [
                    entity
                    for entity in prior_entities
                    if entity.casefold() not in _WH_ENTITY
                    and re.search(
                        rf"(?i)(?<![A-Za-z0-9]){re.escape(entity)}(?![A-Za-z0-9])",
                        question,
                    )
                ]
                if len(named) == 1:
                    active = named[:1]
                    resolved = self._rewrite_with_entity(question, active[0])
                elif current_entities:
                    # Prefer an explicit product mention in the current question.
                    overlap = [
                        entity
                        for entity in current_entities
                        if entity.casefold() not in _WH_ENTITY
                    ]
                    if len(overlap) == 1:
                        active = overlap[:1]
                        resolved = self._rewrite_with_entity(question, active[0])
                    else:
                        ambiguous = True
                        active = prior_entities[:2]
                        clarification = (
                            "Which entity are you referring to: "
                            + " or ".join(active)
                            + "?"
                        )
                        warnings.append("ambiguous_pronoun_reference")
                        resolved = question
                else:
                    ambiguous = True
                    active = prior_entities[:2]
                    clarification = (
                        "Which entity are you referring to: "
                        + " or ".join(active)
                        + "?"
                    )
                    warnings.append("ambiguous_pronoun_reference")
                    resolved = question
            elif prior_entities:
                active = prior_entities[:1]
                resolved = self._rewrite_with_entity(question, active[0])
            else:
                warnings.append("followup_without_resolvable_entity")
                requires_history = bool(turns)
        else:
            active = current_entities[:3] or prior_entities[:1]
            # Fresh factual question — history not required.
            requires_history = False
            resolved = question

        return ResolvedQueryContext(
            query=question,
            requires_history=requires_history,
            resolved_query=resolved,
            active_entities=active,
            context_switch=False,
            ambiguous=ambiguous,
            clarification_question=clarification,
            warnings=warnings,
        )

    def _is_context_switch(
        self,
        question: str,
        prior_entities: list[str],
        current_entities: list[str],
    ) -> bool:
        lowered = question.casefold()
        if re.search(r"(?i)\bforget that\b|\bnever mind\b|\bunrelated\b", lowered):
            return True
        if re.search(r"(?i)\bnow tell me about\b|\bswitching to\b", lowered):
            return True
        if re.search(r"(?i)\bback to\b", lowered):
            # Explicit reactivation is a soft switch to a named entity.
            return True
        if not prior_entities or not current_entities:
            return False
        prior_fold = {item.casefold() for item in prior_entities}
        # New capitalized entity that was not previously active.
        if any(entity.casefold() not in prior_fold for entity in current_entities):
            # Avoid treating "Europe" style generics alone as switch without cue.
            if _CONTEXT_SWITCH_RE.search(question) or _COMPARE_RE.search(question) is None:
                if any(
                    token in lowered
                    for token in ("now", "instead", "tell me about", "what about")
                ):
                    return True
                # Distinct product-like entity mentioned without pronouns → switch.
                if not _PRONOUN_RE.search(question) and len(current_entities[0]) > 2:
                    return True
        return False

    def _looks_like_followup(self, question: str) -> bool:
        tokens = [token for token in re.findall(r"[A-Za-z0-9]+", question) if token]
        if not tokens:
            return False
        if _PRONOUN_RE.search(question):
            return True
        if question.strip().endswith("?") and len(tokens) <= 6:
            # Short questions often depend on prior topic ("recommended concentration?").
            if not self._extract_entities(question):
                return True
        return False

    def _rewrite_with_entity(self, question: str, entity: str) -> str:
        text = question.strip()
        # Replace leading possessive / pronoun forms.
        rewritten = re.sub(r"(?i)\bits\b", f"{entity}'s", text)
        rewritten = re.sub(r"(?i)\bit\b", entity, rewritten)
        rewritten = re.sub(r"(?i)\bthis\b", entity, rewritten)
        rewritten = re.sub(r"(?i)\bthat\b", entity, rewritten)
        if rewritten == text and entity.casefold() not in text.casefold():
            rewritten = f"{text.rstrip('?')} for {entity}?"
        return rewritten

    def _entities_from_history(self, turns: list[ConversationTurn]) -> list[str]:
        entities: list[str] = []
        # Prefer most recent user turns.
        for turn in reversed(turns):
            if turn.role not in {"user", "human"}:
                continue
            for entity in self._extract_entities(turn.content):
                if entity not in entities:
                    entities.append(entity)
            if len(entities) >= 4:
                break
        return entities

    def _extract_entities(self, text: str) -> list[str]:
        entities: list[str] = []

        def _add(candidate: str) -> None:
            cleaned = candidate.strip().rstrip("?.!,;:")
            cleaned = re.sub(r"(?i)^(about|for|regarding)\s+", "", cleaned).strip()
            if not cleaned:
                return
            parts = cleaned.split()
            while parts and parts[0].rstrip("?.!,;:") in _STOP_ENTITY:
                parts = parts[1:]
            cleaned = " ".join(parts).strip().rstrip("?.!,;:")
            if len(cleaned) < 2:
                return
            if cleaned in _FIELD_LABEL_ENTITY or cleaned.casefold() in {
                item.casefold() for item in _FIELD_LABEL_ENTITY
            }:
                return
            if cleaned.casefold() in _WH_ENTITY:
                return
            # Skip short all-caps field labels (INCI, CAS, APHA, …).
            if cleaned.isupper() and len(cleaned) <= 5 and " " not in cleaned:
                return
            if cleaned not in entities:
                entities.append(cleaned)

        for match in _EXPLICIT_ENTITY_RE.finditer(text):
            candidate = re.split(r"[.?!,]", match.group(1).strip())[0].strip()
            _add(candidate)
        for match in _PRODUCTISH_RE.finditer(text):
            _add(match.group(1))
        # Split coordinated product mentions: "Product A and Product B".
        for match in re.finditer(
            r"\b(Product|Ingredient|Supplier)\s+([A-Za-z0-9\-]+)\s+and\s+"
            r"(?:Product|Ingredient|Supplier)?\s*([A-Za-z0-9\-]+)\b",
            text,
            flags=re.IGNORECASE,
        ):
            label = match.group(1)
            _add(f"{label} {match.group(2)}")
            _add(f"{label} {match.group(3)}")
        return entities[:6]

    def _prefer_topic_entities(self, entities: list[str]) -> list[str]:
        """Drop field-label noise and prefer longer product-like names."""
        filtered = [
            entity
            for entity in entities
            if entity not in _FIELD_LABEL_ENTITY
            and entity.casefold() not in {item.casefold() for item in _FIELD_LABEL_ENTITY}
            and entity.casefold() not in _WH_ENTITY
            and not (entity.isupper() and len(entity) <= 5 and " " not in entity)
        ]
        # Never fall back to Wh-/field-label-only lists — empty is safer than "Who".
        ranked = list(filtered)

        def _score(entity: str) -> tuple[int, int, int]:
            has_digit = any(ch.isdigit() for ch in entity)
            return (len(entity.split()), len(entity), 1 if has_digit else 0)

        ranked = sorted(ranked, key=_score, reverse=True)
        # Keep original encounter order among equals after preferring stronger topics.
        preferred = sorted(
            ranked,
            key=lambda item: (-_score(item)[0], -_score(item)[1], -_score(item)[2]),
        )
        # De-dupe while preserving preference order.
        out: list[str] = []
        for entity in preferred:
            if entity not in out:
                out.append(entity)
        return out


@dataclass
class ConversationState:
    """Optional mutable conversation tracker for multi-turn tests."""

    active_entities: list[str] = field(default_factory=list)
    turns: list[ConversationTurn] = field(default_factory=list)
    resolver: QueryContextResolver = field(default_factory=QueryContextResolver)

    def ask(self, query: str) -> ResolvedQueryContext:
        resolved = self.resolver.resolve(
            query,
            self.turns,
            known_entities=list(self.active_entities),
        )
        self.turns.append(ConversationTurn(role="user", content=query))
        if resolved.context_switch:
            self.active_entities = list(resolved.active_entities)
        elif resolved.active_entities and not resolved.ambiguous:
            self.active_entities = list(resolved.active_entities)
        return resolved
