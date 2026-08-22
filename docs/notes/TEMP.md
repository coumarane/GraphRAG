You are a principal Python architect specializing in multimodal RAG, GraphRAG, document intelligence, LangChain, OpenAI, Neo4j, Qdrant, PostgreSQL, MinIO, MinerU and Docling.

Build a complete production-ready multimodal GraphRAG platform named:

```text
GraphRAG
```

The solution must follow the principal architecture and capabilities of the open-source RAG-Anything project while remaining an independent implementation.

Do not copy the RAG-Anything source code.

Use RAG-Anything as an architectural reference for:

* unified multimodal document understanding
* context-aware processing of images, tables and equations
* graph-centric knowledge construction
* multimodal entity and relationship extraction
* cross-modal retrieval
* local and global GraphRAG queries
* preserving relationships between document elements
* processing heterogeneous document types through a normalized representation

Do not use LightRAG as the primary persistence or retrieval engine.

Instead, implement the equivalent capabilities using:

* Neo4j for graph storage and traversal
* Qdrant for vector retrieval
* PostgreSQL for application and ingestion metadata
* MinIO for original documents and extracted assets
* Redis for queues, locks and caching
* OpenAI for text and vision models
* LangChain only where it provides clear value

## 1. Fundamental design decision

The platform must not be a conventional text-only RAG system.

It must understand a document as a connected multimodal structure containing:

* text
* headings
* sections
* paragraphs
* lists
* images
* charts
* diagrams
* tables
* formulas
* equations
* captions
* footnotes
* page layout
* bounding boxes
* reading order
* cross-references
* surrounding textual context

All modalities must be represented in one normalized document model and one connected knowledge graph.

Do not convert every document into plain Markdown and discard its original structure.

Markdown may be generated as a secondary representation, but the structured representation must remain the authoritative parsing output.

## 2. LangChain usage policy

Use current LangChain 1.x packages where appropriate.

LangChain must not become the domain architecture.

Use LangChain for:

* OpenAI chat-model adapters
* embedding adapters
* structured model outputs
* prompt templates
* document interfaces at integration boundaries
* retriever adapters
* optional reranking composition
* optional LangGraph workflows
* tracing integration where useful

Do not use LangChain for:

* parsing orchestration
* storage ownership
* tenant isolation
* ingestion-state management
* graph persistence
* entity identity management
* document-version management
* transaction management
* core chunking rules
* citation validation
* application domain models

The application must continue to work if LangChain model adapters are replaced by direct provider SDK implementations.

Create application-owned interfaces such as:

```python
class ChatModel(Protocol):
    async def generate(
        self,
        request: GenerationRequest,
    ) -> GenerationResponse: ...


class EmbeddingModel(Protocol):
    async def embed_documents(
        self,
        texts: Sequence[str],
    ) -> list[list[float]]: ...

    async def embed_query(
        self,
        text: str,
    ) -> list[float]: ...


class StructuredExtractor(Protocol):
    async def extract(
        self,
        request: ExtractionRequest,
        output_schema: type[BaseModel],
    ) -> BaseModel: ...
```

Implement these interfaces using LangChain OpenAI adapters initially.

## 3. Technology stack

Use:

* latest stable Python version supported by all required libraries
* FastAPI
* Pydantic v2
* pydantic-settings
* SQLAlchemy 2 async
* asyncpg
* Alembic
* PostgreSQL
* MinIO
* Qdrant
* Neo4j
* Redis
* LangChain 1.x
* LangGraph where durable workflow orchestration is justified
* official OpenAI Python SDK
* `langchain-openai`
* MinerU
* Docling
* Marker
* PaddleOCR
* pypdfium2
* Typer
* structlog
* OpenTelemetry
* Prometheus
* pytest
* Ruff
* mypy
* Docker
* Docker Compose
* `uv`

Do not force Python 3.14 if MinerU, PaddleOCR, PaddlePaddle, Marker, Docling or native dependencies do not support it.

Verify compatibility in a clean container.

Use Python 3.13 when it is the newest commonly supported version.

Document the decision in:

```text
docs/dependency-compatibility.md
```

## 4. Target architecture

Use clean architecture:

```text
src/
  enterprise_rag/
    api/
      routes/
      dependencies/
      schemas/

    cli/
      ingest.py
      query.py
      inspect.py
      reindex.py

    application/
      ingestion/
      parsing/
      multimodal/
      graph/
      indexing/
      retrieval/
      generation/
      evaluation/

    domain/
      documents/
      elements/
      chunks/
      graph/
      retrieval/
      models/
      citations/

    infrastructure/
      parsers/
        mineru/
        docling/
        marker/
        paddleocr/
        pdfium/

      models/
        langchain_openai/
        openai_direct/

      persistence/
        postgres/
        minio/
        qdrant/
        neo4j/
        redis/

      workers/
      observability/

    config/
    shared/

scripts/
  upload_document.py
  query_documents.py
```

Dependency direction:

```text
API / CLI / Worker
        ↓
Application services
        ↓
Domain interfaces and models
        ↑
Infrastructure adapters
```

Domain packages must not import:

* LangChain
* OpenAI
* Qdrant
* Neo4j
* MinIO
* Redis
* SQLAlchemy
* parser SDKs

## 5. RAG-Anything-style ingestion pipeline

Implement this logical flow:

```text
Document
  ↓
Inspection and classification
  ↓
Parser selection
  ↓
Structured multimodal parsing
  ↓
Normalized document model
  ↓
Context-aware multimodal enrichment
  ↓
Hierarchical semantic chunking
  ↓
Text and multimodal embeddings
  ↓
Entity, relationship and claim extraction
  ↓
Cross-modal knowledge graph construction
  ↓
Vector indexing
  ↓
Graph indexing
  ↓
Document and asset persistence
```

Each stage must be independently resumable and idempotent.

Persist stage status in PostgreSQL.

Stages:

```text
VALIDATE
HASH
STORE_ORIGINAL
INSPECT
SELECT_PARSER
PARSE
NORMALIZE
STORE_ELEMENTS
EXTRACT_ASSETS
ENRICH_IMAGES
ENRICH_TABLES
ENRICH_EQUATIONS
BUILD_CONTEXT
CHUNK
EMBED
INDEX_VECTOR
EXTRACT_ENTITIES
EXTRACT_RELATIONSHIPS
BUILD_GRAPH
INDEX_GRAPH
SUMMARIZE_COMMUNITIES
FINALIZE
```

## 6. Normalized multimodal document model

Create an application-owned normalized document model.

```python
class NormalizedDocument(BaseModel):
    document_id: UUID
    version_id: UUID
    title: str | None
    language: str | None
    metadata: dict[str, Any]
    pages: list[NormalizedPage]
    elements: list[DocumentElement]
    sections: list[DocumentSection]
    assets: list[DocumentAsset]
    references: list[ElementReference]
    parser_info: ParserInfo
```

Create typed document elements:

```python
DocumentElement = Annotated[
    TextElement
    | HeadingElement
    | ListElement
    | TableElement
    | ImageElement
    | ChartElement
    | DiagramElement
    | EquationElement
    | CaptionElement
    | FootnoteElement
    | CodeElement,
    Field(discriminator="element_type"),
]
```

Every element must preserve:

* stable element ID
* tenant ID
* document ID
* document-version ID
* page number
* page range
* bounding box
* reading-order index
* parent section
* previous element ID
* next element ID
* nearby element IDs
* caption relationship
* source asset key
* parser confidence
* OCR confidence
* source text
* normalized text
* metadata
* content hash

## 7. Parser system

Create a common parser interface:

```python
class MultimodalDocumentParser(Protocol):
    @property
    def name(self) -> str: ...

    async def inspect(
        self,
        source: ParseSource,
    ) -> ParserInspection: ...

    async def parse(
        self,
        source: ParseSource,
        options: ParseOptions,
    ) -> NormalizedDocument: ...
```

Implement:

* `MinerUParser`
* `DoclingParser`
* `MarkerParser`
* `PaddleOCRParser`
* `PdfiumInspector`
* `AutomaticParserRouter`

### Parser roles

#### MinerU

Use for:

* complex PDFs
* scientific documents
* formulas
* multi-column layouts
* dense academic papers
* advanced table extraction
* heterogeneous page structures

#### Docling

Use for:

* general enterprise documents
* DOCX
* PPTX
* HTML
* structured PDFs
* tables
* reading-order preservation
* layout-aware conversion

#### Marker

Use as:

* PDF-to-structured-Markdown fallback
* alternative parser for difficult PDFs
* parser comparison and quality fallback

#### PaddleOCR

Use for:

* scanned PDFs
* document images
* multilingual OCR
* low-text-density pages
* OCR fallback
* layout detection where supported

#### pypdfium2

Use for:

* PDF inspection
* text-density calculation
* page rendering
* thumbnail generation
* image generation for vision models
* page-level fallback extraction

Do not use pypdfium2 as the main semantic document parser.

## 8. Parser auto-selection

Inspect each file before selecting a parser.

Calculate:

* file type
* MIME type
* page count
* file size
* text density
* scanned-page ratio
* image coverage
* table probability
* formula probability
* number of columns
* layout complexity
* detected languages
* extractable text quality

Default routing:

```text
Structured office document       → Docling
General text-native PDF          → Docling
Scientific or formula-heavy PDF  → MinerU
Complex multi-column PDF         → MinerU
Scanned PDF                      → PaddleOCR
Image document                   → PaddleOCR
Parser failure                   → configured fallback chain
Page rendering                   → pypdfium2
PDF-to-Markdown fallback         → Marker
```

Allow explicit parser override.

Example configuration:

```yaml
parsing:
  default_profile: balanced

  profiles:
    fast:
      primary: docling
      fallbacks:
        - marker

    balanced:
      primary: docling
      fallbacks:
        - mineru
        - marker
        - paddleocr

    scientific:
      primary: mineru
      fallbacks:
        - docling
        - marker

    scanned:
      primary: paddleocr
      fallbacks:
        - mineru

    accurate:
      primary: mineru
      fallbacks:
        - docling
        - marker
        - paddleocr
```

## 9. Context-aware multimodal processing

Implement a central capability comparable to RAG-Anything's context-aware multimodal processing.

Images, tables, charts and equations must not be analyzed in isolation.

For every multimodal element, construct contextual input containing:

* document title
* current heading
* complete section path
* element caption
* preceding text elements
* following text elements
* referenced footnotes
* nearby table or image
* page number
* document type
* relevant domain metadata

Create:

```python
class ElementContext(BaseModel):
    document_title: str | None
    section_path: list[str]
    heading: str | None
    caption: str | None
    preceding_text: str | None
    following_text: str | None
    nearby_element_summaries: list[str]
    page_number: int
    document_metadata: dict[str, Any]
```

Context-window construction must be token bounded.

Configuration:

```yaml
multimodal_context:
  enabled: true
  preceding_elements: 3
  following_elements: 3
  max_context_tokens: 1800
  include_caption: true
  include_section_path: true
  include_nearby_tables: true
  include_nearby_figures: true
```

## 10. Multimodal processors

Create independent processors:

```python
class MultimodalElementProcessor(Protocol):
    async def process(
        self,
        element: DocumentElement,
        context: ElementContext,
    ) -> EnrichedElement: ...
```

Implement:

* `ImageProcessor`
* `ChartProcessor`
* `DiagramProcessor`
* `TableProcessor`
* `EquationProcessor`

### Image processing

For each relevant image:

* extract the original image when possible
* otherwise render the bounding-box region
* store it in MinIO
* describe it with the configured vision model
* extract visible text
* identify objects and labels
* connect it with its caption and section
* generate a searchable textual representation
* preserve the original image citation

### Chart processing

Extract:

* chart type
* title
* x-axis
* y-axis
* units
* legend
* series
* key values
* trends
* anomalies
* comparisons
* conclusions supported by the chart

Do not fabricate values that cannot be read reliably.

### Table processing

Preserve:

* headers
* rows
* merged cells
* nested headers
* footnotes
* caption
* page number
* original cell coordinates

Create:

* structured JSON representation
* Markdown representation
* compact semantic summary
* row-level child chunks when appropriate
* table-level parent chunk

### Equation processing

Preserve:

* original visual representation
* LaTeX when available
* surrounding explanation
* variables
* definitions
* semantic interpretation
* relationship to nearby text

Do not ask the language model to solve an equation unless required for understanding the document.

## 11. OpenAI models

Use provider-independent model roles.

Configuration:

```yaml
models:
  chat_provider: langchain_openai
  embedding_provider: langchain_openai

  text_model: ${OPENAI_TEXT_MODEL}
  vision_model: ${OPENAI_VISION_MODEL}
  extraction_model: ${OPENAI_EXTRACTION_MODEL}
  summarization_model: ${OPENAI_SUMMARIZATION_MODEL}
  query_model: ${OPENAI_QUERY_MODEL}
  answer_model: ${OPENAI_ANSWER_MODEL}
  embedding_model: ${OPENAI_EMBEDDING_MODEL}
```

Do not scatter concrete model names throughout the codebase.

Use LangChain's current OpenAI adapters for initial implementations:

```python
from langchain_openai import ChatOpenAI
from langchain_openai import OpenAIEmbeddings
```

Use structured output with Pydantic models.

Example:

```python
structured_model = chat_model.with_structured_output(EntityRelationshipExtraction)
```

Add direct OpenAI SDK adapters as an alternative implementation.

Support:

```yaml
models:
  implementation: langchain
```

or:

```yaml
models:
  implementation: openai_direct
```

Both implementations must satisfy the same application-owned interfaces.

## 12. Hierarchical and multimodal chunking

Create chunks based on semantic document structure.

Chunk types:

* text chunk
* section chunk
* image chunk
* chart chunk
* table chunk
* table-row chunk
* equation chunk
* multimodal composite chunk
* document summary chunk
* community summary chunk

Use parent-child chunking.

### Parent chunks

Represent:

* semantic sections
* complete tables
* figures with related context
* equation groups
* multimodal document regions

### Child chunks

Represent retrieval-sized units.

Default targets:

```yaml
chunking:
  strategy: multimodal_hierarchical
  parent_target_tokens: 2500
  child_target_tokens: 600
  overlap_tokens: 80

  preserve_tables: true
  preserve_equations: true
  preserve_figure_context: true
  generate_table_row_chunks: true
  generate_image_chunks: true
  generate_composite_chunks: true
```

Do not split:

* individual table rows across chunks
* images from their captions
* equations from immediate explanations
* headings from the first paragraph
* related chart legends from the chart description

## 13. Cross-modal knowledge graph

The graph must represent document structure and extracted knowledge.

### Structural nodes

* Tenant
* Document
* DocumentVersion
* Page
* Section
* Chunk
* TextElement
* Image
* Chart
* Diagram
* Table
* TableRow
* Equation
* Caption

### Semantic nodes

* Entity
* Person
* Organization
* Product
* Ingredient
* Chemical
* Regulation
* Location
* Topic
* Concept
* Claim
* Measurement
* Community

### Structural relationships

* HAS_VERSION
* HAS_PAGE
* HAS_SECTION
* HAS_ELEMENT
* HAS_CHUNK
* NEXT_ELEMENT
* PREVIOUS_ELEMENT
* CONTAINS
* HAS_CAPTION
* DESCRIBES
* APPEARS_ON
* DERIVED_FROM
* NEAR
* REFERENCES
* CONTINUES_ON
* HAS_ROW

### Semantic relationships

* MENTIONS
* RELATES_TO
* SUPPORTS
* CONTRADICTS
* EXPLAINS
* ILLUSTRATES
* MEASURES
* COMPARES
* PRODUCED_BY
* CONTAINS_INGREDIENT
* REGULATED_BY
* PART_OF
* SIMILAR_TO
* MEMBER_OF_COMMUNITY

A chart, table, image or equation must be able to participate directly in the knowledge graph.

Example:

```text
(Document)-[:HAS_SECTION]->(Section)
(Section)-[:HAS_ELEMENT]->(Chart)
(Chart)-[:HAS_CAPTION]->(Caption)
(Chart)-[:MEASURES]->(Chemical)
(Chart)-[:SUPPORTS]->(Claim)
(Claim)-[:DERIVED_FROM]->(Chunk)
```

## 14. Graph extraction

Perform extraction primarily at parent-chunk or multimodal-composite level.

For each semantic region, extract:

* entities
* typed entity mentions
* relationships
* factual claims
* topics
* measurements
* temporal references
* references to visual evidence

Use structured output:

```python
class ExtractedEntity(BaseModel):
    name: str
    normalized_name: str
    entity_type: EntityType
    description: str | None
    aliases: list[str]
    confidence: float
    source_element_ids: list[UUID]


class ExtractedRelationship(BaseModel):
    source_entity: str
    target_entity: str
    predicate: RelationshipPredicate
    description: str | None
    confidence: float
    source_element_ids: list[UUID]


class ExtractedClaim(BaseModel):
    statement: str
    subject: str | None
    predicate: str | None
    object: str | None
    confidence: float
    supporting_element_ids: list[UUID]
```

Treat model output as untrusted.

Validate all node labels, relationship predicates and properties before Neo4j insertion.

Use parameterized Cypher exclusively.

## 15. Entity resolution

Implement tenant-scoped entity resolution.

Use:

* normalized names
* aliases
* exact identifiers
* domain identifiers
* case normalization
* punctuation normalization
* acronym matching
* fuzzy similarity
* embedding similarity
* neighborhood compatibility
* entity-type compatibility
* source confidence

Never merge entities using name similarity alone.

Persist:

* canonical entity
* aliases
* merge confidence
* merge strategy
* source mentions
* manual-review requirement

## 16. Vector representations

Generate multiple vector representations when useful:

* child-text embedding
* parent-summary embedding
* image-description embedding
* table-summary embedding
* equation-description embedding
* entity-description embedding
* community-summary embedding

Use separate named vectors or separate collections when necessary.

Preferred initial Qdrant design:

```text
Collection: rag_chunks
Named vectors:
  content
  summary
```

Optional:

```text
Collection: rag_entities
Collection: rag_communities
```

Every Qdrant payload must include:

* tenant_id
* document_id
* document_version_id
* chunk_id
* parent_chunk_id
* element_type
* modality
* page_start
* page_end
* section_path
* parser
* content_hash
* security labels
* source object key

Tenant filtering is mandatory for every search.

## 17. Retrieval modes

Implement modes inspired by GraphRAG and RAG-Anything:

```text
naive
local
global
hybrid
multimodal
mix
auto
```

### Naive retrieval

Vector-only child-chunk search.

### Local retrieval

Resolve query entities and retrieve:

* matching entities
* graph neighbors
* related claims
* source chunks
* connected multimodal elements

### Global retrieval

Search:

* community summaries
* high-level topics
* global document summaries
* cross-document themes

### Hybrid retrieval

Combine:

* vector similarity
* graph proximity
* sparse text search
* entity overlap
* metadata filters
* source authority
* reranking

### Multimodal retrieval

Explicitly retrieve:

* images
* charts
* diagrams
* tables
* equations
* their related context
* source assets

### Mix retrieval

Combine global and local graph context with vector and multimodal retrieval.

### Auto retrieval

Classify the query and choose the appropriate strategy.

Examples:

```text
"What does the chart show about viscosity?"
→ multimodal or local

"Compare the safety limits across all suppliers."
→ global or mix

"What is the recommended storage temperature?"
→ naive or hybrid

"How is ingredient X related to regulation Y?"
→ local graph retrieval
```

## 18. Retrieval orchestration

Create an application-owned retrieval pipeline:

```text
Query
  ↓
Query normalization
  ↓
Intent classification
  ↓
Entity extraction
  ↓
Modality detection
  ↓
Retrieval strategy selection
  ↓
Parallel vector / graph / keyword retrieval
  ↓
Result normalization
  ↓
Fusion
  ↓
Reranking
  ↓
Parent and neighboring-element expansion
  ↓
Context assembly
  ↓
Citation validation
  ↓
Answer generation
```

LangGraph may be used to implement this workflow only when it provides:

* observable state transitions
* retries
* conditional branching
* resumability
* testability

Do not use an agent for deterministic retrieval steps.

## 19. Cross-document retrieval

Support relationships across different documents.

Examples:

* one supplier specification refers to an ingredient described elsewhere
* multiple documents describe the same chemical
* a regulation applies to products from multiple suppliers
* a chart in one document supports a claim made in another
* duplicate or conflicting measurements exist across documents

The graph must enable:

```text
Document A
  → Entity
  → Related Entity
  → Claim
  → Table or Chart
  → Document B
```

Preserve provenance at every traversal step.

## 20. Answer generation

Answers must be based only on retrieved evidence.

The answer model must receive:

* query
* retrieval mode
* text evidence
* graph evidence
* multimodal descriptions
* table data
* citation identifiers
* explicit grounding instructions

Return:

```json
{
  "answer": "...",
  "retrieval_mode": "mix",
  "citations": [
    {
      "citation_id": "C1",
      "document_id": "...",
      "document_name": "...",
      "document_version_id": "...",
      "page_start": 4,
      "page_end": 4,
      "section_path": ["Physical Properties", "Viscosity"],
      "element_id": "...",
      "chunk_id": "...",
      "modality": "chart",
      "source_object_key": "...",
      "evidence": "..."
    }
  ],
  "graph_paths": [
    {
      "nodes": ["Ingredient A", "Regulation B"],
      "relationships": ["REGULATED_BY"],
      "supporting_citations": ["C1", "C2"]
    }
  ]
}
```

The language model must never invent citation IDs.

Validate every citation after generation.

## 21. Storage ownership

### PostgreSQL

System of record for:

* tenants
* documents
* document versions
* ingestion runs
* processing stages
* parser runs
* pages
* document elements
* chunks
* assets
* extraction results
* model usage
* audit records
* retrieval traces
* answer traces

### MinIO

Store:

* original files
* rendered pages
* thumbnails
* extracted images
* chart crops
* equation crops
* normalized parser JSON
* generated Markdown
* generated HTML
* debug artifacts

### Qdrant

Store:

* chunk embeddings
* multimodal textual-representation embeddings
* entity embeddings
* community-summary embeddings

### Neo4j

Store:

* document structure graph
* semantic knowledge graph
* cross-document relationships
* source provenance
* communities

### Redis

Use for:

* task queue
* distributed locks
* parser concurrency limits
* rate-limit coordination
* short-lived caches
* ingestion progress events

## 22. Ingestion CLI

Create:

```text
scripts/upload_document.py
```

Also expose:

```text
rag-anything ingest
```

Use Typer.

Example:

```bash
uv run python scripts/upload_document.py ./documents/report.pdf \
  --tenant-id demo \
  --parser auto \
  --parser-profile balanced \
  --llm-implementation langchain \
  --text-model "$OPENAI_TEXT_MODEL" \
  --vision-model "$OPENAI_VISION_MODEL" \
  --embedding-model "$OPENAI_EMBEDDING_MODEL" \
  --ocr auto \
  --multimodal enabled \
  --graph enabled \
  --retrieval-profile mix
```

Support:

```text
SOURCE

--tenant-id TEXT
--document-id UUID
--title TEXT
--document-type TEXT

--parser auto|mineru|docling|marker|paddleocr
--parser-profile fast|balanced|accurate|scientific|scanned
--fallback-parsers TEXT
--failure-mode fail-fast|fallback|best-effort

--llm-implementation langchain|openai-direct
--llm-provider openai
--text-model TEXT
--vision-model TEXT
--extraction-model TEXT
--summarization-model TEXT
--embedding-model TEXT

--ocr auto|always|never
--ocr-language TEXT
--ocr-min-confidence FLOAT

--multimodal enabled|disabled
--process-images
--process-charts
--process-tables
--process-equations
--context-aware
--context-before-elements INTEGER
--context-after-elements INTEGER

--graph enabled|disabled
--entity-resolution enabled|disabled
--community-detection enabled|disabled

--chunking-strategy multimodal-hierarchical|semantic|page
--parent-chunk-tokens INTEGER
--child-chunk-tokens INTEGER
--chunk-overlap-tokens INTEGER

--metadata JSON
--metadata-file PATH
--security-label TEXT
--tags TEXT

--force
--resume
--dry-run
--wait
--output json|table
--log-level TEXT
--correlation-id UUID
```

## 23. CLI implementation requirements

The script must:

1. Validate the source.
2. Detect MIME type from content.
3. Calculate SHA-256.
4. check duplicate document versions.
5. Store the original in MinIO.
6. Create an ingestion run.
7. Inspect the document.
8. Select the parser.
9. Parse into the normalized document model.
10. Persist pages and elements.
11. Extract multimodal assets.
12. Build context for each multimodal element.
13. Enrich images, charts, tables and equations.
14. Build parent and child chunks.
15. Generate embeddings.
16. Index vectors in Qdrant.
17. Extract entities, relationships and claims.
18. Resolve entity identities.
19. Build the structural and semantic graph.
20. Index the graph in Neo4j.
21. Optionally detect graph communities.
22. Mark the run completed.
23. Print a structured summary.

Example output:

```json
{
  "status": "completed",
  "document_id": "019...",
  "version_id": "019...",
  "ingestion_run_id": "019...",
  "parser_requested": "auto",
  "parser_used": "mineru",
  "pages": 97,
  "elements": {
    "text": 821,
    "images": 24,
    "charts": 7,
    "tables": 31,
    "equations": 48
  },
  "chunks": {
    "parents": 64,
    "children": 286,
    "multimodal": 73
  },
  "graph": {
    "entities": 419,
    "claims": 192,
    "nodes": 1382,
    "relationships": 3271,
    "communities": 18
  },
  "vectors": 359,
  "duration_seconds": 128.4,
  "warnings": []
}
```

## 24. Query CLI

Create:

```text
scripts/query_documents.py
```

Expose:

```text
rag-anything query
```

Example:

```bash
rag-anything query \
  "Compare the particle-size charts across all product documents" \
  --tenant-id demo \
  --mode mix \
  --include-images \
  --include-graph-paths \
  --top-k 12 \
  --output json
```

Arguments:

```text
QUESTION

--tenant-id TEXT
--mode naive|local|global|hybrid|multimodal|mix|auto
--document-id UUID
--document-type TEXT
--tags TEXT
--include-images
--include-tables
--include-equations
--include-graph-paths
--top-k INTEGER
--graph-depth INTEGER
--rerank
--answer-model TEXT
--output json|markdown|table
```

## 25. APIs

Create:

```text
POST   /api/v1/documents/ingest
GET    /api/v1/ingestion-runs/{run_id}
GET    /api/v1/documents/{document_id}
GET    /api/v1/documents/{document_id}/elements
GET    /api/v1/documents/{document_id}/graph
DELETE /api/v1/documents/{document_id}

POST   /api/v1/query
POST   /api/v1/retrieval/search
POST   /api/v1/graph/search

GET    /api/v1/assets/{asset_id}
GET    /api/v1/health/live
GET    /api/v1/health/ready
GET    /metrics
```

Large-document ingestion must run asynchronously through workers.

## 26. Multitenancy and security

Enforce tenant isolation in every adapter.

### PostgreSQL

Use `tenant_id` on every tenant-owned record.

Prepare PostgreSQL row-level security.

### Qdrant

Reject searches without a tenant filter.

### Neo4j

Include tenant filtering in every query.

### MinIO

Use object keys:

```text
tenants/{tenant_id}/documents/{document_id}/versions/{version_id}/...
```

Implement:

* MIME validation
* file-size limits
* page-count limits
* filename sanitization
* path-traversal prevention
* SSRF protection
* parser timeouts
* LLM token limits
* secret redaction
* Cypher parameterization
* SQL parameterization
* prompt-injection isolation
* document-content trust boundaries

Document content must never be able to change:

* system prompts
* model configuration
* parser selection
* authorization
* credentials
* tool permissions

## 27. Deletion and reindexing

Document deletion must remove or deactivate:

* PostgreSQL records
* Qdrant points
* Neo4j document nodes
* orphaned semantic relationships
* MinIO assets
* cache entries

Do not delete a shared semantic entity if it is still referenced by another document.

Implement:

```text
rag-anything reindex
rag-anything rebuild-graph
rag-anything rebuild-vectors
rag-anything inspect-document
```

## 28. Evaluation

Create an evaluation framework for:

* text retrieval
* image retrieval
* table retrieval
* equation retrieval
* cross-modal retrieval
* graph-path accuracy
* entity resolution
* citation accuracy
* answer groundedness
* context precision
* context recall

Create sample evaluation questions such as:

```text
Which chart supports the claim about viscosity?

Compare the values in the two supplier tables.

Which regulation is connected to Ingredient X?

What does Equation 4 calculate?

Find the image that illustrates the packaging process.

Which documents provide conflicting values for density?
```

## 29. Observability

Log:

* tenant ID
* document ID
* version ID
* ingestion-run ID
* parser
* parser fallback
* page
* element type
* model
* token usage
* duration
* retry count
* graph node count
* graph relationship count
* vector count

Add metrics for:

* parsed pages
* extracted images
* extracted tables
* extracted equations
* OCR pages
* vision calls
* parser failures
* fallback count
* embedding latency
* graph-extraction latency
* ingestion latency
* retrieval latency
* retrieval mode usage
* citation-validation failures

## 30. Testing

Implement unit tests for:

* parser routing
* normalized-document conversion
* context-window construction
* multimodal element processing
* table preservation
* equation preservation
* chunk generation
* deterministic IDs
* graph validation
* entity resolution
* tenant-filter enforcement
* retrieval fusion
* citation validation
* CLI argument precedence

Implement integration tests using containers for:

* PostgreSQL
* MinIO
* Qdrant
* Neo4j
* Redis

Test:

* complete multimodal ingestion
* scanned PDF ingestion
* parser fallback
* duplicate ingestion
* resumable ingestion
* image and table retrieval
* cross-document graph retrieval
* tenant isolation
* reindexing
* document deletion

Mock OpenAI calls by default.

## 31. Project deliverables

Generate:

```text
pyproject.toml
uv.lock
docker-compose.yml
Dockerfile
Dockerfile.worker
Makefile
.env.example

README.md

docs/
  architecture.md
  dependency-compatibility.md
  multimodal-document-model.md
  parser-selection.md
  context-aware-processing.md
  graph-schema.md
  ingestion-pipeline.md
  retrieval-modes.md
  langchain-integration.md
  multitenancy.md
  security.md
  evaluation.md
  troubleshooting.md
```

Add Mermaid diagrams for:

* system architecture
* ingestion sequence
* multimodal processing
* graph construction
* query retrieval
* storage ownership
* parser fallback
* entity resolution

## 32. Implementation rules

Mandatory:

* full type annotations
* Pydantic v2
* async I/O
* bounded concurrency
* dependency injection
* explicit timeouts
* explicit transactions
* no bare exceptions
* no silent failures
* no global mutable clients
* deterministic IDs
* idempotent storage operations
* UTC-aware timestamps
* structured exceptions
* parameterized Cypher
* strict tenant filtering
* no deprecated LangChain APIs
* no placeholder-only implementations
* no unfinished `pass`
* no TODO-only production paths

Run:

```bash
uv run ruff format .
uv run ruff check .
uv run mypy src
uv run pytest
```

Fix all errors.

## 33. Implementation sequence

Proceed in this order:

1. Inspect the RAG-Anything public architecture and document the concepts being reproduced.
2. Produce the project tree.
3. Verify Python and dependency compatibility.
4. Create configuration.
5. Create domain models and interfaces.
6. Create the normalized multimodal document model.
7. Create parser adapters.
8. Create parser inspection and routing.
9. Create PostgreSQL persistence.
10. Create MinIO asset storage.
11. Create context-aware multimodal processors.
12. Create chunking.
13. Create LangChain and direct OpenAI model adapters.
14. Create Qdrant indexing.
15. Create Neo4j structural graph.
16. Create semantic extraction and entity resolution.
17. Create semantic graph construction.
18. Create ingestion orchestration.
19. Create the ingestion CLI.
20. Create retrieval modes.
21. Create the query CLI.
22. Create answer generation and citation validation.
23. Create FastAPI endpoints.
24. Create workers.
25. Create Docker Compose.
26. Create tests.
27. Create documentation.
28. Run formatting, linting, typing and tests.
29. Fix all failures.

## 34. First Cursor response

Before generating files, present:

1. Architecture comparison with RAG-Anything.
2. Features reproduced.
3. Features intentionally redesigned.
4. LangChain usage boundaries.
5. Storage ownership matrix.
6. Normalized multimodal document model.
7. Parser routing matrix.
8. Graph schema.
9. Retrieval-mode design.
10. Complete project tree.
11. Implementation sequence.

After presenting the design, immediately start generating the project files.

Do not wait for additional confirmation.

Do not merely create an architectural prototype.

Generate a complete runnable implementation.
