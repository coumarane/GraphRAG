# Plugin/Extension Architecture — Proposal

**Status: proposed, not started.** No code from this document has been written yet. This is
a design + phased rollout plan for turning the backend into an enterprise-grade plugin
platform (pluggable storage backends, parsers, and LLM providers), produced from a full-repo
architecture review. It is meant to be picked up and executed later — by a human or by a
Claude Code agent — once the decision is made to proceed.

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
  from `backend/`.
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
   if/elif — it's a binary OpenAI-or-`Fake*` choice. Only `infrastructure/models/openai_direct/`
   exists as a real adapter. `domain/billing/openai_pricing.py` is an OpenAI-only cost table
   (vendor lock-in in billing too).

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
`tests/unit/test_runtime_object_store.py` and the rest of the unit suite depend on this. The
plugin registry sits only in front of `build_runtime_container()`, never inside
`build_local_container()`.

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
class directly), exposing `plugin_name`, `capability`, `trust_tier: Literal["core","verified",
"community"]`, `build(settings: Settings) -> <ProtocolType>`, optional
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
names unchanged**, so the k8s secret provider class needs zero edits. `runtime.py::
object_store_backend()` becomes a one-line shim (`get_settings().plugins.object_store.backend`)
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

**Phase 1 — Parsers (do first: lowest blast radius).** `ParserRegistry.__init__`'s 6 parsers
become core factory entries; `ParserName` loosens from a closed gate to an open string key
(enum kept as a convenience alias); `DEFAULT_ROUTE_PROFILES` becomes registry-aware
(unregistered parser in a profile → `ConfigurationError` at startup, not a `KeyError`
mid-ingestion). **Must also fix**: `ParseDocumentService.inspect()`
(`infrastructure/parsers/registry.py`) currently hardcodes
`self._registry.get(ParserName.DOCLING)` for its inspection step, independent of the
routing/fallback chain — this is a second hidden coupling to a specific built-in name that
Phase 1 needs to make an explicit, overridable registry slot rather than leaving it masked.
**Done when**: a 7th parser installs via a `graph_rag.parser` entry point + a new profile in
`config/*.yaml` with zero edits to `registry.py`/`types.py`/`routing.py`; existing 6 parsers
behave identically; CI green.

**Phase 2 — Storage/queue backends, one group at a time**, in order: `object_store` →
`vector_store` → `graph_store` → `metadata_store` → `ingest_queue`. Each is independently
shippable since they're already separate `if/elif` blocks on separate env vars.

- `object_store`/`vector_store`/`graph_store` are clean 1:1 "factory returns one instance" swaps.
- `metadata_store` (Postgres) is the hard one: the branch also builds a shared `AsyncSession`,
  an `asyncio.Lock`, and 8 repositories wrapped in `LockedAsyncProxy`, plus wires
  `on_commit`/`ready_checks` as side effects — it doesn't fit the one-factory-one-instance
  shape. **Decide explicitly** (don't let this slide): either model it as a factory returning a
  typed `MetadataStoreBundle` dataclass (recommended, for consistency with the other four), or
  keep it a permanently special-cased non-registry path and document why.
- `ingest_queue` reuses the already-isolated `_wire_ingest_queue()` — lowest risk of the
  remaining two since it receives `raw_session`/`db_lock` as already-built params rather than
  owning that machinery.

**Done when** (per sub-step): the env var resolves through `PluginRegistry`; existing
`monkeypatch.setenv(...)` + `build_runtime_container(Settings())` tests pass unchanged;
**`local.py` is never touched by any diff in this phase** (verify via `git diff --stat` showing
no `local.py` line); `infrastructure/workers/main.py::run_worker()` needs no changes (it only
calls `build_runtime_container(settings)` — confirmed already centralized correctly, a good
precedent).

**Phase 3 — LLM providers (do last: greenfield, most entangled).** `_resolve_models()`'s binary
OpenAI-or-Fake becomes a real `chat_model`/`embedding_model`/`reranker` registry lookup — but
the zero-config `Fake*` fallback for `use_live_models=False` must remain the untouched default
(tests depend on it). New core factories wrap `infrastructure/models/openai_direct/` and
`infrastructure/models/langchain_openai/`. **`domain/billing/openai_pricing.py` needs an
explicit decision**, not a silent defer: either generalize to a `PricingProvider` protocol per
provider, or explicitly document non-OpenAI providers as reporting null cost in
`api/routes/ops.py::usage_dashboard`. Last because it's the most new code (no existing if/elif
to generalize from) and entangled with billing/usage in ways storage/parsers aren't.

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
- **Observability tagging**: extend `ObservabilityMiddleware` with `plugin_name`/`capability`/
  `trust_tier` labels. `ParserSelection`'s existing `attempted_parsers`/`warnings` fields are
  the right pattern to replicate for storage/LLM plugin provenance in ingestion-run/
  query-response records.
- **Admin introspection**: `graph-rag plugins list` (under the new `plugin_app`) and
  `GET /ops/plugins` added to the **existing** `api/routes/ops.py` (same shape as its
  `dashboard()`/`usage_dashboard()`). Gate both through the **existing** RBAC seam —
  `application/authorization/gate.py::require_action` with a new `Action.ADMIN_PLUGINS` member
  added to `domain/authorization/models.py::Action` (confirmed pattern: sits alongside
  `ADMIN_USERS`/`ADMIN_POLICIES`/`ADMIN_QUOTAS`/`ADMIN_TENANT`, value `"admin.plugins"`). Do
  not invent a parallel authz path.

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

## Open Decisions to Make Explicitly (don't let these slide silently)

1. **Metadata-store bundle shape** (Phase 2, item 4) — bundle dataclass vs. permanent special case.
2. **Billing vendor-lock** (Phase 3) — generalize pricing or document OpenAI-only + null-cost fallback.
3. **`ParseDocumentService.inspect()`'s hardcoded `docling` dependency** (Phase 1) — must become
   an overridable named slot, not silently rely on `docling` always being installed.
4. **Deployment topology for installed plugins**: does "install a plugin" mean rebuilding the
   worker-base image (edits to `Dockerfile.worker-base` + the `build-and-push-*-image.yml`
   workflows, slow ArgoCD cycle) or a runtime pip install from a private index (faster, but
   breaks the current digest-pinned-image immutability model)? Resolve this before Phase 2
   ships, since it changes what "third-party plugin" operationally means for this specific
   deployment.
5. **Entry-point discovery cost** — `importlib.metadata.entry_points()` scans all installed
   distributions' metadata at process start; benchmark against current API/worker cold-start
   times before Phase 0 ships (mitigated by `lru_cache`, but worth measuring given the
   worker-base image already bundles several heavy parser extras).

---

## Verification Per Phase

- **Phase 0**: new unit tests for `PluginRegistry` against a fake capability; full existing
  `pytest tests/unit` suite green (proves zero behavior change); `Settings.plugins` round-trip
  test (YAML + env override, mirroring existing `PostgresSettings`/`MinioSettings` tests).
- **Phase 1**: existing parser tests (`tests/unit/test_parser_normalize.py`,
  `test_parser_routing.py`) green unchanged; new test registering a fake 7th parser via a stub
  entry point and confirming it's selectable by name with no core-file edits; confirm
  `ParseDocumentService.inspect()`'s new inspector slot defaults to `docling` when installed
  and fails loud (not silently falls back) when the override target is missing.
- **Phase 2**: per sub-step, existing `tests/unit/test_runtime_*.py`-style tests
  (`monkeypatch.setenv` + `build_runtime_container(Settings())`) pass unchanged;
  `git diff --stat` confirms `local.py` untouched; a local `docker compose up -d --wait` smoke
  run (`Makefile`'s existing `up` target) against real MinIO/Qdrant/Neo4j/Postgres containers
  still ingests + queries a sample doc successfully (`uv run graph-rag ingest
  ../data/examples/sample.pdf ...` / `graph-rag query ...`, same commands already documented
  in the README).
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
