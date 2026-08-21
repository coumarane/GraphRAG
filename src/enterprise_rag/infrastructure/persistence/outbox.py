"""Outbox repository adapters (Postgres + in-memory)."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from enterprise_rag.domain.ingestion.outbox import OutboxEventRecord
from enterprise_rag.infrastructure.persistence.postgres.models.outbox import OutboxEventModel
from enterprise_rag.shared.exceptions import NotFoundError


def _to_record(model: OutboxEventModel) -> OutboxEventRecord:
    return OutboxEventRecord(
        outbox_event_id=model.outbox_event_id,
        tenant_id=model.tenant_id,
        event_type=model.event_type,
        aggregate_id=model.aggregate_id,
        payload=dict(model.payload or {}),
        publish_attempts=model.publish_attempts,
        last_error=model.last_error,
        published_at=model.published_at,
        stream_message_id=model.stream_message_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class SqlAlchemyOutboxStore:
    """Platform outbox. Do not set tenant GUC — this table has no RLS."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert(self, event: OutboxEventRecord) -> OutboxEventRecord:
        result = await self._session.execute(
            select(OutboxEventModel).where(
                OutboxEventModel.outbox_event_id == event.outbox_event_id
            )
        )
        model = result.scalar_one_or_none()
        if model is None:
            model = OutboxEventModel(
                outbox_event_id=event.outbox_event_id,
                tenant_id=event.tenant_id,
                event_type=event.event_type,
                aggregate_id=event.aggregate_id,
                payload=dict(event.payload),
                publish_attempts=event.publish_attempts,
                last_error=event.last_error,
                published_at=event.published_at,
                stream_message_id=event.stream_message_id,
            )
            self._session.add(model)
        else:
            if model.published_at is None:
                model.payload = dict(event.payload)
            if event.stream_message_id and not model.stream_message_id:
                model.stream_message_id = event.stream_message_id
        await self._session.flush()
        return _to_record(model)

    async def get(self, outbox_event_id: UUID) -> OutboxEventRecord | None:
        result = await self._session.execute(
            select(OutboxEventModel).where(OutboxEventModel.outbox_event_id == outbox_event_id)
        )
        model = result.scalar_one_or_none()
        return _to_record(model) if model is not None else None

    async def get_by_aggregate(
        self,
        *,
        tenant_id: UUID,
        event_type: str,
        aggregate_id: UUID,
    ) -> OutboxEventRecord | None:
        result = await self._session.execute(
            select(OutboxEventModel).where(
                OutboxEventModel.tenant_id == tenant_id,
                OutboxEventModel.event_type == event_type,
                OutboxEventModel.aggregate_id == aggregate_id,
            )
        )
        model = result.scalar_one_or_none()
        return _to_record(model) if model is not None else None

    async def list_unpublished(self, *, limit: int = 50) -> list[OutboxEventRecord]:
        stmt = (
            select(OutboxEventModel)
            .where(OutboxEventModel.published_at.is_(None))
            .order_by(OutboxEventModel.created_at.asc())
            .limit(limit)
        )
        bind = self._session.get_bind()
        dialect = bind.dialect.name if bind is not None else ""
        if dialect == "postgresql":
            stmt = stmt.with_for_update(skip_locked=True)
        result = await self._session.execute(stmt)
        return [_to_record(model) for model in result.scalars().all()]

    async def mark_published(
        self,
        outbox_event_id: UUID,
        stream_message_id: str,
    ) -> OutboxEventRecord:
        result = await self._session.execute(
            select(OutboxEventModel).where(OutboxEventModel.outbox_event_id == outbox_event_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            raise NotFoundError(
                "Outbox event not found",
                details={"outbox_event_id": str(outbox_event_id)},
            )
        model.stream_message_id = stream_message_id
        model.published_at = model.published_at or datetime.now(UTC)
        model.last_error = None
        model.updated_at = datetime.now(UTC)
        await self._session.flush()
        return _to_record(model)

    async def record_publish_failure(self, outbox_event_id: UUID, error: str) -> None:
        result = await self._session.execute(
            select(OutboxEventModel).where(OutboxEventModel.outbox_event_id == outbox_event_id)
        )
        model = result.scalar_one_or_none()
        if model is None:
            return
        model.publish_attempts = int(model.publish_attempts or 0) + 1
        model.last_error = error
        model.updated_at = datetime.now(UTC)
        await self._session.flush()

    async def list_published_for_sweeper(self, *, limit: int = 100) -> list[OutboxEventRecord]:
        result = await self._session.execute(
            select(OutboxEventModel)
            .where(OutboxEventModel.published_at.is_not(None))
            .order_by(OutboxEventModel.published_at.desc())
            .limit(limit)
        )
        return [_to_record(model) for model in result.scalars().all()]


class InMemoryOutboxStore:
    """Process-local outbox used by unit and reliability tests."""

    def __init__(self) -> None:
        self.events: dict[UUID, OutboxEventRecord] = {}

    async def upsert(self, event: OutboxEventRecord) -> OutboxEventRecord:
        existing = self.events.get(event.outbox_event_id)
        if existing is None:
            self.events[event.outbox_event_id] = event
            return event
        if existing.published_at is None:
            existing.payload = dict(event.payload)
        if event.stream_message_id and not existing.stream_message_id:
            existing.stream_message_id = event.stream_message_id
        return existing

    async def get(self, outbox_event_id: UUID) -> OutboxEventRecord | None:
        return self.events.get(outbox_event_id)

    async def get_by_aggregate(
        self,
        *,
        tenant_id: UUID,
        event_type: str,
        aggregate_id: UUID,
    ) -> OutboxEventRecord | None:
        for event in self.events.values():
            if (
                event.tenant_id == tenant_id
                and event.event_type == event_type
                and event.aggregate_id == aggregate_id
            ):
                return event
        return None

    async def list_unpublished(self, *, limit: int = 50) -> list[OutboxEventRecord]:
        rows = [event for event in self.events.values() if event.published_at is None]
        rows.sort(key=lambda item: item.created_at or datetime.min.replace(tzinfo=UTC))
        return rows[:limit]

    async def mark_published(
        self,
        outbox_event_id: UUID,
        stream_message_id: str,
    ) -> OutboxEventRecord:
        event = self.events.get(outbox_event_id)
        if event is None:
            raise NotFoundError(
                "Outbox event not found",
                details={"outbox_event_id": str(outbox_event_id)},
            )
        event.stream_message_id = stream_message_id
        event.published_at = event.published_at or datetime.now(UTC)
        event.last_error = None
        event.updated_at = datetime.now(UTC)
        return event

    async def record_publish_failure(self, outbox_event_id: UUID, error: str) -> None:
        event = self.events.get(outbox_event_id)
        if event is None:
            return
        event.publish_attempts += 1
        event.last_error = error
        event.updated_at = datetime.now(UTC)

    async def list_published_for_sweeper(self, *, limit: int = 100) -> list[OutboxEventRecord]:
        rows = [event for event in self.events.values() if event.published_at is not None]
        return rows[:limit]
