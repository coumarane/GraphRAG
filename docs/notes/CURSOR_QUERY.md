You are now acting as a Principal AI/RAG Engineer, QA Architect, and adversarial evaluator.

The GraphRAG / multimodal RAG solution has already been implemented according to:

* `CURSOR.md`
* `specs/`
* `contracts/`

Your task is NOT to redesign the solution from scratch.

Your task is to aggressively challenge the existing implementation using the real PDF documents available in the repository, identify weaknesses, fix them, and demonstrate through automated tests that the solution is reliable.

Treat this as an enterprise RAG acceptance and robustness test.

# PRIMARY OBJECTIVE

Validate that the system can ingest, understand, retrieve, cross-reference and accurately answer questions from arbitrary heterogeneous PDFs containing combinations of:

* native text
* scanned text
* OCR text
* headings
* subheadings
* headers
* footers
* page numbers
* logos
* watermarks
* images
* photographs
* scientific images
* SEM images
* microscopy images
* diagrams
* flow diagrams
* charts
* graphs
* tables
* multi-page tables
* formulas
* equations
* chemical formulas
* units
* symbols
* superscripts
* subscripts
* footnotes
* references
* captions
* multi-column layouts
* mixed layouts
* rotated pages
* low-resolution scans
* embedded text inside images
* repeated document boilerplate

Use ALL relevant parsers already supported by the system:

* Docling
* MinerU
* Marker
* PaddleOCR
* pypdfium2

Do not assume one parser is always the best.

Determine where each parser performs well or poorly and ensure the parser routing/fallback logic produces the best normalized document representation.

The final objective is:

> A user should be able to upload one or many heterogeneous PDFs and ask natural questions about them, including follow-up questions and cross-document questions, while receiving grounded, correctly cited answers without hallucination.

---

# 1. DISCOVER THE TEST CORPUS

Locate all PDFs available in the project's sample/test document directories.

Inspect likely locations such as:

```text
backend/sample_data/
sample_data/
samples/
tests/fixtures/documents/
data/samples/
```

Do not assume the directory name. Find the actual files.

Create an inventory containing:

```text
filename
file size
page count
PDF type
detected languages
text-native/scanned/mixed
image count
table count
formula/equation indicators
layout complexity
parser candidates
```

Classify every document approximately as:

```text
TEXT_NATIVE
SCANNED
MIXED
SCIENTIFIC
TECHNICAL_DATASHEET
SDS
REGULATORY
MARKETING
PRODUCT_SPECIFICATION
PRESENTATION_STYLE
TABLE_HEAVY
IMAGE_HEAVY
FORMULA_HEAVY
UNKNOWN
```

Do not rely only on filename classification.

Inspect the actual contents.

---

# 2. CREATE A PDF FORENSICS TOOL

Create:

```text
scripts/analyze_pdf.py
```

Usage:

```bash
uv run python scripts/analyze_pdf.py path/to/document.pdf
```

And:

```bash
uv run python scripts/analyze_pdf.py backend/sample_data \
    --recursive \
    --compare-parsers
```

For every PDF report:

```json
{
  "pages": 42,
  "text_native_pages": 32,
  "scanned_pages": 10,
  "images": 18,
  "tables": 9,
  "equations": 14,
  "headers_detected": true,
  "footers_detected": true,
  "multi_column_pages": 7,
  "languages": ["en"],
  "parser_recommendation": "mineru",
  "parser_confidence": 0.89
}
```

This utility must help evaluate parser-routing decisions.

---

# 3. PARSER CHALLENGE

Run representative documents through:

```text
Docling
MinerU
Marker
PaddleOCR
```

Use pypdfium2 for:

* PDF inspection
* page rendering
* page images
* text-density analysis
* visual comparison

Do NOT blindly run expensive OCR on every page.

For each parser compare:

* missing text
* duplicated text
* corrupted text
* incorrect reading order
* heading preservation
* list preservation
* table preservation
* table cell accuracy
* equation preservation
* image extraction
* image-caption association
* page attribution
* header/footer handling
* OCR accuracy
* Unicode accuracy
* superscripts/subscripts
* document structure preservation
* processing latency
* memory consumption
* parser failures

Build a parser-quality report.

Example:

```text
Document: technical_datasheet.pdf

                         Docling   MinerU   Marker   PaddleOCR
Text accuracy              0.97      0.96     0.92       0.91
Reading order              0.96      0.98     0.87       0.85
Tables                     0.91      0.96     0.82       0.72
Equations                  0.72      0.97     0.90       0.65
Images                     0.94      0.95     0.71       0.88
Scanned pages              0.60      0.82     0.55       0.97
```

Exact metrics may require heuristic/manual-ground-truth comparison.

Do not fabricate metric values.

If automated ground truth cannot establish a metric reliably, mark it:

```text
NEEDS_REVIEW
```

---

# 4. VERIFY NORMALIZATION

Regardless of parser, verify that the resulting normalized representation preserves:

```text
Document
 ├─ Page
 │   ├─ Header
 │   ├─ Heading
 │   ├─ Paragraph
 │   ├─ Table
 │   ├─ Image
 │   ├─ Chart
 │   ├─ Equation
 │   ├─ Caption
 │   └─ Footer
```

Ensure parser-specific structures are converted correctly into the application's common:

```text
NormalizedDocument
```

No downstream retrieval component should need to know whether an element originated from:

```text
Docling
MinerU
Marker
PaddleOCR
```

Add tests for this requirement.

---

# 5. HEADER / FOOTER / LOGO HANDLING

Specifically challenge:

* repeating headers
* repeating footers
* company logos
* copyright messages
* confidentiality banners
* document IDs
* page numbers
* revision information

They must remain available as metadata when useful, but they must NOT pollute every semantic chunk.

Example:

A repeated company footer occurring on 80 pages must not appear as meaningful content in 80 retrieval chunks.

Implement boilerplate detection based on:

* positional consistency
* normalized text similarity
* page-frequency ratio

Preserve useful document metadata separately.

---

# 6. IMAGE AND SCIENTIFIC IMAGE TESTING

Find PDFs containing:

* normal photographs
* product photographs
* diagrams
* SEM images
* microscope images
* scientific figures
* charts
* technical drawings

For every relevant image verify:

1. image extraction
2. page association
3. bounding box
4. caption association
5. surrounding context
6. MinIO storage
7. vision-model description
8. searchable representation
9. Neo4j connection
10. Qdrant representation
11. source citation

For SEM / microscopy images, the system must distinguish between:

* what is explicitly visually observable
* what the caption states
* what surrounding text claims

Do NOT allow the vision model to invent scientific measurements or interpretations.

Example:

If the scale bar is unreadable:

```text
The system must not invent particle size.
```

If surrounding text says:

```text
SEM images show particles around 20 μm
```

the system may report the statement, but attribution must remain to the textual/caption evidence.

---

# 7. TABLE CHALLENGE

Locate complex tables.

Test:

* simple tables
* multi-column tables
* merged cells
* repeated headers
* continued tables across pages
* units in headers
* footnotes
* scientific notation
* missing cells
* comparison tables

Generate questions requiring:

```text
single-cell lookup
row comparison
column comparison
maximum/minimum
multi-row reasoning
cross-table comparison
cross-document table comparison
```

Example:

```text
Which ingredient has the highest viscosity?

Compare viscosity at 20°C between Product A and Product B.

Which supplier reports the lowest density?

Which documents disagree about the recommended concentration?
```

Do not flatten tables into text in a way that destroys row/column semantics.

---

# 8. FORMULA AND EQUATION CHALLENGE

Find documents containing equations and formulas.

Verify:

* equation detection
* LaTeX/structured representation when available
* superscripts
* subscripts
* symbols
* Greek characters
* units
* nearby explanation
* page attribution

Generate questions such as:

```text
What does Equation 3 calculate?

What variable represents viscosity?

Which equation contains temperature?

Explain the formula using the document's definition.

Where is this equation used later in the document?
```

The answer must distinguish:

```text
document explanation
```

from:

```text
LLM interpretation
```

Prefer document-grounded explanation.

---

# 9. OCR CHALLENGE

Find scanned or partially scanned pages.

Test:

```text
OCR auto
OCR always
OCR never
```

Validate that `auto` activates OCR only where required.

Challenge:

* low-resolution scans
* skewed text
* rotated pages
* small fonts
* image labels
* scientific symbols
* tables in scans

Record OCR confidence.

Low-confidence OCR text must not be treated as equally trustworthy as high-confidence native text.

Retrieval scoring should be capable of taking provenance/confidence into account.

---

# 10. CHUNKING VALIDATION

Inspect generated parent and child chunks.

Detect:

* sentence truncation
* heading detached from content
* table broken incorrectly
* caption detached from image
* equation detached from explanation
* excessive overlap
* duplicated content
* missing content
* chunks dominated by footer/header
* semantically unrelated information combined together

Create:

```text
scripts/inspect_chunks.py
```

Support:

```bash
rag-anything inspect-document DOCUMENT_ID --show-chunks
```

For each chunk show:

```text
chunk_id
parent_chunk_id
document
page
section
modality
token_count
source elements
content
```

Add automated chunk-integrity tests.

---

# 11. VECTOR RETRIEVAL CHALLENGE

For every test document generate questions whose expected evidence is known.

Measure whether the correct chunks appear in:

```text
top 1
top 3
top 5
top 10
```

Record:

```text
HitRate@1
HitRate@3
HitRate@5
HitRate@10
MRR
```

Test:

* exact wording
* paraphrasing
* abbreviations
* synonyms
* spelling variation
* singular/plural
* scientific terminology
* unit-aware queries

Example:

Document contains:

```text
Sodium Hyaluronate
```

Test queries:

```text
Does the product contain sodium hyaluronate?

Does it contain hyaluronic acid salt?

What HA derivative is present?
```

Do not optimize for exact keyword matching only.

---

# 12. GRAPH RETRIEVAL CHALLENGE

Validate Neo4j independently of vector retrieval.

Test:

```text
Entity → Document
Entity → Entity
Entity → Claim
Entity → Regulation
Product → Ingredient
Ingredient → Property
Table → Entity
Image → Entity
Claim → Evidence
```

Generate graph questions requiring multiple hops.

Examples:

```text
Which products contain Ingredient X?

Which suppliers manufacture products containing Ingredient X?

Which regulation applies to Ingredient X?

Which documents discuss Ingredient X and particle size?

What properties are associated with Ingredient X across the corpus?
```

Prevent graph contamination from incorrectly merged entities.

---

# 13. CROSS-DOCUMENT QUERY CHALLENGE

This is mandatory.

Ingest at least 2 documents at the same time and test questions requiring evidence from multiple documents.

Test:

### Comparison

```text
Compare Product A and Product B.

How do their particle sizes differ?

Which one has the higher recommended concentration?
```

### Aggregation

```text
List all products containing Ingredient X.
```

### Contradiction

```text
Do any documents report conflicting values for density?
```

### Relationship

```text
Which suppliers mention the same ingredient?
```

### Evidence synthesis

```text
Based on all documents, what evidence supports Ingredient X for skin hydration?
```

Every factual statement must retain its originating document citation.

Never blend values from multiple documents without preserving provenance.

---

# 14. QUERY ROUTING

Implement or validate query classification.

Examples:

```text
"What is the INCI name?"
→ factual/vector

"What ingredients does this product contain?"
→ entity/vector

"How is Ingredient A connected to Regulation B?"
→ graph/local

"Compare all products."
→ cross-document/global

"What does this image show?"
→ multimodal

"What is shown in Figure 3?"
→ multimodal

"Compare the two tables."
→ multimodal + structured-table retrieval

"Summarize everything about Ingredient X."
→ mix/global
```

Do not send every query through the same retrieval strategy.

---

# 15. CONVERSATION CONTEXT

This is critical.

The chatbot must understand conversational follow-ups.

Test:

```text
User:
What is Product A used for?

Assistant:
...

User:
What is its recommended concentration?
```

The second question must resolve:

```text
its → Product A
```

Test:

```text
User:
Compare Product A and Product B.

User:
Which one has the smaller particle size?
```

Resolve:

```text
which one → Product A / Product B
```

Test:

```text
User:
Tell me about Ingredient X.

User:
Which products contain it?

User:
What about Supplier Y?
```

Conversation state must preserve useful references.

---

# 16. CONTEXT SWITCH DETECTION

The system must NOT blindly assume every new question belongs to the previous conversational topic.

Example:

```text
User:
Tell me about Product A.

User:
What is its density?

User:
What regulations apply in Europe?

User:
Now tell me about Product B.
```

The last query explicitly changes entity/context.

The system must reset or update the active entity appropriately.

Another example:

```text
User:
What does Figure 2 show?

User:
How does this relate to particle size?

User:
Forget that. Which products contain titanium dioxide?
```

The final query must not remain anchored to Figure 2.

Implement query contextualization that produces something conceptually similar to:

```json
{
  "query": "Which products contain titanium dioxide?",
  "requires_history": false,
  "resolved_query": "Which products contain titanium dioxide?",
  "active_entities": ["Titanium Dioxide"],
  "context_switch": true
}
```

For genuine follow-up:

```json
{
  "query": "What is its density?",
  "requires_history": true,
  "resolved_query": "What is the density of Product A?",
  "active_entities": ["Product A"],
  "context_switch": false
}
```

Do NOT simply concatenate all previous chat messages to the retrieval query.

Create explicit:

```text
QueryContextResolver
```

with structured output.

---

# 17. HISTORY CONTAMINATION TESTS

Challenge the chatbot with conversations deliberately designed to confuse it.

Example:

```text
Q1: What is Product Alpha?
Q2: What is its recommended use?
Q3: Tell me about Product Beta.
Q4: What is its density?
```

Q4 must refer to Product Beta, not Product Alpha.

Another:

```text
Q1: What is Ingredient X?
Q2: Which supplier provides it?
Q3: What is the capital of France?
Q4: Back to Ingredient X: what is its INCI name?
```

Q3 is independent.

Q4 explicitly reactivates Ingredient X.

Create automated conversation-context regression tests.

---

# 18. AMBIGUITY HANDLING

If several entities could match a reference, do not guess.

Example:

```text
User:
Compare Product A and Product B.

User:
What is its density?
```

`its` is ambiguous.

The application should either:

1. resolve it from strong conversational evidence, or
2. ask the user which product they mean.

Never silently invent the target entity.

---

# 19. HALLUCINATION RESISTANCE

Create adversarial questions for facts NOT present in the documents.

Examples:

```text
What is the CEO's birthday?

What is the factory's annual electricity usage?

What is this product's 2035 forecast revenue?

What clinical trial proved this ingredient cures eczema?
```

If evidence does not exist, answer clearly:

```text
I could not find this information in the provided documents.
```

Do NOT answer from model world knowledge unless the application explicitly supports external knowledge and the user requests it.

For document-chat mode:

```text
DOCUMENT EVIDENCE > MODEL KNOWLEDGE
```

No evidence means no factual answer.

---

# 20. PARTIAL-EVIDENCE TESTING

Challenge questions where only part of the answer exists.

Example:

Document contains:

```text
Density = 1.05 g/cm³
```

but no temperature.

Question:

```text
What is its density at 25°C?
```

Correct behavior:

```text
The document reports a density of 1.05 g/cm³, but I could not find evidence that the measurement was taken at 25°C.
```

Do not silently add the requested condition.

---

# 21. CONFLICTING-EVIDENCE HANDLING

If two documents disagree:

```text
Document A:
Particle size = 15 μm

Document B:
Particle size = 22 μm
```

Do NOT choose one silently.

Return:

```text
The documents report different values:

- Document A: 15 μm
- Document B: 22 μm
```

with separate citations.

The retrieval/generation layer must explicitly support contradiction detection.

---

# 22. NUMERIC FIDELITY

Challenge all numeric information:

* decimal separators
* thousands separators
* percentages
* ranges
* ± values
* scientific notation
* units
* temperatures
* concentrations
* dimensions
* particle sizes

Examples:

```text
0.05%
5%
5.0 × 10⁻³
20 ± 2 μm
0.8–1.2 g/cm³
25 °C
```

Never alter units.

Never convert units unless requested.

When converting, preserve original value and indicate the conversion.

---

# 23. CITATION VALIDATION

Every answer based on documents must carry citations linked to actual retrieved evidence.

Verify:

```text
document
page
section
element
chunk
modality
```

Never cite a chunk merely because it is semantically similar.

The cited evidence must support the specific statement.

Implement:

```text
CitationValidator
```

After answer generation verify:

```text
citation exists
citation was retrieved
source exists
page exists
evidence exists
evidence supports claim
```

Reject unsupported citations.

---

# 24. SOURCE ATTRIBUTION

For multimodal sources distinguish:

```text
TEXT
TABLE
IMAGE
CHART
DIAGRAM
SEM_IMAGE
EQUATION
OCR
CAPTION
```

Example answer:

```text
According to the table on page 7...
```

or:

```text
Figure 4 on page 12 shows...
```

rather than pretending all evidence came from ordinary paragraph text.

---

# 25. RETRIEVAL TRACEABILITY

For debugging, add an optional retrieval trace.

Example:

```json
{
  "original_query": "...",
  "resolved_query": "...",
  "context_switch": false,
  "retrieval_mode": "mix",
  "entities": ["Titanium Dioxide"],
  "vector_hits": [...],
  "graph_hits": [...],
  "multimodal_hits": [...],
  "reranked_hits": [...],
  "final_context": [...]
}
```

Expose this only in debug/admin mode.

Never expose internal chain-of-thought.

This is retrieval provenance, not model reasoning.

---

# 26. ADVERSARIAL QUESTION GENERATOR

Create:

```text
scripts/generate_rag_challenge.py
```

For every ingested document automatically generate test questions covering:

```text
FACTUAL
PARAPHRASE
SEMANTIC
TABLE
IMAGE
CHART
EQUATION
GRAPH
MULTI_HOP
CROSS_DOCUMENT
NEGATIVE
AMBIGUOUS
CONTRADICTION
FOLLOW_UP
CONTEXT_SWITCH
```

Questions must be generated from document evidence.

Store:

```text
question
expected answer/evidence
source document
source page
source element
question type
difficulty
```

Do not use only LLM-generated expected answers.

Whenever possible, derive expected evidence directly from the parsed source.

---

# 27. BUILD A RAG EVALUATION DATASET

Create:

```text
tests/evaluation/generated/
```

Generate dataset records such as:

```json
{
  "id": "q-001",
  "type": "table",
  "question": "What is the recommended concentration?",
  "expected_evidence": [
    {
      "document_id": "...",
      "page": 4,
      "element_id": "...",
      "text": "Recommended use level: 1–3%"
    }
  ],
  "must_answer": true
}
```

Negative example:

```json
{
  "id": "q-099",
  "type": "negative",
  "question": "Who is the CEO of the manufacturer?",
  "expected_evidence": [],
  "must_answer": false
}
```

---

# 28. AUTOMATED RAG EVALUATION

Create:

```text
scripts/evaluate_rag.py
```

Usage:

```bash
uv run python scripts/evaluate_rag.py \
    --documents backend/sample_data \
    --generate-questions \
    --cross-document \
    --conversation-tests \
    --output reports/rag-evaluation.json
```

Measure at minimum:

```text
document ingestion success rate
page coverage
element coverage
retrieval hit rate
HitRate@1
HitRate@3
HitRate@5
MRR
citation precision
citation recall
answer groundedness
answer correctness
no-answer accuracy
hallucination rate
cross-document retrieval accuracy
follow-up resolution accuracy
context-switch accuracy
entity resolution accuracy
table retrieval accuracy
image retrieval accuracy
equation retrieval accuracy
```

Use deterministic/heuristic metrics wherever possible.

Use an LLM-as-judge only as an additional signal, never as the only evaluation method.

---

# 29. TEST QUERY TYPE MATRIX

At minimum create tests for:

| Query Type           | Required           |
| -------------------- | ------------------ |
| Direct factual       | Yes                |
| Paraphrased factual  | Yes                |
| Semantic             | Yes                |
| Metadata             | Yes                |
| Table                | Yes                |
| Image                | Yes                |
| SEM image            | Yes when available |
| Chart                | Yes                |
| Formula/equation     | Yes                |
| OCR                  | Yes when available |
| Multi-hop graph      | Yes                |
| Cross-document       | Yes                |
| Comparison           | Yes                |
| Aggregation          | Yes                |
| Contradiction        | Yes                |
| Negative/no evidence | Yes                |
| Follow-up            | Yes                |
| Pronoun resolution   | Yes                |
| Context switch       | Yes                |
| Ambiguous reference  | Yes                |

---

# 30. CROSS-DOCUMENT ENTITY RESOLUTION

Pay special attention to equivalent entity names.

Examples:

```text
TiO2
Titanium dioxide
Titanium Dioxide
CI 77891
```

Do not automatically assume every alias is equivalent unless evidence or domain normalization supports it.

Support:

```text
canonical entity
aliases
source-specific labels
identifiers
confidence
```

Cross-document queries depend strongly on correct entity resolution.

---

# 31. DUPLICATE CONTENT

Test documents that contain:

* duplicated pages
* repeated table headers
* repeated regulatory text
* same paragraph across documents
* multiple versions of same datasheet

Avoid retrieving five duplicate chunks as five independent pieces of evidence.

Implement retrieval-result deduplication.

Do not destroy provenance while deduplicating.

---

# 32. DOCUMENT VERSIONING

If two versions of the same document exist:

```text
ProductA_v1.pdf
ProductA_v2.pdf
```

The system must understand document/version relationships.

Default retrieval behavior should prefer the current version when appropriate while retaining older versions for historical questions.

Test:

```text
What changed between the two versions?

What was the recommended concentration in the previous version?
```

---

# 33. FAILURE INJECTION

Deliberately test:

* Docling failure
* MinerU failure
* PaddleOCR failure
* OpenAI timeout
* embedding timeout
* Qdrant failure
* Neo4j failure
* PostgreSQL retry
* malformed PDF
* encrypted PDF
* huge PDF
* empty PDF

Validate:

```text
fallback
retry
resume
idempotency
partial failure reporting
```

A parser failure must never silently produce an apparently successful empty document.

---

# 34. PERFORMANCE

Measure:

```text
parsing time/page
OCR time/page
vision calls/document
embedding time
graph extraction time
total ingestion time
query retrieval latency
answer TTFT
total answer latency
peak memory
```

Find obviously unnecessary expensive operations.

Examples:

Do NOT:

```text
OCR every native page
send every image to vision
regenerate embeddings unnecessarily
re-extract unchanged graph entities
```

Optimize without compromising retrieval quality.

---

# 35. FIX THE IMPLEMENTATION

This is critical.

Do not only produce an evaluation report.

When a test exposes a weakness:

1. identify the root cause
2. identify the responsible layer
3. modify the implementation
4. add a regression test
5. rerun the relevant evaluation
6. verify improvement
7. ensure no regression elsewhere

Possible areas to fix include:

```text
parser router
normalization
OCR routing
table processing
image processing
context construction
chunking
embedding
Qdrant filters
Neo4j graph extraction
entity resolution
retrieval fusion
reranking
query contextualization
conversation handling
citation validation
answer-generation prompts
no-answer behavior
```

Never hide a failure by weakening the test.

---

# 36. DO NOT OVERFIT

This requirement is mandatory.

Do not create:

```python
if filename == "specific_test.pdf":
    ...
```

Do not add special-case answers for sample documents.

Do not hard-code:

```text
specific product names
specific questions
specific PDF layouts
specific expected answers
```

Fix the generalized architecture and algorithms.

The same implementation must work when a completely new document is uploaded tomorrow.

---

# 37. REGRESSION SUITE

For every bug found, add a regression test.

Create appropriate suites under:

```text
tests/
  unit/
  integration/
  ingestion/
  parsers/
  retrieval/
  graph/
  multimodal/
  conversation/
  evaluation/
```

Every fixed issue must become permanently testable.

---

# 38. FINAL REPORT

Create:

```text
reports/rag-reliability-report.md
```

Include:

## Corpus

Documents analyzed and their characteristics.

## Parser results

Which parser performs best for which document type.

## Problems identified

For each:

```text
severity
document
query/test
root cause
affected layer
fix
regression test
result after fix
```

## Retrieval metrics

Before and after changes.

## Conversation metrics

Including:

```text
follow-up resolution
pronoun resolution
context-switch detection
ambiguity handling
```

## Hallucination results

Report:

```text
negative questions tested
correct refusals
unsupported answers
hallucination rate
```

## Cross-document results

Report:

```text
cross-document questions
retrieval accuracy
citation accuracy
entity-resolution issues
```

## Remaining limitations

Be explicit.

Do not claim 100% reliability unless the evidence demonstrates it.

---

# 39. ACCEPTANCE CRITERIA

The system is NOT considered validated simply because:

```text
PDF ingestion succeeds
```

It must demonstrate:

* high page-content coverage
* correct structural extraction
* correct multimodal extraction
* reliable table understanding
* reliable OCR fallback
* correct formula preservation
* correct image/caption association
* useful chunks
* strong retrieval
* correct graph relationships
* correct cross-document queries
* correct conversation follow-ups
* correct context switching
* accurate citations
* appropriate no-answer behavior
* low hallucination rate
* parser failure recovery
* deterministic regression tests

Target quality goals:

```text
Document ingestion success       >= 99%
Expected-page coverage           >= 99%
Retrieval HitRate@5              >= 95%
Citation validity                >= 99%
No-answer correctness            >= 95%
Follow-up context accuracy       >= 95%
Context-switch accuracy          >= 98%
Cross-document evidence recall   >= 90%
```

Treat these as engineering targets rather than numbers to game.

If a target is not reached, report the actual result and investigate why.

---

# 40. EXECUTION ORDER

Execute in this order.

### Phase 1 — Corpus Discovery

Inspect every available PDF.

Do not change code yet.

### Phase 2 — Parsing Evaluation

Challenge:

* Docling
* MinerU
* Marker
* PaddleOCR
* pypdfium2

Determine parsing weaknesses.

### Phase 3 — Normalization

Validate preservation of every important element.

Fix normalization issues.

### Phase 4 — Ingestion

Validate:

```text
MinIO
PostgreSQL
Qdrant
Neo4j
```

and provenance consistency.

### Phase 5 — Chunking

Inspect chunks and fix structural problems.

### Phase 6 — Retrieval

Challenge vector, graph, hybrid and multimodal retrieval.

### Phase 7 — Cross-Document Retrieval

Challenge multi-document reasoning.

### Phase 8 — Conversation

Challenge follow-ups, pronouns, context changes and ambiguity.

### Phase 9 — Hallucination

Run negative and partial-evidence tests.

### Phase 10 — Multimodal

Challenge images, SEM images, tables, charts and formulas.

### Phase 11 — Failure Injection

Challenge parser/model/storage failures.

### Phase 12 — Optimization

Improve quality and remove unnecessary expensive processing.

### Phase 13 — Full Regression

Run the complete suite.

### Phase 14 — Report

Generate the final reliability report.

---

# 41. WORKING RULES

Do NOT stop at analysis.

Inspect the existing source code.

Run the application.

Run the real PDFs.

Inspect PostgreSQL.

Inspect Qdrant.

Inspect Neo4j.

Inspect MinIO objects.

Inspect normalized parser outputs.

Inspect actual chunks.

Inspect actual retrieved documents.

Inspect actual citations.

Identify defects from evidence.

Fix the implementation.

Run tests after every meaningful change.

Do not rewrite working components without a demonstrated reason.

Do not downgrade architecture merely to make a test pass.

Do not use mocks for the core end-to-end PDF evaluation unless an external service cannot be invoked.

For ordinary unit tests, mocks remain appropriate.

Never claim a fix works without running the relevant tests.

---

# 42. FIRST RESPONSE

Before changing code, provide:

1. PDFs discovered.
2. Characteristics of each PDF.
3. Existing ingestion pipeline discovered in the code.
4. Existing parser implementations.
5. Existing chunking implementation.
6. Existing Qdrant retrieval implementation.
7. Existing Neo4j implementation.
8. Existing conversation/query-context handling.
9. Existing citation-generation mechanism.
10. Test matrix you are about to execute.

Then immediately begin Phase 1 and continue through the phases.

Do not ask for confirmation unless execution is genuinely blocked by unavailable credentials or infrastructure.

Your role is to challenge the implementation, find weaknesses, fix them, prove the fixes with regression tests, and improve the generalized solution rather than optimizing specifically for the current sample PDFs.
