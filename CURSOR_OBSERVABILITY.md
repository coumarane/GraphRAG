Implement a complete Document Parsing Observability, Audit, and Comparison framework for the RAG/GraphRAG ingestion pipeline.

The objective is to make every document ingestion fully traceable and measurable.

For every uploaded document, I want to know:

* how many pages the document contains;
* what elements exist on each page;
* how many elements of each type were detected;
* which parser detected each element;
* which processing tool handled each element;
* which LLM/vision model was used;
* which fallback parser/model was used;
* what succeeded;
* what failed;
* what was skipped;
* what was detected but not processed;
* why something was not processed;
* extraction confidence/quality where available;
* processing duration;
* token usage where applicable;
* parser/model configuration and versions;
* warnings and errors;
* final normalized output produced by the ingestion pipeline.

This must be persisted in PostgreSQL and designed so that two ingestion runs of the same document can later be compared.

Do not implement this as simple application logs. Create a proper structured parsing audit model.

# 1. Document-level report

For every ingestion run, persist a document-level report containing at least:

* document_id
* ingestion_run_id
* original_filename
* file_hash
* MIME type
* file size
* total pages
* ingestion start time
* ingestion end time
* total duration
* ingestion status
* primary parser selected
* parser version
* fallback parsers attempted
* OCR strategy
* vision strategy
* text LLM used
* vision LLM used
* embedding model
* configuration/profile used
* application version / git commit if available
* overall extraction quality score if available
* total detected elements
* total successfully processed elements
* total failed elements
* total skipped elements
* total warnings
* total errors

The ingestion run must be immutable once completed so it can be compared historically.

# 2. Page-level report

Create one structured report for every page.

For each page store:

* page_number
* page width/height if available
* whether native text exists
* whether OCR was required
* OCR engine used
* page parser used
* fallback parser used if any
* page processing status
* page processing duration
* number of detected elements
* number of successfully processed elements
* number of failed elements
* number of skipped elements
* warnings
* errors
* page-level extraction confidence/quality

Also store counts by element type, for example:

* paragraph
* heading
* title
* list
* table
* image
* chart
* diagram
* equation
* caption
* footer
* header
* footnote
* form
* code block
* scanned region
* unknown

Do not hard-code only these types. Use the application's normalized element taxonomy and allow extension.

# 3. Element-level audit

Every detected page element must have its own audit record.

Store at least:

* element_id
* ingestion_run_id
* document_id
* page_number
* normalized_element_type
* original parser element type
* bounding box
* reading order
* parent element if applicable
* section/heading hierarchy
* parser that detected it
* parser version
* processing tool
* processing stage
* model used
* model version
* prompt/template version if applicable
* input reference
* output reference
* confidence score
* quality score
* processing duration
* token usage if an LLM was used
* retry count
* fallback chain
* final processing status
* warning/error code
* warning/error message
* skip reason
* failure reason

Processing status should use a controlled state model such as:

* detected
* queued
* processing
* processed
* partially_processed
* skipped
* failed
* fallback_processed
* unsupported

# 4. Processing provenance

For every element, I need to understand exactly which component processed it.

Example:

Page 12
Table 3
Detected by: Docling
Parsed by: Docling
Validation: internal table validator
Fallback: none
Vision enrichment: GPT vision model
Normalization: application table normalizer
Status: processed

Another example:

Page 15
Image 2
Detected by: MinerU
OCR: PaddleOCR
Vision enrichment: GPT-4.x vision model
Status: fallback_processed
Reason: MinerU returned no usable caption

Another example:

Page 21
Equation 1
Detected by: Docling
Processing status: skipped
Reason: equation processing disabled by current ingestion profile

The system should make this provenance queryable directly from the database.

# 5. Pipeline stage tracking

Do not record only the final parser.

Track every important processing stage independently.

Typical stages may include:

* file validation
* PDF metadata extraction
* page rendering
* layout detection
* native text extraction
* OCR
* table detection
* table structure extraction
* image extraction
* chart detection
* diagram detection
* equation extraction
* caption association
* heading detection
* reading-order reconstruction
* vision enrichment
* LLM enrichment
* normalization
* chunking
* entity extraction
* relationship extraction
* embeddings
* Qdrant indexing
* Neo4j indexing
* PostgreSQL metadata persistence

For each stage record:

* stage name
* started_at
* completed_at
* duration
* status
* tool
* tool version
* model if applicable
* model version
* configuration
* input count
* output count
* warning count
* error count

# 6. Parser/model routing decisions

The report must explain why a particular parser/model was selected.

For example:

* Docling selected as primary parser because document is digitally generated PDF.
* PaddleOCR invoked because page 7 contains no native text.
* Vision model invoked because chart structure could not be represented reliably through OCR.
* MinerU fallback invoked because Docling table extraction failed.
* Vision processing skipped because image area was below configured threshold.

Persist machine-readable routing reason codes, not only free text.

Examples:

PRIMARY_PARSER_SELECTED
NO_NATIVE_TEXT
OCR_REQUIRED
TABLE_EXTRACTION_FAILED
LOW_CONFIDENCE
VISION_REQUIRED
UNSUPPORTED_ELEMENT
FEATURE_DISABLED
FALLBACK_TRIGGERED
QUALITY_THRESHOLD_FAILED
MODEL_ERROR
TIMEOUT
TOKEN_LIMIT
RATE_LIMIT

# 7. Missing/unprocessed content detection

This is particularly important.

The ingestion pipeline should explicitly identify detected content that was not successfully represented in the final normalized document.

For every page compare:

detected elements
vs.
processed elements
vs.
normalized elements

If something disappears between stages, record it.

Example:

Page 9:
Detected:

* 4 paragraphs
* 1 table
* 2 images

Normalized:

* 4 paragraphs
* 1 image

Report:

Missing:

* table: failed during table structure extraction
* image: intentionally ignored because classified as decorative

The report must distinguish:

* intentionally skipped
* unsupported
* parsing failure
* filtering
* deduplication
* low-confidence rejection
* processing disabled
* unknown loss

There must never be silent element loss.

# 8. Quality metrics

Where possible calculate quality metrics for:

Document:

* extraction completeness
* OCR coverage
* element processing coverage
* normalization completeness

Page:

* detected vs processed ratio
* processed vs normalized ratio
* OCR confidence
* layout confidence

Element:

* parser confidence
* OCR confidence
* vision confidence
* validation status

Do not fabricate confidence values when a parser/model does not provide one.

Represent unavailable scores as null and record the source of every score.

# 9. Database model

Design normalized PostgreSQL tables rather than one huge JSON blob.

A possible model may contain:

document_ingestion_runs
document_parse_reports
page_parse_reports
element_parse_reports
processing_stage_runs
element_processing_events
parser_invocations
model_invocations
ingestion_errors
ingestion_warnings
ingestion_metrics

JSONB may be used for parser-specific metadata/configuration, but important queryable fields must be proper typed columns.

Use foreign keys and indexes suitable for:

* retrieving one full ingestion report;
* comparing two runs;
* finding failed pages;
* finding failed element types;
* comparing parsers;
* comparing models;
* comparing versions;
* analyzing processing time;
* analyzing token usage;
* identifying frequently failing element types.

# 10. Ingestion run versioning

Every reprocessing of a document must create a new ingestion_run_id.

Never overwrite previous parsing reports.

Identify documents using a stable document_id and file hash.

Example:

document_id = DOC-123

Run 1:
Docling 2.x
PaddleOCR 3.x
Vision Model A

Run 2:
Docling 3.x
PaddleOCR 3.x
Vision Model B

Both runs must remain available for comparison.

# 11. Comparison capability

Implement a backend service/API allowing two ingestion runs to be compared.

The comparison should show at least:

Document-level differences:

* total elements
* successful elements
* failed elements
* skipped elements
* processing time
* quality/completeness scores

Page-level differences:

* element counts
* extracted types
* missing elements
* parser/model changes
* processing errors

Element-level differences:

* newly extracted elements
* missing elements
* changed element classification
* changed text
* changed table extraction
* changed image/chart interpretation
* changed confidence
* changed parser/model

Support comparison by:

* document_id
* ingestion_run_id
* parser version
* model version
* ingestion profile

# 12. Report API

Expose APIs such as:

GET /documents/{document_id}/ingestion-runs

GET /documents/{document_id}/ingestion-runs/{run_id}/report

GET /documents/{document_id}/ingestion-runs/{run_id}/pages

GET /documents/{document_id}/ingestion-runs/{run_id}/pages/{page_number}

GET /documents/{document_id}/ingestion-runs/{run_id}/elements

GET /documents/{document_id}/ingestion-runs/{run_id}/errors

GET /documents/{document_id}/ingestion-runs/{run_id}/warnings

GET /documents/{document_id}/ingestion-runs/{run_id}/pipeline

GET /documents/{document_id}/compare?run_a=...&run_b=...

Adapt endpoint names to the current project's API conventions.

# 13. Example report

A page report should conceptually be able to represent:

Document: supplier-product-specification.pdf
Pages: 42

Page 7

Detected elements:

* Heading: 2
* Paragraph: 6
* Table: 2
* Image: 1
* Chart: 1

Processing:

Heading 1

* detector: Docling
* parser: Docling
* status: processed

Table 1

* detector: Docling
* parser: Docling
* validation: failed
* fallback: MinerU
* final status: fallback_processed

Image 1

* extractor: Docling
* OCR: PaddleOCR
* vision enrichment: configured vision model
* final status: processed

Chart 1

* detector: MinerU
* vision enrichment: configured vision model
* final status: processed

Table 2

* detector: Docling
* status: failed
* reason: TABLE_STRUCTURE_EXTRACTION_FAILED

Page summary:

* detected: 12
* processed: 11
* failed: 1
* skipped: 0
* completeness: 91.67%

# 14. Logs vs audit data

Keep normal technical logs for debugging, but do not depend on logs for reporting.

Structured audit information must be persisted separately.

Application logs answer:

"What happened technically?"

Parsing audit reports answer:

"What content existed, what processed it, what was produced, what was lost, and why?"

# 15. Performance

Observability must not significantly slow ingestion.

Implement event collection efficiently.

Avoid committing one database transaction per low-level operation.

Batch persistence where appropriate.

Large raw parser outputs, rendered pages, extracted images, and intermediate assets should remain in MinIO/object storage.

PostgreSQL should store metadata and references to those assets rather than unnecessarily duplicating large binary/raw outputs.

# 16. Multi-tenancy and security

Preserve tenant isolation throughout the audit schema.

Every document/run/page/element report must be scoped correctly by tenant/project/workspace according to the existing security model.

A user must never gain visibility into parser reports for documents they cannot access.

# 17. Testing

Add tests covering:

* normal multi-page PDF;
* scanned PDF requiring OCR;
* mixed native-text/scanned PDF;
* images;
* tables;
* charts;
* diagrams;
* equations;
* parser fallback;
* OCR fallback;
* vision enrichment;
* unsupported element;
* intentionally skipped element;
* parser failure;
* model failure;
* timeout;
* partially processed page;
* content lost between detection and normalization;
* repeated ingestion of same document;
* comparison between two ingestion runs;
* model version change;
* parser version change.

# 18. Implementation approach

Before modifying code, inspect the current ingestion architecture.

Identify:

* parser adapters;
* normalized document model;
* Docling integration;
* MinerU integration;
* Marker integration if present;
* PaddleOCR integration;
* pypdfium2 rendering;
* vision processing;
* LLM enrichment;
* MinIO storage;
* PostgreSQL models;
* Qdrant indexing;
* Neo4j indexing;
* ingestion orchestration.

Do not duplicate existing metadata or telemetry mechanisms unnecessarily.

Create a common instrumentation abstraction that every parser and processing component can use.

For example, conceptually:

ParsingAuditCollector
-> document_started()
-> page_started()
-> element_detected()
-> processing_started()
-> model_invoked()
-> fallback_triggered()
-> element_processed()
-> element_skipped()
-> element_failed()
-> page_completed()
-> document_completed()

The exact implementation should follow the existing architecture and coding conventions.

# 19. Critical invariant

There must be NO SILENT CONTENT LOSS.

For every content element detected during ingestion, the system must eventually be able to answer:

1. What was it?
2. Where was it?
3. Who detected it?
4. Which parser processed it?
5. Which model processed/enriched it?
6. What output was produced?
7. Was a fallback used?
8. Did it succeed?
9. If it failed or was skipped, why?
10. Did it reach the final normalized document?
11. Did it reach chunking/vector indexing/graph indexing?

# 20. Final deliverables

After implementation provide:

* architecture changes;
* database schema;
* migrations;
* models/entities;
* audit collector/service;
* parser integration changes;
* LLM/vision invocation instrumentation;
* APIs;
* comparison service;
* tests;
* example JSON report for one ingestion;
* example comparison between two ingestion runs;
* remaining limitations.

Prefer a generic, parser-independent design.

Do not build this specifically around Docling, MinerU, PaddleOCR, or one LLM.

Those are processing providers.

The application's audit model must remain stable even when parsers and models are replaced in the future.