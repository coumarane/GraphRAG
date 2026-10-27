# ADR 0003: Accepted originals are immutable

**Status**: Accepted for feature `001-reliable-upload-ingestion`  
**Date**: 2026-10-27

## Context

A write URL that still names the accepted object can replace those bytes until it expires. MinIO and Azure Blob both allow that overwrite. Constitution Principle II says the staging URL must not be able to change the accepted bytes. Principle III says resume must not create a second original.

## Decision

The write URL names only a staging key under the member's tenant prefix. On successful completion the API streams that object once, checks size, type, and archives, and copies it to the final original key used by the existing pipeline. The copy records byte size and etag (Azure Blob also records the version id when versioning is enabled). The staging object is then deleted. The worker and any later read refuse the final object when size or etag no longer match the committed row.

Where the backend supports it, the final object is also locked: MinIO object retention on the final key, or an Azure Blob immutability policy on that blob. The protected final key is mandatory even when retention is unavailable, because the write URL never names that key. Completion does not create a document row if the copy or the pin fails.

## Consequences

- Two object writes happen per accepted file: staging, then final. The staging object is temporary.
- Reprocess and resume read the final key. They do not upload a second original.
- A client that saved the write URL cannot modify the accepted document.

## Evidence

- Current `presign_get` checks `assert_tenant_object_prefix` before signing.
- `original_object_key` already defines the final tenant-prefixed key.
