# RAG Reliability Report

Generated as part of `CURSOR_QUERY.md` validation (2026-08-08).

## Status summary

| Phase | Status | Notes |
| --- | --- | --- |
| 1 Corpus discovery | Done | 29 `sample_data` PDFs + 7 eval corpus + `examples/sample.pdf` |
| 2 Parsing evaluation | Partial | pdfium forensics complete; Docling/MinerU/Marker/PaddleOCR **not installed** |
| 3 Normalization | Done | Boilerplate reclassification + regression tests |
| 4 Ingestion | Done (subset) | Real MinIO/Postgres/Qdrant/Neo4j ingest of eval PDFs |
| 5 Chunking | Done | `inspect_chunks.py` + line-split fix for brochure PDFs |
| 6 Retrieval | Done (eval corpus) | Live HitRate@5 = **1.0** on generated questions |
| 7 Cross-document | Done (subset) | Conflicting densities answered with dual-doc citations |
| 8 Conversation | Done | `QueryContextResolver` + regression suite |
| 9 Hallucination | Done (eval) | Live no-answer accuracy = **1.0** on negative probes |
| 10 Multimodal | Partial | Vision path exists in local pipeline; full SEM/chart matrix still open |
| 11 Failure injection | Done (unit) | Parser failure fails loudly (no silent empty success) |
| 12 Optimization | Partial | Avoided OCR-every-page; vision still page-selective |
| 13 Full regression | Partial | Focused unit + live eval corpus; not all 29 sample PDFs |
| 14 Report | This file | |

## Corpus

Inventory: `reports/corpus-inventory.json` (29 sample_data files).

Classification counts (approximate, multi-label):

| Label | Count |
| --- | --- |
| TEXT_NATIVE | 24 |
| FORMULA_HEAVY / SCIENTIFIC | 16 |
| PRESENTATION_STYLE | 16 |
| TABLE_HEAVY / TECHNICAL_DATASHEET | 10 |
| MIXED | 3 |
| SCANNED / IMAGE_HEAVY | 2 |

Fully scanned (pdfium text density ≈ 0):

- `BNB CHEM-Product Catalog.pdf` (15 pages) → router recommends **paddleocr**
- `SUNSPHERE-CATALOG.pdf` (12 pages) → router recommends **paddleocr**

Largest / complex presentations:

- `Presentation-SAKAMOTO RANGE-V4.pdf` (115 pages)
- `NSG ALL PRODUCT-PRESENTATION ICE 2023.pdf` (99 pages)
- `NOF LINEUP CATALOG INCI NAME.pdf` (80 pages)

Synthetic evaluation corpus (`evaluation/corpus/`): charts, complex_tables, scanned, scientific_equations, shared_entities_a/b, text_heavy.

## Parser results

Tooling: `scripts/analyze_pdf.py` (+ `--compare-parsers`).

Comparison artifact: `reports/parser-comparison-eval-corpus.json`.

| Parser | Availability in this environment |
| --- | --- |
| pypdfium2 | Installed / used by live ingest |
| Docling | **NEEDS_REVIEW** — package not installed; not in `pyproject` extras |
| MinerU | **NEEDS_REVIEW** — package not installed |
| Marker | **NEEDS_REVIEW** — package not installed |
| PaddleOCR | **NEEDS_REVIEW** — package not installed |

Routing recommendations from inspection (sample_data):

- docling: 18
- mineru: 9
- paddleocr: 2

**Important defect:** the production `ProcessRegisteredDocumentService` path still parses with **pdfium (+ selective OpenAI vision)**, not the `ParseDocumentService` registry. Adapter code exists, but optional heavy parsers are not wired into live ingest and are not installable via current extras.

## Problems identified

### P1 — Live ingest bypasses parser registry

- **severity:** high
- **document:** all PDFs
- **root cause:** `local_pipeline._extract_pdf_raw` is the live parse path
- **affected layer:** ingestion
- **fix status:** documented; not fully rewired (blocked by missing Docling/MinerU/Marker/PaddleOCR deps)
- **workaround:** pdfium + vision enrichment for sparse/visual pages

### P2 — Single-newline brochure pages collapsed to one element

- **severity:** high
- **document:** e.g. Acerola TDS / many presentations
- **root cause:** `\n\n` split kept a single giant block when PDFs only use `\r\n`
- **affected layer:** local PDF extraction
- **fix:** normalize newlines and fall back to line splits
- **regression test:** `tests/unit/test_pdf_line_splitting.py`
- **result after fix:** Acerola produces ≥5 elements

### P3 — Repeated headers/footers could pollute chunks

- **severity:** medium
- **root cause:** no boilerplate detector before chunking
- **fix:** `domain/parsing/boilerplate.py` + normalize hook promoting chrome to `PAGE_HEADER`/`PAGE_FOOTER` (already skipped by chunker)
- **regression test:** `tests/unit/test_boilerplate.py`

### P4 — Conversation follow-ups were frontend string-prepend only

- **severity:** high
- **root cause:** no backend `QueryContextResolver`
- **fix:** structured resolver with pronoun rewrite, ambiguity clarification, context-switch detection; wired into `QueryDocumentsService` + API `conversation_history`
- **regression test:** `tests/unit/test_conversation_context.py`
- **result:** follow-up / switch / ambiguity cases pass

### P5 — Product-specific retrieval expansions (overfit risk)

- **severity:** medium
- **document / query:** SILKYFLAKE / NATUTECT / METASHINE-oriented expansions in `intent.py`
- **root cause:** prior chat fixes hard-coded sample brochure phrases
- **status:** flagged against CURSOR_QUERY §36; not fully generalized in this pass
- **recommended follow-up:** replace with evidence-driven synonym expansion

### P6 — CLI ingest uses noop orchestration

- **severity:** medium
- **root cause:** `enterprise-rag ingest --wait` runs noop stage handlers (“local noop orchestration”)
- **affected layer:** CLI
- **workaround:** API/`ProcessRegisteredDocumentService` via runtime container
- **status:** open

## Retrieval metrics

### Offline (fake embeddings) — `reports/rag-evaluation.json`

| Metric | Value |
| --- | --- |
| Ingestion success | 1.0 |
| HitRate@5 | 0.65 |
| HitRate@10 | 1.0 |
| MRR | 0.42 |
| Citation validity | 1.0 |
| No-answer accuracy | 1.0 |

### Live OpenAI — `reports/rag-evaluation-live.json`

| Metric | Value | Target |
| --- | --- | --- |
| Ingestion success | 1.0 | ≥0.99 |
| HitRate@1 | 0.29 | — |
| HitRate@3 | 0.94 | — |
| HitRate@5 | **1.00** | ≥0.95 |
| HitRate@10 | 1.00 | — |
| MRR | 0.61 | — |
| Citation validity | **1.00** | ≥0.99 |
| Groundedness | **1.00** | — |
| No-answer accuracy | **1.00** | ≥0.95 |

Generated dataset: `tests/evaluation/generated/questions.json`  
Challenge set: `tests/evaluation/generated/challenge.json`

## Conversation metrics

From automated resolver tests + eval harness:

| Metric | Result |
| --- | --- |
| Follow-up resolution | pass |
| Pronoun resolution | pass |
| Context-switch detection | pass |
| Ambiguity handling (compare A/B → “its”) | asks clarification |
| Pronoun after switch (Alpha → Beta) | resolves to Beta |

## Hallucination results

Negative probes (`CEO birthday`, `2035 forecast revenue`, eczema clinical trial templates):

- Live eval no-answer accuracy: **1.0**
- Citation validator clears unused IDs on insufficient-evidence answers (uncommitted citation validation improvement)

## Cross-document results

Real storage ingest of `shared_entities_a.pdf` + `shared_entities_b.pdf` (Postgres + MinIO + Qdrant + Neo4j):

Question: *Do Supplier A and Supplier B report different densities for Ingredient X?*

Answer (abridged):

- Supplier A: 0.970 g/mL
- Supplier B: 0.940 g/mL
- Explicit conflict noted
- Citations from **both** documents

Graph build during ingest: ~30 nodes / ~60 relationships per short datasheet.

## Remaining limitations

1. **Optional parsers not installed** — cannot complete quantitative Docling/MinerU/Marker/PaddleOCR challenge matrices; metrics marked `NEEDS_REVIEW`.
2. **Live path is pdfium-centric** — registry routing is not yet the production ingest path.
3. **Not all 29 sample_data PDFs** were fully ingested/queried end-to-end in this pass (cost/latency); focus was evaluation corpus + representative real-store dual-doc case.
4. **Fully scanned catalogs** (`BNB CHEM`, `SUNSPHERE`) need PaddleOCR or vision-heavy OCR before text RAG is meaningful.
5. **CLI `--wait` noop** does not run `ProcessRegisteredDocumentService`.
6. **Intent synonym expansions** still contain brochure-specific hard-coding (overfit risk).
7. **Multimodal SEM/chart numeric fidelity** needs a dedicated live matrix beyond the current vision enrichment heuristics.
8. SQLAlchemy async connection finalizer emits noisy logging errors on short scripts (observability issue, not answer quality).

## Artifacts & tooling added

- `scripts/analyze_pdf.py`
- `scripts/inspect_chunks.py`
- `scripts/evaluate_rag.py`
- `scripts/generate_rag_challenge.py`
- `src/enterprise_rag/domain/parsing/boilerplate.py`
- `src/enterprise_rag/domain/conversation/context_resolver.py`
- `tests/unit/test_boilerplate.py`
- `tests/unit/test_conversation_context.py`
- `tests/unit/test_failure_injection.py`
- `tests/unit/test_pdf_line_splitting.py`
- `reports/corpus-inventory.json`
- `reports/parser-comparison-eval-corpus.json`
- `reports/rag-evaluation.json`
- `reports/rag-evaluation-live.json`

## Acceptance vs targets

| Target | Actual (live eval corpus) |
| --- | --- |
| Document ingestion success ≥ 99% | 100% (eval corpus / dual-doc real store) |
| Retrieval HitRate@5 ≥ 95% | **100%** |
| Citation validity ≥ 99% | **100%** |
| No-answer correctness ≥ 95% | **100%** |
| Follow-up context accuracy ≥ 95% | resolver suite pass |
| Context-switch accuracy ≥ 98% | resolver suite pass |
| Cross-document evidence recall ≥ 90% | dual-doc conflict query succeeded with both citations |

**Verdict:** Reliability validation is substantially advanced for pdfium-based ingest + retrieval + conversation + hallucination on the evaluation corpus and a real dual-document storage path. Full heterogeneous parser challenge and complete 29-PDF sample_data matrix remain blocked on optional parser dependencies and broader live ingest coverage.
