"""Quota reservation service with atomic counters."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Lock
from uuid import UUID

from graph_rag.domain.ids import new_id
from graph_rag.domain.quotas.models import (
    QuotaAssignment,
    QuotaMetric,
    QuotaPeriod,
    QuotaPlan,
    QuotaReservation,
    UsageCounter,
)
from graph_rag.shared.exceptions import QuotaExceededError


def period_key_for(period: QuotaPeriod, *, now: datetime | None = None) -> str:
    stamp = now or datetime.now(UTC)
    if period == QuotaPeriod.DAY:
        return stamp.strftime("%Y-%m-%d")
    if period == QuotaPeriod.MONTH:
        return stamp.strftime("%Y-%m")
    return "lifetime"


def reset_at_for(period: QuotaPeriod, *, now: datetime | None = None) -> str:
    stamp = now or datetime.now(UTC)
    if period == QuotaPeriod.DAY:
        nxt = stamp.replace(hour=0, minute=0, second=0, microsecond=0)
        from datetime import timedelta

        return (nxt + timedelta(days=1)).isoformat()
    if period == QuotaPeriod.MONTH:
        year = stamp.year + (1 if stamp.month == 12 else 0)
        month = 1 if stamp.month == 12 else stamp.month + 1
        return datetime(year, month, 1, tzinfo=UTC).isoformat()
    return "never"


DEFAULT_LIMITS: dict[str, int] = {
    f"{QuotaMetric.DOCUMENTS.value}:{QuotaPeriod.MONTH.value}": 1_000,
    f"{QuotaMetric.PAGES.value}:{QuotaPeriod.MONTH.value}": 50_000,
    f"{QuotaMetric.STORAGE_BYTES.value}:{QuotaPeriod.MONTH.value}": 10_000_000_000,
    f"{QuotaMetric.QUERIES.value}:{QuotaPeriod.DAY.value}": 1_000,
    f"{QuotaMetric.QUERIES.value}:{QuotaPeriod.MONTH.value}": 20_000,
    f"{QuotaMetric.OCR_PAGES.value}:{QuotaPeriod.MONTH.value}": 50_000,
    f"{QuotaMetric.VISION_CALLS.value}:{QuotaPeriod.MONTH.value}": 5_000,
    f"{QuotaMetric.LLM_TOKENS.value}:{QuotaPeriod.MONTH.value}": 5_000_000,
    f"{QuotaMetric.EMBEDDING_TOKENS.value}:{QuotaPeriod.MONTH.value}": 20_000_000,
}


@dataclass
class InMemoryQuotaService:
    """Process-local quota service suitable for tests and memory mode."""

    plans: dict[UUID, QuotaPlan] = field(default_factory=dict)
    assignments: list[QuotaAssignment] = field(default_factory=list)
    counters: dict[tuple[UUID, UUID | None, str, str, str], UsageCounter] = field(
        default_factory=dict
    )
    reservations: dict[UUID, QuotaReservation] = field(default_factory=dict)
    usage_events: list[dict[str, object]] = field(default_factory=list)
    _lock: Lock = field(default_factory=Lock)

    def ensure_default_plan(self) -> QuotaPlan:
        for plan in self.plans.values():
            if plan.name == "default":
                return plan
        plan = QuotaPlan(
            plan_id=new_id(),
            name="default",
            description="Default tenant/user quota plan",
            limits=dict(DEFAULT_LIMITS),
        )
        self.plans[plan.plan_id] = plan
        return plan

    def assign_default(self, *, tenant_id: UUID, user_id: UUID | None = None) -> QuotaAssignment:
        plan = self.ensure_default_plan()
        assignment = QuotaAssignment(
            assignment_id=new_id(),
            tenant_id=tenant_id,
            user_id=user_id,
            plan_id=plan.plan_id,
            period=QuotaPeriod.MONTH,
        )
        self.assignments.append(assignment)
        return assignment

    def _limits_for(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID | None,
        metric: QuotaMetric,
        period: QuotaPeriod,
    ) -> int | None:
        key = f"{metric.value}:{period.value}"
        tenant_limit: int | None = None
        user_limit: int | None = None
        for assignment in self.assignments:
            if not assignment.is_active or assignment.tenant_id != tenant_id:
                continue
            plan = self.plans.get(assignment.plan_id)
            if plan is None:
                continue
            limit = assignment.overrides.get(key, plan.limits.get(key))
            if limit is None:
                continue
            if assignment.user_id is None:
                tenant_limit = int(limit)
            elif user_id is not None and assignment.user_id == user_id:
                user_limit = int(limit)
        if user_limit is not None and tenant_limit is not None:
            return min(user_limit, tenant_limit)
        return user_limit if user_limit is not None else tenant_limit

    def _counter(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID | None,
        metric: QuotaMetric,
        period: QuotaPeriod,
        period_key: str,
    ) -> UsageCounter:
        key = (tenant_id, user_id, metric.value, period.value, period_key)
        counter = self.counters.get(key)
        if counter is None:
            counter = UsageCounter(
                counter_id=new_id(),
                tenant_id=tenant_id,
                user_id=user_id,
                metric=metric,
                period=period,
                period_key=period_key,
            )
            self.counters[key] = counter
        return counter

    def reserve(
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
        resolved_period = period or (
            QuotaPeriod.DAY if metric == QuotaMetric.QUERIES else QuotaPeriod.MONTH
        )
        pkey = period_key_for(resolved_period)
        with self._lock:
            # Ensure at least a tenant assignment exists.
            if not any(a.tenant_id == tenant_id and a.user_id is None for a in self.assignments):
                self.assign_default(tenant_id=tenant_id, user_id=None)

            limit = self._limits_for(
                tenant_id=tenant_id,
                user_id=user_id,
                metric=metric,
                period=resolved_period,
            )
            # Also enforce day queries against month when both exist.
            scopes: list[tuple[UUID | None, int | None]] = [(user_id, limit)]
            if user_id is not None:
                tenant_only = self._limits_for(
                    tenant_id=tenant_id,
                    user_id=None,
                    metric=metric,
                    period=resolved_period,
                )
                scopes.append((None, tenant_only))

            for scope_user, scope_limit in scopes:
                if scope_limit is None:
                    continue
                counter = self._counter(
                    tenant_id=tenant_id,
                    user_id=scope_user,
                    metric=metric,
                    period=resolved_period,
                    period_key=pkey,
                )
                projected = counter.used + counter.reserved + quantity
                if projected > scope_limit:
                    remaining = max(0, scope_limit - counter.used - counter.reserved)
                    raise QuotaExceededError(
                        f"Quota exceeded for {metric.value}",
                        details={
                            "error": "quota_exceeded",
                            "quota": metric.value,
                            "limit": scope_limit,
                            "used": counter.used + counter.reserved,
                            "remaining": remaining,
                            "reset_at": reset_at_for(resolved_period),
                            "period": resolved_period.value,
                            "scope": "tenant" if scope_user is None else "user",
                        },
                    )

            for scope_user, scope_limit in scopes:
                if scope_limit is None:
                    continue
                counter = self._counter(
                    tenant_id=tenant_id,
                    user_id=scope_user,
                    metric=metric,
                    period=resolved_period,
                    period_key=pkey,
                )
                counter.reserved += quantity

            reservation = QuotaReservation(
                reservation_id=new_id(),
                tenant_id=tenant_id,
                user_id=user_id,
                metric=metric,
                period=resolved_period,
                period_key=pkey,
                quantity=quantity,
                status="reserved",
                created_at=datetime.now(UTC),
            )
            self.reservations[reservation.reservation_id] = reservation
            return reservation

    def commit(self, *, reservation_id: UUID, actual_quantity: int) -> None:
        with self._lock:
            reservation = self.reservations.get(reservation_id)
            if reservation is None or reservation.status != "reserved":
                return
            actual = max(0, actual_quantity)
            scopes = [reservation.user_id]
            if reservation.user_id is not None:
                scopes.append(None)
            for scope_user in scopes:
                counter = self._counter(
                    tenant_id=reservation.tenant_id,
                    user_id=scope_user,
                    metric=reservation.metric,
                    period=reservation.period,
                    period_key=reservation.period_key,
                )
                counter.reserved = max(0, counter.reserved - reservation.quantity)
                counter.used += actual
            reservation.status = "committed"
            self.usage_events.append(
                {
                    "event_id": new_id(),
                    "tenant_id": reservation.tenant_id,
                    "user_id": reservation.user_id,
                    "metric": reservation.metric.value,
                    "operation": "commit",
                    "usage_type": "actual",
                    "quantity": actual,
                    "reservation_id": reservation_id,
                }
            )

    def release(self, *, reservation_id: UUID) -> None:
        with self._lock:
            reservation = self.reservations.get(reservation_id)
            if reservation is None or reservation.status != "reserved":
                return
            scopes = [reservation.user_id]
            if reservation.user_id is not None:
                scopes.append(None)
            for scope_user in scopes:
                counter = self._counter(
                    tenant_id=reservation.tenant_id,
                    user_id=scope_user,
                    metric=reservation.metric,
                    period=reservation.period,
                    period_key=reservation.period_key,
                )
                counter.reserved = max(0, counter.reserved - reservation.quantity)
            reservation.status = "released"
            self.usage_events.append(
                {
                    "event_id": new_id(),
                    "tenant_id": reservation.tenant_id,
                    "user_id": reservation.user_id,
                    "metric": reservation.metric.value,
                    "operation": "release",
                    "usage_type": "release",
                    "quantity": 0,
                    "reservation_id": reservation_id,
                }
            )

    def snapshot(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID | None = None,
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for metric in QuotaMetric:
            for period in (QuotaPeriod.DAY, QuotaPeriod.MONTH):
                limit = self._limits_for(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    metric=metric,
                    period=period,
                )
                if limit is None:
                    continue
                pkey = period_key_for(period)
                counter = self._counter(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    metric=metric,
                    period=period,
                    period_key=pkey,
                )
                used = counter.used + counter.reserved
                rows.append(
                    {
                        "metric": metric.value,
                        "period": period.value,
                        "period_key": pkey,
                        "limit": limit,
                        "used": used,
                        "remaining": max(0, limit - used),
                        "reset_at": reset_at_for(period),
                    }
                )
        return rows
