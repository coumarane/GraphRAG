"""Exception hierarchy unit tests."""

from __future__ import annotations

import pytest

from graph_rag.shared.exceptions import (
    CitationValidationError,
    ConfigurationError,
    GraphRagError,
    ParserError,
    PermanentError,
    TenantError,
    TransientError,
    UnsupportedDocumentError,
    ValidationError,
)


def test_base_error_payload() -> None:
    err = GraphRagError("boom", details={"stage": "VALIDATE"})
    payload = err.to_dict()
    assert payload["code"] == "graph_rag_error"
    assert payload["message"] == "boom"
    assert payload["details"]["stage"] == "VALIDATE"


def test_code_override() -> None:
    err = ValidationError("bad input", code="custom_validation")
    assert err.code == "custom_validation"
    assert err.http_status == 422


def test_cause_chaining() -> None:
    cause = ValueError("root")
    err = ConfigurationError("invalid config", cause=cause)
    assert err.__cause__ is cause


@pytest.mark.parametrize(
    ("exc_type", "code"),
    [
        (TransientError, "transient_error"),
        (PermanentError, "permanent_error"),
        (TenantError, "tenant_error"),
        (ParserError, "parser_error"),
        (CitationValidationError, "citation_validation_error"),
    ],
)
def test_default_codes(exc_type: type[GraphRagError], code: str) -> None:
    assert exc_type("x").code == code


def test_unsupported_document_is_permanent_parser_error() -> None:
    err = UnsupportedDocumentError("not supported")
    assert isinstance(err, ParserError)
    assert isinstance(err, PermanentError)
    assert err.code == "unsupported_document"
