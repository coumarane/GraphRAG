"""``GET /documents/{id}/pages/{page}/render`` and ``.../layout`` route tests.

Back the "Parsed content" click-to-highlight viewer: a page rendered to PNG
(``render_visual_png``, previously only used internally by Vision-tier
extraction) alongside that page's element bounding boxes, read directly from
the cached "normalized" object-store artifact rather than the dead
``/elements`` route (confirmed elsewhere: its ``ElementView`` projection is
never constructed anywhere in the codebase).

Uses the real ``../data/examples/sample.pdf`` fixture (skip-if-missing) --
``render_visual_png`` calls ``pypdfium2.PdfDocument(data)`` directly, which
raises immediately on the placeholder ``b"%PDF-1.4\\n..."`` bytes used freely
elsewhere in this test suite for routes that never touch PDF internals.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from graph_rag.api.app import create_app
from graph_rag.application.runtime import build_local_container
from graph_rag.domain.ids import new_id


@pytest.fixture
def container(monkeypatch: pytest.MonkeyPatch):
    from graph_rag.config.settings import clear_settings_cache

    monkeypatch.setenv("AUTH_ENABLED", "false")
    clear_settings_cache()
    try:
        yield build_local_container(auto_process_ingest=True)
    finally:
        clear_settings_cache()


@pytest.fixture
def client(container):
    return TestClient(create_app(container))


@pytest.fixture
def tenant_headers():
    return {
        "X-Tenant-Key": "demo",
        "X-Correlation-ID": str(new_id()),
    }


def _ingest_ready_document(client, tenant_headers, tmp_path: Path) -> str:
    sample = Path("../data/examples/sample.pdf")
    if not sample.exists():
        pytest.skip("../data/examples/sample.pdf missing")
    dest = tmp_path / "sample.pdf"
    dest.write_bytes(sample.read_bytes())
    with dest.open("rb") as handle:
        response = client.post(
            "/api/v1/documents/ingest",
            headers=tenant_headers,
            files={"file": ("sample.pdf", handle, "application/pdf")},
            data={"title": "Sample"},
        )
    assert response.status_code == 202, response.text
    return response.json()["document_id"]


def test_render_route_returns_png_for_seeded_document(
    client, tenant_headers, tmp_path: Path
) -> None:
    document_id = _ingest_ready_document(client, tenant_headers, tmp_path)
    response = client.get(f"/api/v1/documents/{document_id}/pages/1/render", headers=tenant_headers)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    assert response.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_render_route_404_unknown_document(client, tenant_headers) -> None:
    response = client.get(f"/api/v1/documents/{new_id()}/pages/1/render", headers=tenant_headers)
    assert response.status_code == 404, response.text


def test_render_route_404_page_out_of_range(client, tenant_headers, tmp_path: Path) -> None:
    document_id = _ingest_ready_document(client, tenant_headers, tmp_path)
    response = client.get(
        f"/api/v1/documents/{document_id}/pages/999/render", headers=tenant_headers
    )
    assert response.status_code == 404, response.text


def test_layout_route_returns_elements_filtered_by_page(
    client, tenant_headers, tmp_path: Path
) -> None:
    document_id = _ingest_ready_document(client, tenant_headers, tmp_path)
    response = client.get(f"/api/v1/documents/{document_id}/pages/1/layout", headers=tenant_headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["page"] == 1
    assert all(item["page_start"] <= 1 <= item["page_end"] for item in body["elements"])


def test_layout_route_elements_have_precise_bounding_boxes(
    client, tenant_headers, tmp_path: Path
) -> None:
    """Regression test: the Docling adapter must extract real element geometry.

    Previously Docling's own per-item ``prov[0].bbox`` was read only to
    recover a page number, then discarded -- every element's
    ``bounding_box`` was null, so the click-to-highlight overlay had nothing
    to draw for structurally parsed content (text, headings, tables), and
    even vision-enriched elements only ever got a crude full-page fallback.
    """
    document_id = _ingest_ready_document(client, tenant_headers, tmp_path)
    response = client.get(f"/api/v1/documents/{document_id}/pages/1/layout", headers=tenant_headers)
    assert response.status_code == 200, response.text
    elements = response.json()["elements"]
    assert elements, "expected at least one element on page 1"
    boxed = [el for el in elements if el["bounding_box"] is not None]
    assert boxed, "expected at least one element with a bounding box"
    for el in boxed:
        box = el["bounding_box"]
        assert 0.0 <= box["x0"] < box["x1"] <= 1.0
        assert 0.0 <= box["y0"] < box["y1"] <= 1.0
        assert (box["x0"], box["y0"], box["x1"], box["y1"]) != (0.0, 0.0, 1.0, 1.0)


def test_layout_route_404_unknown_document(client, tenant_headers) -> None:
    response = client.get(f"/api/v1/documents/{new_id()}/pages/1/layout", headers=tenant_headers)
    assert response.status_code == 404, response.text


def test_layout_route_404_page_out_of_range(client, tenant_headers, tmp_path: Path) -> None:
    document_id = _ingest_ready_document(client, tenant_headers, tmp_path)
    response = client.get(
        f"/api/v1/documents/{document_id}/pages/999/layout", headers=tenant_headers
    )
    assert response.status_code == 404, response.text
