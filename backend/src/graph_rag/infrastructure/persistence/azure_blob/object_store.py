"""Azure Blob object-store adapter."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from graph_rag.config.settings import AzureBlobSettings
from graph_rag.domain.storage.object_keys import assert_tenant_object_prefix
from graph_rag.domain.storage.protocols import StoredObject
from graph_rag.domain.tenant import TenantContext
from graph_rag.shared.exceptions import ConfigurationError, NotFoundError, StorageError, ValidationError


class AzureBlobObjectStore:
    """Azure Blob SDK wrapper with blocking calls executed in a thread."""

    def __init__(self, settings: AzureBlobSettings) -> None:
        from azure.storage.blob import BlobServiceClient

        self._settings = settings
        self._container = settings.container

        if settings.access_key and settings.access_key.get_secret_value():
            self._blob_service = BlobServiceClient(
                account_url=settings.account_url,
                credential=settings.access_key.get_secret_value(),
            )
            self._sas_mode = "account_key"
            return

        if (
            settings.tenant_id
            and settings.client_id
            and settings.client_secret
            and settings.client_secret.get_secret_value()
        ):
            from azure.identity import ClientSecretCredential

            credential = ClientSecretCredential(
                tenant_id=settings.tenant_id,
                client_id=settings.client_id,
                client_secret=settings.client_secret.get_secret_value(),
            )
            self._blob_service = BlobServiceClient(
                account_url=settings.account_url,
                credential=credential,
            )
            self._sas_mode = "user_delegation"
            return

        raise ConfigurationError(
            "Azure Blob storage requires either AZURE_BLOB_ACCESS_KEY or "
            "AZURE_BLOB_TENANT_ID + AZURE_BLOB_CLIENT_ID + AZURE_BLOB_CLIENT_SECRET"
        )

    async def ensure_bucket(self) -> None:
        from azure.core.exceptions import ResourceExistsError

        def _ensure() -> None:
            try:
                self._blob_service.create_container(self._container)
            except ResourceExistsError:
                return

        try:
            await asyncio.to_thread(_ensure)
        except Exception as exc:
            raise StorageError("Failed to ensure Azure Blob container", cause=exc) from exc

    async def put_bytes(
        self,
        tenant: TenantContext,
        *,
        object_key: str,
        data: bytes,
        content_type: str,
        content_hash: str,
    ) -> StoredObject:
        from azure.storage.blob import ContentSettings

        tenant.ensure_authorized()
        assert_tenant_object_prefix(object_key, tenant.tenant_id)
        if not data:
            raise ValidationError("Cannot store empty object")

        def _put() -> str | None:
            blob = self._blob_service.get_blob_client(container=self._container, blob=object_key)
            result = blob.upload_blob(
                data,
                overwrite=True,
                content_settings=ContentSettings(content_type=content_type),
                metadata={
                    "content_sha256": content_hash,
                    "tenant_id": str(tenant.tenant_id),
                },
            )
            return getattr(result, "etag", None)

        try:
            etag = await asyncio.to_thread(_put)
        except Exception as exc:
            raise StorageError(
                "Failed to store object in Azure Blob",
                details={"object_key": object_key},
                cause=exc,
            ) from exc

        return StoredObject(
            bucket=self._container,
            object_key=object_key,
            content_type=content_type,
            content_hash=content_hash.lower(),
            byte_size=len(data),
            etag=etag.strip('"') if isinstance(etag, str) else etag,
        )

    async def get_bytes(self, tenant: TenantContext, *, object_key: str) -> bytes:
        from azure.core.exceptions import ResourceNotFoundError

        tenant.ensure_authorized()
        assert_tenant_object_prefix(object_key, tenant.tenant_id)

        def _get() -> bytes:
            blob = self._blob_service.get_blob_client(container=self._container, blob=object_key)
            return blob.download_blob().readall()

        try:
            return await asyncio.to_thread(_get)
        except ResourceNotFoundError as exc:
            raise NotFoundError(
                "Object not found",
                details={"object_key": object_key},
                cause=exc,
            ) from exc
        except Exception as exc:
            raise StorageError(
                "Failed to read object from Azure Blob",
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
            container = self._blob_service.get_container_client(self._container)
            for blob in container.list_blobs(name_starts_with=prefix):
                if not blob.name:
                    continue
                container.delete_blob(blob.name)
                deleted += 1
            return deleted

        try:
            return await asyncio.to_thread(_delete)
        except Exception as exc:
            raise StorageError(
                "Failed to delete Azure Blob prefix",
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
        from azure.storage.blob import BlobSasPermissions, generate_blob_sas

        tenant.ensure_authorized()
        assert_tenant_object_prefix(object_key, tenant.tenant_id)
        if expires_seconds < 1 or expires_seconds > 3600:
            raise ValidationError(
                "Presigned URL expiry must be between 1 and 3600 seconds",
                details={"expires_seconds": expires_seconds},
            )

        if self._sas_mode == "account_key":
            assert self._settings.access_key is not None
            sas = generate_blob_sas(
                account_name=self._settings.account_name,
                container_name=self._container,
                blob_name=object_key,
                account_key=self._settings.access_key.get_secret_value(),
                permission=BlobSasPermissions(read=True),
                expiry=datetime.now(UTC) + timedelta(seconds=expires_seconds),
            )
        else:
            def _delegation_sas() -> str:
                delegation_key = self._blob_service.get_user_delegation_key(
                    key_start_time=datetime.now(UTC) - timedelta(minutes=5),
                    key_expiry_time=datetime.now(UTC) + timedelta(seconds=expires_seconds),
                )
                return generate_blob_sas(
                    account_name=self._settings.account_name,
                    container_name=self._container,
                    blob_name=object_key,
                    user_delegation_key=delegation_key,
                    permission=BlobSasPermissions(read=True),
                    expiry=datetime.now(UTC) + timedelta(seconds=expires_seconds),
                )

            try:
                sas = await asyncio.to_thread(_delegation_sas)
            except Exception as exc:
                raise StorageError(
                    "Failed to create Azure Blob user delegation SAS",
                    details={"object_key": object_key},
                    cause=exc,
                ) from exc

        return f"{self._settings.account_url.rstrip('/')}/{self._container}/{object_key}?{sas}"
