"""Object storage domain contracts."""

from graph_rag.domain.storage.limits import (
    assert_safe_zip_archive,
    assert_within_page_limit,
)
from graph_rag.domain.storage.mime import (
    DEFAULT_ALLOWED_MIME_TYPES,
    assert_allowed_mime_type,
    assert_within_size_limit,
)
from graph_rag.domain.storage.object_keys import (
    assert_tenant_object_prefix,
    asset_object_key,
    derived_markdown_object_key,
    normalized_document_object_key,
    original_object_key,
    page_object_key,
    sanitize_filename,
)
from graph_rag.domain.storage.protocols import (
    HashingService,
    ObjectStore,
    SourceBytes,
    SourceLoader,
    StoredObject,
    version_prefix,
)

__all__ = [
    "DEFAULT_ALLOWED_MIME_TYPES",
    "HashingService",
    "ObjectStore",
    "SourceBytes",
    "SourceLoader",
    "StoredObject",
    "assert_allowed_mime_type",
    "assert_safe_zip_archive",
    "assert_tenant_object_prefix",
    "assert_within_page_limit",
    "assert_within_size_limit",
    "asset_object_key",
    "derived_markdown_object_key",
    "normalized_document_object_key",
    "original_object_key",
    "page_object_key",
    "sanitize_filename",
    "version_prefix",
]
