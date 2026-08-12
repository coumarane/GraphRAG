#!/usr/bin/env python3
"""Batch reliability next-steps: re-embed, OCR catalogs, sample matrix, chart checks."""

from __future__ import annotations

import asyncio
import json
import os
import re
from pathlib import Path
from uuid import UUID

from enterprise_rag.application.ingestion import RegisterSourceRequest
from enterprise_rag.application.runtime.runtime import build_runtime_container
from enterprise_rag.domain.ids import new_id
from enterprise_rag.domain.retrieval.enums import RetrievalMode
from enterprise_rag.domain.retrieval.models import QueryRequest, RetrievalFilters
from enterprise_rag.domain.tenant import TenantContext

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "sample_data"
REPORTS = ROOT / "reports"

NSG_ID = UUID("019fdde7-25d9-7469-bff2-1bb70eaee2ab")
EMU_ID = UUID("019fddd2-96f6-7d9c-b6c6-25e21f006bba")

REEMBED = [
    {
        "path": SAMPLE / "EMULGEN 2020G-SPEC & COMPOSITION.PDF",
        "document_id": EMU_ID,
        "title": "EMULGEN 2020G SPEC",
        "parser": "pdfium",
        "vision_max_pages": 0,
    },
    {
        "path": SAMPLE / "NSG ALL PRODUCT-PRESENTATION ICE 2023.pdf",
        "document_id": NSG_ID,
        "title": "NSG ALL PRODUCT-PRESENTATION ICE 2023",
        "parser": "pdfium",
        "vision_max_pages": 0,
    },
]

OCR_DOCS = [
    {
        "path": SAMPLE / "BNB CHEM-Product Catalog.pdf",
        "title": "BNB CHEM-Product Catalog",
        "parser": "paddleocr",
        "vision_max_pages": 0,
    },
    {
        "path": SAMPLE / "SUNSPHERE-CATALOG.pdf",
        "title": "SUNSPHERE-CATALOG",
        "parser": "paddleocr",
        "vision_max_pages": 0,
    },
]

MATRIX_DOCS = [
    {
        "path": SAMPLE / "Acerola Extract WB-E TDS.pdf",
        "title": "Acerola Extract WB-E TDS",
        "parser": "pdfium",
        "vision_max_pages": 0,
    },
    {
        "path": SAMPLE / "ASTAXANTHIN-Catalog.pdf",
        "title": "ASTAXANTHIN-Catalog",
        "parser": "pdfium",
        "vision_max_pages": 0,
    },
    {
        "path": SAMPLE / "BORON NITRIDE SHP-6- Presentation.pdf",
        "title": "BORON NITRIDE SHP-6 Presentation",
        "parser": "pdfium",
        "vision_max_pages": 0,
    },
    {
        "path": SAMPLE / "CARFIL 1.3-BG.pdf",
        "title": "CARFIL 1.3-BG",
        "parser": "pdfium",
        "vision_max_pages": 0,
    },
]


async def _ingest_one(container, tenant: TenantContext, item: dict) -> dict:
    path: Path = item["path"]
    if not path.exists():
        return {"title": item["title"], "status": "missing", "path": str(path)}
    os.environ["VISION_MAX_PAGES"] = str(item.get("vision_max_pages", 0))
    process = container.require_process_ingestion()
    process.vision_max_pages = int(item.get("vision_max_pages", 0))

    # Drop prior version projections when re-forcing the same document.
    existing_id = item.get("document_id")
    if existing_id is not None:
        existing = await container.require_document_repo().get_document(tenant, existing_id)
        if existing is not None and existing.current_version_id is not None:
            try:
                await container.vector_store.delete_version(
                    tenant,
                    document_id=existing.document_id,
                    version_id=existing.current_version_id,
                )
            except Exception as exc:  # noqa: BLE001
                print(f"warn vector clear: {exc}", flush=True)
            if container.graph_store is not None:
                try:
                    await container.graph_store.delete_version(
                        tenant,
                        document_id=existing.document_id,
                        version_id=existing.current_version_id,
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"warn graph clear: {exc}", flush=True)

    request = RegisterSourceRequest(
        local_path=str(path),
        document_id=item.get("document_id"),
        title=item["title"],
        parser_requested=item.get("parser", "auto"),
        force_new_version=True,
        correlation_id=str(new_id()),
    )
    result = await container.require_register_source().execute(tenant, request)
    await process.execute(tenant, result.ingestion_run_id)
    if container.on_commit is not None:
        await container.on_commit()  # type: ignore[misc]
    run = await container.require_ingestion_repo().get_run(tenant, result.ingestion_run_id)
    doc = await container.require_document_repo().get_document(tenant, result.document_id)
    chunks = []
    if doc is not None and doc.current_version_id is not None:
        # Force hydrate from Qdrant for durable lookup.
        hydrate = getattr(container.chunk_store, "hydrate_from_qdrant", None)
        if callable(hydrate):
            hydrate(tenant, document_ids=[result.document_id])
        chunks = container.chunk_store.list_for_version(
            tenant,
            document_id=result.document_id,
            version_id=doc.current_version_id,
        )
    preview_lens = [len(ch.text) for ch in chunks]
    return {
        "title": item["title"],
        "status": "ok",
        "document_id": str(result.document_id),
        "version_id": str(result.version_id),
        "run_status": run.status.value if run else None,
        "pages_processed": run.pages_processed if run else None,
        "elements_processed": run.elements_processed if run else None,
        "chunk_count": len(chunks),
        "max_text_preview": max(preview_lens) if preview_lens else 0,
        "page_count_meta": (doc.metadata or {}).get("page_count") if doc else None,
        "parser_used": run.parser_used if run else None,
        "parser_requested": item.get("parser"),
    }


async def _ask(container, tenant, question: str, doc_ids: list[UUID]) -> dict:
    out = await container.query.query(
        tenant,
        QueryRequest(
            question=question,
            mode=RetrievalMode.AUTO,
            filters=RetrievalFilters(document_ids=doc_ids),
            top_k=12,
        ),
    )
    answer = out.response.answer or ""
    cites = out.response.citations or []
    evidence = out.retrieval.result.evidence if out.retrieval else []
    return {
        "question": question,
        "answer": answer,
        "citation_count": len(cites),
        "evidence_count": len(evidence),
        "evidence_docs": sorted({str(e.document_id) for e in evidence}),
        "modalities": sorted({str(e.modality) for e in evidence}),
        "numbers_in_answer": re.findall(r"\d+(?:\.\d+)?", answer),
    }


def _chart_fidelity_pass(row: dict, required_tokens: list[str]) -> bool:
    ans = row["answer"].casefold()
    return all(token.casefold() in ans for token in required_tokens) and row["citation_count"] > 0


async def main() -> None:
    # Prefer durable backends from .env via settings.
    container = build_runtime_container()
    tenant_rec = await container.tenant_repo.get_by_key("demo")
    tenant = TenantContext(tenant_id=tenant_rec.tenant_id, tenant_key="demo")

    ingest_results: list[dict] = []
    print("=== RE-EMBED NSG + EMULGEN ===", flush=True)
    for item in REEMBED:
        print(f">> {item['title']}", flush=True)
        try:
            ingest_results.append(await _ingest_one(container, tenant, item))
        except Exception as exc:  # noqa: BLE001
            ingest_results.append(
                {"title": item["title"], "status": "error", "error": f"{type(exc).__name__}:{exc}"}
            )
        print(json.dumps(ingest_results[-1], indent=2), flush=True)

    print("=== OCR SCANNED CATALOGS ===", flush=True)
    for item in OCR_DOCS:
        print(f">> {item['title']}", flush=True)
        try:
            ingest_results.append(await _ingest_one(container, tenant, item))
        except Exception as exc:  # noqa: BLE001
            ingest_results.append(
                {"title": item["title"], "status": "error", "error": f"{type(exc).__name__}:{exc}"}
            )
        print(json.dumps(ingest_results[-1], indent=2), flush=True)

    print("=== HETEROGENEOUS MATRIX ===", flush=True)
    for item in MATRIX_DOCS:
        print(f">> {item['title']}", flush=True)
        try:
            ingest_results.append(await _ingest_one(container, tenant, item))
        except Exception as exc:  # noqa: BLE001
            ingest_results.append(
                {"title": item["title"], "status": "error", "error": f"{type(exc).__name__}:{exc}"}
            )
        print(json.dumps(ingest_results[-1], indent=2), flush=True)

    # Resolve latest IDs for OCR/matrix docs by title.
    docs, _ = await container.document_repo.list_documents(tenant, offset=0, limit=200)
    by_title = {(d.title or "").strip(): d for d in docs}

    challenges: list[dict] = []
    print("=== CHALLENGE QUERIES ===", flush=True)
    challenge_specs = [
        (EMU_ID, "What is the CAS number and hydroxyl value range for EMULGEN 2020G?", ["32128-65-7", "45"]),
        (NSG_ID, "In METASHINE Aurora, which grade shows the highest L* brilliance?", ["MTH100RS"]),
        (
            by_title.get("BNB CHEM-Product Catalog").document_id
            if by_title.get("BNB CHEM-Product Catalog")
            else None,
            "What company or brand is presented in the BNB CHEM product catalog?",
            ["B&B", "BNB", "chemical"],
        ),
        (
            by_title.get("SUNSPHERE-CATALOG").document_id
            if by_title.get("SUNSPHERE-CATALOG")
            else None,
            "What product line or materials does the SUNSPHERE catalog describe?",
            ["SUNSPHERE", "silica", "sphere"],
        ),
        (
            by_title.get("Acerola Extract WB-E TDS").document_id
            if by_title.get("Acerola Extract WB-E TDS")
            else None,
            "What is Acerola Extract WB-E used for or what is its key claim?",
            ["Acerola", "vitamin", "C"],
        ),
    ]
    for doc_id, question, tokens in challenge_specs:
        if doc_id is None:
            challenges.append({"question": question, "status": "skip_missing_doc"})
            continue
        print(f">> {question[:70]}...", flush=True)
        row = await _ask(container, tenant, question, [doc_id])
        soft = any(t.casefold() in row["answer"].casefold() for t in tokens)
        row["ok"] = soft and row["citation_count"] > 0
        row["expected_any"] = tokens
        challenges.append(row)
        print(f"   ok={row['ok']} cites={row['citation_count']}", flush=True)

    print("=== CHART NUMERIC FIDELITY ===", flush=True)
    chart_specs = [
        (
            "aurora_mth100rs_lstar",
            "According to the METASHINE Aurora drawdown brilliance chart, which grade has the highest L* values across PWC?",
            ["MTH100RS"],
        ),
        (
            "aurora_mt1080_transparency",
            "According to the METASHINE Aurora series notes, which grade has the highest transparency among all?",
            ["MT1080RS"],
        ),
        (
            "particle_size_effect",
            "What do small glass flake particles improve versus large particles in the NSG presentation?",
            ["coverage", "glitter"],
        ),
    ]
    chart_results = []
    for cid, question, tokens in chart_specs:
        row = await _ask(container, tenant, question, [NSG_ID])
        row["id"] = cid
        row["ok"] = _chart_fidelity_pass(row, tokens)
        chart_results.append(row)
        print(f">> {cid} ok={row['ok']}", flush=True)

    payload = {
        "ingest": ingest_results,
        "challenges": challenges,
        "chart_fidelity": chart_results,
        "summary": {
            "ingest_ok": sum(1 for r in ingest_results if r.get("status") == "ok"),
            "ingest_total": len(ingest_results),
            "challenge_ok": sum(1 for r in challenges if r.get("ok")),
            "challenge_total": sum(1 for r in challenges if "ok" in r),
            "chart_ok": sum(1 for r in chart_results if r.get("ok")),
            "chart_total": len(chart_results),
        },
    }
    out = REPORTS / "reliability-next-batch.json"
    out.write_text(json.dumps(payload, indent=2, default=str))
    print("Wrote", out)
    print(json.dumps(payload["summary"], indent=2))


if __name__ == "__main__":
    asyncio.run(main())
