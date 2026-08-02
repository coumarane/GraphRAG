"""Observability: redaction, metrics, tracing and audit."""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient

from enterprise_rag.api.app import create_app
from enterprise_rag.application.runtime import build_local_container
from enterprise_rag.domain.ids import new_id
from enterprise_rag.infrastructure.observability import (
    AuditEvent,
    InMemoryAuditStore,
    clear_spans,
    get_metrics,
    recorded_spans,
    reset_metrics,
    start_span,
)
from enterprise_rag.shared.logging import configure_logging, get_logger, reset_logging_state
from enterprise_rag.shared.redaction import redact_mapping, redact_string, redact_url


def setup_function() -> None:
    reset_metrics()
    clear_spans()
    reset_logging_state()


def test_redacts_secrets_and_presigned_urls() -> None:
    assert "[REDACTED]" in redact_string("Authorization: Bearer sk-abcdefghijklmnopqrst")
    url = (
        "https://bucket.s3.amazonaws.com/obj?"
        "X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=deadbeef&keep=1"
    )
    redacted = redact_url(url)
    assert "deadbeef" not in redacted
    assert "keep=1" in redacted
    payload = redact_mapping(
        {
            "api_key": "secret-value",
            "password": "hunter2",
            "ok": "visible",
            "content": "x" * 500,
        }
    )
    assert payload["api_key"] == "[REDACTED]"
    assert payload["password"] == "[REDACTED]"
    assert payload["ok"] == "visible"
    assert "REDACTED" in payload["content"] or len(payload["content"]) < 500


def test_structlog_redacts_sensitive_fields() -> None:
    stream = io.StringIO()
    configure_logging(level="INFO", json_logs=True, stream=stream, service_name="test")
    logger = get_logger("test.redaction")
    logger.info("event", api_key="super-secret", authorization="Bearer abc", note="safe")
    output = stream.getvalue()
    assert "super-secret" not in output
    assert "Bearer abc" not in output
    assert "safe" in output


def test_metrics_and_spans() -> None:
    metrics = get_metrics()
    metrics.incr("documents_submitted_total")
    with metrics.timer("stage_duration_seconds", labels={"stage": "parse"}):
        pass
    with start_span(
        "parse.document",
        attributes={"document_id": str(new_id()), "content": "SECRET"},
    ):
        pass
    snap = metrics.snapshot()
    assert snap["counters"]["documents_submitted_total"] == 1
    assert "stage_duration_seconds{stage=parse}" in snap["histograms"]
    spans = recorded_spans()
    assert spans
    assert "content" not in spans[-1].attributes
    text = metrics.render_prometheus()
    assert "documents_submitted_total" in text


@pytest.mark.asyncio
async def test_audit_store_retains_events() -> None:
    store = InMemoryAuditStore(retention_days=7)
    event = await store.append(
        AuditEvent(
            tenant_id=new_id(),
            event_type="model_usage",
            payload={"model": "fake", "tokens": 10},
        )
    )
    assert event.retain_until is not None
    listed = await store.list_for_tenant(event.tenant_id, event_type="model_usage")
    assert len(listed) == 1


def test_api_metrics_and_correlation_header() -> None:
    container = build_local_container()
    client = TestClient(create_app(container))
    correlation = str(new_id())
    live = client.get(
        "/api/v1/health/live",
        headers={"X-Correlation-ID": correlation},
    )
    assert live.status_code == 200
    assert live.headers.get("X-Correlation-ID") == correlation

    json_metrics = client.get("/api/v1/metrics")
    assert json_metrics.status_code == 200
    body = json_metrics.json()
    assert "counters" in body
    assert body["flat"]["requests_total"] >= 1

    prom = client.get("/metrics")
    assert prom.status_code == 200
    assert "http_requests_total" in prom.text or "text/plain" in prom.headers["content-type"]
