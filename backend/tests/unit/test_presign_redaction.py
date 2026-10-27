"""Write URLs lose their signature before they can reach a log line."""

from graph_rag.shared.redaction import redact_url


def test_write_url_signature_is_redacted() -> None:
    raw = (
        "http://127.0.0.1:9000/enterprise-rag/tenants/t/uploads/u/staging/a.pdf"
        "?X-Amz-Signature=super-secret&X-Amz-Algorithm=AWS4-HMAC-SHA256"
    )
    cleaned = redact_url(raw)
    assert "super-secret" not in cleaned
    assert "X-Amz-Signature" in cleaned
    assert "[REDACTED]" in cleaned
