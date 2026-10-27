"""Azure Blob browser uploads must send the block-blob header."""

from graph_rag.application.ingestion.upload_session import direct_put_headers
from graph_rag.infrastructure.persistence.azure_blob.object_store import AzureBlobObjectStore
from graph_rag.infrastructure.persistence.minio.object_store import MinioObjectStore


def test_azure_store_requests_the_block_blob_header() -> None:
    store = AzureBlobObjectStore.__new__(AzureBlobObjectStore)
    assert direct_put_headers(store) == {"x-ms-blob-type": "BlockBlob"}


def test_minio_and_memory_stores_add_no_put_header() -> None:
    assert direct_put_headers(MinioObjectStore.__new__(MinioObjectStore)) == {}
    assert direct_put_headers(object()) == {}
