# RAG Reliability Report

Generated as part of `CURSOR_QUERY.md` validation (2026-08-08).

## Status summary

| Phase | Status | Notes |
| --- | --- | --- |
| 1 Corpus discovery | Done | 29 `sample_data` PDFs + 7 eval corpus + `examples/sample.pdf` |
| 2 Parsing evaluation | Improved | Live path uses parser registry; Docling installed via `parsers-docling`; pdfium final fallback |
| 3 Normalization | Done | Boilerplate reclassification + regression tests |
| 4 Ingestion | Done | CLI `--wait` runs `ProcessRegisteredDocumentService` against real backends |
| 5 Chunking | Done | `inspect_chunks.py` + line-split fix for brochure PDFs |
| 6 Retrieval | Done (eval + NSG/EMULGEN) | Live HitRate@5 = **1.0**; Qdrant-backed chunk/lexical hydrate |
| 7 Cross-document | Done (subset + NSG/EMULGEN) | Dual-doc conflict + surfactant vs pigment compare with both citations |
| 8 Conversation | Done | Field-label ambiguity fix; follow-up CAS resolve on EMULGEN |
| 9 Hallucination | Done (eval + NSG/EMULGEN) | Flash-point / molecular-weight probes refused |
| 10 Multimodal | Partial (improved) | NSG chart/image/table/equation evidence used in live answers |
| 11 Failure injection | Done (unit) | Parser failure fails loudly (no silent empty success) |
| 12 Optimization | Partial | Avoided OCR-every-page; vision still page-selective |
| 13 Full regression | Partial | Focused unit + live eval corpus; not all 29 sample PDFs |
| 14 Report | This file | |

### Follow-up completed 2026-08-08 (NSG + EMULGEN live challenge)

Validated two frontend-uploaded documents already in the demo tenant:

| Document | ID | Chunks (Qdrant-backed lookup) | Modalities |
| --- | --- | --- | --- |
| NSG ALL PRODUCT-PRESENTATION ICE 2023 | `019fdde7-25d9-7469-bff2-1bb70eaee2ab` | 260 / 99 pages | text, table, chart, image, equation, composite |
| EMULGEN 2020G SPEC | `019fddd2-96f6-7d9c-b6c6-25e21f006bba` | 2 / 1 page | text (spec table flattened into text) |

**Challenge matrix:** 24 queries covering factual, table specs, chart/L*, negatives, cross-doc, and conversation follow-ups → **24/24 pass** after fixes (artifact: `reports/nsg-emulgen-challenge.json`).

**Defects found and fixed (general, not product-overfit):**

1. Chunk/lexical stores were in-memory only → empty after API restart despite Qdrant vectors. Added `QdrantChunkLookupStore` + `QdrantHydratingLexicalStore` when `VECTOR_STORE_BACKEND=qdrant`.
2. Pronoun follow-ups treated datasheet labels (e.g. INCI) as competing entities → false clarification. Field-label filtering in `QueryContextResolver`.
3. Multi-doc filters drowned small docs under large presentations. Added `ensure_document_coverage` + per-missing-doc supplemental naive retrieval.
4. Increased vector `text_preview` length to 8000 for future re-embeds (existing points still 2000).

**Sample grounded answers:** EMULGEN INCI/CAS/pH/hydroxyl/water/mp/packing all correct with citations; NSG particle-size, METASHINE Aurora L*/transparency, gold plasmon HC/ZC, MAR'VINA/SILKYFLAKE; negatives refused; cross-doc compare cites both docs.
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

- **severity:** high → **fixed**
- **document:** all PDFs
- **root cause:** `local_pipeline` used pdfium-only extraction
- **fix:** route through `ParseDocumentService` with pdfium as final fallback; Docling available via `uv sync --extra parsers-docling`
- **verification:** CLI ingest of `text_heavy.pdf` reported `parser_used: docling`

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

- **severity:** medium → **mitigated**
- **root cause:** synonym expansions injected brochure SKUs (SILKYFLAKE / FTD008 / NATUTECT)
- **fix:** expansions reduced to generic scientific synonyms (NIR, MIU/MMD, friction, surface-treated)
- **regression test:** `test_texture_evaluation_expands_to_generic_surface_terms`

### P6 — CLI ingest uses noop orchestration

- **severity:** medium → **fixed**
- **root cause:** `enterprise-rag ingest --wait` ran noop stage handlers
- **fix:** `--wait` now executes `ProcessRegisteredDocumentService` and commits; CLI prefers runtime backends from env
- **verification:** ingest response `duration_note: ProcessRegisteredDocumentService`

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

1. **MinerU / Marker** still need manual install (not packaged in extras yet); PaddleOCR is available via `parsers-ocr`.
2. Docling adapter currently flattens mostly to markdown text blocks (page attribution can be coarse).
3. **Not all 29 sample_data PDFs** were fully ingested/queried end-to-end in this pass (cost/latency).
4. **Fully scanned catalogs** (`BNB CHEM`, `SUNSPHERE`) still need PaddleOCR/vision-heavy OCR for good text RAG (`uv sync --extra parsers-ocr`).
5. **Multimodal SEM/chart numeric fidelity** needs a dedicated live matrix beyond current vision enrichment heuristics.
6. Some chart-boost heuristics in retrieval still mention sample brochure cues; synonym expansions are generalized.
7. SQLAlchemy async connection finalizer emits noisy logging errors on short scripts (observability issue, not answer quality).
8. EMULGEN document metadata still lacks `page_count` (content is 1 page; reprocess would refresh metadata + 8000-char previews).
9. Existing Qdrant payloads still store 2000-char `text_preview` until documents are re-embedded.
10. Some NSG chart slides contain conflicting callouts (MTH100RS vs MT1080RS “highest transparency”); answers may hedge or prefer one wording.
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
- `reports/nsg-emulgen-challenge.json`
- `src/enterprise_rag/infrastructure/persistence/chunks/qdrant_lookup.py`
- `src/enterprise_rag/infrastructure/persistence/chunks/lexical_qdrant.py`
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
