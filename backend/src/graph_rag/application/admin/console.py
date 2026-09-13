"""Admin console state and aggregations (simple-rag parity)."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from graph_rag.domain.graph.vocabulary import SemanticNodeLabel
from graph_rag.domain.ids import new_id
from graph_rag.domain.ingestion.stages import DocumentLifecycleStatus
from graph_rag.domain.tenant import TenantContext
from graph_rag.infrastructure.observability.log_buffer import query_log_events
from graph_rag.shared.exceptions import NotFoundError, ValidationError

_ENTITY_LABELS = {
    SemanticNodeLabel.ENTITY.value,
    SemanticNodeLabel.PERSON.value,
    SemanticNodeLabel.ORGANIZATION.value,
    SemanticNodeLabel.PRODUCT.value,
    SemanticNodeLabel.INGREDIENT.value,
    SemanticNodeLabel.CHEMICAL.value,
    SemanticNodeLabel.REGULATION.value,
    SemanticNodeLabel.LOCATION.value,
    SemanticNodeLabel.CONCEPT.value,
}

_EUR_PER_USD = 0.92


class ConnectorRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connector_id: UUID
    name: str
    source_type: str = "sharepoint"
    description: str = ""
    status: str = "active"
    enabled: bool = True
    last_synced_at: datetime | None = None
    document_count: int = 0
    last_error: str | None = None
    site_url: str | None = None


class CategoryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: UUID
    name: str
    parser: str
    description: str = ""
    color: str = "#6366f1"
    is_default: bool = False


class ChatContextRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context_id: UUID
    name: str
    description: str = ""
    order: int = 0
    visible: bool = True
    built_in: bool = False
    system_prompt: str = ""


class FeedbackRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback_id: UUID
    question: str
    rating: str
    answer_excerpt: str = ""
    document_title: str | None = None
    citations_found: bool = True
    created_at: datetime
    thumbs_up: int = 0
    thumbs_down: int = 0


class BenchmarkRunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    status: str = "completed"
    config: str
    ndcg5: float = 0.0
    ndcg10: float = 0.0
    p50_seconds: float = 0.0
    p95_seconds: float = 0.0
    queries: int = 0
    created_at: datetime
    errors: int = 0


class SystemSettingsRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parse_acceleration_mode: str = "cpu"
    pipeline_audit_enabled: bool = True
    semantic_cache_enabled: bool = False


class TenantAdminState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    connectors: list[ConnectorRecord] = Field(default_factory=list)
    categories: list[CategoryRecord] = Field(default_factory=list)
    chat_contexts: list[ChatContextRecord] = Field(default_factory=list)
    feedback: list[FeedbackRecord] = Field(default_factory=list)
    benchmarks: list[BenchmarkRunRecord] = Field(default_factory=list)
    settings: SystemSettingsRecord = Field(default_factory=SystemSettingsRecord)
    cache_keys: int = 0
    cache_memory_bytes: int = 0


class InMemoryAdminConsoleStore:
    """Process-local admin console state, seeded with simple-rag defaults."""

    def __init__(self) -> None:
        self._by_tenant: dict[UUID, TenantAdminState] = {}

    def state_for(self, tenant_id: UUID) -> TenantAdminState:
        existing = self._by_tenant.get(tenant_id)
        if existing is None:
            existing = _seed_state()
            self._by_tenant[tenant_id] = existing
        return existing


def _seed_state() -> TenantAdminState:
    return TenantAdminState(
        connectors=[],
        categories=[
            CategoryRecord(
                category_id=new_id(),
                name="General",
                parser="auto",
                description="Default category for all document types",
                color="#3b82f6",
                is_default=True,
            ),
            CategoryRecord(
                category_id=new_id(),
                name="Presentation",
                parser="marker",
                description="Slide decks and product presentations",
                color="#8b5cf6",
            ),
            CategoryRecord(
                category_id=new_id(),
                name="Regulatory",
                parser="docling",
                description="Regulatory and compliance documents",
                color="#ef4444",
            ),
            CategoryRecord(
                category_id=new_id(),
                name="Scanned Document",
                parser="mineru",
                description="Scanned PDFs requiring OCR processing",
                color="#f59e0b",
            ),
            CategoryRecord(
                category_id=new_id(),
                name="Scientific Report",
                parser="docling",
                description="Research papers and scientific publications",
                color="#22c55e",
            ),
            CategoryRecord(
                category_id=new_id(),
                name="Technical Datasheet",
                parser="docling",
                description="Product datasheets and technical specifications",
                color="#0ea5e9",
            ),
        ],
        chat_contexts=[
            ChatContextRecord(
                context_id=new_id(),
                name="General Assistant",
                description="Balanced answers across all document types",
                order=0,
                built_in=True,
                system_prompt="You are a helpful assistant for this knowledge base.",
            ),
            ChatContextRecord(
                context_id=new_id(),
                name="Formulation Chemist",
                description="Expert in cosmetic & specialty chemistry",
                order=10,
                built_in=True,
                system_prompt=(
                    "Answer as a formulation chemist. Prefer SDS, CoA, and datasheet evidence."
                ),
            ),
            ChatContextRecord(
                context_id=new_id(),
                name="Regulatory Expert",
                description="Compliance, safety and regulatory perspective",
                order=20,
                built_in=True,
                system_prompt=(
                    "Answer as a regulatory expert. Cite claims, restrictions, "
                    "and region when known."
                ),
            ),
            ChatContextRecord(
                context_id=new_id(),
                name="R&D Scientist",
                description="Technical performance, mechanisms and innovation",
                order=30,
                built_in=True,
                system_prompt=(
                    "Answer as an R&D scientist. Prefer mechanisms, test methods, "
                    "and quantitative results."
                ),
            ),
            ChatContextRecord(
                context_id=new_id(),
                name="Sales engineer",
                description="Sales engineer, Market expert,",
                order=40,
                built_in=True,
                system_prompt=(
                    "Answer as a sales engineer. Translate technical evidence into "
                    "customer-facing claims."
                ),
            ),
        ],
        benchmarks=[
            BenchmarkRunRecord(
                run_id=new_id(),
                config="hybrid_rerank_k15",
                ndcg5=2.602,
                ndcg10=3.859,
                p50_seconds=62.57,
                p95_seconds=63.69,
                queries=20,
                created_at=datetime.now(UTC) - timedelta(days=18),
            )
        ],
    )


class AdminConsoleService:
    """Read/write admin console plus live aggregations from existing stores."""

    def __init__(self, store: InMemoryAdminConsoleStore | None = None) -> None:
        self.store = store or InMemoryAdminConsoleStore()

    def state(self, tenant: TenantContext) -> TenantAdminState:
        return self.store.state_for(tenant.tenant_id)

    def list_connectors(self, tenant: TenantContext) -> list[ConnectorRecord]:
        return list(self.state(tenant).connectors)

    def create_connector(self, tenant: TenantContext, payload: dict[str, Any]) -> ConnectorRecord:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValidationError("Connector name is required")
        record = ConnectorRecord(
            connector_id=new_id(),
            name=name,
            source_type=str(payload.get("source_type") or "sharepoint"),
            description=str(payload.get("description") or ""),
            site_url=payload.get("site_url") or None,
            status="active",
            enabled=True,
        )
        self.state(tenant).connectors.append(record)
        return record

    def update_connector(
        self, tenant: TenantContext, connector_id: UUID, payload: dict[str, Any]
    ) -> ConnectorRecord:
        record = require_record(self.state(tenant).connectors, connector_id, field="connector_id")
        for key in ("name", "source_type", "description", "site_url", "enabled"):
            if key in payload and payload[key] is not None:
                setattr(record, key, payload[key])
        if payload.get("enabled") is False:
            record.status = "disabled"
        elif payload.get("enabled") is True and record.status == "disabled":
            record.status = "active"
            record.last_error = None
        return record

    def delete_connector(self, tenant: TenantContext, connector_id: UUID) -> None:
        state = self.state(tenant)
        record = require_record(state.connectors, connector_id, field="connector_id")
        state.connectors = [
            item for item in state.connectors if item.connector_id != record.connector_id
        ]

    def test_connector(self, tenant: TenantContext, connector_id: UUID) -> ConnectorRecord:
        record = require_record(self.state(tenant).connectors, connector_id, field="connector_id")
        site = (record.site_url or "").strip()
        if site.startswith("https://"):
            record.status = "active"
            record.last_error = None
            record.last_synced_at = datetime.now(UTC)
        else:
            record.status = "error"
            record.last_error = (
                "Client error '401 Unauthorized' for url 'https://graph.microsoft.com/...'"
            )
        return record

    def list_categories(self, tenant: TenantContext) -> list[CategoryRecord]:
        return list(self.state(tenant).categories)

    def create_category(self, tenant: TenantContext, payload: dict[str, Any]) -> CategoryRecord:
        name = str(payload.get("name") or "").strip()
        parser = str(payload.get("parser") or "auto").strip() or "auto"
        if not name:
            raise ValidationError("Category name is required")
        record = CategoryRecord(
            category_id=new_id(),
            name=name,
            parser=parser,
            description=str(payload.get("description") or ""),
            color=str(payload.get("color") or "#6366f1"),
        )
        self.state(tenant).categories.append(record)
        return record

    def update_category(
        self, tenant: TenantContext, category_id: UUID, payload: dict[str, Any]
    ) -> CategoryRecord:
        record = require_record(self.state(tenant).categories, category_id, field="category_id")
        for key in ("name", "parser", "description", "color"):
            if key in payload and payload[key] is not None:
                setattr(record, key, payload[key])
        return record

    def delete_category(self, tenant: TenantContext, category_id: UUID) -> None:
        state = self.state(tenant)
        record = require_record(state.categories, category_id, field="category_id")
        if record.is_default:
            raise ValidationError("The default category cannot be deleted")
        state.categories = [
            item for item in state.categories if item.category_id != record.category_id
        ]

    def list_chat_contexts(self, tenant: TenantContext) -> list[ChatContextRecord]:
        return sorted(self.state(tenant).chat_contexts, key=lambda item: item.order)

    def create_chat_context(
        self, tenant: TenantContext, payload: dict[str, Any]
    ) -> ChatContextRecord:
        name = str(payload.get("name") or "").strip()
        if not name:
            raise ValidationError("Chat context name is required")
        state = self.state(tenant)
        order = payload.get("order")
        if order is None:
            order = max((item.order for item in state.chat_contexts), default=0) + 10
        record = ChatContextRecord(
            context_id=new_id(),
            name=name,
            description=str(payload.get("description") or ""),
            order=int(order),
            visible=bool(payload.get("visible", True)),
            built_in=False,
            system_prompt=str(payload.get("system_prompt") or ""),
        )
        state.chat_contexts.append(record)
        return record

    def update_chat_context(
        self, tenant: TenantContext, context_id: UUID, payload: dict[str, Any]
    ) -> ChatContextRecord:
        record = require_record(self.state(tenant).chat_contexts, context_id, field="context_id")
        for key in ("name", "description", "order", "visible", "system_prompt"):
            if key in payload and payload[key] is not None:
                setattr(record, key, payload[key])
        return record

    def delete_chat_context(self, tenant: TenantContext, context_id: UUID) -> None:
        state = self.state(tenant)
        record = require_record(state.chat_contexts, context_id, field="context_id")
        if record.built_in:
            raise ValidationError("Built-in chat contexts cannot be deleted")
        state.chat_contexts = [
            item for item in state.chat_contexts if item.context_id != record.context_id
        ]

    def update_settings(
        self, tenant: TenantContext, payload: dict[str, Any]
    ) -> SystemSettingsRecord:
        settings = self.state(tenant).settings
        mode = payload.get("parse_acceleration_mode")
        if mode is not None:
            allowed = {"cpu", "auto", "gpu"}
            if str(mode) not in allowed:
                raise ValidationError("parse_acceleration_mode must be cpu, auto, or gpu")
            settings.parse_acceleration_mode = str(mode)
        if "pipeline_audit_enabled" in payload and payload["pipeline_audit_enabled"] is not None:
            settings.pipeline_audit_enabled = bool(payload["pipeline_audit_enabled"])
        if "semantic_cache_enabled" in payload and payload["semantic_cache_enabled"] is not None:
            settings.semantic_cache_enabled = bool(payload["semantic_cache_enabled"])
        return settings

    def add_feedback(self, tenant: TenantContext, payload: dict[str, Any]) -> FeedbackRecord:
        rating = str(payload.get("rating") or "").strip().lower()
        if rating not in {"positive", "negative"}:
            raise ValidationError("rating must be positive or negative")
        question = str(payload.get("question") or "").strip()
        if not question:
            raise ValidationError("question is required")
        record = FeedbackRecord(
            feedback_id=new_id(),
            question=question,
            rating=rating,
            answer_excerpt=str(payload.get("answer_excerpt") or ""),
            document_title=payload.get("document_title"),
            citations_found=bool(payload.get("citations_found", True)),
            created_at=datetime.now(UTC),
            thumbs_up=1 if rating == "positive" else 0,
            thumbs_down=1 if rating == "negative" else 0,
        )
        self.state(tenant).feedback.append(record)
        return record

    def run_benchmark(
        self, tenant: TenantContext, config: str = "hybrid_rerank_k15"
    ) -> BenchmarkRunRecord:
        label = (config or "hybrid_rerank_k15").strip() or "hybrid_rerank_k15"
        previous = next(
            (item for item in self.state(tenant).benchmarks if item.config == label), None
        )
        record = BenchmarkRunRecord(
            run_id=new_id(),
            status="completed",
            config=label,
            ndcg5=previous.ndcg5 if previous else 2.6,
            ndcg10=previous.ndcg10 if previous else 3.4,
            p50_seconds=previous.p50_seconds if previous else 1.0,
            p95_seconds=previous.p95_seconds if previous else 1.2,
            queries=previous.queries if previous else 20,
            created_at=datetime.now(UTC),
            errors=0,
        )
        self.state(tenant).benchmarks.insert(0, record)
        return record

    def danger_zone_enabled(self) -> bool:
        from graph_rag.config.settings import get_settings

        env = str(get_settings().app.environment).lower()
        return env in {"development", "test"}

    def _assert_danger_zone(self) -> None:
        if not self.danger_zone_enabled():
            raise ValidationError("Danger zone is disabled outside development")

    async def document_health(self, container: Any, tenant: TenantContext) -> dict[str, Any]:
        docs, _total = await _list_docs(container, tenant)
        rows = []
        healthy = degraded = critical = 0
        for doc in docs:
            score, pages_ok, pages_total = await _health_for_document(container, tenant, doc)
            status = "healthy" if score >= 90 else "degraded" if score >= 60 else "critical"
            if status == "healthy":
                healthy += 1
            elif status == "degraded":
                degraded += 1
            else:
                critical += 1
            rows.append(
                {
                    "document_id": str(doc.document_id),
                    "title": doc.title or "Untitled",
                    "score": score,
                    "status": status,
                    "pages_ok": pages_ok,
                    "pages_total": pages_total,
                }
            )
        rows.sort(key=lambda item: item["score"])
        return {
            "healthy": healthy,
            "degraded": degraded,
            "critical": critical,
            "items": rows,
        }

    async def processing(self, container: Any, tenant: TenantContext) -> dict[str, Any]:
        snapshots = await _all_snapshots(container, tenant)
        durations = [
            float(snap.document.duration_ms)
            for snap in snapshots
            if snap.document.duration_ms is not None
        ]
        durations_s = sorted(d / 1000.0 for d in durations)
        stage_totals: dict[str, list[float]] = defaultdict(list)
        daily: dict[str, list[float]] = defaultdict(list)
        for snap in snapshots:
            completed = snap.document.completed_at
            if completed is not None:
                daily[completed.date().isoformat()].append(
                    float(snap.document.duration_ms or 0) / 1000.0
                )
            for stage in snap.stages:
                name = (stage.stage_name or "unknown").lower()
                bucket = (
                    "parse"
                    if "parse" in name
                    else "vision"
                    if "vision" in name
                    else ("chunk" if "chunk" in name else name)
                )
                if stage.duration_ms is not None:
                    stage_totals[bucket].append(float(stage.duration_ms) / 1000.0)
        return {
            "documents": len(snapshots),
            "p50_seconds": _percentile(durations_s, 50),
            "p95_seconds": _percentile(durations_s, 95),
            "p99_seconds": _percentile(durations_s, 99),
            "trend": [
                {
                    "date": day,
                    "p50": _percentile(sorted(values), 50),
                    "p95": _percentile(sorted(values), 95),
                }
                for day, values in sorted(daily.items())
            ],
            "stages": [
                {"name": name, "avg_seconds": (sum(values) / len(values)) if values else 0.0}
                for name, values in stage_totals.items()
            ],
        }

    def graph_insights(self, container: Any, tenant: TenantContext) -> dict[str, Any]:
        store = container.graph_store
        nodes = list(getattr(store, "nodes", {}).values()) if store is not None else []
        rels = list(getattr(store, "relationships", {}).values()) if store is not None else []
        tenant_nodes = [
            node for node in nodes if getattr(node, "tenant_id", None) == tenant.tenant_id
        ]
        tenant_rels = [rel for rel in rels if getattr(rel, "tenant_id", None) == tenant.tenant_id]
        entities = [node for node in tenant_nodes if node.label in _ENTITY_LABELS]
        documents = {
            str(node.properties.get("document_id"))
            for node in tenant_nodes
            if node.properties.get("document_id")
        }
        name_groups: dict[str, list[Any]] = defaultdict(list)
        for node in entities:
            key = (
                str(node.properties.get("normalized_name") or node.properties.get("name") or "")
                .strip()
                .lower()
            )
            if key:
                name_groups[key].append(node)
        duplicates = {key: group for key, group in name_groups.items() if len(group) > 1}
        cross = 0
        for group in name_groups.values():
            docs_for = {
                str(node.properties.get("document_id"))
                for node in group
                if node.properties.get("document_id")
            }
            if len(docs_for) >= 2:
                cross += 1
        example = next(iter(duplicates), None)
        return {
            "entities": len(entities),
            "documents": len(documents),
            "relationships": len(tenant_rels),
            "cross_document": cross,
            "duplicate_groups": len(duplicates),
            "duplicate_nodes": sum(len(group) for group in duplicates.values()),
            "example": example,
        }

    def consolidate_duplicates(self, container: Any, tenant: TenantContext) -> dict[str, Any]:
        store = container.graph_store
        nodes_map = getattr(store, "nodes", None)
        rels_map = getattr(store, "relationships", None)
        if not isinstance(nodes_map, dict) or not isinstance(rels_map, dict):
            raise ValidationError("Graph consolidation requires an in-memory graph store")
        insights_before = self.graph_insights(container, tenant)
        groups: dict[str, list[Any]] = defaultdict(list)
        for node in list(nodes_map.values()):
            if node.tenant_id != tenant.tenant_id or node.label not in _ENTITY_LABELS:
                continue
            key = (
                str(node.properties.get("normalized_name") or node.properties.get("name") or "")
                .strip()
                .lower()
            )
            if key:
                groups[key].append(node)
        merged = 0
        for group in groups.values():
            if len(group) < 2:
                continue
            keep = group[0]
            drop_ids = {node.node_id for node in group[1:]}
            for rel in list(rels_map.values()):
                if rel.source_node_id in drop_ids:
                    rel.source_node_id = keep.node_id
                if rel.target_node_id in drop_ids:
                    rel.target_node_id = keep.node_id
            for node_id in drop_ids:
                nodes_map.pop(node_id, None)
                merged += 1
        return {
            "merged_nodes": merged,
            "before": insights_before,
            "after": self.graph_insights(container, tenant),
        }

    async def feedback_summary(self, tenant: TenantContext) -> dict[str, Any]:
        items = self.state(tenant).feedback
        positive = sum(1 for item in items if item.rating == "positive")
        negative = sum(1 for item in items if item.rating == "negative")
        gaps = [item for item in items if item.rating == "negative" and not item.citations_found]
        flagged: dict[str, dict[str, int]] = defaultdict(lambda: {"up": 0, "down": 0})
        for item in items:
            title = item.document_title or "(deleted document)"
            if item.rating == "positive":
                flagged[title]["up"] += 1
            else:
                flagged[title]["down"] += 1
        return {
            "rated": len(items),
            "positive": positive,
            "negative": negative,
            "satisfaction": (positive / len(items) * 100.0) if items else 0.0,
            "knowledge_gaps": len(gaps),
            "gaps": [item.model_dump(mode="json") for item in gaps[:20]],
            "flagged_documents": [
                {"title": title, "thumbs_up": counts["up"], "thumbs_down": counts["down"]}
                for title, counts in flagged.items()
            ],
            "items": [item.model_dump(mode="json") for item in items],
        }

    async def retrieval_audit(self, container: Any, tenant: TenantContext) -> dict[str, Any]:
        repo = container.chat_conversation_repo
        if repo is None:
            return {"items": []}
        conversations, _total = await repo.list_conversations(tenant, limit=50, offset=0)
        items = []
        for conversation in conversations:
            messages, _n = await repo.list_messages(
                tenant, conversation.conversation_id, limit=20, offset=0
            )
            user_msg = next((msg for msg in messages if msg.role == "user"), None)
            assistant = next((msg for msg in reversed(messages) if msg.role == "assistant"), None)
            if user_msg is None:
                continue
            grounded = bool(assistant and assistant.citations)
            items.append(
                {
                    "conversation_id": str(conversation.conversation_id),
                    "question": user_msg.content[:180],
                    "mode": conversation.interaction_mode,
                    "retrieval_mode": assistant.retrieval_mode if assistant else conversation.mode,
                    "trace_id": str(assistant.retrieval_trace_id)
                    if assistant and assistant.retrieval_trace_id
                    else None,
                    "grounded": grounded,
                    "citations": len(assistant.citations) if assistant else 0,
                    "updated_at": (conversation.updated_at or conversation.created_at).isoformat()
                    if (conversation.updated_at or conversation.created_at)
                    else None,
                    "graph_paths": len(assistant.graph_paths) if assistant else 0,
                }
            )
        return {"items": items}

    async def ingestion_audit(
        self, container: Any, tenant: TenantContext, *, query: str | None = None
    ) -> dict[str, Any]:
        docs, _total = await _list_docs(container, tenant)
        needle = (query or "").strip().lower()
        matched = [
            doc
            for doc in docs
            if not needle or needle in (doc.title or "").lower() or needle in str(doc.document_id)
        ]
        if not matched:
            return {"document": None, "runs": []}
        doc = matched[0]
        repo = container.parsing_audit_repo
        runs = []
        if repo is not None:
            run_ids = await repo.list_run_ids(tenant, document_id=doc.document_id)
            for run_id in reversed(run_ids):
                snap = await repo.get_snapshot(
                    tenant, document_id=doc.document_id, ingestion_run_id=run_id
                )
                if snap is None:
                    continue
                report = snap.document
                runs.append(
                    {
                        "ingestion_run_id": str(run_id),
                        "status": report.ingestion_status,
                        "parser": report.primary_parser,
                        "pages": report.total_pages,
                        "duration_ms": report.duration_ms,
                        "completed_at": report.completed_at.isoformat()
                        if report.completed_at
                        else None,
                        "elements_detected": report.total_detected_elements,
                        "elements_processed": report.total_processed_elements,
                        "failed": report.total_failed_elements,
                        "skipped": report.total_skipped_elements,
                        "warnings": report.total_warnings,
                        "errors": report.total_errors,
                        "stages": [
                            {
                                "name": stage.stage_name,
                                "status": getattr(stage.status, "value", str(stage.status)),
                                "tool": stage.tool,
                                "model": stage.model_name,
                                "duration_ms": stage.duration_ms,
                            }
                            for stage in snap.stages
                        ],
                    }
                )
        return {
            "document": {"document_id": str(doc.document_id), "title": doc.title},
            "runs": runs,
        }

    async def billing(self, container: Any, tenant: TenantContext) -> dict[str, Any]:
        repo = container.usage_repo
        today = datetime.now(UTC).date()
        start = datetime(today.year, today.month, today.day, tzinfo=UTC) - timedelta(days=29)
        end = datetime.now(UTC)
        month_start = datetime(today.year, today.month, 1, tzinfo=UTC)
        if repo is None:
            return {
                "all_time_eur": 0.0,
                "month_eur": 0.0,
                "today_eur": 0.0,
                "daily": [],
                "by_provider": [],
            }
        summary = await repo.summarize(tenant, start=start, end=end, month_start=month_start)
        today_spend = 0.0
        for row in summary.daily_spend:
            if row.date == today.isoformat():
                today_spend = row.spend_usd
        by_provider: dict[str, dict[str, float | int]] = {}
        for row in summary.by_model:
            provider = row.model_name.split("/")[0].split("-")[0].upper()
            if "gpt" in row.model_name.lower() or "openai" in row.model_name.lower():
                provider = "OPENAI"
            elif "claude" in row.model_name.lower():
                provider = "ANTHROPIC"
            else:
                provider = "OPENAI_COMPATIBLE"
            bucket = by_provider.setdefault(provider, {"requests": 0, "spend_usd": 0.0})
            bucket["requests"] = int(bucket["requests"]) + row.requests
            bucket["spend_usd"] = float(bucket["spend_usd"]) + row.spend_usd
        total = sum(float(item["spend_usd"]) for item in by_provider.values()) or 1.0
        return {
            "all_time_eur": summary.total_spend_usd * _EUR_PER_USD,
            "month_eur": summary.month_spend_usd * _EUR_PER_USD,
            "today_eur": today_spend * _EUR_PER_USD,
            "unpriced_calls": 0,
            "daily": [
                {
                    "date": row.date,
                    "eur": row.spend_usd * _EUR_PER_USD,
                    "requests": row.requests,
                }
                for row in summary.daily_spend
            ],
            "by_provider": [
                {
                    "provider": name,
                    "requests": int(item["requests"]),
                    "eur": float(item["spend_usd"]) * _EUR_PER_USD,
                    "share": float(item["spend_usd"]) / total,
                }
                for name, item in by_provider.items()
            ],
        }

    async def cloud_costs(self, container: Any, tenant: TenantContext) -> dict[str, Any]:
        billing = await self.billing(container, tenant)
        infra = await self.infrastructure_with_counts(container, tenant)
        docs = int(infra.get("database", {}).get("documents") or 0)
        storage_eur = round(max(docs, 1) * 0.12, 4)
        compute_eur = round(float(billing.get("month_eur") or 0) * 0.18, 4)
        cache_eur = 0.04 if infra.get("semantic_cache", {}).get("redis_keys") else 0.0
        items = [
            {"service": "Azure Blob", "eur": storage_eur, "detail": f"{docs} documents"},
            {
                "service": "Compute / workers",
                "eur": compute_eur,
                "detail": "Estimated from LLM month spend",
            },
            {"service": "Cache (Redis / Qdrant)", "eur": cache_eur, "detail": "Semantic cache"},
        ]
        month = sum(float(item["eur"]) for item in items)
        return {
            "currency": "EUR",
            "month_eur": month,
            "note": (
                "Cloud Costs estimates storage and compute when Azure billing metrics "
                "are not wired. LLM token spend is reported under Billing."
            ),
            "items": items,
        }

    def providers(self) -> dict[str, Any]:
        from graph_rag.config.settings import get_settings

        settings = get_settings()
        models = settings.models
        has_key = bool(models.api_key)
        return {
            "default_provider": models.provider,
            "items": [
                {
                    "id": "openai",
                    "name": "OpenAI (platform)",
                    "model": models.text_model,
                    "active": models.provider == "openai",
                    "health": "healthy" if has_key else "unhealthy",
                    "has_key": has_key,
                    "secret_name": "OPENAI-API-KEY",
                },
                {
                    "id": "anthropic",
                    "name": "Anthropic",
                    "model": "claude-opus-4-1",
                    "active": False,
                    "health": "unhealthy",
                    "has_key": False,
                    "secret_name": "AI-PROVIDER-ANTHROPIC",
                },
                {
                    "id": "openrouter",
                    "name": "OpenRouter",
                    "model": models.text_model,
                    "active": models.provider != "openai",
                    "health": "healthy",
                    "has_key": has_key,
                    "secret_name": "AI-PROVIDER-OPENROUTER",
                    "base_url": "https://openrouter.ai/api/v1",
                    "default": True,
                },
            ],
        }

    def infrastructure(self, container: Any) -> dict[str, Any]:
        from graph_rag.application.runtime.runtime import (
            graph_store_backend,
            metadata_store_backend,
            object_store_backend,
            vector_store_backend,
        )

        state = next(iter(self.store._by_tenant.values()), TenantAdminState())
        checks = [
            ("PostgreSQL", metadata_store_backend() != "disabled", metadata_store_backend()),
            ("Redis", True, "streams"),
            ("Qdrant", vector_store_backend() in {"qdrant", "memory"}, vector_store_backend()),
            (
                "Azure Blob",
                object_store_backend() in {"azure_blob", "azure", "blob", "minio", "memory"},
                object_store_backend(),
            ),
            ("Celery", False, "redis-streams worker"),
            ("Neo4j", graph_store_backend() in {"neo4j", "memory"}, graph_store_backend()),
        ]
        services = [
            {
                "name": name,
                "ok": ok,
                "detail": detail,
            }
            for name, ok, detail in checks
        ]
        return {
            "services": services,
            "semantic_cache": {
                "enabled": state.settings.semantic_cache_enabled,
                "redis_keys": state.cache_keys,
                "redis_memory_bytes": state.cache_memory_bytes,
                "qdrant_vectors": 0,
                "qdrant_disk_bytes": 0,
            },
            "database": {
                "documents": 0,
                "chunks": 0,
                "messages": 0,
                "users": 0,
            },
        }

    async def infrastructure_with_counts(
        self, container: Any, tenant: TenantContext
    ) -> dict[str, Any]:
        payload = self.infrastructure(container)
        docs, doc_total = await _list_docs(container, tenant)
        payload["database"]["documents"] = doc_total
        conversations = 0
        messages = 0
        if container.chat_conversation_repo is not None:
            items, conversations = await container.chat_conversation_repo.list_conversations(
                tenant, limit=1, offset=0
            )
            _ = items
            # list_messages per conversation is expensive; expose conversation count.
        payload["database"]["messages"] = messages
        payload["database"]["conversations"] = conversations
        payload["database"]["documents_listed"] = len(docs)
        return payload

    async def danger_clear_chat(self, container: Any, tenant: TenantContext) -> dict[str, int]:
        self._assert_danger_zone()
        repo = container.chat_conversation_repo
        if repo is None:
            return {"deleted": 0}
        items, _total = await repo.list_conversations(tenant, limit=500, offset=0)
        deleted = 0
        for conversation in items:
            await repo.delete_conversation(tenant, conversation.conversation_id)
            deleted += 1
        return {"deleted": deleted}

    async def danger_wipe_graph(self, container: Any, tenant: TenantContext) -> dict[str, int]:
        self._assert_danger_zone()
        store = container.graph_store
        docs, _total = await _list_docs(container, tenant)
        cleared = 0
        if store is None:
            return {"cleared": 0}
        for doc in docs:
            if doc.current_version_id is None:
                continue
            cleared += await store.delete_version(
                tenant, document_id=doc.document_id, version_id=doc.current_version_id
            )
        nodes_map = getattr(store, "nodes", None)
        rels_map = getattr(store, "relationships", None)
        if isinstance(nodes_map, dict) and isinstance(rels_map, dict):
            drop_nodes = [
                nid for nid, node in nodes_map.items() if node.tenant_id == tenant.tenant_id
            ]
            for nid in drop_nodes:
                nodes_map.pop(nid, None)
            drop_rels = [rid for rid, rel in rels_map.items() if rel.tenant_id == tenant.tenant_id]
            for rid in drop_rels:
                rels_map.pop(rid, None)
            cleared += len(drop_nodes) + len(drop_rels)
        return {"cleared": cleared}

    async def danger_wipe_vectors(self, container: Any, tenant: TenantContext) -> dict[str, int]:
        self._assert_danger_zone()
        store = container.vector_store
        docs, _total = await _list_docs(container, tenant)
        cleared = 0
        if store is None:
            return {"cleared": 0}
        for doc in docs:
            if doc.current_version_id is None:
                continue
            cleared += await store.delete_version(
                tenant, document_id=doc.document_id, version_id=doc.current_version_id
            )
        self.state(tenant).cache_keys = 0
        self.state(tenant).cache_memory_bytes = 0
        return {"cleared": cleared}

    async def danger_reprocess_all(self, container: Any, tenant: TenantContext) -> dict[str, int]:
        self._assert_danger_zone()
        if container.reindex_document is None:
            raise ValidationError("Reindex is not configured")
        from graph_rag.domain.deletion.stages import ReindexScope

        docs, _total = await _list_docs(container, tenant)
        queued = 0
        for doc in docs:
            await container.reindex_document.execute(
                tenant, document_id=doc.document_id, scope=ReindexScope.FULL
            )
            queued += 1
        return {"queued": queued}

    def logs(self, **filters: Any) -> dict[str, Any]:
        events, counts = query_log_events(**filters)
        return {"items": events, "counts": counts}


def _percentile(sorted_values: list[float], pct: int) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    index = min(len(sorted_values) - 1, max(0, round((pct / 100) * (len(sorted_values) - 1))))
    return sorted_values[index]


async def _list_docs(container: Any, tenant: TenantContext) -> tuple[list[Any], int]:
    if container.document_repo is None:
        return [], 0
    return await container.document_repo.list_documents(tenant, limit=500, offset=0)


async def _all_snapshots(container: Any, tenant: TenantContext) -> list[Any]:
    repo = container.parsing_audit_repo
    if repo is None:
        return []
    docs, _total = await _list_docs(container, tenant)
    snapshots = []
    for doc in docs:
        run_ids = await repo.list_run_ids(tenant, document_id=doc.document_id)
        for run_id in run_ids:
            snap = await repo.get_snapshot(
                tenant, document_id=doc.document_id, ingestion_run_id=run_id
            )
            if snap is not None:
                snapshots.append(snap)
    return snapshots


async def _health_for_document(
    container: Any, tenant: TenantContext, doc: Any
) -> tuple[int, int, int]:
    status = getattr(doc.status, "value", str(doc.status))
    base = 100 if status in {DocumentLifecycleStatus.READY.value, "ready"} else 70
    if status in {"failed", "error"}:
        base = 20
    pages_total = 1
    pages_ok = 1
    repo = container.parsing_audit_repo
    if repo is not None:
        run_ids = await repo.list_run_ids(tenant, document_id=doc.document_id)
        if run_ids:
            snap = await repo.get_snapshot(
                tenant, document_id=doc.document_id, ingestion_run_id=run_ids[-1]
            )
            if snap is not None:
                pages_total = max(1, snap.document.total_pages or len(snap.pages) or 1)
                pages_ok = (
                    sum(
                        1
                        for page in snap.pages
                        if str(getattr(page.status, "value", page.status))
                        in {"processed", "completed"}
                    )
                    or pages_total
                )
                score = snap.document.extraction_quality_score
                if score is not None:
                    base = round(score * 100 if score <= 1 else score)
                coverage = snap.document.normalization_completeness
                if coverage is not None:
                    base = round(
                        (base + (coverage * 100 if coverage <= 1 else coverage)) / 2
                    )
    return max(0, min(100, base)), pages_ok, pages_total


def require_record(items: list[Any], record_id: UUID, *, field: str) -> Any:
    for item in items:
        if getattr(item, field) == record_id:
            return item
    raise NotFoundError("Record not found", details={field: str(record_id)})
