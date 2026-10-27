"""MinIO object-store adapter."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from typing import Any, BinaryIO
from urllib.parse import urlparse

from minio import Minio
from minio.error import S3Error

from graph_rag.config.settings import MinioSettings
from graph_rag.domain.storage.object_keys import assert_tenant_object_prefix
from graph_rag.domain.storage.protocols import ObjectHead, StoredObject
from graph_rag.domain.tenant import TenantContext
from graph_rag.shared.exceptions import NotFoundError, StorageError, ValidationError


class MinioObjectStore:
    """Synchronous MinIO SDK wrapped with ``asyncio.to_thread``."""

    def __init__(self, settings: MinioSettings, *, client: Minio | None = None) -> None:
        self._settings = settings
        self._bucket = settings.bucket
        if client is not None:
            self._client = client
        else:
            endpoint = settings.endpoint
            secure = settings.secure
            # Allow full URLs in config while MinIO client expects host[:port].
            if "://" in endpoint:
                parsed = urlparse(endpoint)
                endpoint = parsed.netloc or parsed.path
                if parsed.scheme == "https":
                    secure = True
                elif parsed.scheme == "http":
                    secure = False
            self._client = Minio(
                endpoint,
                access_key=settings.access_key.get_secret_value(),
                secret_key=settings.secret_key.get_secret_value(),
                secure=secure,
            )

    async def ensure_bucket(self) -> None:
        def _ensure() -> None:
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)

        try:
            await asyncio.to_thread(_ensure)
        except S3Error as exc:
            raise StorageError("Failed to ensure MinIO bucket", cause=exc) from exc

    async def put_bytes(
        self,
        tenant: TenantContext,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
        content_hash: str,
    ) -> StoredObject:
        tenant.ensure_authorized()
        assert_tenant_object_prefix(object_key, tenant.tenant_id)
        if not data:
            raise ValidationError("Cannot store empty object")

        def _put() -> str | None:
            from io import BytesIO

            stream: BinaryIO = BytesIO(data)
            result = self._client.put_object(
                self._bucket,
                object_key,
                stream,
                length=len(data),
                content_type=content_type,
                metadata={"content-sha256": content_hash, "tenant-id": str(tenant.tenant_id)},
            )
            return getattr(result, "etag", None)

        try:
            etag = await asyncio.to_thread(_put)
        except S3Error as exc:
            raise StorageError(
                "Failed to store object in MinIO",
                details={"object_key": object_key},
                cause=exc,
            ) from exc

        return StoredObject(
            bucket=self._bucket,
            object_key=object_key,
            content_type=content_type,
            content_hash=content_hash.lower(),
            byte_size=len(data),
            etag=etag,
        )

    async def get_bytes(self, tenant: TenantContext, *, object_key: str) -> bytes:
        tenant.ensure_authorized()
        assert_tenant_object_prefix(object_key, tenant.tenant_id)

        def _get() -> bytes:
            response = self._client.get_object(self._bucket, object_key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        try:
            return await asyncio.to_thread(_get)
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject", "NotFound"}:
                raise NotFoundError(
                    "Object not found",
                    details={"object_key": object_key},
                    cause=exc,
                ) from exc
            raise StorageError(
                "Failed to read object from MinIO",
                details={"object_key": object_key},
                cause=exc,
            ) from exc

    async def delete_prefix(self, tenant: TenantContext, *, prefix: str) -> int:
        tenant.ensure_authorized()
        assert_tenant_object_prefix(
            prefix if prefix.endswith("/") else f"{prefix}/", tenant.tenant_id
        )

        def _delete() -> int:
            deleted = 0
            objects = self._client.list_objects(self._bucket, prefix=prefix, recursive=True)
            for obj in objects:
                if obj.object_name is None:
                    continue
                self._client.remove_object(self._bucket, obj.object_name)
                deleted += 1
            return deleted

        try:
            return await asyncio.to_thread(_delete)
        except S3Error as exc:
            raise StorageError(
                "Failed to delete MinIO prefix",
                details={"prefix": prefix},
                cause=exc,
            ) from exc

    async def presign_get(
        self,
        tenant: TenantContext,
        *,
        object_key: str,
        expires_seconds: int = 300,
    ) -> str:
        tenant.ensure_authorized()
        assert_tenant_object_prefix(object_key, tenant.tenant_id)
        if expires_seconds < 1 or expires_seconds > 3600:
            raise ValidationError(
                "Presigned URL expiry must be between 1 and 3600 seconds",
                details={"expires_seconds": expires_seconds},
            )

        def _presign() -> str:
            return self._client.presigned_get_object(
                self._bucket,
                object_key,
                expires=timedelta(seconds=expires_seconds),
            )

        try:
            return await asyncio.to_thread(_presign)
        except S3Error as exc:
            raise StorageError(
                "Failed to create presigned URL",
                details={"object_key": object_key},
                cause=exc,
            ) from exc

    def _assert_put_expiry(self, expires_seconds: int) -> None:
        if expires_seconds < 1 or expires_seconds > 900:
            raise ValidationError(
                "Write URL expiry must be between 1 and 900 seconds",
                details={"expires_seconds": expires_seconds},
            )

    async def presign_put(
        self,
        tenant: TenantContext,
        *,
        object_key: str,
        expires_seconds: int = 900,
    ) -> str:
        tenant.ensure_authorized()
        assert_tenant_object_prefix(object_key, tenant.tenant_id)
        self._assert_put_expiry(expires_seconds)
        if "/uploads/" not in object_key or "/staging/" not in object_key:
            raise ValidationError(
                "Write URL can name only a staging key",
                details={"object_key": object_key},
            )

        def _presign() -> str:
            return self._client.presigned_put_object(
                self._bucket,
                object_key,
                expires=timedelta(seconds=expires_seconds),
            )

        try:
            return await asyncio.to_thread(_presign)
        except S3Error as exc:
            raise StorageError(
                "Failed to create write URL",
                details={"object_key": object_key},
                cause=exc,
            ) from exc

    async def iter_bytes(
        self,
        tenant: TenantContext,
        *,
        object_key: str,
        chunk_size: int = 1024 * 1024,
    ) -> AsyncIterator[bytes]:
        tenant.ensure_authorized()
        assert_tenant_object_prefix(object_key, tenant.tenant_id)

        def _open() -> Any:
            return self._client.get_object(self._bucket, object_key)

        try:
            response = await asyncio.to_thread(_open)
        except S3Error as exc:
            raise StorageError(
                "Failed to stream object from MinIO",
                details={"object_key": object_key},
                cause=exc,
            ) from exc
        try:
            while True:
                chunk = await asyncio.to_thread(response.read, chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            response.close()
            response.release_conn()

    async def copy_object(
        self,
        tenant: TenantContext,
        *,
        source_key: str,
        dest_key: str,
        content_type: str,
        content_hash: str,
    ) -> StoredObject:
        from minio.commonconfig import CopySource

        tenant.ensure_authorized()
        assert_tenant_object_prefix(source_key, tenant.tenant_id)
        assert_tenant_object_prefix(dest_key, tenant.tenant_id)

        def _copy() -> str | None:
            result = self._client.copy_object(
                self._bucket,
                dest_key,
                CopySource(self._bucket, source_key),
            )
            return getattr(result, "etag", None)

        try:
            etag = await asyncio.to_thread(_copy)
        except S3Error as exc:
            raise StorageError(
                "Failed to copy object in MinIO",
                details={"source_key": source_key, "dest_key": dest_key},
                cause=exc,
            ) from exc
        head = await self.head_object(tenant, object_key=dest_key)
        return StoredObject(
            bucket=self._bucket,
            object_key=dest_key,
            content_type=content_type,
            content_hash=content_hash,
            byte_size=head.byte_size,
            etag=etag or head.etag,
        )

    async def delete_object(self, tenant: TenantContext, *, object_key: str) -> None:
        tenant.ensure_authorized()
        assert_tenant_object_prefix(object_key, tenant.tenant_id)

        def _delete() -> None:
            self._client.remove_object(self._bucket, object_key)

        try:
            await asyncio.to_thread(_delete)
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchObject", "NotFound"}:
                return
            raise StorageError(
                "Failed to delete MinIO object",
                details={"object_key": object_key},
                cause=exc,
            ) from exc

    async def head_object(self, tenant: TenantContext, *, object_key: str) -> ObjectHead:
        tenant.ensure_authorized()
        assert_tenant_object_prefix(object_key, tenant.tenant_id)

        def _stat() -> Any:
            return self._client.stat_object(self._bucket, object_key)

        try:
            stat = await asyncio.to_thread(_stat)
        except S3Error as exc:
            raise NotFoundError(
                "Object not found",
                details={"object_key": object_key},
                cause=exc,
            ) from exc
        return ObjectHead(
            object_key=object_key,
            byte_size=int(stat.size or 0),
            etag=getattr(stat, "etag", None),
            version_id=getattr(stat, "version_id", None),
        )

    async def lock_object(self, tenant: TenantContext, *, object_key: str) -> None:
        """Best-effort retention. The staging URL cannot write this final key."""
        tenant.ensure_authorized()
        assert_tenant_object_prefix(object_key, tenant.tenant_id)

        def _lock() -> None:
            try:
                from datetime import UTC, datetime, timedelta

                from minio.commonconfig import GOVERNANCE
                from minio.retention import Retention

                self._client.set_object_retention(
                    self._bucket,
                    object_key,
                    Retention(GOVERNANCE, datetime.now(UTC) + timedelta(days=3650)),
                )
            except Exception:
                return

        await asyncio.to_thread(_lock)
