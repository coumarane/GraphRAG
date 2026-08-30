# Plugin/Extension Architecture — Proposal

**Status: partially landed.** Phase 0 (registry scaffolding) and Phase 1 (parser
plugins) are in tree, plus admin introspection (`GET /ops/plugins`,
`graph-rag plugins list`) and an MCP tool server (`/api/v1/mcp/`). The Pipeline
Builder (config composer) covers GitOps-safe chunking/retrieval edits. Later
phases (storage/LLM registries, resilience, conformance) remain open.

### OpenRAG mapping (do not re-litigate)

OpenRAG embeds **Langflow** for the visual node canvas (Agent + OpenSearch + MCP
Tools + “Discover more components”). GraphRAG does **not** vendor that canvas.
GraphRAG equivalents:

| OpenRAG / Langflow | GraphRAG |
|---|---|
| Component inventory / trust | `/plugins` + `GET /ops/plugins` |
| Discover more components | Discover section + `install_hint` / `discoverable` on the catalog |
| Agent tools | MCP server (`docs/mcp-server.md`) + admin MCP card on `/plugins` |
| Flow/settings knobs | Pipeline Builder (`/pipeline-builder`, config composer diffs) |

Do not embed Langflow or copy `lfx` custom components unless that decision is
made separately as a large infra commitment.

## For an agent resuming this work

- **Re-verify every file/line claim below against the current codebase before touching code.**
  This document is a snapshot; the referenced files will have moved on since it was written
  (new commits, possibly renamed modules). Read the actual current content of each file named
  below before relying on it.
- **Follow the phase order.** Do not start Phase *N+1* until Phase *N*'s "Done when" criteria
  are met, committed, and CI is green on `dev`.
- **Preserve the two hard constraints** in every phase (see below) — they are backward-compatibility
  guarantees for a live, deployed system, not preferences.
- Run the repo's existing quality gates before considering any phase complete:
  `make format-check lint typecheck unit evaluation compose-config` (or `make acceptance`),
  from the **repo root** (that is where `Makefile` lives; not `backend/`).
- If, on re-reading, any claim here turns out to be stale or wrong, fix your understanding from
  the live code — don't implement against an assumption this document made that no longer holds.

---

## Context

The backend already has clean hexagonal boundaries — `domain/*/protocols.py` define `Protocol`
interfaces (`ObjectStore`, `GraphStore`, `ChunkVectorStore`, repositories, `ChatModel`/
`EmbeddingModel`/`Reranker`, `MultimodalDocumentParser`) and `domain/models/protocols.py` even
documents the rule explicitly: *"Domain and application code must not import provider SDKs."*
The problem isn't the ports — it's that **selecting which adapter implements a port is
hardcoded**, in three different ways, in three different places:

1. **Storage/queue backends** — `application/runtime/runtime.py::build_runtime_container()`
   (~200 lines) does env-var string `if/elif` chains for `OBJECT_STORE_BACKEND`,
   `VECTOR_STORE_BACKEND`, `GRAPH_STORE_BACKEND`, `METADATA_STORE_BACKEND`, plus a separate
   `_wire_ingest_queue()` for `INGEST_QUEUE_BACKEND`. Adding a backend means editing this file.
   These env vars **bypass `Settings` entirely** (confirmed: none appear in
   `config/settings.py`) — an existing inconsistency, since backend *choice* lives outside
   `Settings` while backend *credentials* (`resolved.minio`, `resolved.qdrant`, ...) live inside it.
2. **Parsers** — `infrastructure/parsers/registry.py::ParserRegistry.__init__` hardcodes a
   fixed dict of 6 parsers; `domain/parsing/types.py::ParserName` is a closed `StrEnum`;
   `domain/parsing/routing.py::DEFAULT_ROUTE_PROFILES` hardcodes fallback chains. Adding a
   parser touches all three.
3. **LLM providers** — `application/runtime/local.py::_resolve_models()` isn't even an
   if/elif — it's a binary OpenAI-or-`Fake*` choice. The live chat path is
   `infrastructure/models/openai_direct/` only; `langchain_openai/` is embeddings-only.
   `domain/billing/openai_pricing.py` is an OpenAI-only cost table (see Phase 3 — usage
   already degrades to null-cost for unknown models).

None of this is throwaway code — it's disciplined, well-tested (ports-and-adapters, DI via a
plain `ServiceContainer` dataclass, a clean FastAPI `Depends` seam via `ContainerDep`/
`TenantDep`). The goal is to formalize the existing ports as a real **plugin contract**,
replace the three ad-hoc selection mechanisms with one **`importlib.metadata`
entry-point-based registry**, and do it staged so the live Kubernetes deployment
(ArgoCD/Harbor, digest-pinned images, CI triggered on `backend/src/**`) never breaks
mid-migration.

### Hard constraint #1 — env-var backward compatibility

Confirmed against the actual k8s manifests: `infra/k8s/api/secretproviderclass.yaml` injects
`OBJECT_STORE_BACKEND`/`VECTOR_STORE_BACKEND`/`GRAPH_STORE_BACKEND`/`METADATA_STORE_BACKEND`
as literal secret-store `objectAlias` names; `infra/k8s/worker/deployment.yaml` writes
`INGEST_QUEUE_BACKEND=redis` into a generated `.env`. **These exact env-var names and string
values (`memory`, `minio`, `azure_blob`, `qdrant`, `neo4j`, `postgres`, `redis`) must keep
working identically** — this is a backward-compatibility requirement, not a style choice.

### Hard constraint #2 — test-injection ergonomics

Confirmed in tests: `application/runtime/local.py::build_local_container(**kwargs)` (~19
keyword-only params, all `None`-defaulted, `x or InMemoryX()` fallback pattern) must stay
callable with **zero args, zero I/O, zero plugin discovery** —
`tests/unit/test_runtime_object_store.py` and the rest of the unit suite depend on this.

**Discovery vs injection (resolved):** `importlib.metadata` discovery and
`PluginRegistry.resolve()` run **only** in `build_runtime_container()`. They must never
run inside `build_local_container()`. It is allowed — and required — for
`build_runtime_container()` to **pass already-built plugin instances in as kwargs**
(the same pattern it already uses for `object_store` / `vector_store` / `graph_store`).
Adding new optional kwargs to `build_local_container` (`parser_registry`, `chunk_store`,
`lexical_store`, …) with in-memory defaults is injection, not discovery, and does **not**
violate this constraint. `git diff --stat` showing a `local.py` kwargs addition is expected
when a new injectable slot is introduced; `git diff` showing `entry_points(` or a registry
lookup inside `local.py` is a constraint violation.

---

## Recommended Architecture

### 1. Plugin contract layer — stay in-tree, don't extract an SDK yet

Formalize `domain/*/protocols.py` as the plugin API **by policy, not by relocation**: extend
the "no provider SDK imports" docstring convention (already in `domain/models/protocols.py`)
to `domain/storage/`, `domain/ingestion/`, `domain/parsing/protocols.py`, and adopt a semver
rule scoped to those modules (additive = minor, signature change = major). Document it in
`docs/plugin-api-versioning.md` once Phase 0 lands.

Do **not** split into a separate `graph-rag-sdk` distribution now — that forces a
dependency-graph decision (which domain types like `TenantContext`/`ParseOptions` move with
the protocols) before there's a real external consumer to validate the boundary against.
Revisit only once ≥2 real third-party plugins exist.

### 2. Discovery mechanism — `PluginRegistry` per capability

New package `application/plugins/`:

- `registry.py` — generic `PluginRegistry[T]`, one instance per capability.
- `discovery.py` — `importlib.metadata.entry_points(group=...)` wrapper, cached.
- `descriptors.py` — the factory contract.

**Entry-point groups**, namespaced `graph_rag.*` (mirrors `sqlalchemy.dialects`/`pytest11`/
`fsspec.specs` conventions): `graph_rag.object_store`, `.vector_store`, `.graph_store`,
`.metadata_store`, `.ingest_queue`, `.parser`, `.chat_model`, `.embedding_model`, `.reranker`,
`.cli_plugins`, `.api_routers`. The entry-point **name** within a group is the existing
backend identifier (`minio`, `qdrant`, `docling`, ...) — this is what makes it backward
compatible.

**Factory contract**: each entry point resolves to a small factory object (not the adapter
class directly), exposing `plugin_name`, `capability`, `trust_tier: Literal["core","verified", "community"]`, `build(settings: Settings) -> <ProtocolType>`, optional
`config_model: type[BaseModel]` (validates a namespaced config dict, doubles as introspection
schema), optional `async def healthcheck(instance) -> bool`. Same pattern OpenTelemetry
exporters / Airflow providers use — it gives a place to hang metadata without touching adapter
classes.

**Resolution**: core factories (hardcoded dict literal per capability, not real entry
points — no benefit to routing your own in-tree adapters through packaging metadata) merge
with discovered entry points; **core names cannot be shadowed unless
`allow_core_override=True` (default `False`)** — a same-named third-party entry point silently
hijacking `minio`/`memory` is a real supply-chain risk, not a formality. Add a CI test
asserting this rejection.

Add `@runtime_checkable` to the domain Protocols (cheap, gives a shallow load-time check that
a plugin's `build()` return value has the right methods — not a substitute for the conformance
suite in §7, but a low-cost early warning).

### 3. Settings integration

Add `PluginsSettings` to `config/settings.py`, structured like the existing 16 sub-models:

```
PluginsSettings
├── enabled: bool = True
├── allow_core_override: bool = False
├── allowlist: list[str] | None = None   # None = allow all discovered (dev only); [] = core-only (prod default)
├── object_store / vector_store / graph_store / metadata_store / ingest_queue: BackendSelection
└── config: dict[str, dict[str, Any]] = {}   # namespaced passthrough for third-party plugin config
```

`_apply_flat_store_env` (already handles Postgres/MinIO/etc. the same way) gains one more
block reading `OBJECT_STORE_BACKEND` etc. into `plugins.object_store.backend` — **env var
names unchanged**, so the k8s secret provider class needs zero edits. `runtime.py:: object_store_backend()` becomes a one-line shim (`get_settings().plugins.object_store.backend`)
kept only because `cli/main.py` still imports it by name. The `if/elif` body in
`build_runtime_container` collapses to
`object_store_registry.resolve(resolved.plugins.object_store.backend).build(resolved)` — same
`ValueError`-shaped failure on an unknown name, now listing the dynamic registry contents
instead of a hardcoded 3-item set.

---

## Phased Rollout

**Phase 0 — Registry scaffolding (no behavior change).** New
`application/plugins/{registry,discovery,descriptors}.py`; `PluginsSettings` added to
`config/settings.py`; empty `[project.entry-points]` tables added to `pyproject.toml` as
documentation. Does not touch `runtime.py`/`local.py`/`ParserRegistry`. **Done when**: registry
is unit-tested against a fake capability group, `Settings.plugins` round-trips through YAML+env
like the other sub-models, full existing test suite passes unchanged.

**Phase 1 — Parsers (do first: lowest blast radius).** This phase *does* edit
`registry.py` / `types.py` / `routing.py` (and the ingest pipelines below). The
"zero core-file edits" bar applies **after** Phase 1 lands, to a *7th* parser.

- `ParserRegistry.__init__`'s 6 parsers become core factory entries (hardcoded dict in
  `application/plugins/`, not packaging metadata). Empty-registry construction remains
  valid for tests that inject their own dict.
- `ParserName` loosens from a closed gate to an open string key (enum kept as a convenience
  alias for the six built-ins). `auto` stays a host sentinel.
- `DEFAULT_ROUTE_PROFILES` becomes registry-aware: an unregistered name in an *enabled*
  YAML/default profile → `ConfigurationError` at **runtime-container startup**, not a
  `KeyError` mid-ingestion. Disabled / not-installed parsers in a fallback chain are
  skipped with a warning (so optional extras like MinerU do not fail boot).
- **Parser injection (resolved):** today
  `application/ingestion/local_pipeline.py` constructs `ParseDocumentService()` with no
  args, which builds the hardcoded six-parser registry and **ignores anything
  `build_runtime_container()` discovered**. Phase 1 must:
  1. Discover/build the parser registry in `build_runtime_container()` only.
  2. Pass it into `build_local_container(parser_registry=...)`.
  3. Hang it on `ServiceContainer` and have `ProcessRegisteredDocumentService` /
     `ParseDocumentService` use that instance. `ParseDocumentService()` with no args
     remains the unit-test default (six core factories, no entry-point scan).
- **Also stop treating these as closed vocabularies** (a 7th parser must not require
  edits here after Phase 1): `infrastructure/parsers/availability.py`
  (`_MODULE_BY_PARSER` / `_EXTRA_BY_PARSER`), `application/ingestion/local_pipeline.py`
  (`_STRUCTURED_PARSERS`, `ParserName.DOCLING` / `PDFIUM` branches), and
  `application/ingestion/stage_pipeline.py` (same). Availability and "structured vs
  fallback" flags move onto the parser factory descriptor (`requires.modules`,
  `provides.parser.structured: bool`).
- **Inspector slot (resolved — keep compatible behavior):** do **not** fail loud when
  Docling is missing. `ParseDocumentService.inspect()` today does
  `get(ParserName.DOCLING)` and, on `ParserError`, silently uses `PdfiumInspector()`.
  Make that an explicit overridable slot whose **default is `pdfium`** (always bundled).
  If Docling is registered, prefer its `inspect()` when the caller has not set
  `plugins.config.parser.inspector`. A *configured* inspector name that is not
  registered is a loud `ConfigurationError` at startup. A missing Docling extra with
  the default slot must keep working (Pdfium inspect), so existing six-parser behavior
  stays identical.

**Done when**: a 7th parser installs via a `graph_rag.parser` entry point + a new profile
in `config/*.yaml` with **no further edits** to `registry.py` / `types.py` / `routing.py`
/ `availability.py` / `local_pipeline.py` / `stage_pipeline.py`; worker ingest actually
uses that parser (not only a unit test against a hand-built `ParserRegistry`); existing
6 parsers behave identically including Pdfium inspect fallback; CI green.

**Phase 2 — Storage/queue backends, one group at a time**, in order: `object_store` →
`vector_store` → `graph_store` → `metadata_store` → `ingest_queue`. Each is independently
shippable since they're already separate `if/elif` blocks on separate env vars.

- `object_store` and `graph_store` are clean 1:1 "factory returns one instance" swaps.
- **`vector_store` is a bundle, not a 1:1 swap (resolved).**
  `build_local_container()` currently does `isinstance(vectors, QdrantChunkVectorStore)`
  to wire `QdrantChunkLookupStore` + `QdrantHydratingLexicalStore`. A third-party
  `ChunkVectorStore` that only returns the vector protocol will search and then fail
  hydration. The `graph_rag.vector_store` factory therefore returns a
  `VectorStoreBundle` dataclass: `vectors: ChunkVectorStore`, `chunks: ChunkLookupStore`,
  `lexical: LexicalSearchStore`. Core `qdrant` and `memory` factories fill all three.
  `build_runtime_container()` passes them as kwargs into `build_local_container`
  (`vector_store=`, plus new `chunk_store=` / `lexical_store=`). The `isinstance(Qdrant…)`
  branch is then deleted. That `local.py` kwargs change is **in scope for the
  `vector_store` sub-step** and does not count as putting discovery inside `local.py`.
- `metadata_store` (Postgres) is the other bundle: the branch also builds a shared
  `AsyncSession`, an `asyncio.Lock`, and 8 repositories wrapped in `LockedAsyncProxy`,
  plus wires `on_commit`/`ready_checks` as side effects. **Resolved: use a typed
  `MetadataStoreBundle` dataclass** for consistency with `VectorStoreBundle`. Do not
  leave it as a permanent special-cased non-registry path.
- `ingest_queue` reuses the already-isolated `_wire_ingest_queue()` — lowest risk of the
  remaining two since it receives `raw_session`/`db_lock` as already-built params rather than
  owning that machinery.

**Done when** (per sub-step): the env var resolves through `PluginRegistry`; existing
`tests/unit/test_runtime_object_store.py`-style tests (`monkeypatch.setenv` +
`build_runtime_container(Settings())`) pass unchanged; `local.py` contains **no**
`entry_points(` / registry lookup (kwargs additions are OK; verify with `git diff`);
`infrastructure/workers/main.py::run_worker()` needs no changes (it only calls
`build_runtime_container(settings)` — confirmed already centralized correctly).

**Phase 3 — LLM providers (do last: greenfield, most entangled).** `_resolve_models()`'s binary
OpenAI-or-Fake becomes a real `chat_model`/`embedding_model`/`reranker` registry lookup — but
the zero-config `Fake*` fallback for `use_live_models=False` must remain the untouched default
(tests depend on it). New core factories wrap `infrastructure/models/openai_direct/` and
`infrastructure/models/langchain_openai/`.

**Billing is a smaller gap than it first looks — re-verified against the actual code.**
`domain/usage/models.py::UsageEvent` already carries a free-text `provider: str` field
alongside `model_name`, and `known_pricing: bool` already exists precisely for the "cost
unknown" case. `application/usage/record.py::build_usage_event()` already accepts an arbitrary
`provider` and calls `estimate_usd(model_name, ..., table=pricing)`, which already returns
`(Decimal("0"), known=False)` for any model name not in the table — **a non-OpenAI provider
plugin recording usage today already degrades gracefully to null-cost, no crash, no schema
change needed.** The only real gap is that `domain/billing/openai_pricing.py`'s default table
only has OpenAI rows, and `load_openai_pricing()` reads `config/openai_pricing.yaml` by a fixed
path — so the table itself isn't yet plugin-discoverable. Phase 3's actual billing work is
narrower than "resolve vendor lock": either (a) let a pricing plugin contribute additional
`(model_name → rate)` rows into the loaded table (simplest, no new protocol), or (b) introduce
a `PricingProvider` protocol keyed by `provider` for providers whose pricing depends on more
than just `model_name` (e.g. per-region rates). Start with (a); only build (b) if a provider
actually needs it. Last overall because it's still the most new registry code (no existing
if/elif to generalize from) and touches usage/billing in ways storage/parsers don't.

**Phase 4 — CLI/API extension points** (can run in parallel with 2/3, but sequencing after
Phase 1 means at least one proven registry pattern exists first).

- CLI: don't restructure the flat `typer.Typer()` — add one new
  `plugin_app = typer.Typer(name="plugins")` (`app.add_typer(plugin_app)`) for
  plugin-contributed commands and the introspection command below. Third-party CLI extensions
  register via `graph_rag.cli_plugins` entry points (each resolving to a `typer.Typer`),
  discovered and `add_typer`'d at startup, gated by `PluginsSettings.enabled`. Existing
  commands/`get_container()`/`set_container()` globals untouched.
- API: the existing `ContainerDep`/`TenantDep` seam in `api/dependencies/__init__.py` is
  already sufficient — a plugin router just types its params with those and gets full DI. Keep
  every existing static `include_router()` call in `api/app.py::create_app()` exactly as-is;
  add a discovery loop after them for `graph_rag.api_routers` entry points. **Validate
  discovered router prefixes against the reserved built-in prefix list at startup and refuse
  (loud failure) on collision** — same no-silent-shadowing principle as core-override in §2.

**Phase 5 — Enterprise hardening** (introduce incrementally per capability group as each Phase
1-3 group lands, not as one big-bang pass):

- **Trust tiers**: `core` (always trusted) / `verified` (third-party, explicitly listed in
  `allowlist`) / `community` (discovered but inert unless `allowlist is None`). Recommend
  `allowlist: None` only in dev/test; `staging`/`production` default to allowlist-required
  (empty = core-only), via `config/production.yaml` the same way other environment hardening
  already layers today.
- **Per-adapter resilience**: no circuit-breaker/timeout module exists anywhere in `graph_rag`
  today (only ingestion-stage retry in `domain/ingestion/retry.py`) — this is genuinely new
  infra, not a refactor. New `application/plugins/resilience.py`: a delegating proxy wrapping
  every method call with `asyncio.wait_for(timeout=...)` + a simple failure-counting circuit
  breaker. Apply by default to `verified`/`community` tier plugins only — don't conflate
  "harden plugins" with "harden existing core adapters" (that's a separate, larger reliability
  workstream).
- **Observability tagging**: two concrete, already-existing hooks to extend rather than a new
  mechanism to invent. (1) `application/usage/context.py::UsageContext` (a `ContextVar` bound
  per-request in `api/dependencies/__init__.py::_bind_usage_context` and per-task in
  ingestion/retrieval code via the `usage_context()` context manager) already flows into every
  `UsageEvent`. `UsageEvent` is `extra="forbid"` and has **no** `plugin_name` / `trust_tier`
  today — adding them only on `UsageContext` does not persist them. Phase 5 must: add the
  fields to `UsageContext`, copy them in `build_usage_event()`, add them to `UsageEvent`,
  and migrate the Postgres usage table. (2) `structlog.contextvars`, bound by
  `ObservabilityMiddleware` per-request — bind `plugin_name`/`capability`/`trust_tier` here too
  so it shows up in every log line emitted while a plugin-resolved adapter is in use, not just
  usage events. `ParserSelection`'s existing `attempted_parsers`/`warnings` fields are the right
  pattern to replicate for storage plugin provenance in ingestion-run records (usage/log context
  doesn't naturally cover non-LLM storage calls the way it covers metered model calls).
- **Admin introspection**: `graph-rag plugins list` (under the new `plugin_app`) and
  `GET /ops/plugins` added to the **existing** `api/routes/ops.py` (same shape as its
  `dashboard()`/`usage_dashboard()`). Gate both through the **existing** RBAC seam —
  `application/authorization/gate.py::require_action` with a new `Action.ADMIN_PLUGINS` member
  added to `domain/authorization/models.py::Action` (confirmed pattern: sits alongside
  `ADMIN_USERS`/`ADMIN_POLICIES`/`ADMIN_QUOTAS`/`ADMIN_TENANT`, value `"admin.plugins"`). Do
  not invent a parallel authz path.
  **Landed:** catalog includes `install_hint` + `discoverable`; `GET /ops/mcp` exposes tool
  list and connect hints for the admin Plugins page.

**Phase 6 — Conformance testing**, started as soon as Phase 1 is stable (cheapest — no network
mocking for `text`/`pdfium`), extended per capability as Phases 2-3 land. New
`graph_rag.testing.contracts` package: one abstract pytest base class per protocol
(`ObjectStoreContractTests`, `ChunkVectorStoreContractTests`, `GraphStoreContractTests`,
`MultimodalDocumentParserContractTests`, `ChatModelContractTests`), each testing the protocol's
documented pre/post-conditions (e.g. `ObjectStore`: tenant-prefix isolation, `delete_prefix`
count, `presign_get` rejecting foreign-tenant keys). Retrofit the built-in adapters as the
first subclasses — no shared abstract base exists across adapter families today, so this also
closes an existing regression-coverage gap, not just a future-plugin gate. Same mechanism as
SQLAlchemy's dialect test suite / fsspec's `AbstractFileSystem` conformance tests.

---

## Resolved decisions (do not re-open during implementation)

1. **Parser injection** — discovery only in `build_runtime_container()`; pass
   `parser_registry=` into `build_local_container` / `ServiceContainer`; ingest must not
   call `ParseDocumentService()` with no args on the worker path. See Hard constraint #2
   and Phase 1.
2. **Inspector default** — slot default is `pdfium` (compatible with today's silent
   fallback). Prefer Docling inspect when that parser is registered. Loud failure only
   when a *configured* inspector name is missing. Do not change default inspect to
   fail-loud when Docling is absent.
3. **Vector store shape** — `VectorStoreBundle` (`vectors` + `chunks` + `lexical`), not
   a single `ChunkVectorStore`. Delete the `isinstance(QdrantChunkVectorStore)` branch
   once kwargs exist. `local.py` kwargs additions are allowed; discovery inside
   `local.py` is not.
4. **Metadata store shape** — `MetadataStoreBundle` dataclass (same pattern as vector).
5. **Billing** — Phase 3 starts by letting a pricing plugin contribute
   `(model_name → rate)` rows to the loaded table. Do not build a `PricingProvider`
   protocol unless a vendor's pricing is not a flat per-model-name rate. Null-cost for
   unknown models already works.
6. **Usage provenance** — `plugin_name` / `trust_tier` must land on `UsageContext`,
   `UsageEvent`, `build_usage_event()`, and the Postgres usage table. Context-only is
   not enough.

## Open decisions (resolve before the named phase ships)

1. **Deployment topology for installed plugins** (before Phase 2): does "install a
   plugin" mean rebuilding the worker-base image (edits to `Dockerfile.worker-base` +
   the `build-and-push-*-image.yml` workflows, slow ArgoCD cycle) or a runtime pip
   install from a private index (faster, but breaks the current digest-pinned-image
   immutability model)? This changes what "third-party plugin" operationally means.
2. **Entry-point discovery cost** (before Phase 0): `importlib.metadata.entry_points()`
   scans all installed distributions' metadata at process start; benchmark against
   current API/worker cold-start times (mitigated by `lru_cache`, but worth measuring
   given the worker-base image already bundles several heavy parser extras).

---

## Verification Per Phase

- **Phase 0**: new unit tests for `PluginRegistry` against a fake capability; full existing
  `pytest tests/unit` suite green (proves zero behavior change); `Settings.plugins` round-trip
  test (YAML + env override, mirroring existing `PostgresSettings`/`MinioSettings` tests).
- **Phase 1**: existing parser tests (`tests/unit/test_parser_normalize.py`,
  `test_parser_routing.py`, `test_parser_registry_fallback.py`) green unchanged; new test
  registering a fake 7th parser via a stub entry point **and** a `build_runtime_container`
  path that injects it into ingest (not only a hand-built `ParserRegistry`); confirm
  `inspect()` defaults to Pdfium when Docling is unregistered, prefers Docling when
  registered, and raises `ConfigurationError` at startup only if
  `plugins.config.parser.inspector` names a missing plugin.
- **Phase 2**: per sub-step, `tests/unit/test_runtime_object_store.py`-style tests
  (`monkeypatch.setenv` + `build_runtime_container(Settings())`) pass unchanged;
  `local.py` has no discovery calls (kwargs for bundles OK); vector-store sub-step
  proves a non-Qdrant stub bundle still hydrates chunks via its own `ChunkLookupStore`;
  a local `docker compose up -d --wait` smoke run (`Makefile`'s existing `up` target,
  repo root) against real MinIO/Qdrant/Neo4j/Postgres containers still ingests + queries
  a sample doc (`uv run graph-rag ingest ../data/examples/sample.pdf ...` /
  `graph-rag query ...`, same commands already documented in the README).
- **Phase 3**: `_resolve_models()` zero-arg/`use_live_models=False` path still returns `Fake*`
  with no network calls (existing tests should catch a regression here immediately); manual
  smoke test with a real `OPENAI_API_KEY` confirming the OpenAI plugin path still answers a
  query end-to-end.
- **Phase 4**: a stub plugin package (used for Phase 6's conformance suite too) registering one
  CLI command and one API router, confirming both appear (`graph-rag plugins list`, and a
  request to the plugin's route) without editing `cli/main.py`/`api/app.py`; a
  colliding-prefix stub confirming the reserved-prefix check refuses to mount.
- **Phase 5**: CI test asserting a same-named discovered entry point cannot override a core
  plugin unless `allow_core_override=True`; a deliberately slow/failing stub plugin confirming
  the circuit breaker opens and the request fails fast rather than hanging.
- **Phase 6**: run the new contract-test suite against every existing built-in adapter (parsers
  first, then storage) — this should pass on day one since built-ins already satisfy their own
  protocols; any failure here indicates the contract test itself needs correction, not the
  adapter.

Throughout every phase: CI must stay green
(`build-and-push-{api,worker,worker-base}-image.yml`, `run-database-migrations.yml` all trigger
on `backend/src/**`/`pyproject.toml`/`uv.lock` changes — expect each phase's merge to rebuild
and redeploy to `dev` automatically).
