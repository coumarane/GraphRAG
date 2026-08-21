"""Build bounded ``ElementContext`` windows for multimodal enrichment."""

from __future__ import annotations

from dataclasses import dataclass

from enterprise_rag.domain.documents.document import NormalizedDocument
from enterprise_rag.domain.elements.context import ElementContext
from enterprise_rag.domain.elements.enums import ElementType
from enterprise_rag.domain.elements.models import (
    CaptionElement,
    DocumentElement,
    FootnoteElement,
    HeadingElement,
    TableElement,
)
from enterprise_rag.domain.models.contracts import TokenCountRequest, TokenCountResponse
from enterprise_rag.domain.models.protocols import TokenCounter

_SKIP_TYPES = {ElementType.PAGE_HEADER, ElementType.PAGE_FOOTER}


@dataclass(frozen=True)
class ContextBuilderConfig:
    """Limits for surrounding element context."""

    preceding_elements: int = 3
    following_elements: int = 3
    max_context_tokens: int = 1800
    include_caption: bool = True
    include_section_path: bool = True
    include_nearby_tables: bool = True
    include_nearby_figures: bool = True
    include_footnotes: bool = True


class HeuristicTokenCounter:
    """Cheap token estimate (~4 chars/token) for context budgeting."""

    async def count(self, request: TokenCountRequest) -> TokenCountResponse:
        return TokenCountResponse(
            token_count=max(1, (len(request.text) + 3) // 4) if request.text else 0,
            model_name=request.model_name,
        )


class ElementContextBuilder:
    """Construct token-bounded context around a target element."""

    def __init__(
        self,
        *,
        config: ContextBuilderConfig | None = None,
        token_counter: TokenCounter | None = None,
    ) -> None:
        self._config = config or ContextBuilderConfig()
        self._token_counter: TokenCounter = token_counter or HeuristicTokenCounter()

    async def build(
        self,
        document: NormalizedDocument,
        element: DocumentElement,
    ) -> ElementContext:
        elements = document.elements
        try:
            index = next(
                i for i, item in enumerate(elements) if item.element_id == element.element_id
            )
        except StopIteration as exc:
            from enterprise_rag.shared.exceptions import ValidationError

            raise ValidationError(
                "Element is not part of the document",
                details={"element_id": str(element.element_id)},
            ) from exc

        preceding = self._collect_neighbors(elements, index, direction=-1)
        following = self._collect_neighbors(elements, index, direction=1)
        caption = self._resolve_caption(elements, element) if self._config.include_caption else None
        nearby = self._nearby_summaries(elements, element, index)
        footnotes = self._page_footnotes(elements, element.page_start)
        heading = self._heading_for(element, elements, index)

        preceding_text = self._join_texts(preceding)
        following_text = self._join_texts(following)
        preceding_text, following_text, nearby, footnotes = await self._fit_budget(
            document_title=document.title,
            section_path=list(element.section_path) if self._config.include_section_path else [],
            heading=heading,
            caption=caption,
            preceding_text=preceding_text,
            following_text=following_text,
            nearby=nearby,
            footnotes=footnotes,
        )

        return ElementContext(
            document_title=document.title,
            document_type=document.mime_type,
            section_path=list(element.section_path) if self._config.include_section_path else [],
            heading=heading,
            caption=caption,
            preceding_text=preceding_text or None,
            following_text=following_text or None,
            nearby_element_summaries=nearby,
            page_number=element.page_start,
            footnotes=footnotes,
            document_metadata=dict(document.metadata),
        )

    def _collect_neighbors(
        self,
        elements: list[DocumentElement],
        index: int,
        *,
        direction: int,
    ) -> list[DocumentElement]:
        limit = (
            self._config.preceding_elements
            if direction < 0
            else self._config.following_elements
        )
        collected: list[DocumentElement] = []
        cursor = index + direction
        while 0 <= cursor < len(elements) and len(collected) < limit:
            candidate = elements[cursor]
            if candidate.element_type not in _SKIP_TYPES:
                collected.append(candidate)
            cursor += direction
        if direction < 0:
            collected.reverse()
        return collected

    def _resolve_caption(
        self,
        elements: list[DocumentElement],
        element: DocumentElement,
    ) -> str | None:
        for item in elements:
            if isinstance(item, CaptionElement) and item.target_element_id == element.element_id:
                return item.normalized_content or item.raw_content
        if isinstance(element, TableElement) and element.table.caption:
            return element.table.caption
        # Adjacent caption on the same page.
        for item in elements:
            if (
                isinstance(item, CaptionElement)
                and item.page_start == element.page_start
                and item.target_element_id is None
            ):
                return item.normalized_content or item.raw_content
        return None

    def _nearby_summaries(
        self,
        elements: list[DocumentElement],
        element: DocumentElement,
        index: int,
    ) -> list[str]:
        summaries: list[str] = []
        interesting = {
            ElementType.TABLE,
            ElementType.IMAGE,
            ElementType.CHART,
            ElementType.DIAGRAM,
            ElementType.EQUATION,
        }
        for offset in (-2, -1, 1, 2):
            pos = index + offset
            if not 0 <= pos < len(elements):
                continue
            neighbor = elements[pos]
            if neighbor.element_id == element.element_id:
                continue
            if neighbor.element_type not in interesting:
                continue
            if neighbor.page_start != element.page_start:
                continue
            if (
                neighbor.element_type is ElementType.TABLE
                and not self._config.include_nearby_tables
            ):
                continue
            if (
                neighbor.element_type
                in {ElementType.IMAGE, ElementType.CHART, ElementType.DIAGRAM}
                and not self._config.include_nearby_figures
            ):
                continue
            text = (
                neighbor.normalized_content
                or neighbor.raw_content
                or neighbor.element_type.value
            )
            summaries.append(f"{neighbor.element_type.value}: {text[:240]}")
        return summaries

    def _page_footnotes(
        self,
        elements: list[DocumentElement],
        page_number: int,
    ) -> list[str]:
        if not self._config.include_footnotes:
            return []
        notes: list[str] = []
        for item in elements:
            if isinstance(item, FootnoteElement) and item.page_start == page_number:
                text = item.normalized_content or item.raw_content or ""
                if text:
                    marker = f"{item.marker}: " if item.marker else ""
                    notes.append(f"{marker}{text}")
        return notes

    def _heading_for(
        self,
        element: DocumentElement,
        elements: list[DocumentElement],
        index: int,
    ) -> str | None:
        if element.section_path:
            return element.section_path[-1]
        for cursor in range(index - 1, -1, -1):
            candidate = elements[cursor]
            if isinstance(candidate, HeadingElement):
                return candidate.normalized_content or candidate.raw_content
        return None

    @staticmethod
    def _join_texts(elements: list[DocumentElement]) -> str:
        parts: list[str] = []
        for item in elements:
            text = item.normalized_content or item.raw_content
            if text:
                parts.append(text.strip())
        return "\n".join(parts)

    async def _fit_budget(
        self,
        *,
        document_title: str | None,
        section_path: list[str],
        heading: str | None,
        caption: str | None,
        preceding_text: str,
        following_text: str,
        nearby: list[str],
        footnotes: list[str],
    ) -> tuple[str, str, list[str], list[str]]:
        async def _tokens(text: str) -> int:
            result = await self._token_counter.count(TokenCountRequest(text=text))
            return int(result.token_count)

        fixed_parts = [
            document_title or "",
            " / ".join(section_path),
            heading or "",
            caption or "",
        ]
        fixed = await _tokens("\n".join(fixed_parts))
        budget = max(0, self._config.max_context_tokens - fixed)

        # Prefer preceding, then following, then nearby, then footnotes.
        preceding_text = await self._truncate(preceding_text, budget // 2)
        used = await _tokens(preceding_text)
        following_budget = max(0, budget - used) // 2 or budget // 2
        following_text = await self._truncate(following_text, following_budget)
        used += await _tokens(following_text)
        remaining = max(0, budget - used)

        trimmed_nearby: list[str] = []
        for item in nearby:
            cost = await _tokens(item)
            if cost > remaining:
                break
            trimmed_nearby.append(item)
            remaining -= cost

        trimmed_notes: list[str] = []
        for item in footnotes:
            cost = await _tokens(item)
            if cost > remaining:
                break
            trimmed_notes.append(item)
            remaining -= cost

        return preceding_text, following_text, trimmed_nearby, trimmed_notes

    async def _truncate(self, text: str, max_tokens: int) -> str:
        if not text or max_tokens <= 0:
            return ""
        result = await self._token_counter.count(TokenCountRequest(text=text))
        if result.token_count <= max_tokens:
            return text
        # Approximate character budget from token limit.
        char_budget = max_tokens * 4
        return text[:char_budget].rstrip()
