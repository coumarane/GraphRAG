"""Create and complete response shapes match the upload-session contract."""

from pathlib import Path

from graph_rag.api.routes.documents import UploadCreateResponse
from graph_rag.api.schemas.common import IngestAcceptedResponse

SCHEMA = (
    Path(__file__).resolve().parents[3]
    / "specs/001-reliable-upload-ingestion/contracts/upload-session.schema.yaml"
)


def test_create_response_has_no_document_id() -> None:
    text = SCHEMA.read_text()
    assert "upload_id" in text
    assert "expires_at" in text
    fields = set(UploadCreateResponse.model_fields)
    assert {"upload_id", "expires_at"} <= fields
    assert "document_id" not in fields
    assert "version_id" not in fields


def test_complete_response_matches_ingest_accepted_and_has_no_write_url() -> None:
    fields = set(IngestAcceptedResponse.model_fields)
    assert {"ingestion_run_id", "document_id", "version_id"} <= fields
    assert "upload" not in fields
    assert "upload_url" not in fields
    assert "write_url" not in fields
