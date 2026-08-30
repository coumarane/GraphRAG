# Document Intelligence — Design Report

**Status: design reviewed and approved, no implementation started.** Answers the design-report
request in `docs/document-intelligent-feature.md`. Two open decisions are flagged inline
(global vs. per-tenant enable/disable; in-line extraction stage vs. a separate async worker) —
both carry a recommendation, but implementation should not proceed past Phase 1/3 without
confirming them. See Section 10 for the phased build order.

## Context

`docs/document-intelligent-feature.md` requests a pluggable document-processing capability
system, plus a new "Document Intelligence" plugin for structured field extraction (conceptually
like Azure Document Intelligence: prebuilt/custom/ad-hoc extraction models, per-model field
schemas, confidence-scored provenance, cost-control via fingerprinting, a provider abstraction
so Azure could be swapped in later). The document explicitly asks for a design report before
any code — this is that report, produced after directly inspecting the repository areas the
document itself names (upload flow, ingestion pipeline, parser abstraction, Docling/MinerU/
Marker/PDFium, Vision integration, Postgres models, Redis workers, Qdrant/Neo4j indexing,
frontend upload components, config system, feature flags) via two research passes plus direct
verification of the highest-stakes claims.

**Headline finding**: this is not a green-field build. A generic plugin-registry pattern
already exists in this codebase (built earlier this session for parsers) and solves the
document's core "avoid if/elif, use a registry" requirement already. Document Intelligence is a
new *capability* layered onto that existing infrastructure, plus one genuinely new concept the
registry doesn't cover 1:1 (one plugin exposing many named "models," each with its own field
schema). Five things are wholly new and carry real effort: the Postgres tables, the frontend
upload UI (no Select/Checkbox/multiselect component exists anywhere yet), document
classification (doesn't exist at all — but the source document itself makes this optional), and
two genuine architectural forks needing an explicit decision (below).

## 1. Existing architecture

- **Plugin registry infrastructure already exists and is proven**, in
  `backend/src/graph_rag/application/plugins/`:
  - `registry.py::PluginRegistry[T]` — one instance per capability, merges core (in-tree) and
    discovered (`importlib.metadata` entry-point) descriptors, enforces `allow_core_override`
    and an `allowlist`, tracks `blocked()` for introspection. `register_discovered()` hard-rejects
    any descriptor self-declaring `trust_tier == "core"` (a real bypass fixed this session).
  - `descriptors.py::PluginDescriptor` — frozen dataclass: `plugin_name`, `capability`,
    `builder: Callable[[Any], Any]`, `trust_tier`, `config_model: type[BaseModel] | None`,
    `extra`, `modules`, `structured`, `metadata`.
  - `discovery.py::PLUGIN_ENTRY_POINT_GROUPS` reserves entry-point group names per capability
    (`object_store`, `vector_store`, `graph_store`, `metadata_store`, `ingest_queue`, `parser`,
    `chat_model`, `embedding_model`, `reranker`, `cli_plugins`, `api_routers`). No
    `document_intelligence` group yet.
  - `parsers.py` is the only capability wired end-to-end today (6 core descriptors,
    `parser_plugin_registry(settings)`, `descriptor_is_installed()` probing optional deps).
  - `catalog.py::build_plugin_catalog()` assembles a read-only inventory across all capability
    registries; powers `GET /api/v1/ops/plugins` (gated by `Action.ADMIN_PLUGINS`),
    `graph-rag plugins list`, and the `/plugins` admin frontend page.
  - `config/settings.py::PluginsSettings` is the process-wide config surface — **not
    per-tenant**; `Settings` is `@lru_cache`d once per process from YAML+env.
- **Ingestion is one fixed, linear, resumable stage machine.**
  `domain/ingestion/stages.py::IngestionStageName` enumerates 22 stages VALIDATE→FINALIZE;
  **confirmed directly**: `INGESTION_STAGE_ORDER = tuple(IngestionStageName)` — declaration
  order *is* execution order. `application/ingestion/stage_pipeline.py::DocumentPipeline`
  maps every stage to a bound method; `PipelineWorkspace.normalized: NormalizedDocument` is
  populated by `stage_normalize` and is exactly what a Document Intelligence plugin must
  consume — the already-normalized document, never raw bytes.
- **One queue, one consumer group, one synchronous task per run.** `RedisStreamIngestionQueue`
  (stream `"ingestion-jobs"`) → `infrastructure/workers/ingestion_worker.py::process_one` →
  `run_document_pipeline` runs the entire 22-stage sequence synchronously in one task on one
  `AsyncSession`. No fan-out/async-post-processing mechanism exists today.
- **Intake and processing are already decoupled.** `api/routes/documents.py::ingest_document`
  builds a `RegisterSourceRequest` (`extra="forbid"`) and calls
  `RegisterSourceService.execute()` (VALIDATE/HASH/REGISTER_DOCUMENT/STORE_ORIGINAL only).
  **Confirmed directly**: `domain/ingestion/records.py:102` —
  `IngestionRunRecord.metadata: dict[str, JsonValue] = Field(default_factory=dict)` — populated
  once by `_create_run`, otherwise unused. This is the natural place to carry extraction
  *options* through to the worker with zero migration.
- **Postgres**: 7 Alembic migrations exist (`0001_lifecycle` … `0007_conversations`); nothing
  resembling plugin/model-registry/extracted-field tables (confirmed via grep, zero hits).
  Conventions, **confirmed directly**: UUID PK via `domain.ids.new_id`, `TenantOwnedMixin` +
  `TimestampMixin` (`infrastructure/persistence/postgres/base.py`), JSON columns aliased
  `metadata_json`. `ingestion_runs`/`ingestion_stages` already have `config_fingerprint`/
  `content_hash` columns (`postgres/models/ingestion.py:44-45,91`) — the fingerprinting pattern
  to copy verbatim. `model_usage_events` (**confirmed**: `capability`, `provider`,
  `estimated_usd`, `document_id`, `ingestion_run_id` columns present,
  `postgres/models/usage.py:15-34`) is a ready template for extraction cost tracking.
- **Vision** goes through the plain multimodal `ChatModel`, not a dedicated `VisionModel`
  adapter (that protocol has no concrete implementation). `application/ingestion/
  visual_enrichment.py::collect_visual_targets` already produces per-page/per-bbox
  `VisualTarget`s and `render_visual_png` crops by bbox when available (bboxes are largely
  unpopulated today, so this is effectively full-page renders in practice); `vision_max_pages`
  caps calls. `MultimodalSettings` toggles are global booleans, no per-region config.
- **Frontend upload** (`frontend/src/app/upload/page.tsx`) is a bare dropzone + title + submit;
  `parser_requested` is hardcoded `"auto"`; no processing-options UI, no Select/Checkbox/
  multiselect components exist anywhere in `frontend/src/components/ui/` (only `avatar`,
  `badge`, `button`, `card`, `input`, `label`, `separator`).
- **No document classification exists anywhere** in the repo.
- Two existing sibling features are useful precedent for the admin surfaces this needs: the
  **MCP server** (`backend/src/graph_rag/mcp/`) and the **config composer**
  (`application/config_composer.py` + `/pipeline-builder` frontend page).

## 2. Plugin design (interfaces, registry, lifecycle, configuration)

Reuse the exact existing pattern rather than inventing a parallel one.

- New capability constant `"document_intelligence"` in a new module
  `application/plugins/document_intelligence.py` (sibling to `parsers.py`), plus
  `discovery.py::PLUGIN_ENTRY_POINT_GROUPS["document_intelligence"] = "graph_rag.document_intelligence"`.
- **`PluginRegistry[T]` reused as-is** — `document_intelligence_plugin_registry(settings)`
  mirrors `parser_plugin_registry(settings)` exactly. No changes to `registry.py`/
  `descriptors.py` needed for the *provider* level — `InternalProvider`/
  `AzureDocumentIntelligenceProvider`/`LLMProvider` each map onto one `PluginDescriptor`.
- **What `PluginDescriptor` does not cover**: the document's per-plugin metadata shape
  (`{id, name, description, enabled, version, capabilities[]}`) and "one plugin exposes many
  models, each with a field schema." Rather than bending `PluginDescriptor` (used by 6 other
  capabilities), add a second, small `Protocol` (matching this codebase's structural-typing
  preference, e.g. `domain/models/protocols.py`) in the new module:
  - `DocumentIntelligencePlugin` — `metadata()`, `is_enabled(settings)`, `get_models()`,
    `get_capabilities()`, `validate_configuration(settings)`, `execute(request)` — the exact
    method set the source document asks for.
  - `DocumentIntelligencePluginMetadata` — `BaseModel` `{id, name, description, enabled,
    version, capabilities: list[str]}`, matching the document's shape verbatim. This is what a
    read-only introspection endpoint returns — intentionally provider-agnostic, so no
    Azure-shaped object ever reaches the frontend.
  - The plugin is still installed via one `PluginDescriptor` per provider implementation in the
    `document_intelligence` registry; `builder(settings)` returns the concrete class; the
    descriptor's existing `config_model` is exactly the "independently configured" mechanism.
- **Enable/disable at two levels**, matching what exists rather than adding a third:
  1. *Installation-level*: `PluginsSettings.enabled`/`allowlist` — identical to parsers today.
  2. *Feature-level*: a new `DocumentIntelligenceSettings(BaseModel)` next to `OcrSettings`/
     `MultimodalSettings` in `config/settings.py`, `enabled: bool = True`,
     `default_provider: str = "internal"`.

**Open decision #1 — global vs. per-tenant enable/disable.** The source document says
"administrators enable/disable" without specifying scope. Nothing in `Settings` is per-tenant
today (`Settings` is process-global, `@lru_cache`d) — building true per-tenant toggles needs new
infrastructure that doesn't exist for *any* capability yet. **Recommendation: ship Phase 1 as a
global toggle** (`DocumentIntelligenceSettings.enabled`, exactly mirroring `OcrSettings.mode`/
`MultimodalSettings.enabled`) — zero new plumbing, matches the source document's own "first
implementation can use current parsers/models" pragmatism. If per-tenant control turns out to
be a hard requirement, that's a separate, larger piece of infrastructure — don't bundle it in
silently. (The Postgres design below leaves room for this: `plugin_configuration.tenant_id` is
nullable from day one, so per-tenant overrides can be added later without a further migration.)

## 3. Document Intelligence design (plugin, provider abstraction, models, fields)

New package `backend/src/graph_rag/application/document_intelligence/`:

- `models.py` — provider-agnostic Pydantic schemas:
  - `FieldType` (`StrEnum`): `STRING, NUMBER, INTEGER, BOOLEAN, DATE, CURRENCY, PERCENTAGE,
    LIST, OBJECT, TABLE` — the document's exact list.
  - `ModelFieldSpec` — `{name, label, type: FieldType, default_selected: bool}`.
  - `ModelType` (`StrEnum`): `PREBUILT, CUSTOM, AD_HOC` — chosen so a future Azure provider maps
    its own taxonomy onto these three without the upload UI changing.
  - `DocumentIntelligenceModel` — `{model_id, name, model_type, version, fields: list[ModelFieldSpec]}`.
  - `ExtractionRequest` — `{tenant_id, document_id, version_id, normalized_document:
    NormalizedDocument, model_id, selected_fields, custom_fields, extraction_configuration}` —
    `normalized_document` is `PipelineWorkspace.normalized`, never raw bytes.
  - `ExtractedFieldResult` — `{name, value, normalized_value, confidence, confidence_band,
    page, source_text, bounding_box, extraction_method, model}` — full provenance per field.
  - `ConfidenceBand` (`StrEnum` `HIGH/MEDIUM/LOW`) derived by one pure function
    `confidence_band(value) -> ConfidenceBand` using the document's exact thresholds (≥0.90 /
    0.70–0.89 / <0.70) — used everywhere confidence is computed so thresholds never drift.
  - `ExtractionMethod` (`StrEnum`): `STRUCTURED_PARSER, RULES, TABLE_EXTRACTION,
    EMBEDDING_SEMANTIC, LLM, VISION` — the exact cheapest-first chain.
  - `ExtractionResult` — `{run_id, model_id, fields, status, partial, provider}`.
- `catalog.py` — built-in prebuilt models (Layout, General Document, SDS, Certificate of
  Analysis, Product Datasheet, Raw Material Specification, Scientific Document) as a static
  tuple, analogous to `application/plugins/parsers.py::CORE_PARSER_DESCRIPTORS` — declarative
  data, not an if/elif dispatcher.
- `providers/internal.py::InternalProvider` — first implementation; runs the extraction chain
  (Section 7) using **only currently-installed parsers/models**, reusing the same multimodal
  `ChatModel` path `stage_pipeline.py::_run_vision` already uses for the Vision tier.
- `providers/azure.py::AzureDocumentIntelligenceProvider` — **not built now**; stubbed with
  `trust_tier="community"` and `modules=("azure.ai.documentintelligence",)` so it's simply
  absent until that SDK is installed, same pattern as the optional `docling`/`marker`/`mineru`
  parser extras.
- `providers/llm.py::LLMProvider` — thin wrapper forcing the LLM tier, for models where
  structured/regex extraction is known not to apply (e.g. Scientific Document free text).
- A `FutureProvider` is a design slot, not code to write now.
- **Custom Schema / Ad-hoc**: `ModelType.CUSTOM` is a persisted, reusable
  `DocumentIntelligenceModel`. `ModelType.AD_HOC` is the document's "query fields" mode — field
  list passed inline with no `model_id`, never persisted as a model row (though the *run* and
  its results are still persisted, since results must stay searchable/auditable regardless).

## 4. Data model (Postgres/Alembic changes)

One new migration, `backend/alembic/versions/0008_document_intelligence.py`, following
`0001_lifecycle.py`/`0004_model_usage.py`'s exact conventions (UUID PK via `new_id`,
`TenantOwnedMixin` + `TimestampMixin` where tenant-scoped, `metadata_json` aliasing). New ORM
modules in `infrastructure/persistence/postgres/models/`:

- **`plugins.py`**
  - `PluginModel` (`plugins`) — durable/queryable counterpart to the in-memory
    `PluginRegistry` for admin audit history (not tenant-owned — mirrors the global registry
    pattern): `plugin_id`, `capability`, `plugin_name`, `version`, `trust_tier`, `enabled`,
    `metadata_json`.
  - `PluginConfigurationModel` (`plugin_configuration`) — `config_id`, `plugin_id (FK)`,
    `tenant_id: UUID | None` (nullable = global default; **this nullable column existing from
    day one is what lets Open Decision #1's per-tenant fork be added later without a further
    migration**, even though Phase 1 only ever writes `tenant_id=NULL` rows), `config_json`,
    timestamps.
- **`document_intelligence.py`**
  - `DocumentIntelligenceModelModel` (`document_intelligence_models`, tenant-owned): `model_id`,
    `model_key` (stable slug), `name`, `model_type`, `version`, `provider`, `is_builtin`,
    `created_by_user_id`, `metadata_json`. Unique `(tenant_id, model_key, version)`.
  - `DocumentIntelligenceModelFieldModel` (`document_intelligence_model_fields`, tenant-owned):
    `field_id`, `model_id (FK, CASCADE)`, `name`, `label`, `field_type`, `default_selected`,
    `sort_order`. Real rows, not JSON — the source document explicitly wants fields
    filterable/reusable, and a checklist UI needs to list them directly.
  - `DocumentExtractionRunModel` (`document_extraction_runs`, tenant-owned): `run_id`,
    `document_id (FK)`, `version_id (FK)`, `ingestion_run_id (FK, nullable)`, `model_id (FK,
    nullable — null for ad-hoc runs)`, `provider`, `plugin_version`, `status`, `fingerprint`
    (copy the `config_fingerprint` pattern verbatim), `selected_fields_json`, `error_code`,
    `error_message`, timestamps.
  - `DocumentExtractedFieldModel` (`document_extracted_fields`, tenant-owned):
    `extracted_field_id`, `run_id (FK, CASCADE)`, `name`, `value_json`, `normalized_value_json`,
    `confidence`, `confidence_band`, `page`, `source_text`, `bounding_box_json`,
    `extraction_method`, `model_name`. Indexed `(tenant_id, run_id, name)`.
  - **Deliberately not one JSONB blob per run** — the source document explicitly requires
    extracted fields to be individually searchable/auditable/filterable (e.g. "find all
    documents where `lot_number = X`"), which real columns support far better than per-field
    GIN expression indexes on a blob.
- Existing tables untouched. No new column on `documents`/`document_versions`/`ingestion_runs`
  is needed for the results (the *request options* already have a home in
  `IngestionRunRecord.metadata`, confirmed above); a back-reference to the extraction run lives
  in that same metadata JSON, not a schema column.

## 5. API changes (backend contracts)

All additive; `RegisterSourceRequest`'s `extra="forbid"` means nothing is smuggled in silently.

- **`POST /api/v1/documents/ingest`** is multipart form fields today, not JSON — add one more
  optional form field, `document_intelligence: str | None = Form(default=None)`, a JSON string
  parsed server-side into a new `DocumentIntelligenceRequest` (`extra="forbid"`):
  `{enabled: bool = False, model_id: str | None, selected_fields: list[str] | None,
  custom_fields: list[ModelFieldSpec] | None}`. Absent/empty → fully backward compatible.
  Parsed value becomes one new optional field on `RegisterSourceRequest`
  (`document_intelligence: DocumentIntelligenceRequest | None = None`).
- `RegisterSourceService.execute()` stores the parsed block into
  `IngestionRunRecord.metadata["document_intelligence"]` at `_create_run` time — no migration
  needed to carry the *options* through to the worker.
- **New read-only endpoints** (new `api/routes/document_intelligence.py`, mounted like other
  routers):
  - `GET /api/v1/document-intelligence/models` → built-ins + tenant's saved custom models, each
    with its `fields` nested (avoids a second round trip for the frontend's checklist). Gated by
    `Action.DOCUMENT_UPLOAD` (any uploading user needs the list, not just admins).
  - `POST /api/v1/document-intelligence/models` → create a `CUSTOM` model; `model_type` forced
    server-side regardless of client input.
  - `GET /api/v1/documents/{document_id}/extractions` → extraction runs + fields, for a
    document-detail provenance/confidence view.
  - Plugin on/off state reuses the **existing** `GET /api/v1/ops/plugins` once
    `document_intelligence` is added to `catalog.py`'s resolved-registries map — no new endpoint.
- `IngestAcceptedResponse` is unchanged — extraction outcome is not synchronous with accept;
  clients poll existing run-status plus the new extractions endpoint.

## 6. Frontend flow (complete upload interaction)

No existing primitive beyond `Button`/`Input`/`Card`/`Label` is reusable here — confirmed no
Select/Checkbox/multiselect exists anywhere in the frontend yet. New components under
`frontend/src/components/document-intelligence/`, plus two new primitives in
`frontend/src/components/ui/` (`checkbox.tsx`, `select.tsx`, matching the existing minimal
style of `button.tsx`/`input.tsx`):

- `ModelSelector.tsx` — fetches the models endpoint, renders the dropdown (built-ins + saved
  custom models + a synthetic `"custom"` option).
- `FieldChecklist.tsx` — one checkbox row per field of the selected model, defaulting from
  `default_selected`, with Select all / Clear all / Recommended (= reset to defaults) buttons.
- `CustomFieldEditor.tsx` — add/remove rows of `{name, type}` for `model_id === "custom"`, plus
  a "save this schema for reuse" checkbox (checked → `POST .../models` on submit, unchecked →
  fields sent inline as ad-hoc `custom_fields`, mirroring Azure `queryFields`).
- `DocumentIntelligencePanel.tsx` — top-level checkbox (**unchecked by default**, so unchecked =
  today's exact behavior); reveals `ModelSelector` then conditionally `FieldChecklist` or
  `CustomFieldEditor`.

**Wiring into `upload/page.tsx`**: new local state alongside existing `title`/`file` state;
render the panel between the dropzone `Card` and submit `Button`. On submit, if enabled,
`form.append("document_intelligence", JSON.stringify(payload))` — exactly the same `FormData`
pattern already used for `file`/`title`. If disabled, the field is never appended, so the
request is byte-for-byte identical to today's for users who don't opt in.
**Progress display**: extend the existing 1.5s poll with an `extraction_status` summary field,
and once terminal, render `GET /api/v1/documents/{id}/extractions` with color-coded confidence
badges — low-confidence fields are shown, never hidden, per the source document's requirement.
**Classification hook** (future, non-blocking — no classifier exists yet): purely a default-
selection behavior in `ModelSelector`/`FieldChecklist` once one ships; no contract change now.

## 7. Processing flow (integration with the existing ingestion worker)

1. **UPLOAD / STORE ORIGINAL** — unchanged, plus stashing the parsed block into
   `IngestionRunRecord.metadata`.
2. **BASE PARSING** — unchanged; produces `PipelineWorkspace.normalized`.
3. **DOCUMENT INTELLIGENCE PLUGIN → MODEL → FIELD EXTRACTION → VALIDATION → PERSIST** — new
   work, sitting right after `STORE_ELEMENTS` and before `CHUNK` (needs `normalized`; chunk
   metadata can then reference extraction results).
4. **CHUNKING/EMBEDDING → QDRANT → OPTIONAL NEO4J** — unchanged stages, with additive
   touch-points only (chunk `meta` gains deliberately-promoted fields; an optional
   post-`INDEX_GRAPH` step creates configured graph nodes).

**Open decision #2 — in-line stage vs. a separate async worker.** Adding
`IngestionStageName.EXTRACT_DOCUMENT_INTELLIGENCE` as a new enum member (auto-picked-up by
`INGESTION_STAGE_ORDER`, confirmed mechanism above) plus a `STAGE_WEIGHTS` entry and a handler
is mechanically simple and needs **no new queue/worker plumbing**. The cost: this stage may call
a slow/costly LLM or Vision model, synchronously, inside the same task that must reach
`FINALIZE`, holding the (already-noted-as-not-concurrency-safe-across-tasks) `AsyncSession`
longer. A genuinely decoupled design needs a second Redis Stream + consumer group or a separate
worker — real new infrastructure. **Recommendation: ship Phase 1 as an in-line stage**, skipped
entirely (zero calls) when disabled — matching "first implementation can use current
parsers/models" and doubling as the backward-compatibility mechanism (Section 9). Revisit only
if extraction routinely becomes the slowest part of a run — don't build the second-queue
infrastructure speculatively now.

**Extraction strategy chain** (inside `InternalProvider.execute()`, cheapest-first, per field):
structured parser fields already on `NormalizedDocument.elements`/tables → regex/rules over
`source_text` → table-cell lookup → embedding similarity over chunk embeddings → LLM (`ChatModel`,
text) → Vision (multimodal `ChatModel`, only when cheaper tiers found nothing *and* the field is
plausibly image-borne, targeted via `visual_enrichment.py`'s existing per-page/bbox machinery,
capped by the existing `vision_max_pages`).

**RAG integration — what goes where, deliberately, not automatically**:
- *Document-metadata level*: a curated subset of high-confidence scalar fields, per a
  `promote_to_document_metadata: bool` flag on each `ModelFieldSpec` row — not automatic.
- *Chunk-metadata level*: only fields relevant to the specific chunk they came from (e.g. a
  table's values on the chunk containing that table) — added to `chunk.metadata` the same way
  `document_name` is stamped today.
- *Neo4j level*: optional, **configurable** field→entity mappings (e.g. a model's `product_name`
  field creates/matches a `Product` node) stored in `document_intelligence_models.metadata_json`
  for Phase 1 — never automatic entity creation for arbitrary custom fields, only explicitly
  mapped ones.
Large/complex structures stay in `document_extracted_fields.value_json`, referenced by ID —
never duplicated into every Qdrant point.

## 8. Cost-control design

Copy the fingerprinting pattern that already exists on `ingestion_runs`/`ingestion_stages`
rather than inventing a new one.

- **Fingerprint** = `hash(document_hash, plugin_version, model_id, model_version,
  selected_fields, extraction_configuration)`, stored on `document_extraction_runs.fingerprint`.
  `document_hash` reuses `DocumentVersionRecord.content_hash` — already computed at the HASH
  stage, no new hashing infra.
- **Reuse rule**: before calling `execute()`, look up an existing `document_extraction_runs` row
  for `(tenant_id, document_id, version_id, fingerprint)` in a completed state; if found, skip
  extraction entirely and reference the prior run's fields.
- **Incremental field addition**: diff the new request's `selected_fields` against the prior
  run's `selected_fields_json`; invoke the chain only for the delta fields, reuse prior rows for
  the rest — a code-level behavior inside `InternalProvider.execute()` given a
  `previously_extracted` map, not a schema change.
- **Vision cost containment**: reuse `vision_max_pages` and targeted bbox rendering — Vision
  runs per-field, only when cheaper tiers fail and the field is plausibly image-borne.
- **Usage tracking**: log LLM/Vision calls into the existing `model_usage_events` table
  (`capability="document_intelligence"`) — already generalizes across capabilities, no new table.

## 9. Backward compatibility

- Omitted/`enabled: false` → `RegisterSourceRequest.document_intelligence` is `None`,
  `IngestionRunRecord.metadata["document_intelligence"]` absent, the new stage returns
  `SKIPPED` immediately — zero extraction-model calls.
- `extra="forbid"` means old clients that never send the field are completely unaffected.
- Disabling the plugin empties `GET /api/v1/document-intelligence/models`, which makes the
  frontend hide the checkbox entirely; an in-flight request while disabled is rejected with a
  clear validation error, not silently ignored.
- Previously-extracted data stays available via `GET /api/v1/documents/{id}/extractions`
  regardless of current plugin state — a separate read path off historical rows.
- No existing columns change type/nullability; no existing enum values removed; the new stage
  enum member is additive (stored as a plain string, not a DB enum type).
- Frontend: the whole panel is additive UI behind one unchecked-by-default checkbox; the
  existing drop → title → submit → poll flow is byte-identical when it stays unchecked.

## 10. Implementation phases (independently testable increments)

1. **Schema + registry skeleton, no extraction logic.** Migration `0008_document_intelligence.py`
   (all 5 tables); `application/plugins/document_intelligence.py` wired into `catalog.py`/
   `GET /api/v1/ops/plugins`; `DocumentIntelligenceSettings` added. Tests: enabled/disabled,
   catalog listing, migration up/down.
2. **Model + field catalog, read-only API.** Built-in models seeded, `GET`/`POST
   /document-intelligence/models`. Tests: listing, field defaults, custom model creation.
3. **Ingest contract extension, no-op extraction stage.** Form field wired through to
   `IngestionRunRecord.metadata`; new stage added as an always-skip stub. Tests: upload with/
   without the block behave identically where expected; stage shows as `skipped`.
4. **`InternalProvider` cheap tiers only** (structured/regex/table/embedding, no LLM/Vision).
   Tests: extraction success, partial extraction, low-confidence surfaced not hidden.
5. **LLM + Vision tiers**, with targeting and caps. Tests: fallback correctness, provider
   failure handling (chain continues, doesn't fail the whole run), cost logged.
6. **Cost control** (fingerprint reuse, incremental field addition). Tests: unchanged
   fingerprint makes zero calls; adding one field only extracts that field.
7. **Custom/ad-hoc models end-to-end.** Tests: custom model round-trip, ad-hoc fields with no
   `model_id`.
8. **Frontend upload flow.** New `Checkbox`/`Select` primitives, panel components, wiring,
   confidence-badge results view. Tests: selection-state behavior; unchecked path submits a
   byte-identical `FormData` to today.
9. **RAG/graph integration** (configured field promotion, configured Neo4j mappings). Tests:
   promoted fields appear in Qdrant metadata only when configured; graph nodes only for mapped
   fields.
10. **(Deferred, optional) Classification-assisted recommendation** — only once a classifier
    exists; purely additive default-selection UI behavior, no contract change beyond an
    optional recommendation hint.

## Verification

Each phase above lists its own test increments — run the full suite plus
`make format-check lint typecheck unit evaluation compose-config` (or `make acceptance`) from
the repo root after each phase, matching this codebase's existing gate. Phase 3's backward-
compatibility test (existing uploads unaffected) and Phase 8's byte-identical-`FormData` test
are the two highest-value regression guards given how additive this feature is meant to be —
don't skip them even under time pressure.

## Critical files

- `backend/src/graph_rag/application/plugins/registry.py`, `parsers.py` (pattern to replicate)
- `backend/src/graph_rag/application/ingestion/stage_pipeline.py`,
  `domain/ingestion/stages.py` (stage insertion point)
- `backend/src/graph_rag/application/ingestion/register_source.py`,
  `domain/ingestion/records.py` (request/metadata plumbing)
- `backend/src/graph_rag/infrastructure/persistence/postgres/models/ingestion.py`,
  `usage.py` (schema/fingerprint/cost conventions to copy)
- `backend/src/graph_rag/api/routes/documents.py` (ingest endpoint)
- `frontend/src/app/upload/page.tsx` (upload flow to extend)
