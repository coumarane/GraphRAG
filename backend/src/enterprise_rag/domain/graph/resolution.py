"""Tenant-scoped entity resolution."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from uuid import UUID

from enterprise_rag.domain.graph.extraction import EntityType, ExtractedEntity
from enterprise_rag.domain.graph.models import (
    EntityResolutionDecision,
    MergeStrategy,
    ResolvedEntity,
)
from enterprise_rag.domain.ids import deterministic_id, new_id
from enterprise_rag.domain.types import JsonValue

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


def normalize_entity_name(name: str) -> str:
    """Case/punctuation-normalized form used for exact matching."""
    folded = unicodedata.normalize("NFKC", name).casefold().strip()
    folded = _PUNCT_RE.sub(" ", folded)
    return _SPACE_RE.sub(" ", folded).strip()


def _acronym(name: str) -> str | None:
    parts = [part for part in re.split(r"[\s\-_/]+", name.strip()) if part]
    if len(parts) < 2:
        return None
    letters = "".join(part[0] for part in parts if part[0].isalpha())
    return letters.casefold() if len(letters) >= 2 else None


def _acronym_candidates(name: str) -> set[str]:
    """Return acronym keys for multi-word names and compact short aliases."""
    candidates: set[str] = set()
    generated = _acronym(name)
    if generated:
        candidates.add(generated)
    compact = normalize_entity_name(name).replace(" ", "")
    if compact.isalpha() and 2 <= len(compact) <= 8:
        candidates.add(compact)
    return candidates


def _compatible_types(a: str, b: str) -> bool:
    if a == b:
        return True
    # Generic Entity is compatible with any typed entity.
    return EntityType.ENTITY.value in {a, b}


@dataclass
class EntityResolver:
    """Resolve extracted mentions into canonical tenant entities.

    Lexical similarity alone never merges entities; type compatibility plus at
    least one strong signal (exact/alias/acronym/identifier) or a combined
    fuzzy+type decision with elevated review flag is required.
    """

    tenant_id: UUID
    fuzzy_threshold: float = 0.92
    entities: dict[UUID, ResolvedEntity] = field(default_factory=dict)
    _by_normalized: dict[str, UUID] = field(default_factory=dict)
    _by_alias: dict[str, UUID] = field(default_factory=dict)
    _by_acronym: dict[str, UUID] = field(default_factory=dict)
    decisions: list[EntityResolutionDecision] = field(default_factory=list)

    def resolve_many(
        self,
        mentions: list[ExtractedEntity],
    ) -> tuple[list[ResolvedEntity], list[EntityResolutionDecision]]:
        for mention in mentions:
            self.resolve(mention)
        return list(self.entities.values()), list(self.decisions)

    def resolve(self, mention: ExtractedEntity) -> ResolvedEntity:
        normalized = normalize_entity_name(mention.normalized_name or mention.name)
        entity_type = mention.entity_type.value
        acronyms = _acronym_candidates(mention.name) | {
            candidate
            for alias in mention.aliases
            for candidate in _acronym_candidates(alias)
        }

        # 1) Exact normalized identifier / name.
        if normalized in self._by_normalized:
            entity_id = self._by_normalized[normalized]
            existing = self.entities[entity_id]
            if _compatible_types(existing.entity_type, entity_type):
                return self._merge(
                    existing,
                    mention,
                    strategy=MergeStrategy.EXACT_NORMALIZED,
                    confidence=max(0.95, mention.confidence),
                    requires_manual_review=False,
                    signals={"normalized": normalized},
                )

        # 2) Exact alias.
        for alias in [mention.name, *mention.aliases]:
            alias_key = normalize_entity_name(alias)
            if alias_key in self._by_alias:
                entity_id = self._by_alias[alias_key]
                existing = self.entities[entity_id]
                if _compatible_types(existing.entity_type, entity_type):
                    return self._merge(
                        existing,
                        mention,
                        strategy=MergeStrategy.EXACT_ALIAS,
                        confidence=max(0.9, mention.confidence),
                        requires_manual_review=False,
                        signals={"alias": alias_key},
                    )

        # 3) Acronym match with type compatibility.
        for acronym in acronyms:
            if acronym not in self._by_acronym:
                continue
            entity_id = self._by_acronym[acronym]
            existing = self.entities[entity_id]
            if _compatible_types(existing.entity_type, entity_type):
                return self._merge(
                    existing,
                    mention,
                    strategy=MergeStrategy.ACRONYM,
                    confidence=0.85,
                    requires_manual_review=True,
                    signals={"acronym": acronym},
                )

        # 4) Fuzzy lexical + type compatibility (never alone without review).
        best: tuple[float, ResolvedEntity] | None = None
        for existing in self.entities.values():
            if not _compatible_types(existing.entity_type, entity_type):
                continue
            score = SequenceMatcher(None, normalized, existing.normalized_name).ratio()
            if score >= self.fuzzy_threshold and (best is None or score > best[0]):
                best = (score, existing)
        if best is not None:
            score, existing = best
            # Require an additional weak alias/token overlap signal.
            tokens_a = set(normalized.split())
            tokens_b = set(existing.normalized_name.split())
            overlap = bool(tokens_a & tokens_b)
            if overlap:
                return self._merge(
                    existing,
                    mention,
                    strategy=MergeStrategy.FUZZY_AND_TYPE,
                    confidence=min(0.8, score),
                    requires_manual_review=True,
                    signals={"fuzzy_score": score, "token_overlap": True},
                )

        return self._create(mention, normalized, acronyms)

    def _create(
        self,
        mention: ExtractedEntity,
        normalized: str,
        acronyms: set[str],
    ) -> ResolvedEntity:
        entity_id = deterministic_id(
            str(self.tenant_id),
            mention.entity_type.value,
            normalized,
        )
        # Collision on deterministic id with incompatible type → new runtime id.
        if entity_id in self.entities and not _compatible_types(
            self.entities[entity_id].entity_type,
            mention.entity_type.value,
        ):
            entity_id = new_id()

        entity = ResolvedEntity(
            entity_id=entity_id,
            tenant_id=self.tenant_id,
            canonical_name=mention.name.strip(),
            normalized_name=normalized,
            entity_type=mention.entity_type.value,
            aliases=sorted({normalize_entity_name(a) for a in mention.aliases if a}),
            description=mention.description,
            mention_count=1,
            source_element_ids=list(mention.source_element_ids),
        )
        self.entities[entity_id] = entity
        self._index(entity, acronyms)
        self.decisions.append(
            EntityResolutionDecision(
                mention_name=mention.name,
                canonical_entity_id=entity_id,
                merge_strategy=MergeStrategy.NEW_ENTITY,
                confidence=mention.confidence,
                requires_manual_review=False,
                signals={"normalized": normalized},
            )
        )
        return entity

    def _merge(
        self,
        existing: ResolvedEntity,
        mention: ExtractedEntity,
        *,
        strategy: MergeStrategy,
        confidence: float,
        requires_manual_review: bool,
        signals: dict[str, JsonValue],
    ) -> ResolvedEntity:
        aliases = set(existing.aliases)
        aliases.add(normalize_entity_name(mention.name))
        aliases.update(normalize_entity_name(alias) for alias in mention.aliases if alias)
        aliases.discard(existing.normalized_name)
        element_ids = list(
            dict.fromkeys([*existing.source_element_ids, *mention.source_element_ids])
        )
        updated = existing.model_copy(
            update={
                "aliases": sorted(aliases),
                "mention_count": existing.mention_count + 1,
                "source_element_ids": element_ids,
                "description": existing.description or mention.description,
            }
        )
        self.entities[existing.entity_id] = updated
        self._index(
            updated,
            _acronym_candidates(mention.name)
            | {c for alias in mention.aliases for c in _acronym_candidates(alias)},
        )
        self.decisions.append(
            EntityResolutionDecision(
                mention_name=mention.name,
                canonical_entity_id=existing.entity_id,
                merge_strategy=strategy,
                confidence=confidence,
                requires_manual_review=requires_manual_review,
                signals=signals,
            )
        )
        return updated

    def _index(self, entity: ResolvedEntity, acronyms: set[str]) -> None:
        self._by_normalized[entity.normalized_name] = entity.entity_id
        self._by_alias[entity.normalized_name] = entity.entity_id
        for alias in entity.aliases:
            self._by_alias[alias] = entity.entity_id
        for acronym in acronyms | _acronym_candidates(entity.canonical_name):
            self._by_acronym[acronym] = entity.entity_id
