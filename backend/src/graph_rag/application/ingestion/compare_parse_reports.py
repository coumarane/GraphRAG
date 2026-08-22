"""Compare two parsing audit snapshots for the same document."""

from __future__ import annotations

from uuid import UUID

from graph_rag.domain.parsing.audit import ParsingAuditSnapshot
from graph_rag.domain.parsing.audit_protocols import ParseReportDiff, ParsingAuditRepository
from graph_rag.domain.tenant import TenantContext
from graph_rag.shared.exceptions import NotFoundError, ValidationError


def _delta(a: object, b: object) -> dict[str, object]:
    return {"run_a": a, "run_b": b, "changed": a != b}


class CompareParseReportsService:
    """Backend comparison of two immutable ingestion parse reports."""

    def __init__(self, audit_repo: ParsingAuditRepository) -> None:
        self._repo = audit_repo

    async def compare(
        self,
        tenant: TenantContext,
        *,
        document_id: UUID,
        run_a: UUID,
        run_b: UUID,
    ) -> ParseReportDiff:
        if run_a == run_b:
            raise ValidationError("run_a and run_b must differ")
        snap_a = await self._repo.get_snapshot(
            tenant, document_id=document_id, ingestion_run_id=run_a
        )
        snap_b = await self._repo.get_snapshot(
            tenant, document_id=document_id, ingestion_run_id=run_b
        )
        if snap_a is None or snap_b is None:
            raise NotFoundError(
                "Parse report not found for one or both runs",
                details={
                    "document_id": str(document_id),
                    "run_a": str(run_a),
                    "run_b": str(run_b),
                    "found_a": snap_a is not None,
                    "found_b": snap_b is not None,
                },
            )
        return diff_snapshots(document_id=document_id, run_a=run_a, run_b=run_b, a=snap_a, b=snap_b)


def diff_snapshots(
    *,
    document_id: UUID,
    run_a: UUID,
    run_b: UUID,
    a: ParsingAuditSnapshot,
    b: ParsingAuditSnapshot,
) -> ParseReportDiff:
    da = a.document
    db = b.document
    document_deltas = {
        "total_detected_elements": _delta(da.total_detected_elements, db.total_detected_elements),
        "total_processed_elements": _delta(
            da.total_processed_elements, db.total_processed_elements
        ),
        "total_failed_elements": _delta(da.total_failed_elements, db.total_failed_elements),
        "total_skipped_elements": _delta(da.total_skipped_elements, db.total_skipped_elements),
        "total_normalized_elements": _delta(
            da.total_normalized_elements, db.total_normalized_elements
        ),
        "duration_ms": _delta(da.duration_ms, db.duration_ms),
        "primary_parser": _delta(da.primary_parser, db.primary_parser),
        "parser_version": _delta(da.parser_version, db.parser_version),
        "vision_llm": _delta(da.vision_llm, db.vision_llm),
        "extraction_completeness": _delta(
            da.extraction_completeness, db.extraction_completeness
        ),
        "normalization_completeness": _delta(
            da.normalization_completeness, db.normalization_completeness
        ),
    }

    pages_a = {p.page_number: p for p in a.pages}
    pages_b = {p.page_number: p for p in b.pages}
    page_deltas: list[dict] = []
    for page_number in sorted(set(pages_a) | set(pages_b)):
        pa = pages_a.get(page_number)
        pb = pages_b.get(page_number)
        page_deltas.append(
            {
                "page_number": page_number,
                "detected": _delta(
                    None if pa is None else pa.detected_elements,
                    None if pb is None else pb.detected_elements,
                ),
                "processed": _delta(
                    None if pa is None else pa.processed_elements,
                    None if pb is None else pb.processed_elements,
                ),
                "failed": _delta(
                    None if pa is None else pa.failed_elements,
                    None if pb is None else pb.failed_elements,
                ),
                "element_type_counts": _delta(
                    None if pa is None else pa.element_type_counts,
                    None if pb is None else pb.element_type_counts,
                ),
                "page_parser": _delta(
                    None if pa is None else pa.page_parser,
                    None if pb is None else pb.page_parser,
                ),
                "errors": _delta(
                    None if pa is None else pa.errors,
                    None if pb is None else pb.errors,
                ),
            }
        )

    def _elem_key(item) -> tuple:
        return (
            item.page_number,
            item.normalized_element_type,
            item.reading_order,
            str(item.element_id) if item.element_id else None,
        )

    elems_a = {_elem_key(e): e for e in a.elements}
    elems_b = {_elem_key(e): e for e in b.elements}
    element_deltas: list[dict] = []
    for key in sorted(set(elems_a) | set(elems_b), key=lambda k: (k[0] or 0, k[1] or "", k[2] or 0)):
        ea = elems_a.get(key)
        eb = elems_b.get(key)
        if ea is None:
            element_deltas.append(
                {
                    "change": "added_in_run_b",
                    "page_number": key[0],
                    "element_type": key[1],
                    "run_b_status": eb.status.value if eb else None,
                }
            )
        elif eb is None:
            element_deltas.append(
                {
                    "change": "missing_in_run_b",
                    "page_number": key[0],
                    "element_type": key[1],
                    "run_a_status": ea.status.value,
                }
            )
        elif (
            ea.status != eb.status
            or ea.parser_name != eb.parser_name
            or ea.model_name != eb.model_name
            or ea.confidence_score != eb.confidence_score
            or ea.normalized_element_type != eb.normalized_element_type
        ):
            element_deltas.append(
                {
                    "change": "modified",
                    "page_number": key[0],
                    "element_type": key[1],
                    "status": _delta(ea.status.value, eb.status.value),
                    "parser_name": _delta(ea.parser_name, eb.parser_name),
                    "model_name": _delta(ea.model_name, eb.model_name),
                    "confidence_score": _delta(ea.confidence_score, eb.confidence_score),
                }
            )

    stages_a = {s.stage_name: s for s in a.stages}
    stages_b = {s.stage_name: s for s in b.stages}
    stage_deltas = []
    for name in sorted(set(stages_a) | set(stages_b)):
        sa = stages_a.get(name)
        sb = stages_b.get(name)
        stage_deltas.append(
            {
                "stage_name": name,
                "duration_ms": _delta(
                    None if sa is None else sa.duration_ms,
                    None if sb is None else sb.duration_ms,
                ),
                "status": _delta(
                    None if sa is None else sa.status.value,
                    None if sb is None else sb.status.value,
                ),
                "tool": _delta(None if sa is None else sa.tool, None if sb is None else sb.tool),
                "model_name": _delta(
                    None if sa is None else sa.model_name,
                    None if sb is None else sb.model_name,
                ),
            }
        )

    return ParseReportDiff(
        document_id=document_id,
        run_a=run_a,
        run_b=run_b,
        document_deltas=document_deltas,
        page_deltas=page_deltas,
        element_deltas=element_deltas,
        stage_deltas=stage_deltas,
        summary={
            "pages_compared": len(page_deltas),
            "element_changes": len(element_deltas),
            "content_losses_a": len(a.content_losses),
            "content_losses_b": len(b.content_losses),
        },
    )
