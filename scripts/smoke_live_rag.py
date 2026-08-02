#!/usr/bin/env python3
"""Live smoke test: parse PDF -> chunk -> embed (OpenAI) -> retrieve -> answer."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from enterprise_rag.application.chunking import EmbedChunksService, HierarchicalMultimodalChunker
from enterprise_rag.application.generation import GenerateAnswerService, QueryDocumentsService
from enterprise_rag.application.retrieval import RetrieveEvidenceService
from enterprise_rag.domain.chunks.vectors import ChunkingResult
from enterprise_rag.domain.elements.enums import ElementType
from enterprise_rag.domain.ids import new_id
from enterprise_rag.domain.parsing.normalize import normalize_parser_result
from enterprise_rag.domain.parsing.types import ParseSource, RawElement, RawPage, RawParserResult
from enterprise_rag.domain.retrieval.enums import RetrievalMode
from enterprise_rag.domain.retrieval.models import QueryRequest
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.infrastructure.models import OpenAIChatModel, OpenAIEmbeddingModel
from enterprise_rag.infrastructure.persistence.chunks import (
    InMemoryChunkLookupStore,
    InMemoryLexicalSearchStore,
)
from enterprise_rag.infrastructure.persistence.neo4j import InMemoryGraphStore
from enterprise_rag.infrastructure.persistence.qdrant import InMemoryChunkVectorStore
from enterprise_rag.shared.logging import configure_logging, get_logger

logger = get_logger(__name__)


def _extract_pdf_raw(path: Path, *, max_pages: int | None) -> RawParserResult:
    import pypdfium2 as pdfium

    data = path.read_bytes()
    document = pdfium.PdfDocument(data)
    try:
        page_count = len(document)
        limit = min(page_count, max_pages) if max_pages else page_count
        elements: list[RawElement] = []
        pages: list[RawPage] = []
        order = 0
        for index in range(limit):
            page = document[index]
            text_page = page.get_textpage()
            try:
                text = (text_page.get_text_bounded() or "").strip()
            finally:
                text_page.close()
            page.close()
            pages.append(RawPage(page_number=index + 1, text_density=float(len(text))))
            if not text:
                continue
            # Split large pages into paragraphs for better chunking.
            blocks = [block.strip() for block in text.split("\n") if block.strip()]
            if not blocks:
                blocks = [text]
            for block in blocks:
                elements.append(
                    RawElement(
                        element_type=ElementType.TEXT,
                        page_start=index + 1,
                        page_end=index + 1,
                        reading_order=order,
                        raw_content=block,
                        normalized_content=block,
                    )
                )
                order += 1
    finally:
        document.close()

    if not elements:
        raise RuntimeError("No extractable text found in PDF (may be scanned-only)")

    return RawParserResult(
        parser_name="pdfium_text",
        parser_version="smoke-1",
        title=path.name,
        page_count=len(pages),
        pages=pages,
        elements=elements,
        warnings=[] if (max_pages is None or page_count <= (max_pages or page_count)) else [
            f"truncated_to_{limit}_of_{page_count}_pages"
        ],
    )


async def run_smoke(
    *,
    pdf_path: Path,
    pdf_bytes: bytes,
    question: str,
    max_pages: int | None,
    max_chunks: int | None,
    embedding_model: str,
    answer_model: str,
) -> dict[str, object]:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is required")

    tenant_id = new_id()
    document_id = new_id()
    version_id = new_id()
    tenant = TenantContext(tenant_id=tenant_id, tenant_key="demo")

    raw = await asyncio.to_thread(_extract_pdf_raw, pdf_path, max_pages=max_pages)
    source = ParseSource(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        filename=pdf_path.name,
        mime_type="application/pdf",
        content=pdf_bytes,
    )
    document = normalize_parser_result(raw, source)
    chunks = HierarchicalMultimodalChunker().chunk(document)
    all_chunks = list(chunks.all_chunks)
    if max_chunks is not None:
        all_chunks = all_chunks[:max_chunks]
        chunks = ChunkingResult(
            parents=[c for c in all_chunks if c.parent_chunk_id is None],
            children=[c for c in all_chunks if c.parent_chunk_id is not None],
        )

    embedder = OpenAIEmbeddingModel(model_name=embedding_model, api_key=api_key)
    chat = OpenAIChatModel(model_name=answer_model, api_key=api_key)
    vectors = InMemoryChunkVectorStore()
    chunk_store = InMemoryChunkLookupStore()
    lexical = InMemoryLexicalSearchStore()
    graph = InMemoryGraphStore()

    embedded = await EmbedChunksService(embedder).embed(all_chunks, parser="pdfium_text")
    if not embedded.records:
        raise RuntimeError("No embeddings produced")
    await vectors.ensure_collection(vector_size=len(embedded.records[0].content_vector))
    await vectors.upsert(tenant, embedded.records)
    await chunk_store.upsert(tenant, all_chunks)
    await lexical.upsert(tenant, all_chunks)

    query = QueryDocumentsService(
        RetrieveEvidenceService(
            embedding_model=embedder,
            vector_store=vectors,
            chunk_store=chunk_store,
            graph_store=graph,
            lexical_store=lexical,
        ),
        GenerateAnswerService(chat),
    )
    outcome = await query.query(
        tenant,
        QueryRequest(
            question=question,
            mode=RetrievalMode.NAIVE,
            top_k=8,
            rerank=False,
        ),
    )
    response = outcome.response
    return {
        "document": pdf_path.name,
        "pages_parsed": document.page_count,
        "elements": len(document.elements),
        "chunks_indexed": len(embedded.records),
        "warnings_parse": list(raw.warnings),
        "question": question,
        "answer": response.answer,
        "retrieval_mode": response.retrieval_mode.value,
        "citations": [c.model_dump(mode="json") for c in response.citations],
        "evidence_count": len(outcome.retrieval.result.evidence),
        "response_warnings": list(response.warnings),
        "models": {"embedding": embedding_model, "answer": answer_model},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf", type=Path)
    parser.add_argument(
        "--question",
        default="What are biodegradable particles and what are their key benefits?",
    )
    parser.add_argument("--max-pages", type=int, default=12)
    parser.add_argument("--max-chunks", type=int, default=40)
    parser.add_argument("--embedding-model", default="text-embedding-3-small")
    parser.add_argument("--answer-model", default="gpt-4.1-mini")
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    configure_logging(level="INFO", stream=sys.stderr)
    if not args.pdf.is_file():
        raise SystemExit(f"PDF not found: {args.pdf}")

    # Load .env if present without printing secrets.
    env_path = Path(".env")
    if env_path.is_file() and not os.environ.get("OPENAI_API_KEY"):
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("OPENAI_API_KEY=") and not line.strip().endswith("="):
                os.environ["OPENAI_API_KEY"] = line.split("=", 1)[1].strip().strip('"').strip("'")

    result = asyncio.run(
        run_smoke(
            pdf_path=args.pdf.resolve(),
            pdf_bytes=args.pdf.read_bytes(),
            question=args.question,
            max_pages=args.max_pages,
            max_chunks=args.max_chunks,
            embedding_model=args.embedding_model,
            answer_model=args.answer_model,
        )
    )
    text = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
