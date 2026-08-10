"""Local PDF → chunk → embed → index pipeline for API/dev runtimes."""

from __future__ import annotations

import asyncio
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from enterprise_rag.application.chunking import EmbedChunksService, HierarchicalMultimodalChunker
from enterprise_rag.application.graph.build_graph import BuildKnowledgeGraphService
from enterprise_rag.application.ingestion.parsing_audit_collector import ParsingAuditCollector
from enterprise_rag.domain.chunks.protocols import ChunkVectorStore
from enterprise_rag.domain.chunks.vectors import ChunkingResult
from enterprise_rag.domain.elements.enums import ElementType
from enterprise_rag.domain.graph.protocols import GraphStore
from enterprise_rag.domain.graph.structural import StructuralGraphBuilder
from enterprise_rag.domain.ingestion.protocols import DocumentRepository, IngestionRepository
from enterprise_rag.domain.ingestion.stages import (
    DocumentLifecycleStatus,
    IngestionRunStatus,
    StageStatus,
)
from enterprise_rag.domain.parsing.audit import (
    ElementProcessingStatus,
    RoutingReasonCode,
    StageRunStatus,
)
from enterprise_rag.domain.parsing.audit_protocols import ParsingAuditRepository
from enterprise_rag.domain.models.contracts import (
    ChatMessage,
    GenerationRequest,
    ImageBytesContentPart,
    MessageRole,
    ModelRole,
    TextContentPart,
)
from enterprise_rag.domain.models.protocols import ChatModel, EmbeddingModel, StructuredExtractor
from enterprise_rag.domain.parsing.normalize import normalize_parser_result
from enterprise_rag.domain.parsing.types import (
    OcrMode,
    ParseOptions,
    ParserName,
    ParserProfile,
    ParseSource,
    RawElement,
    RawParserResult,
)
from enterprise_rag.domain.retrieval.condition_facets import (
    extract_condition_facets,
    facets_from_chart_axes,
    merge_facets,
    prose_for_facets,
)
from enterprise_rag.domain.retrieval.protocols import ChunkLookupStore, LexicalSearchStore
from enterprise_rag.domain.storage.protocols import ObjectStore
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.infrastructure.parsers.pdfium.extractor import (
    extract_pdf_raw as _extract_pdf_raw,
    extract_text_raw as _extract_text_raw,
)
from enterprise_rag.infrastructure.parsers.registry import ParseDocumentService
from enterprise_rag.shared.exceptions import NotFoundError, ParserError, ValidationError
from enterprise_rag.shared.logging import get_logger

# Back-compat for scripts/tests that imported private helpers from this module.
extract_pdf_raw = _extract_pdf_raw
extract_text_raw = _extract_text_raw

logger = get_logger(__name__)

_FIGURE_HINT = re.compile(
    r"(?i)\b(sem|tem|xrd|afm|microscope|micrograph|figure|fig\.|chart|diagram|photo|"
    r"comparison|appearance|tone-?up|soft-?focus|angle of measurement|byk|l\*|mica|"
    r"map|factory|factories|head office|branch|laboratory|company introduction)\b"
)
_CHART_PAGE_HINT = re.compile(
    r"(?i)\b(comparison with|synthetic mica|soft-?focus|tone-?up|"
    r"angle of measurement|byk-?mac|transparent|gloss type|matte type|"
    r"natural tone|l\*\s*-?\s*15|measurement conditions)\b"
)
_MAP_LOCATION_HINT = re.compile(
    r"(?i)\b(head office|factory|factories|branch|laboratory|company introduction|"
    r"research and development|location|sites?|plant)\b"
)
_PERCENT_TOKEN = re.compile(r"(?<!\d)\d{1,3}(?:\.\d+)?\s*%")
_FLAT_CHART_HINT = re.compile(
    r"(?i)\b("
    r"irritation|patch test|concentration level|response\s*,?\s*%|"
    r"bar chart|test report|human skin|no skin irritation|"
    r"moisture level|time after application|legend|control|"
    r"series|axis|ranking"
    r")\b"
)
_VISION_PROMPT = """Analyze this page from a technical cosmetics / powder / company brochure PDF.
Return ONLY valid JSON (no markdown fences) with this shape:
{
  "page_summary": "short summary of the slide purpose",
  "ocr_text": "ALL readable text on the page, including titles, map labels, legends, axes, callout bubbles, footnotes, and measurement conditions",
  "measurement_conditions": "e.g. Background: Black, thickness: 20µm, BYK-mac — empty if none",
  "callouts": ["exact callout / speech-bubble labels such as Soft-focus effect or Transparent"],
  "tables": [{"caption": "", "markdown": "| col | ... |"}],
  "formulas": [{"text": "", "description": ""}],
  "figures": [{
    "type": "sem|photo|chart|diagram|map|table_image|other",
    "title": "chart or figure title if present",
    "description": "what the figure shows; for charts describe axes, series names, relative ranking, and trends; for maps list every labeled site",
    "ocr_labels": "legend entries, axis labels, series names, numeric annotations, map pin labels (factories, offices, branches)",
    "values_markdown": "| x category | series A | series B | ... |\\n|---|---|---|\\n| ... | ... | ... |",
    "axes": {"x": "Concentration Level", "y": "Irritation Response, %"},
    "legend": ["series A", "series B"],
    "series_ranking": "e.g. at 75%: Propylene Glycol highest, BPDO-800N and Control at 0",
    "trends": ["short trend statements grounded in the chart"]
  }]
}
Rules:
- Be precise for SEM/microscopy images, line charts, bar charts, tables, maps, and chemical formulas.
- For charts: capture every legend series name, axis labels, callouts, and measurement conditions exactly.
- For bar/line charts: ALWAYS fill values_markdown with one column per legend series and one row per x-axis category. Read bar heights / numeric annotations; do NOT copy y-axis scale ticks (10, 20, 30) as series values.
- Missing / absent bars at a category mean 0 when the chart baseline is 0. Different series can have different values — do not copy one series onto another.
- Also copy values_markdown into tables[] when the chart is a quantitative comparison.
- For maps / company location slides: OCR every pin label (factories, head office, branches, labs, subsidiaries) into ocr_text and figures.ocr_labels.
- Do not invent unseen numeric values; approximate rankings from the visual if exact numbers are unreadable.
"""


def _parse_parser_name(value: str | None) -> ParserName | None:
    if not value:
        return None
    lowered = value.strip().casefold()
    if lowered in {"", "auto"}:
        return None
    try:
        return ParserName(lowered)
    except ValueError:
        return None


async def _parse_document_raw(
    *,
    data: bytes,
    filename: str,
    mime_type: str,
    tenant_id: UUID,
    document_id: UUID,
    version_id: UUID,
    parser_requested: str | None,
    max_pages: int,
) -> tuple[RawParserResult, list[str]]:
    """Parse via registry routing with pdfium always available as final fallback."""
    source = ParseSource(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        filename=filename,
        mime_type=mime_type or "application/octet-stream",
        content=data,
    )
    override = _parse_parser_name(parser_requested)
    options = ParseOptions(
        profile=ParserProfile.BALANCED,
        parser_override=override,
        ocr_mode=OcrMode.AUTO,
        failure_mode="fallback",
    )
    service = ParseDocumentService()
    attempted: list[str] = []
    try:
        selection = await service.select_parser(source, options)
        chain = [selection.primary, *selection.fallbacks]
        if ParserName.PDFIUM not in chain:
            chain.append(ParserName.PDFIUM)
        last_error: Exception | None = None
        for parser_name in chain:
            attempted.append(parser_name.value)
            try:
                raw = await service.parse_raw(source, parser_name, options)
                if not raw.elements and parser_name is not ParserName.PDFIUM:
                    raise ParserError(
                        "Parser returned no elements",
                        details={"parser": parser_name.value},
                    )
                raw.metadata = {
                    **dict(raw.metadata),
                    "selected_parser": selection.primary.value,
                    "attempted_parsers": list(attempted),
                    "routing_reason": selection.reason,
                }
                if attempted and attempted[-1] != selection.primary.value:
                    raw.warnings.append(
                        f"parser_fallback_used:{attempted[-1]}_after_{selection.primary.value}"
                    )
                return raw, attempted
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "ingest_parser_attempt_failed",
                    parser=parser_name.value,
                    error=str(exc),
                )
                continue
        raise ParserError(
            "All parser attempts failed",
            details={"attempted": attempted, "last_error": str(last_error)},
            cause=last_error,
        )
    except Exception as exc:
        logger.warning("ingest_parser_routing_failed", error=str(exc))
        mime = mime_type.lower()
        if mime == "application/pdf" or filename.lower().endswith(".pdf"):
            raw = await asyncio.to_thread(
                _extract_pdf_raw, data, filename=filename, max_pages=max_pages
            )
            raw.warnings.append(f"parser_routing_fallback:{type(exc).__name__}")
            return raw, attempted or ["pdfium"]
        if mime.startswith("text/") or filename.lower().endswith(
            (".txt", ".md", ".markdown", ".csv")
        ):
            raw = _extract_text_raw(data, filename=filename)
            raw.warnings.append(f"parser_routing_fallback:{type(exc).__name__}")
            return raw, attempted or ["plaintext"]
        raise


def _render_page_png(data: bytes, page_number: int, *, scale: float = 1.5) -> bytes:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(data)
    try:
        page = document[page_number - 1]
        try:
            bitmap = page.render(scale=scale)
            pil = bitmap.to_pil()
            from io import BytesIO

            buffer = BytesIO()
            pil.save(buffer, format="PNG", optimize=True)
            return buffer.getvalue()
        finally:
            page.close()
    finally:
        document.close()


def _page_element_stats(
    raw: RawParserResult,
) -> tuple[dict[int, str], dict[int, float], dict[int, float], dict[int, int]]:
    """Aggregate native text / image presence per page when parser metrics are sparse."""
    page_texts: dict[int, list[str]] = {}
    text_chars: dict[int, int] = {}
    image_counts: dict[int, int] = {}
    for element in raw.elements:
        page = int(element.page_start or 1)
        content = (element.normalized_content or element.raw_content or "").strip()
        if content:
            page_texts.setdefault(page, []).append(content)
            text_chars[page] = text_chars.get(page, 0) + len(content)
        if element.element_type in {ElementType.IMAGE, ElementType.CHART}:
            image_counts[page] = image_counts.get(page, 0) + 1
    joined = {page: "\n".join(parts) for page, parts in page_texts.items()}
    densities = {page: float(chars) for page, chars in text_chars.items()}
    coverages: dict[int, float] = {}
    for page, count in image_counts.items():
        # Heuristic: one or more image/chart elements with little text ≈ visual page.
        density = densities.get(page, 0.0)
        if count >= 1 and density < 400:
            coverages[page] = 0.75 if density < 200 else 0.55
        else:
            coverages[page] = min(1.0, 0.35 + 0.15 * count)
    return joined, densities, coverages, image_counts


def _looks_like_flat_chart_ocr(text: str) -> bool:
    """True when OCR flattened a chart into loose % labels without structure."""
    if not text or not text.strip():
        return False
    percent_count = len(_PERCENT_TOKEN.findall(text))
    if percent_count < 4:
        return False
    if _FLAT_CHART_HINT.search(text) or _CHART_PAGE_HINT.search(text):
        return True
    # Many percent tokens plus categorical concentration / comparison cues.
    if percent_count >= 6 and re.search(
        r"(?i)\b(25\s*%|50\s*%|75\s*%|concentration|comparison|vs\.?|versus)\b",
        text,
    ):
        return True
    return False


def _select_vision_pages(raw: RawParserResult, *, max_pages: int = 15) -> list[int]:
    if max_pages <= 0:
        return []
    scored: list[tuple[int, int]] = []
    forced: list[tuple[int, int]] = []  # (priority, page_number); higher first
    element_texts, element_densities, element_coverages, image_counts = _page_element_stats(raw)
    page_texts = {
        int(k): str(v)
        for k, v in (raw.metadata.get("page_texts") or {}).items()
        if str(k).isdigit()
    }
    for page_number, text in element_texts.items():
        page_texts.setdefault(page_number, text)

    for page in raw.pages:
        text = page_texts.get(page.page_number, "")
        score = 0
        force_priority = 0
        density = page.text_density
        if density is None:
            density = element_densities.get(page.page_number, 0.0)
        coverage = page.image_coverage
        if coverage is None:
            coverage = element_coverages.get(page.page_number, 0.0)
        image_count = image_counts.get(page.page_number, 0)
        if density < 80:
            score += 100
        if density < 200:
            score += 20
        if coverage >= 0.5:
            score += 40
        if image_count >= 1:
            score += 60
        if _FIGURE_HINT.search(text):
            score += 50
        if _MAP_LOCATION_HINT.search(text) and (image_count >= 1 or density < 250):
            score += 100
            force_priority = max(force_priority, 800)
        if _CHART_PAGE_HINT.search(text):
            score += 120
            force_priority = max(force_priority, 900)
        # PaddleOCR/etc. often flattens bar charts to text-only % fragments.
        if _looks_like_flat_chart_ocr(text):
            score += 140
            force_priority = max(force_priority, 1000)
        # Prefer sparse visual pages (charts/photos/maps) even without keyword text.
        if coverage >= 0.5 and density < 120:
            score += 80
            if 40 <= page.page_number <= 80:
                score += 40
                force_priority = max(force_priority, 600)
        if image_count >= 1 and density < 250:
            score += 90
            force_priority = max(force_priority, 700)
        if force_priority > 0:
            forced.append((force_priority, page.page_number))
        if score > 0:
            scored.append((score, page.page_number))
    # Higher priority/score first; on ties prefer earlier pages.
    forced.sort(key=lambda item: (-item[0], item[1]))
    scored.sort(key=lambda item: (-item[0], item[1]))
    selected: list[int] = []
    for _, page_number in forced:
        if page_number not in selected:
            selected.append(page_number)
        if len(selected) >= max_pages:
            return sorted(selected)
    for _, page_number in scored:
        if page_number not in selected:
            selected.append(page_number)
        if len(selected) >= max_pages:
            break
    return sorted(selected)


def _parse_vision_json(text: str) -> dict[str, object]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", cleaned)
        if not match:
            return {
                "page_summary": cleaned[:500],
                "ocr_text": cleaned[:4000],
                "tables": [],
                "formulas": [],
                "figures": [],
            }
        payload = json.loads(match.group(0))
    return payload if isinstance(payload, dict) else {}


async def _vision_enrich_pages(
    chat: ChatModel,
    data: bytes,
    raw: RawParserResult,
    *,
    max_pages: int = 15,
) -> list[RawElement]:
    if max_pages <= 0:
        return []
    pages = _select_vision_pages(raw, max_pages=max_pages)
    if not pages:
        return []
    start_order = max((el.reading_order for el in raw.elements), default=-1) + 1
    extras: list[RawElement] = []
    order = start_order
    for page_number in pages:
        payload: dict[str, object] = {}
        for attempt in range(3):
            try:
                png = await asyncio.to_thread(_render_page_png, data, page_number)
                response = await chat.generate(
                    GenerationRequest(
                        messages=[
                            ChatMessage(
                                role=MessageRole.USER,
                                content=[
                                    TextContentPart(text=_VISION_PROMPT),
                                    ImageBytesContentPart(data=png, mime_type="image/png"),
                                ],
                            )
                        ],
                        role=ModelRole.VISION,
                        model_name=os.environ.get("OPENAI_VISION_MODEL") or None,
                        temperature=0.0,
                        prompt_version="local-pdf-vision-v3-barcharts",
                    )
                )
                payload = _parse_vision_json(response.text)
                break
            except Exception as exc:
                if attempt >= 2:
                    logger.warning(
                        "vision_page_enrichment_failed",
                        page=page_number,
                        error=str(exc),
                    )
                    raw.warnings.append(f"vision_failed_page_{page_number}")
                    payload = {}
                else:
                    await asyncio.sleep(1.5 * (attempt + 1))
                    continue
        if not payload:
            continue

        ocr = str(payload.get("ocr_text") or "").strip()
        summary = str(payload.get("page_summary") or "").strip()
        conditions = str(payload.get("measurement_conditions") or "").strip()
        callouts_raw = payload.get("callouts")
        callouts = (
            [str(item).strip() for item in callouts_raw if str(item).strip()]
            if isinstance(callouts_raw, list)
            else []
        )
        figures = payload.get("figures") if isinstance(payload.get("figures"), list) else []
        tables = payload.get("tables") if isinstance(payload.get("tables"), list) else []
        formulas = payload.get("formulas") if isinstance(payload.get("formulas"), list) else []

        figure_bits: list[str] = []
        chart_figures: list[dict[str, object]] = []
        for figure in figures:
            if not isinstance(figure, dict):
                continue
            figure_type = str(figure.get("type") or "figure").strip().lower()
            values_md = str(
                figure.get("values_markdown") or figure.get("data_markdown") or ""
            ).strip()
            bit = (
                f"[{figure_type}] "
                f"{figure.get('title') or ''} "
                f"{figure.get('description') or ''} "
                f"{values_md} "
                f"{figure.get('ocr_labels') or ''} "
                f"{figure.get('series_ranking') or ''}".strip()
            ).strip()
            if bit:
                figure_bits.append(bit)
            if figure_type == "chart" or values_md:
                chart_figures.append(figure)

        enrichment_bits = [
            summary,
            f"Measurement conditions: {conditions}" if conditions else "",
            ("Callouts: " + "; ".join(callouts)) if callouts else "",
            *figure_bits,
        ]
        description = "\n".join(part for part in enrichment_bits if part) or "Visual page content"
        page_path = [f"Page {page_number}"]

        if chart_figures:
            for figure in chart_figures:
                legend_raw = figure.get("legend")
                legend = (
                    [str(item) for item in legend_raw if str(item).strip()]
                    if isinstance(legend_raw, list)
                    else []
                )
                trends_raw = figure.get("trends")
                trends = (
                    [str(item) for item in trends_raw if str(item).strip()]
                    if isinstance(trends_raw, list)
                    else []
                )
                axes = figure.get("axes") if isinstance(figure.get("axes"), dict) else {}
                ranking = str(figure.get("series_ranking") or "").strip()
                values_md = str(
                    figure.get("values_markdown") or figure.get("data_markdown") or ""
                ).strip()
                facets = merge_facets(
                    facets_from_chart_axes(axes if isinstance(axes, dict) else {}),
                    extract_condition_facets(conditions),
                    extract_condition_facets(
                        " ".join(
                            str(part)
                            for part in (
                                figure.get("title"),
                                figure.get("description"),
                                figure.get("ocr_labels"),
                                values_md,
                                ocr,
                            )
                            if part
                        )
                    ),
                )
                facet_prose = prose_for_facets(facets)
                chart_text = "\n".join(
                    part
                    for part in [
                        str(figure.get("title") or summary or "").strip(),
                        str(figure.get("description") or "").strip(),
                        f"Chart values:\n{values_md}" if values_md else "",
                        f"OCR: {ocr}" if ocr else "",
                        f"Labels: {figure.get('ocr_labels') or ''}".strip(),
                        f"Measurement conditions: {conditions}" if conditions else "",
                        ("Callouts: " + "; ".join(callouts)) if callouts else "",
                        f"Ranking: {ranking}" if ranking else "",
                        ("Trends: " + "; ".join(trends)) if trends else "",
                        ("Legend: " + "; ".join(legend)) if legend else "",
                        facet_prose,
                    ]
                    if part
                )
                chart_meta: dict[str, object] = {
                    "chart_type": str(figure.get("type") or "chart"),
                    "title": str(figure.get("title") or summary or "").strip() or None,
                    "visual_description": chart_text,
                    "ocr_text": ocr or chart_text,
                    "values_markdown": values_md or None,
                    "axes": axes,
                    "legend": legend,
                    "trends": trends,
                    "callouts": callouts,
                    "measurement_conditions": conditions or None,
                    "series_ranking": ranking or None,
                    "source": "openai_vision_chart",
                }
                if not facets.is_empty:
                    chart_meta["condition_facets"] = facets.to_metadata()
                extras.append(
                    RawElement(
                        element_type=ElementType.CHART,
                        page_start=page_number,
                        page_end=page_number,
                        reading_order=order,
                        section_path=page_path,
                        raw_content=chart_text,
                        normalized_content=chart_text,
                        ocr_confidence=0.75,
                        metadata=chart_meta,
                    )
                )
                order += 1
                if values_md and not any(
                    isinstance(t, dict) and str(t.get("markdown") or "").strip() == values_md
                    for t in tables
                ):
                    tables = [
                        *tables,
                        {
                            "caption": str(figure.get("title") or summary or f"Page {page_number} chart").strip(),
                            "markdown": values_md,
                        },
                    ]
        elif ocr or summary or figures:
            image_facets = merge_facets(
                extract_condition_facets(conditions),
                extract_condition_facets(f"{ocr}\n{description}"),
            )
            image_meta: dict[str, object] = {
                "visual_description": description,
                "ocr_text": ocr or description,
                "callouts": callouts,
                "measurement_conditions": conditions or None,
                "source": "openai_vision_page",
            }
            if not image_facets.is_empty:
                image_meta["condition_facets"] = image_facets.to_metadata()
            extras.append(
                RawElement(
                    element_type=ElementType.IMAGE,
                    page_start=page_number,
                    page_end=page_number,
                    reading_order=order,
                    section_path=page_path,
                    raw_content=description,
                    normalized_content=description,
                    ocr_confidence=0.7,
                    metadata=image_meta,
                )
            )
            order += 1

        for table in tables:
            if not isinstance(table, dict):
                continue
            markdown = str(table.get("markdown") or "").strip()
            caption = str(table.get("caption") or f"Page {page_number} vision table").strip()
            if not markdown:
                continue
            extras.append(
                RawElement(
                    element_type=ElementType.TABLE,
                    page_start=page_number,
                    page_end=page_number,
                    reading_order=order,
                    section_path=page_path,
                    raw_content=markdown,
                    normalized_content=markdown,
                    metadata={"caption": caption, "source": "openai_vision_table"},
                )
            )
            order += 1

        for formula in formulas:
            if not isinstance(formula, dict):
                continue
            text = str(formula.get("text") or "").strip()
            formula_description = str(formula.get("description") or text).strip()
            if not text and not formula_description:
                continue
            extras.append(
                RawElement(
                    element_type=ElementType.EQUATION,
                    page_start=page_number,
                    page_end=page_number,
                    reading_order=order,
                    section_path=page_path,
                    raw_content=text or formula_description,
                    normalized_content=formula_description or text,
                    metadata={
                        "latex": text or formula_description,
                        "semantic_description": formula_description or text,
                        "source": "openai_vision_formula",
                    },
                )
            )
            order += 1

    if extras:
        raw.warnings.append(f"vision_enriched_pages={len(pages)}")
    return extras


@dataclass
class ProcessRegisteredDocumentService:
    """Index a registered document in-process (no separate worker queue)."""

    document_repo: DocumentRepository
    ingestion_repo: IngestionRepository
    object_store: ObjectStore
    embedding_model: EmbeddingModel
    vector_store: ChunkVectorStore
    chunk_store: ChunkLookupStore
    lexical_store: LexicalSearchStore
    graph_store: GraphStore | None = None
    chat_model: ChatModel | None = None
    structured_extractor: StructuredExtractor | None = None
    parsing_audit_repo: ParsingAuditRepository | None = None
    max_pages: int = 2_000
    vision_max_pages: int = 28
    semantic_graph: bool = True
    on_commit: object | None = None

    async def execute(self, tenant: TenantContext, ingestion_run_id: UUID) -> None:
        run = await self.ingestion_repo.get_run(tenant, ingestion_run_id)
        if run is None:
            raise NotFoundError(
                "Ingestion run not found",
                details={"ingestion_run_id": str(ingestion_run_id)},
            )
        stages = await self.ingestion_repo.list_stages(tenant, ingestion_run_id)
        version = await self.document_repo.get_version(tenant, run.version_id)
        if version is None or not version.original_object_key:
            raise NotFoundError(
                "Document version or object key missing",
                details={"version_id": str(run.version_id)},
            )

        now = datetime.now(UTC)
        run.status = IngestionRunStatus.RUNNING
        run.updated_at = now
        await self.ingestion_repo.update_run(tenant, run)

        document = await self.document_repo.get_document(tenant, run.document_id)
        if document is not None:
            document.status = DocumentLifecycleStatus.INGESTING
            document.updated_at = now
            await self.document_repo.update_document(tenant, document)

        audit = ParsingAuditCollector(
            tenant_id=tenant.tenant_id,
            document_id=run.document_id,
            version_id=run.version_id,
            ingestion_run_id=ingestion_run_id,
        )
        try:
            data = await self.object_store.get_bytes(
                tenant, object_key=version.original_object_key
            )
            filename = version.source_filename or Path(version.original_object_key).name
            mime = (version.mime_type or "").lower()
            embed_name = getattr(self.embedding_model, "model_name", None) or type(
                self.embedding_model
            ).__name__
            vision_name = None
            if self.chat_model is not None:
                vision_name = getattr(self.chat_model, "model_name", None) or type(
                    self.chat_model
                ).__name__
            audit.document_started(
                original_filename=filename,
                file_hash=version.content_hash,
                mime_type=version.mime_type,
                file_size_bytes=version.byte_size,
                config_profile="local_pipeline",
                ocr_strategy="auto",
                vision_strategy="page_enrichment" if self.chat_model else "disabled",
                embedding_model=str(embed_name),
                vision_llm=str(vision_name) if vision_name else None,
            )

            audit.stage_started("PARSE", tool="parser_registry", input_count=1)
            raw, attempted = await _parse_document_raw(
                data=data,
                filename=filename,
                mime_type=version.mime_type or "application/octet-stream",
                tenant_id=tenant.tenant_id,
                document_id=run.document_id,
                version_id=run.version_id,
                parser_requested=run.parser_requested,
                max_pages=self.max_pages,
            )
            primary = raw.parser_name
            fallbacks = [name for name in attempted if name != primary]
            audit.record_routing(
                RoutingReasonCode.PRIMARY_PARSER_SELECTED
                if not run.parser_requested or run.parser_requested in {"auto", None}
                else RoutingReasonCode.PARSER_OVERRIDE,
                message=f"Primary parser selected: {primary}",
                selected_tool=primary,
                details={"attempted": attempted, "requested": run.parser_requested},
            )
            if fallbacks:
                audit.record_routing(
                    RoutingReasonCode.FALLBACK_TRIGGERED,
                    message=f"Fallback parsers attempted: {', '.join(fallbacks)}",
                    selected_tool=primary,
                    details={"fallbacks": fallbacks},
                )
            audit.document.primary_parser = primary
            audit.document.fallback_parsers = fallbacks
            for order, element in enumerate(raw.elements):
                page_no = int(element.page_start)
                bbox = None
                if element.bounding_boxes:
                    box = element.bounding_boxes[0]
                    bbox = {
                        "x0": float(box.x0),
                        "y0": float(box.y0),
                        "x1": float(box.x1),
                        "y1": float(box.y1),
                    }
                audit.element_detected(
                    page_number=page_no,
                    normalized_element_type=element.element_type.value,
                    original_parser_element_type=str(
                        element.metadata.get("raw_type") or element.element_type.value
                    ),
                    detector=primary,
                    parser_name=primary,
                    reading_order=element.reading_order if element.reading_order else order,
                    bbox=bbox,
                    section_path=list(element.section_path),
                    confidence_score=element.parser_confidence,
                    confidence_source=(
                        "parser" if element.parser_confidence is not None else None
                    ),
                )
                page = audit.ensure_page(page_no)
                audit._pages[page_no] = page.model_copy(
                    update={
                        "page_parser": primary,
                        "page_width": page.page_width,
                        "page_height": page.page_height,
                    }
                )
            for page in raw.pages or []:
                existing = audit.ensure_page(int(page.page_number))
                audit._pages[int(page.page_number)] = existing.model_copy(
                    update={
                        "page_width": page.width,
                        "page_height": page.height,
                        "has_native_text": not bool(page.is_scanned),
                        "ocr_required": bool(page.is_scanned),
                        "page_parser": primary,
                        "status": existing.status,
                    }
                )
                audit.page_completed(
                    int(page.page_number),
                    page_parser=primary,
                    has_native_text=not bool(page.is_scanned),
                    ocr_required=bool(page.is_scanned),
                )
            audit.stage_completed(
                "PARSE",
                status=StageRunStatus.COMPLETED,
                output_count=len(raw.elements),
                warning_count=len(raw.warnings or []),
            )

            if self.chat_model is not None and (
                mime == "application/pdf" or filename.lower().endswith(".pdf")
            ):
                audit.stage_started(
                    "VISION_ENRICHMENT",
                    tool="vision",
                    model_name=str(vision_name),
                )
                audit.record_routing(
                    RoutingReasonCode.VISION_REQUIRED,
                    message="Vision enrichment for sparse/visual PDF pages",
                    selected_model=str(vision_name),
                )
                # Vision enrichment for sparse/visual pages regardless of primary parser.
                vision_elements = await _vision_enrich_pages(
                    self.chat_model,
                    data,
                    raw,
                    max_pages=self.vision_max_pages,
                )
                if vision_elements:
                    raw.elements.extend(vision_elements)
                    for order, element in enumerate(vision_elements):
                        page_no = int(element.page_start)
                        report = audit.element_detected(
                            page_number=page_no,
                            normalized_element_type=element.element_type.value,
                            detector="vision",
                            parser_name=primary,
                            reading_order=10_000 + order,
                            status=ElementProcessingStatus.PROCESSED,
                        )
                        audit.element_processed(
                            report,
                            processing_tool="vision_enrichment",
                            model_name=str(vision_name),
                            status=ElementProcessingStatus.PROCESSED,
                        )
                audit.stage_completed(
                    "VISION_ENRICHMENT",
                    status=StageRunStatus.COMPLETED,
                    output_count=len(vision_elements or []),
                )

            if not raw.elements:
                raise ValidationError(
                    "No extractable content found in document",
                    details={"filename": filename, "attempted_parsers": attempted},
                )

            source = ParseSource(
                tenant_id=tenant.tenant_id,
                document_id=run.document_id,
                version_id=run.version_id,
                filename=filename,
                mime_type=version.mime_type or "application/octet-stream",
                content=data,
            )
            audit.stage_started("NORMALIZE", tool="normalize_parser_result")
            normalized = normalize_parser_result(raw, source)
            normalized_ids = {element.element_id for element in normalized.elements}
            # Pair detected raw elements to normalized ones by page+type+order best-effort.
            by_page_type: dict[tuple[int | None, str | None], list] = {}
            for element in normalized.elements:
                key = (element.page_start, element.element_type.value)
                by_page_type.setdefault(key, []).append(element)
            for report in list(audit._elements):
                key = (report.page_number, report.normalized_element_type)
                bucket = by_page_type.get(key) or []
                if bucket:
                    matched = bucket.pop(0)
                    audit.update_element(
                        report,
                        element_id=matched.element_id,
                        section_path=list(matched.section_path or []),
                        reached_normalized=True,
                        status=ElementProcessingStatus.PROCESSED,
                        processing_tool="normalizer",
                    )
            audit.mark_normalized(normalized_ids)
            audit.stage_completed(
                "NORMALIZE",
                status=StageRunStatus.COMPLETED,
                output_count=len(normalized.elements),
            )

            audit.stage_started("CHUNK", tool="HierarchicalMultimodalChunker")
            chunks = HierarchicalMultimodalChunker().chunk(normalized)
            all_chunks = list(chunks.all_chunks)
            doc_title = (
                (document.title or "").strip()
                if document is not None
                else ""
            ) or filename
            stamped: list = []
            for chunk in all_chunks:
                meta = dict(chunk.metadata)
                meta["document_name"] = doc_title
                stamped.append(chunk.model_copy(update={"metadata": meta}))
            all_chunks = stamped
            audit.stage_completed("CHUNK", output_count=len(all_chunks))
            audit.mark_downstream(chunking=True)

            audit.stage_started("EMBED", tool=str(embed_name), model_name=str(embed_name))
            embedded = await EmbedChunksService(self.embedding_model).embed(
                all_chunks, parser=raw.parser_name
            )
            if not embedded.records:
                raise ValidationError("No embeddings produced from document")
            audit.stage_completed("EMBED", output_count=len(embedded.records))

            audit.stage_started("INDEX_VECTOR", tool="vector_store")
            await self.vector_store.ensure_collection(
                vector_size=len(embedded.records[0].content_vector)
            )
            await self.vector_store.upsert(tenant, embedded.records)
            await self.chunk_store.upsert(tenant, all_chunks)
            await self.lexical_store.upsert(tenant, all_chunks)
            audit.stage_completed("INDEX_VECTOR", output_count=len(embedded.records))
            audit.mark_downstream(vector_index=True)

            graph_counts: dict[str, int] = {}
            if self.graph_store is not None:
                audit.stage_started("INDEX_GRAPH", tool="graph_store")
                chunking_result = ChunkingResult(
                    parents=[c for c in all_chunks if c.parent_chunk_id is None],
                    children=[c for c in all_chunks if c.parent_chunk_id is not None],
                )
                if self.structured_extractor is not None and self.semantic_graph:
                    try:
                        # Cap extraction cost on large decks while still covering
                        # section parents and table/multimodal children.
                        parents = list(chunking_result.parents)[:30]
                        children = [
                            child
                            for child in chunking_result.children
                            if child.chunk_type.value in {"multimodal_composite", "table"}
                        ][:30]
                        build_result = await BuildKnowledgeGraphService(
                            self.structured_extractor,
                            self.graph_store,
                        ).build(
                            tenant,
                            normalized,
                            ChunkingResult(parents=parents, children=children),
                            persist=True,
                        )
                        graph_counts = dict(build_result.upsert_counts)
                    except Exception as graph_exc:
                        logger.warning(
                            "semantic_graph_build_failed",
                            error=str(graph_exc),
                            document_id=str(run.document_id),
                        )
                        raw.warnings.append(f"semantic_graph_failed:{type(graph_exc).__name__}")
                        projected = StructuralGraphBuilder().build(
                            normalized, chunking_result
                        )
                        graph_counts = await self.graph_store.upsert_graph(
                            tenant, projected
                        )
                else:
                    projected = StructuralGraphBuilder().build(normalized, chunking_result)
                    graph_counts = await self.graph_store.upsert_graph(tenant, projected)
                audit.stage_completed(
                    "INDEX_GRAPH",
                    output_count=int(graph_counts.get("nodes") or 0)
                    + int(graph_counts.get("relationships") or 0),
                )
                audit.mark_downstream(graph_index=True)

            for warning in raw.warnings or []:
                audit.add_issue(severity="warning", message=str(warning), stage_name="PARSE")

            done = datetime.now(UTC)
            for stage in stages:
                stage.status = StageStatus.COMPLETED
                stage.attempt_count = max(1, stage.attempt_count)
                stage.started_at = stage.started_at or done
                stage.completed_at = done
                stage.warning = None
                stage.error_code = None
                stage.error_message = None
                await self.ingestion_repo.update_stage(tenant, stage)

            run.status = (
                IngestionRunStatus.COMPLETED_WITH_WARNINGS
                if raw.warnings
                else IngestionRunStatus.COMPLETED
            )
            run.pages_processed = normalized.page_count
            run.elements_processed = len(normalized.elements)
            run.parser_used = raw.parser_name
            run.latest_warning = raw.warnings[0] if raw.warnings else None
            run.error_code = None
            run.error_message = None
            run.updated_at = done
            await self.ingestion_repo.update_run(tenant, run)

            if document is not None:
                meta = dict(document.metadata)
                meta["page_count"] = normalized.page_count
                document.metadata = meta
                document.status = DocumentLifecycleStatus.READY
                document.updated_at = done
                await self.document_repo.update_document(tenant, document)

            snapshot = audit.document_completed(
                ingestion_status=run.status.value,
                primary_parser=raw.parser_name,
                fallback_parsers=fallbacks,
                total_pages=normalized.page_count,
                total_normalized_elements=len(normalized.elements),
            )
            if self.parsing_audit_repo is not None:
                await self.parsing_audit_repo.save_snapshot(tenant, snapshot)

            if callable(self.on_commit):
                maybe = self.on_commit()
                if asyncio.iscoroutine(maybe):
                    await maybe

            type_counts: dict[str, int] = {}
            for element in normalized.elements:
                key = element.element_type.value
                type_counts[key] = type_counts.get(key, 0) + 1

            logger.info(
                "local_ingest_completed",
                ingestion_run_id=str(ingestion_run_id),
                document_id=str(run.document_id),
                chunks=len(embedded.records),
                pages=normalized.page_count,
                element_types=type_counts,
                graph_nodes=graph_counts.get("nodes"),
                graph_relationships=graph_counts.get("relationships"),
                audit_elements=snapshot.document.total_detected_elements,
                content_losses=len(snapshot.content_losses),
            )
        except Exception as exc:
            failed = datetime.now(UTC)
            run.status = IngestionRunStatus.FAILED
            run.error_code = type(exc).__name__
            run.error_message = str(exc)
            run.updated_at = failed
            await self.ingestion_repo.update_run(tenant, run)
            if document is not None:
                document.status = DocumentLifecycleStatus.FAILED
                document.updated_at = failed
                await self.document_repo.update_document(tenant, document)
            try:
                audit.add_issue(
                    severity="error",
                    message=str(exc),
                    code=type(exc).__name__,
                    stage_name="FINALIZE",
                )
                snapshot = audit.document_completed(
                    ingestion_status=IngestionRunStatus.FAILED.value,
                )
                if self.parsing_audit_repo is not None:
                    await self.parsing_audit_repo.save_snapshot(tenant, snapshot)
            except Exception:
                logger.warning(
                    "parsing_audit_persist_failed",
                    ingestion_run_id=str(ingestion_run_id),
                    exc_info=True,
                )
            if callable(self.on_commit):
                maybe = self.on_commit()
                if asyncio.iscoroutine(maybe):
                    await maybe
            logger.exception(
                "local_ingest_failed",
                ingestion_run_id=str(ingestion_run_id),
                document_id=str(run.document_id),
            )
            raise
