"""Shared quota reservations backed by PostgreSQL row locks."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from graph_rag.application.quotas.service import DEFAULT_LIMITS, period_key_for, reset_at_for
from graph_rag.domain.ids import new_id
from graph_rag.domain.quotas.models import QuotaMetric, QuotaPeriod, QuotaReservation
from graph_rag.infrastructure.persistence.postgres.models.abac import (
    QuotaAssignmentModel,
    QuotaPlanModel,
    QuotaReservationModel,
    UsageCounterModel,
)
from graph_rag.shared.exceptions import QuotaExceededError


class PostgresQuotaService:
    """Reserve, commit, and release against ``usage_counters``.

    Each call opens its own session so two API processes share one budget.
    The tenant counter is locked before the user counter.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def reserve(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID | None,
        metric: QuotaMetric,
        quantity: int,
        period: QuotaPeriod | None = None,
    ) -> QuotaReservation:
        if quantity < 0:
            quantity = 0
        resolved = period or (
            QuotaPeriod.DAY if metric == QuotaMetric.QUERIES else QuotaPeriod.MONTH
        )
        pkey = period_key_for(resolved)
        async with self._session_factory() as session, session.begin():
            await self._lock_scope(session, tenant_id, None, metric, resolved, pkey)
            if user_id is not None:
                await self._lock_scope(session, tenant_id, user_id, metric, resolved, pkey)
            scopes: list[UUID | None] = [None]
            if user_id is not None:
                scopes.append(user_id)
            for scope in scopes:
                limit = await self._limit(session, tenant_id, scope, metric, resolved)
                counter = await self._counter(session, tenant_id, scope, metric, resolved, pkey)
                projected = counter.used + counter.reserved + quantity
                if projected > limit:
                    remaining = max(0, limit - counter.used - counter.reserved)
                    raise QuotaExceededError(
                        f"Quota exceeded for {metric.value}",
                        details={
                            "quota": metric.value,
                            "limit": limit,
                            "used": counter.used + counter.reserved,
                            "remaining": remaining,
                            "reset_at": reset_at_for(resolved),
                        },
                    )
            for scope in scopes:
                counter = await self._counter(session, tenant_id, scope, metric, resolved, pkey)
                counter.reserved += quantity
            reservation = QuotaReservationModel(
                reservation_id=new_id(),
                tenant_id=tenant_id,
                user_id=user_id,
                metric=metric.value,
                period=resolved.value,
                period_key=pkey,
                quantity=quantity,
                status="reserved",
            )
            session.add(reservation)
            await session.flush()
            return QuotaReservation(
                reservation_id=reservation.reservation_id,
                tenant_id=tenant_id,
                user_id=user_id,
                metric=metric,
                period=resolved,
                period_key=pkey,
                quantity=quantity,
                status="reserved",
                created_at=datetime.now(UTC),
            )

    async def commit(self, *, reservation_id: UUID, actual_quantity: int) -> None:
        async with self._session_factory() as session, session.begin():
            reservation = await self._reservation(session, reservation_id)
            if reservation.status != "reserved":
                return
            if actual_quantity > reservation.quantity:
                raise QuotaExceededError(
                    "Actual usage exceeds the reservation",
                    details={
                        "quota": reservation.metric,
                        "limit": reservation.quantity,
                        "used": actual_quantity,
                        "remaining": 0,
                        "reset_at": reset_at_for(QuotaPeriod(reservation.period)),
                    },
                )
            metric = QuotaMetric(reservation.metric)
            period = QuotaPeriod(reservation.period)
            await self._settle(
                session,
                reservation,
                used_delta=actual_quantity,
                reserved_delta=-reservation.quantity,
            )
            reservation.status = "committed"
            reservation.quantity = actual_quantity
            _ = metric, period

    async def release(self, *, reservation_id: UUID) -> None:
        async with self._session_factory() as session, session.begin():
            reservation = await session.get(QuotaReservationModel, reservation_id)
            if reservation is None or reservation.status != "reserved":
                return
            await self._settle(
                session,
                reservation,
                used_delta=0,
                reserved_delta=-reservation.quantity,
            )
            reservation.status = "released"

    async def _lock_scope(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        user_id: UUID | None,
        metric: QuotaMetric,
        period: QuotaPeriod,
        period_key: str,
    ) -> None:
        key = f"{tenant_id}:{user_id}:{metric.value}:{period.value}:{period_key}"
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": key})

    async def _limit(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        user_id: UUID | None,
        metric: QuotaMetric,
        period: QuotaPeriod,
    ) -> int:
        stmt = (
            select(QuotaAssignmentModel, QuotaPlanModel)
            .join(QuotaPlanModel, QuotaPlanModel.plan_id == QuotaAssignmentModel.plan_id)
            .where(
                QuotaAssignmentModel.tenant_id == tenant_id,
                QuotaAssignmentModel.is_active.is_(True),
            )
        )
        if user_id is None:
            stmt = stmt.where(QuotaAssignmentModel.user_id.is_(None))
        else:
            stmt = stmt.where(QuotaAssignmentModel.user_id == user_id)
        row = (await session.execute(stmt)).first()
        key = f"{metric.value}:{period.value}"
        if row is None:
            return int(DEFAULT_LIMITS.get(key, 0))
        assignment, plan = row
        overrides = assignment.overrides or {}
        limits = plan.limits or {}
        if key in overrides:
            return int(overrides[key])
        if key in limits:
            return int(limits[key])
        return int(DEFAULT_LIMITS.get(key, 0))

    async def _counter(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        user_id: UUID | None,
        metric: QuotaMetric,
        period: QuotaPeriod,
        period_key: str,
    ) -> UsageCounterModel:
        stmt = select(UsageCounterModel).where(
            UsageCounterModel.tenant_id == tenant_id,
            UsageCounterModel.metric == metric.value,
            UsageCounterModel.period == period.value,
            UsageCounterModel.period_key == period_key,
        )
        if user_id is None:
            stmt = stmt.where(UsageCounterModel.user_id.is_(None))
        else:
            stmt = stmt.where(UsageCounterModel.user_id == user_id)
        stmt = stmt.with_for_update()
        found = (await session.execute(stmt)).scalar_one_or_none()
        if found is not None:
            return found
        created = UsageCounterModel(
            counter_id=new_id(),
            tenant_id=tenant_id,
            user_id=user_id,
            metric=metric.value,
            period=period.value,
            period_key=period_key,
            used=0,
            reserved=0,
        )
        session.add(created)
        await session.flush()
        return created

    async def _reservation(
        self, session: AsyncSession, reservation_id: UUID
    ) -> QuotaReservationModel:
        reservation = await session.get(QuotaReservationModel, reservation_id)
        if reservation is None:
            raise QuotaExceededError(
                "Quota reservation was not found",
                details={
                    "quota": "unknown",
                    "limit": 0,
                    "used": 0,
                    "remaining": 0,
                    "reset_at": "never",
                },
            )
        return reservation

    async def _settle(
        self,
        session: AsyncSession,
        reservation: QuotaReservationModel,
        *,
        used_delta: int,
        reserved_delta: int,
    ) -> None:
        metric = QuotaMetric(reservation.metric)
        period = QuotaPeriod(reservation.period)
        scopes: list[UUID | None] = [None]
        if reservation.user_id is not None:
            scopes.append(reservation.user_id)
        for scope in scopes:
            await self._lock_scope(
                session,
                reservation.tenant_id,
                scope,
                metric,
                period,
                reservation.period_key,
            )
            counter = await self._counter(
                session,
                reservation.tenant_id,
                scope,
                metric,
                period,
                reservation.period_key,
            )
            counter.used += used_delta
            counter.reserved += reserved_delta
            if counter.reserved < 0:
                counter.reserved = 0
