#!/usr/bin/env python3
"""Inspect hierarchical chunks for a PDF without full storage indexing.

Usage:
  uv run python scripts/inspect_chunks.py path/to/document.pdf
  uv run python scripts/inspect_chunks.py path/to/document.pdf --json-out reports/chunks.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

from enterprise_rag.application.chunking import HierarchicalMultimodalChunker
from enterprise_rag.infrastructure.parsers.pdfium.extractor import extract_pdf_raw as _extract_pdf_raw
from enterprise_rag.domain.parsing.normalize import normalize_parser_result
from enterprise_rag.domain.parsing.types import ParseSource


async def inspect_path(path: Path, *, max_pages: int = 50) -> dict[str, Any]:
    data = path.read_bytes()
    raw = _extract_pdf_raw(data, filename=path.name, max_pages=max_pages)
    source = ParseSource(
        tenant_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        filename=path.name,
        mime_type="application/pdf",
        content=data,
    )
    document = normalize_parser_result(raw, source)
    result = HierarchicalMultimodalChunker().chunk(document)
    all_chunks = list(result.all_chunks)
    chunks = []
    for chunk in all_chunks:
        chunks.append(
            {
                "chunk_id": str(chunk.chunk_id),
                "parent_chunk_id": str(chunk.parent_chunk_id) if chunk.parent_chunk_id else None,
                "document": path.name,
                "page_start": chunk.page_start,
                "page_end": chunk.page_end,
                "section": list(chunk.section_path),
                "modality": chunk.modality.value,
                "chunk_type": chunk.chunk_type.value,
                "token_count": chunk.token_count,
                "source_elements": [
                    str(item) for item in (chunk.metadata.get("source_element_ids") or [])
                ],
                "content": chunk.text[:1200],
            }
        )
    header_footer_pollution = sum(
        1
        for chunk in all_chunks
        if "confidential" in chunk.text.casefold()
        or "all rights reserved" in chunk.text.casefold()
    )
    return {
        "document": path.name,
        "pages": document.page_count,
        "elements": len(document.elements),
        "boilerplate": document.metadata.get("boilerplate"),
        "chunk_count": len(all_chunks),
        "header_footer_pollution_chunks": header_footer_pollution,
        "chunks": chunks,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect chunks for a PDF")
    parser.add_argument("path", type=Path)
    parser.add_argument("--max-pages", type=int, default=50)
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()
    if not args.path.exists():
        print(f"Not found: {args.path}", file=sys.stderr)
        raise SystemExit(1)
    report = asyncio.run(inspect_path(args.path, max_pages=args.max_pages))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    print(text)
    if args.json_out:
        out = Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
