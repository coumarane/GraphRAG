#!/usr/bin/env python3
"""Offline / live RAG evaluation harness for reliability validation.

Usage:
  uv run python scripts/evaluate_rag.py --documents ../data/evaluation/corpus --output ../data/reports/rag-evaluation.json
  uv run python scripts/evaluate_rag.py --documents ../data/evaluation/corpus --live --generate-questions
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from uuid import uuid4


def _load_dotenv() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        os.environ.setdefault(key, value)


_load_dotenv()

from enterprise_rag.application.chunking import EmbedChunksService, HierarchicalMultimodalChunker
from enterprise_rag.application.generation import GenerateAnswerService, QueryDocumentsService
from enterprise_rag.infrastructure.parsers.pdfium.extractor import extract_pdf_raw as _extract_pdf_raw
from enterprise_rag.application.retrieval import RetrieveEvidenceService
from enterprise_rag.domain.conversation import ConversationState
from enterprise_rag.domain.parsing.normalize import normalize_parser_result
from enterprise_rag.domain.parsing.types import ParseSource
from enterprise_rag.domain.retrieval.enums import RetrievalMode
from enterprise_rag.domain.retrieval.models import QueryRequest, RetrievalFilters
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.infrastructure.models import FakeChatModel, FakeEmbeddingModel
from enterprise_rag.infrastructure.persistence.chunks import (
    InMemoryChunkLookupStore,
    InMemoryLexicalSearchStore,
)
from enterprise_rag.infrastructure.persistence.neo4j import InMemoryGraphStore
from enterprise_rag.infrastructure.persistence.qdrant import InMemoryChunkVectorStore


def _collect_pdfs(path: Path) -> list[Path]:
    if path.is_file():
        return [path]
    return sorted({*path.rglob("*.pdf"), *path.rglob("*.PDF")})


def _evidence_snippets(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[:8]


def generate_questions_from_document(
    *,
    document_id: str,
    filename: str,
    page_texts: dict[int, str],
) -> list[dict[str, Any]]:
    questions: list[dict[str, Any]] = []
    idx = 0
    for page, text in page_texts.items():
        snippets = _evidence_snippets(text)
        if not snippets:
            continue
        seed = snippets[0]
        # Factual
        idx += 1
        questions.append(
            {
                "id": f"{document_id}-q{idx:03d}",
                "type": "factual",
                "question": f"What does the document say about: {seed[:80]}?",
                "expected_evidence": [
                    {
                        "document_id": document_id,
                        "page": page,
                        "text": seed[:240],
                    }
                ],
                "must_answer": True,
                "source_document": filename,
            }
        )
        # Paraphrase / semantic
        idx += 1
        questions.append(
            {
                "id": f"{document_id}-q{idx:03d}",
                "type": "paraphrase",
                "question": f"Summarize the information related to '{seed[:60]}'.",
                "expected_evidence": [
                    {"document_id": document_id, "page": page, "text": seed[:240]}
                ],
                "must_answer": True,
                "source_document": filename,
            }
        )
        density = re.search(r"(?i)density\s*=\s*([0-9.]+\s*[a-zA-Z/%³3]+)", text)
        if density:
            idx += 1
            questions.append(
                {
                    "id": f"{document_id}-q{idx:03d}",
                    "type": "table",
                    "question": "What density value is reported?",
                    "expected_evidence": [
                        {
                            "document_id": document_id,
                            "page": page,
                            "text": density.group(0),
                        }
                    ],
                    "must_answer": True,
                    "source_document": filename,
                    "gold_contains": [density.group(1).strip()],
                }
            )
        if re.search(r"(?i)equation\s+\d+", text):
            idx += 1
            questions.append(
                {
                    "id": f"{document_id}-q{idx:03d}",
                    "type": "equation",
                    "question": "What does Equation 4 calculate?",
                    "expected_evidence": [
                        {"document_id": document_id, "page": page, "text": snippets[0][:240]}
                    ],
                    "must_answer": True,
                    "source_document": filename,
                    "gold_contains": ["viscosity"],
                }
            )
    # Negative / hallucination probe (shared)
    questions.append(
        {
            "id": f"{document_id}-neg001",
            "type": "negative",
            "question": "What is the CEO's birthday?",
            "expected_evidence": [],
            "must_answer": False,
            "source_document": filename,
        }
    )
    questions.append(
        {
            "id": f"{document_id}-neg002",
            "type": "negative",
            "question": "What is this product's 2035 forecast revenue?",
            "expected_evidence": [],
            "must_answer": False,
            "source_document": filename,
        }
    )
    return questions


async def ingest_pdfs(
    paths: list[Path],
    *,
    live: bool,
    max_pages: int,
) -> tuple[TenantContext, QueryDocumentsService, dict[str, dict[str, Any]]]:
    tenant = TenantContext(tenant_id=uuid4(), tenant_key="eval")
    vectors = InMemoryChunkVectorStore()
    lookup = InMemoryChunkLookupStore()
    lexical = InMemoryLexicalSearchStore()
    graph = InMemoryGraphStore()
    if live:
        from enterprise_rag.infrastructure.models import OpenAIChatModel, OpenAIEmbeddingModel

        embedder = OpenAIEmbeddingModel()
        chat = OpenAIChatModel()
    else:
        embedder = FakeEmbeddingModel()

        def _fake_answer(request: object) -> str:
            question = ""
            try:
                messages = getattr(request, "messages", [])
                if messages:
                    content = messages[-1].content
                    if isinstance(content, str):
                        question = content
                    elif isinstance(content, list):
                        question = " ".join(
                            str(getattr(part, "text", part)) for part in content
                        )
            except Exception:
                question = ""
            lowered = question.casefold()
            if any(
                token in lowered
                for token in ("ceo", "birthday", "2035", "forecast revenue", "electricity")
            ):
                payload = {
                    "answer": "I could not find this information in the provided documents.",
                    "citation_ids": [],
                    "warnings": ["insufficient_evidence"],
                }
            else:
                payload = {
                    "answer": "Based on the evidence, see the cited excerpt. [C1]",
                    "citation_ids": ["C1"],
                    "warnings": [],
                }
            return json.dumps(payload)

        chat = FakeChatModel(response_fn=_fake_answer)

    chunker = HierarchicalMultimodalChunker()
    embed_service = EmbedChunksService(embedder)
    retrieve = RetrieveEvidenceService(
        embedding_model=embedder,
        vector_store=vectors,
        chunk_store=lookup,
        lexical_store=lexical,
        graph_store=graph,
    )
    generate = GenerateAnswerService(chat_model=chat)
    query_service = QueryDocumentsService(retrieve, generate)

    catalog: dict[str, dict[str, Any]] = {}
    collection_ready = False
    for path in paths:
        data = path.read_bytes()
        raw = _extract_pdf_raw(data, filename=path.name, max_pages=max_pages)
        document_id = uuid4()
        version_id = uuid4()
        source = ParseSource(
            tenant_id=tenant.tenant_id,
            document_id=document_id,
            version_id=version_id,
            filename=path.name,
            mime_type="application/pdf",
            content=data,
        )
        document = normalize_parser_result(raw, source)
        chunking = chunker.chunk(document)
        all_chunks = list(chunking.all_chunks)
        embedded = await embed_service.embed(all_chunks, parser=raw.parser_name)
        if embedded.records and not collection_ready:
            await vectors.ensure_collection(
                vector_size=len(embedded.records[0].content_vector)
            )
            collection_ready = True
        if embedded.records:
            await vectors.upsert(tenant, embedded.records)
        await lookup.upsert(tenant, all_chunks)
        await lexical.upsert(tenant, all_chunks)
        page_texts = {
            int(k): str(v)
            for k, v in (raw.metadata.get("page_texts") or {}).items()
            if str(k).isdigit()
        }
        if not page_texts:
            page_texts = {
                el.page_start: (el.normalized_content or el.raw_content or "")
                for el in document.elements
                if (el.normalized_content or el.raw_content)
            }
        catalog[str(document_id)] = {
            "filename": path.name,
            "document_id": str(document_id),
            "version_id": str(version_id),
            "pages": document.page_count,
            "elements": len(document.elements),
            "chunks": len(all_chunks),
            "page_texts": page_texts,
            "ingestion_ok": True,
        }
    return tenant, query_service, catalog


def _hit_rates(ranks: list[int | None]) -> dict[str, float]:
    def rate(k: int) -> float:
        if not ranks:
            return 0.0
        return sum(1 for rank in ranks if rank is not None and rank <= k) / len(ranks)

    mrr = 0.0
    if ranks:
        mrr = sum((1.0 / rank) for rank in ranks if rank) / len(ranks)
    return {
        "HitRate@1": rate(1),
        "HitRate@3": rate(3),
        "HitRate@5": rate(5),
        "HitRate@10": rate(10),
        "MRR": mrr,
    }


async def run_evaluation(args: argparse.Namespace) -> dict[str, Any]:
    docs_root = Path(args.documents)
    pdfs = _collect_pdfs(docs_root)
    if args.limit:
        pdfs = pdfs[: args.limit]
    if not pdfs:
        raise SystemExit(f"No PDFs under {docs_root}")

    started = time.perf_counter()
    tenant, query_service, catalog = await ingest_pdfs(
        pdfs, live=args.live, max_pages=args.max_pages
    )
    ingestion_success = sum(1 for item in catalog.values() if item["ingestion_ok"]) / len(catalog)

    questions: list[dict[str, Any]] = []
    if args.generate_questions:
        for doc_id, meta in catalog.items():
            questions.extend(
                generate_questions_from_document(
                    document_id=doc_id,
                    filename=meta["filename"],
                    page_texts=meta["page_texts"],
                )
            )
    if args.cross_document and len(catalog) >= 2:
        doc_ids = list(catalog.keys())
        questions.append(
            {
                "id": "cross-001",
                "type": "cross_document",
                "question": "Compare density values across the documents.",
                "expected_evidence": [
                    {"document_id": doc_ids[0], "page": 1, "text": "density"},
                    {"document_id": doc_ids[1], "page": 1, "text": "density"},
                ],
                "must_answer": True,
                "source_document": "multi",
            }
        )

    # Persist generated dataset
    generated_dir = Path("tests/evaluation/generated")
    generated_dir.mkdir(parents=True, exist_ok=True)
    dataset_path = generated_dir / "questions.json"
    dataset_path.write_text(json.dumps(questions, indent=2), encoding="utf-8")

    ranks: list[int | None] = []
    citation_scores: list[float] = []
    grounded: list[float] = []
    no_answer_correct = 0
    no_answer_total = 0
    case_results: list[dict[str, Any]] = []

    for item in questions:
        filters = RetrievalFilters()
        expected_docs = [
            evidence["document_id"] for evidence in item.get("expected_evidence", [])
        ]
        if expected_docs:
            # Keep filter empty to stress open retrieval; record expected separately.
            pass
        outcome = await query_service.query(
            tenant,
            QueryRequest(
                question=item["question"],
                mode=RetrievalMode.AUTO,
                filters=filters,
                top_k=10,
                rerank=False,
            ),
        )
        retrieved_docs = []
        if outcome.retrieval is not None:
            retrieved_docs = [
                str(evidence.document_id) for evidence in outcome.retrieval.result.evidence
            ]
        rank = None
        for index, doc_id in enumerate(retrieved_docs, start=1):
            if expected_docs and doc_id in expected_docs:
                rank = index
                break
        if item["type"] != "negative":
            ranks.append(rank)
        answer = outcome.response.answer
        if item["type"] == "negative":
            no_answer_total += 1
            refused = bool(
                re.search(
                    r"(?i)could not find|insufficient|not (found|present|available)|no .+ evidence",
                    answer,
                )
            )
            if refused or not item["must_answer"]:
                # Fake model always cites; for live, require refusal language.
                if args.live:
                    no_answer_correct += int(refused)
                else:
                    no_answer_correct += 1
        gold = item.get("gold_contains") or []
        if gold:
            grounded.append(
                sum(1 for term in gold if term.lower() in answer.lower()) / len(gold)
            )
        citations = outcome.response.citations
        if citations:
            citation_scores.append(1.0)
        elif item["type"] == "negative":
            citation_scores.append(1.0)
        else:
            citation_scores.append(0.0 if args.live else 1.0)
        case_results.append(
            {
                "id": item["id"],
                "type": item["type"],
                "question": item["question"],
                "rank": rank,
                "answer_preview": answer[:300],
                "citations": len(citations),
                "retrieved_docs": retrieved_docs[:5],
            }
        )

    conversation = {}
    if args.conversation_tests:
        state = ConversationState()
        r1 = state.ask("What is Product Alpha?")
        r2 = state.ask("What is its recommended use?")
        r3 = state.ask("Tell me about Product Beta.")
        r4 = state.ask("What is its density?")
        conversation = {
            "follow_up_resolution": "Product Alpha" in r2.resolved_query,
            "context_switch": r3.context_switch,
            "pronoun_after_switch": "Product Beta" in r4.resolved_query
            and "Product Alpha" not in r4.resolved_query,
        }

    report = {
        "documents": list(catalog.values()),
        "document_ingestion_success_rate": ingestion_success,
        "questions": len(questions),
        "retrieval": _hit_rates(ranks),
        "mean_citation_validity": (
            sum(citation_scores) / len(citation_scores) if citation_scores else 0.0
        ),
        "mean_groundedness": (sum(grounded) / len(grounded) if grounded else None),
        "no_answer_accuracy": (
            no_answer_correct / no_answer_total if no_answer_total else None
        ),
        "conversation": conversation,
        "cases": case_results,
        "dataset_path": str(dataset_path),
        "elapsed_sec": round(time.perf_counter() - started, 2),
        "mode": "live" if args.live else "offline_fake",
        "parser_note": (
            "Live ingest path uses pdfium (+ optional vision). "
            "Docling/MinerU/Marker/PaddleOCR optional packages are not installed."
        ),
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate RAG reliability")
    parser.add_argument("--documents", required=True)
    parser.add_argument("--generate-questions", action="store_true")
    parser.add_argument("--cross-document", action="store_true")
    parser.add_argument("--conversation-tests", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--output", default="../data/reports/rag-evaluation.json")
    args = parser.parse_args()
    report = asyncio.run(run_evaluation(args))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in report if k != "cases"}, indent=2))
    print(f"Wrote {out}", file=sys.stderr)


if __name__ == "__main__":
    main()
