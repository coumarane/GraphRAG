# 01 — Product Requirements

## Problem

Traditional RAG pipelines flatten documents into text and lose relationships among layout, figures, tables, equations and nearby explanations. The platform must treat a document as a connected multimodal evidence structure.

## Supported inputs

Initial production scope:

- PDF, including text-native, scanned, mixed and complex scientific PDFs;
- DOCX;
- PPTX;
- XLSX;
- images: PNG, JPEG, TIFF and WebP;
- HTML;
- Markdown;
- plain text.

Architecture must permit new formats without changing application orchestration.

## Functional requirements

### Ingestion

- Upload local files and download safe remote URLs.
- Detect MIME type from bytes.
- Calculate SHA-256 before processing.
- Detect duplicate document versions.
- Route automatically to a parser or honor an explicit parser.
- Persist every pipeline stage and permit resume.
- Preserve source page, element, region and object-store provenance.

### Multimodal understanding

- Process text, images, charts, diagrams, tables and equations.
- Include bounded surrounding context when interpreting non-text elements.
- Preserve structured table data and equation source representations.
- Generate searchable descriptions without replacing original structures.

### GraphRAG

- Create a structural graph of documents and elements.
- Create a semantic graph of entities, claims, measurements and relations.
- Resolve entities across documents within the same tenant.
- Support graph communities and summaries as an optional enrichment.

### Retrieval

Support:

- naive vector retrieval;
- local graph retrieval;
- global/community retrieval;
- hybrid retrieval;
- multimodal retrieval;
- mixed local/global/vector retrieval;
- automatic strategy selection.

### Answers

- Return a grounded answer.
- Return structured citations.
- Cite document, version, page, element, chunk and source asset.
- Optionally return supporting graph paths.
- Never cite unavailable evidence.

## Non-functional requirements

- strict multi-tenancy;
- idempotent ingestion;
- horizontal worker scaling;
- bounded resource consumption;
- observable execution;
- auditable model usage;
- replaceable model and parser providers;
- deterministic identifiers where source identity is stable;
- graceful partial failure with explicit status.

## Definition of done

A release is acceptable when:

1. A mixed PDF containing text, images and tables can be ingested end to end.
2. Original and extracted assets are visible in MinIO.
3. Metadata and state exist in PostgreSQL.
4. Child chunks can be found in Qdrant with mandatory tenant filtering.
5. Structural and semantic nodes can be inspected in Neo4j.
6. A query can retrieve a chart or table through its textual description and graph context.
7. The answer contains valid page- and element-level citations.
8. Resume does not duplicate vectors, nodes or assets.
9. Cross-tenant retrieval tests fail closed.
