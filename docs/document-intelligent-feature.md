Act as a senior software architect and AI/RAG engineer.

I want to introduce a **plugin architecture for document-processing capabilities** in the existing application.

The objective is to allow document-processing features to be enabled or disabled independently, and to make advanced document extraction work similarly to Azure Document Intelligence.

Do not start implementing immediately.

First inspect the repository and identify the current:

* document upload flow;
* ingestion pipeline;
* parser abstraction;
* Docling integration;
* MinerU integration;
* Marker/PDFium integration;
* Vision model integration;
* PostgreSQL models;
* Redis jobs/workers;
* Qdrant indexing;
* Neo4j extraction;
* frontend upload components;
* configuration system;
* feature flags, if any.

Do not invent classes, APIs or database structures that do not exist.

## 1. Introduce a plugin architecture

Create a generic document-processing plugin contract.

A plugin should represent one optional capability, for example:

```text
docling_parser
mineru_parser
marker_parser
vision_analysis
document_intelligence
document_classifier
entity_extraction
graph_extraction
```

Each plugin must expose metadata similar to:

```json
{
  "id": "document-intelligence",
  "name": "Document Intelligence",
  "description": "Structured field extraction from documents",
  "enabled": true,
  "version": "1.0",
  "capabilities": [
    "classification",
    "field_extraction",
    "tables",
    "key_value_pairs"
  ]
}
```

Plugins must be independently:

```text
enabled
disabled
configured
versioned
```

Disabling a plugin must not require code removal or redeployment.

Avoid large `if/else` chains such as:

```python
if plugin == "docling":
...
elif plugin == "mineru":
...
elif plugin == "azure":
...
```

Use a registry/interface/strategy pattern.

Example conceptual design:

```text
DocumentPlugin
    ├── metadata()
    ├── is_enabled()
    ├── get_models()
    ├── get_capabilities()
    ├── validate_configuration()
    └── execute()
```

Adapt this to the existing codebase conventions.

---

## 2. New Document Intelligence plugin

Implement a new plugin:

```text
document-intelligence
```

This plugin provides structured document extraction similar conceptually to Azure Document Intelligence.

It must support multiple extraction models.

Examples:

```text
Layout
General Document
Custom Schema
SDS
Certificate of Analysis
Product Datasheet
Raw Material Specification
Scientific Document
```

Do not hard-code the architecture specifically for cosmetics.

The plugin must support additional models later.

---

## 3. Model registry

Each Document Intelligence model should be registered through configuration or persistence.

Conceptually:

```json
{
  "id": "cosmetics-product-specification",
  "name": "Cosmetics Product Specification",
  "type": "custom",
  "enabled": true,
  "description": "Extract structured product specification information"
}
```

The application should expose available models dynamically.

Do not hard-code the model list directly in the upload UI.

---

## 4. Field schema per model

Each model must define the fields it knows how to extract.

Example:

```json
{
  "model_id": "cosmetics-product-specification",
  "fields": [
    {
      "name": "product_name",
      "label": "Product Name",
      "type": "string",
      "default_selected": true
    },
    {
      "name": "inci_name",
      "label": "INCI Name",
      "type": "string",
      "default_selected": true
    },
    {
      "name": "supplier",
      "label": "Supplier",
      "type": "string",
      "default_selected": true
    },
    {
      "name": "recommended_usage",
      "label": "Recommended Usage",
      "type": "string",
      "default_selected": false
    },
    {
      "name": "ph",
      "label": "pH",
      "type": "number",
      "default_selected": false
    }
  ]
}
```

Supported field types should be extensible and may include:

```text
string
number
integer
boolean
date
currency
percentage
list
object
table
```

---

## 5. Upload user experience

Modify the document upload screen.

When the Document Intelligence plugin is enabled, provide an optional section:

```text
Document processing

[ ] Document Intelligence
```

If selected:

```text
Model:
[ Cosmetics Product Specification ▼ ]
```

After selecting a model, dynamically show the fields supported by that model.

Example:

```text
Fields to extract:

[x] Product Name
[x] INCI Name
[x] Supplier
[x] CAS Number
[ ] Recommended Usage
[ ] pH
[ ] Viscosity
[ ] Regulatory Status
```

Support:

```text
Select all
Clear all
Recommended fields
```

The user should not need to manually enter field names when using an existing model.

---

## 6. Custom model mode

Also provide:

```text
Model:
[ Custom Extraction ▼ ]
```

When `Custom Extraction` is selected, allow the user to define fields dynamically.

Example:

```text
Field name           Type

Product Name         String
INCI                  String
Usage Level           Percentage
Supplier              String
Claims                List
```

The user must be able to add/remove fields.

The schema should be saved so it can optionally be reused as a custom model.

---

## 7. Query-field mode

Also support a lightweight mode similar to Azure Document Intelligence `queryFields`.

Example:

```text
Extract these fields from this document:

Product Name
INCI
Supplier
Recommended Usage
CAS Number
```

This should not require creating a permanent model.

Internally represent it as an ad-hoc extraction schema.

---

## 8. Upload API contract

Extend the current upload API without breaking existing clients.

Conceptually the request might include:

```json
{
  "document_intelligence": {
    "enabled": true,
    "model_id": "cosmetics-product-specification",
    "selected_fields": [
      "product_name",
      "inci_name",
      "supplier",
      "recommended_usage"
    ]
  }
}
```

For custom extraction:

```json
{
  "document_intelligence": {
    "enabled": true,
    "model_id": "custom",
    "fields": [
      {
        "name": "product_name",
        "type": "string"
      },
      {
        "name": "recommended_usage",
        "type": "percentage"
      }
    ]
  }
}
```

Use the current API conventions of the project rather than blindly implementing these exact structures.

---

## 9. Processing flow

The new feature should integrate into ingestion like this:

```text
UPLOAD
   ↓
STORE ORIGINAL DOCUMENT
   ↓
BASE DOCUMENT PARSING
   ↓
DOCUMENT INTELLIGENCE PLUGIN
   ↓
SELECTED MODEL
   ↓
FIELD EXTRACTION
   ↓
FIELD VALIDATION
   ↓
PERSIST STRUCTURED RESULTS
   ↓
CHUNKING / EMBEDDING
   ↓
QDRANT
   ↓
OPTIONAL NEO4J EXTRACTION
```

The plugin must receive the normalized document representation when possible.

Do not parse the PDF again unnecessarily.

---

## 10. Extracted field result

Each extracted field must contain more than just a value.

Return something similar to:

```json
{
  "field": "recommended_usage",
  "value": "2-5%",
  "normalized_value": {
    "min": 2,
    "max": 5,
    "unit": "%"
  },
  "confidence": 0.94,
  "page": 3,
  "source_text": "Recommended usage: 2-5%",
  "bounding_box": null,
  "extraction_method": "llm"
}
```

Every extracted value must preserve provenance.

At minimum persist:

```text
value
confidence
page
source reference
extraction method
model
```

Do not persist AI-generated values without traceability to the source document.

---

## 11. Confidence handling

Every extracted field must have a confidence score.

Example:

```text
>= 0.90 → HIGH
0.70–0.89 → MEDIUM
< 0.70 → LOW
```

Low-confidence values should be visible in the UI.

Do not silently convert low-confidence extraction into trusted document metadata.

---

## 12. Extraction strategies

The plugin must not assume that every field requires an LLM call.

Implement a strategy chain.

For example:

```text
structured parser
↓
regex/rules
↓
table extraction
↓
embedding/semantic extraction
↓
LLM
↓
Vision
```

Only use expensive models when simpler extraction methods cannot reliably determine the value.

---

## 13. Vision

If a field exists only inside:

```text
image
chart
diagram
scanned page
```

the plugin may call the configured Vision model.

Vision should be invoked only for relevant pages/regions where possible.

Do not send the entire document to the Vision model by default.

---

## 14. Persistence model

Inspect the existing PostgreSQL schema first.

Introduce appropriate persistence for:

```text
plugins
plugin_configuration

document_intelligence_models
document_intelligence_model_fields

document_extraction_runs
document_extracted_fields
```

A possible extracted field structure:

```text
id
document_id
extraction_run_id
model_id
field_name
field_type
raw_value
normalized_value
confidence
page_number
source_element_id
extraction_method
created_at
```

Avoid storing everything as opaque JSON if the data needs to be searchable, auditable or filterable.

JSONB can still be used for complex typed values and provider-specific metadata.

---

## 15. Plugin configuration

Administrators should be able to enable or disable plugins.

Example:

```text
Administration
   ↓
AI / Processing Plugins

Docling                 Enabled
MinerU                  Enabled
Marker                  Enabled
Vision                  Enabled
Document Intelligence   Enabled
Graph Extraction        Enabled
```

When Document Intelligence is disabled:

* it must disappear from upload options;
* existing extracted data must remain available;
* ingestion without it must continue working;
* no Document Intelligence model calls should occur.

---

## 16. Provider abstraction

Do not tie the `document-intelligence` plugin directly to Azure.

Create a provider abstraction.

Conceptually:

```text
DocumentIntelligencePlugin
       |
       +-- InternalProvider
       |
       +-- AzureDocumentIntelligenceProvider
       |
       +-- LLMProvider
       |
       +-- FutureProvider
```

The first implementation can use our current parsers and models.

Azure Document Intelligence may be integrated later.

The frontend must deal with:

```text
plugin
model
field schema
```

not Azure-specific API objects.

---

## 17. Prebuilt and custom models

Model types should support at least:

```text
PREBUILT
CUSTOM
AD_HOC
```

Examples:

```text
PREBUILT
  layout
  general-document

CUSTOM
  cosmetics-product-spec
  sds
  coa

AD_HOC
  user-selected query fields
```

This architecture should allow a future Azure provider to map those concepts to Azure prebuilt/custom models without changing the upload UI.

---

## 18. Integration with classification

If document classification already exists or is planned, integrate the two concepts cleanly.

Example:

```text
uploaded document
↓
classifier predicts SDS
↓
recommended model:
SDS Extraction
↓
UI displays:

Detected document:
Safety Data Sheet — 96%

Recommended extraction model:
SDS Extraction

Recommended fields:
[x] Product Name
[x] CAS Number
[x] Ingredients
[x] Hazards
[x] Handling
[x] Storage
```

The user can accept or change the recommended model.

Do not make classification mandatory for extraction.

---

## 19. RAG integration

Selected extracted fields should optionally become searchable metadata.

For example, Qdrant payload:

```json
{
  "document_id": "...",
  "document_type": "PRODUCT_DATASHEET",
  "product_name": "...",
  "supplier": "...",
  "inci": ["..."]
}
```

However, do not blindly duplicate large extracted structures into every Qdrant point.

Determine which fields belong at:

```text
document metadata level
chunk metadata level
Neo4j graph level
```

---

## 20. Neo4j integration

Structured extracted fields should optionally feed GraphRAG.

Example:

```text
Product Name
    ↓
(:Product)

Supplier
    ↓
(:Supplier)

INCI
    ↓
(:Ingredient)

CAS Number
    ↓
Ingredient.cas_number
```

Do not create graph entities automatically for every arbitrary custom field.

Use configurable graph mappings.

---

## 21. Cost control

This feature must explicitly minimize AI model usage.

Persist outputs of extraction runs.

Generate fingerprints from:

```text
document_hash
plugin_version
model_id
model_version
selected_fields
extraction_configuration
```

If the fingerprint is unchanged:

```text
DO NOT RUN EXTRACTION AGAIN
```

Reuse the previous extraction output.

If a user adds only one additional field:

```text
existing fields:
Product Name
INCI
Supplier

new field:
Recommended Usage
```

extract only:

```text
Recommended Usage
```

Do not re-extract every previously completed field unless required.

---

## 22. Validation and regression tests

Implement tests for:

```text
plugin enabled
plugin disabled
model listing
field listing
field selection
custom fields
upload without plugin
upload with plugin
extraction success
extraction failure
low confidence extraction
partial extraction
cache reuse
adding one new field
provider failure
Vision fallback
```

Existing ingestion and RAG tests must continue passing.

---

## 23. First deliverable

Before changing code, return a design report containing:

### Existing architecture

Show where this feature fits in the current repository.

### Plugin design

Interfaces, registry, lifecycle and configuration.

### Document Intelligence design

Plugin, provider abstraction, models and fields.

### Data model

Required PostgreSQL/Alembic changes.

### API changes

Backend contracts.

### Frontend flow

Show the complete upload interaction.

### Processing flow

Show integration with the existing ingestion worker.

### Cost-control design

Explain how unnecessary parser/model calls are avoided.

### Backward compatibility

Explain how existing uploads continue working unchanged.

### Implementation phases

Break the implementation into independently testable increments.

Do not implement code until the design has been reviewed.

Most importantly:

**Reuse existing abstractions where appropriate and do not invent duplicate infrastructure when equivalent mechanisms already exist in the repository.**
