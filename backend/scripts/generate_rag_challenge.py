#!/usr/bin/env python3
"""Generate adversarial RAG challenge questions from parsed document evidence.

Usage:
  uv run python scripts/generate_rag_challenge.py evaluation/corpus --output tests/evaluation/generated/challenge.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from graph_rag.infrastructure.parsers.pdfium.extractor import extract_pdf_raw as _extract_pdf_raw
from graph_rag.domain.parsing.normalize import normalize_parser_result
from graph_rag.domain.parsing.types import ParseSource


def _questions_for_text(document_id: str, filename: str, page: int, text: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    seed = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if not seed:
        return items
    base = {
        "source_document": filename,
        "source_page": page,
        "expected_evidence": [{"document_id": document_id, "page": page, "text": seed[:240]}],
    }
    items.append(
        {
            "id": f"{document_id}-fact",
            "type": "FACTUAL",
            "question": f"According to the document, what is stated near: {seed[:70]}?",
            "difficulty": "easy",
            "must_answer": True,
            **base,
        }
    )
    items.append(
        {
            "id": f"{document_id}-para",
            "type": "PARAPHRASE",
            "question": f"In other words, what does the source claim about '{seed[:50]}'?",
            "difficulty": "medium",
            "must_answer": True,
            **base,
        }
    )
    if re.search(r"(?i)density|viscosity|concentration|particle size", text):
        items.append(
            {
                "id": f"{document_id}-table",
                "type": "TABLE",
                "question": "What numeric property values (density/viscosity/concentration) are reported?",
                "difficulty": "medium",
                "must_answer": True,
                **base,
            }
        )
    if re.search(r"(?i)equation|eta|tau|gamma", text):
        items.append(
            {
                "id": f"{document_id}-eq",
                "type": "EQUATION",
                "question": "What does the equation calculate, using the document's definition?",
                "difficulty": "hard",
                "must_answer": True,
                **base,
            }
        )
    items.append(
        {
            "id": f"{document_id}-neg",
            "type": "NEGATIVE",
            "question": "What clinical trial proved this ingredient cures eczema?",
            "difficulty": "easy",
            "must_answer": False,
            "expected_evidence": [],
            "source_document": filename,
            "source_page": page,
        }
    )
    items.append(
        {
            "id": f"{document_id}-partial",
            "type": "PARTIAL",
            "question": "What is the density at 25°C?",
            "difficulty": "hard",
            "must_answer": False,
            "expected_evidence": base["expected_evidence"] if "density" in text.casefold() else [],
            "source_document": filename,
            "source_page": page,
            "notes": "Must not invent temperature condition if absent.",
        }
    )
    return items


async def build(path: Path) -> list[dict[str, Any]]:
    pdfs = [path] if path.is_file() else sorted({*path.rglob("*.pdf"), *path.rglob("*.PDF")})
    out: list[dict[str, Any]] = []
    for pdf in pdfs:
        data = pdf.read_bytes()
        raw = _extract_pdf_raw(data, filename=pdf.name, max_pages=30)
        document_id = str(uuid4())
        source = ParseSource(
            tenant_id=uuid4(),
            document_id=uuid4(),
            version_id=uuid4(),
            filename=pdf.name,
            mime_type="application/pdf",
            content=data,
        )
        document = normalize_parser_result(raw, source)
        page_texts: dict[int, str] = {}
        for element in document.elements:
            text = (element.normalized_content or element.raw_content or "").strip()
            if not text:
                continue
            page_texts[element.page_start] = (
                page_texts.get(element.page_start, "") + "\n" + text
            ).strip()
        for page, text in page_texts.items():
            out.extend(_questions_for_text(document_id, pdf.name, page, text))
    # Cross-document challenges when multiple PDFs exist.
    if len(pdfs) >= 2:
        out.append(
            {
                "id": "cross-compare",
                "type": "CROSS_DOCUMENT",
                "question": "Do any documents report conflicting values for density?",
                "difficulty": "hard",
                "must_answer": True,
                "expected_evidence": [],
                "source_document": "multi",
            }
        )
        out.append(
            {
                "id": "cross-agg",
                "type": "AGGREGATION",
                "question": "List all products or ingredients mentioned across the documents.",
                "difficulty": "medium",
                "must_answer": True,
                "expected_evidence": [],
                "source_document": "multi",
            }
        )
    out.extend(
        [
            {
                "id": "follow-up-template",
                "type": "FOLLOW_UP",
                "question": "What is its recommended concentration?",
                "difficulty": "medium",
                "must_answer": True,
                "notes": "Requires prior entity in conversation.",
            },
            {
                "id": "context-switch-template",
                "type": "CONTEXT_SWITCH",
                "question": "Forget that. Which products contain titanium dioxide?",
                "difficulty": "medium",
                "must_answer": True,
            },
            {
                "id": "ambiguous-template",
                "type": "AMBIGUOUS",
                "question": "What is its density?",
                "difficulty": "hard",
                "must_answer": False,
                "notes": "After comparing two products, should ask clarification.",
            },
        ]
    )
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--output", default="tests/evaluation/generated/challenge.json")
    args = parser.parse_args()
    items = asyncio.run(build(args.path))
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(items, indent=2), encoding="utf-8")
    print(f"Wrote {len(items)} challenge questions to {out}")


if __name__ == "__main__":
    main()
