"""Logging configuration unit tests."""

from __future__ import annotations

import io
import logging

from graph_rag.shared.logging import (
    bind_context,
    clear_context,
    configure_logging,
    get_logger,
    reset_logging_state,
)


def setup_function() -> None:
    reset_logging_state()


def teardown_function() -> None:
    reset_logging_state()
    clear_context()


def test_configure_logging_emits_json() -> None:
    stream = io.StringIO()
    configure_logging(level="INFO", json_logs=True, stream=stream, service_name="test-svc")
    logger = get_logger("unit.test")
    bind_context(tenant_id="demo", correlation_id="cid-1")
    logger.info("hello", stage="VALIDATE")
    output = stream.getvalue()
    assert "hello" in output
    assert "tenant_id" in output
    assert "demo" in output
    assert "VALIDATE" in output


def test_get_logger_auto_configures() -> None:
    logger = get_logger("auto")
    assert logger is not None
    assert logging.getLogger().handlers
