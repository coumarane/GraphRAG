"""User repository adapters (Postgres + in-memory)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from enterprise_rag.domain.auth.models import TenantMembershipRecord, UserRecord, UserStatus
from enterprise_rag.domain.ids import new_id
from enterprise_rag.domain.types import JsonValue
from enterprise_rag.infrastructure.persistence.postgres.models.abac import TenantMembershipModel
from enterprise_rag.infrastructure.persistence.postgres.models.users import UserModel
from enterprise_rag.shared.exceptions import ConflictError, NotFoundError


def _attrs(value: dict[str, object] | None) -> dict[str, JsonValue]:
    return dict(value or {})  # type: ignore[arg-type]


def _to_record(model: UserModel) -> UserRecord:
    status = UserStatus(model.status) if model.status else UserStatus.ACTIVE
    return UserRecord(
        user_id=model.user_id,
        tenant_id=model.tenant_id,
        email=model.email,
        password_hash=model.password_hash,
        display_name=model.display_name,
        role=model.role,
        status=status,
        is_active=model.is_active and status == UserStatus.ACTIVE,
        attributes=_attrs(model.attributes),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _membership_to_record(model: TenantMembershipModel) -> TenantMembershipRecord:
    return TenantMembershipRecord(
        membership_id=model.membership_id,
        user_id=model.user_id,
        tenant_id=model.tenant_id,
        status=UserStatus(model.status),
        attributes=_attrs(model.attributes),
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


class SqlAlchemyUserRepository:
    """Postgres-backed user repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_email(self, email: str) -> UserRecord | None:
        result = await self._session.execute(
            select(UserModel).where(func.lower(UserModel.email) == email.strip().casefold())
        )
        model = result.scalar_one_or_none()
        return _to_record(model) if model is not None else None

    async def get_by_id(self, user_id: UUID) -> UserRecord | None:
        model = await self._session.get(UserModel, user_id)
        return _to_record(model) if model is not None else None

    async def count_users(self) -> int:
        result = await self._session.execute(select(func.count()).select_from(UserModel))
        return int(result.scalar_one())

    async def list_by_tenant(self, tenant_id: UUID) -> list[UserRecord]:
        result = await self._session.execute(
            select(UserModel).where(UserModel.tenant_id == tenant_id).order_by(UserModel.email)
        )
        return [_to_record(model) for model in result.scalars().all()]

    async def create(self, user: UserRecord) -> UserRecord:
        existing = await self.get_by_email(user.email)
        if existing is not None:
            raise ConflictError(
                "User already exists",
                details={"email": user.email},
            )
        attrs = dict(user.attributes)
        if user.role == "admin":
            attrs.setdefault("admin", True)
        status = user.status if isinstance(user.status, UserStatus) else UserStatus.ACTIVE
        model = UserModel(
            user_id=user.user_id or new_id(),
            tenant_id=user.tenant_id,
            email=user.email.strip().casefold(),
            password_hash=user.password_hash,
            display_name=user.display_name,
            role=user.role,
            status=status.value,
            is_active=user.is_active and status == UserStatus.ACTIVE,
            attributes=attrs,
        )
        self._session.add(model)
        await self._session.flush()
        membership = TenantMembershipModel(
            membership_id=new_id(),
            user_id=model.user_id,
            tenant_id=model.tenant_id,
            status=status.value,
            attributes=attrs,
        )
        self._session.add(membership)
        await self._session.flush()
        return _to_record(model)

    async def update(self, user: UserRecord) -> UserRecord:
        model = await self._session.get(UserModel, user.user_id)
        if model is None:
            raise NotFoundError("User not found", details={"user_id": str(user.user_id)})
        status = user.status if isinstance(user.status, UserStatus) else UserStatus.ACTIVE
        model.display_name = user.display_name
        model.role = user.role
        model.status = status.value
        model.is_active = user.is_active and status == UserStatus.ACTIVE
        model.attributes = dict(user.attributes)
        await self._session.flush()
        return _to_record(model)

    async def get_membership(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
    ) -> TenantMembershipRecord | None:
        result = await self._session.execute(
            select(TenantMembershipModel).where(
                TenantMembershipModel.user_id == user_id,
                TenantMembershipModel.tenant_id == tenant_id,
            )
        )
        model = result.scalar_one_or_none()
        return _membership_to_record(model) if model is not None else None


class InMemoryUserRepository:
    """Process-local user store for memory metadata backend."""

    def __init__(self) -> None:
        self._by_id: dict[UUID, UserRecord] = {}
        self._by_email: dict[str, UUID] = {}
        self._memberships: dict[tuple[UUID, UUID], TenantMembershipRecord] = {}

    async def get_by_email(self, email: str) -> UserRecord | None:
        user_id = self._by_email.get(email.strip().casefold())
        if user_id is None:
            return None
        return self._by_id.get(user_id)

    async def get_by_id(self, user_id: UUID) -> UserRecord | None:
        return self._by_id.get(user_id)

    async def count_users(self) -> int:
        return len(self._by_id)

    async def list_by_tenant(self, tenant_id: UUID) -> list[UserRecord]:
        return sorted(
            [u for u in self._by_id.values() if u.tenant_id == tenant_id],
            key=lambda u: u.email,
        )

    async def create(self, user: UserRecord) -> UserRecord:
        key = user.email.strip().casefold()
        if key in self._by_email:
            raise ConflictError("User already exists", details={"email": user.email})
        attrs = dict(user.attributes)
        if user.role == "admin":
            attrs.setdefault("admin", True)
        record = user.model_copy(
            update={
                "user_id": user.user_id or new_id(),
                "email": key,
                "attributes": attrs,
            }
        )
        self._by_id[record.user_id] = record
        self._by_email[key] = record.user_id
        membership = TenantMembershipRecord(
            membership_id=new_id(),
            user_id=record.user_id,
            tenant_id=record.tenant_id,
            status=record.status,
            attributes=attrs,
        )
        self._memberships[(record.user_id, record.tenant_id)] = membership
        return record

    async def update(self, user: UserRecord) -> UserRecord:
        if user.user_id not in self._by_id:
            raise NotFoundError("User not found", details={"user_id": str(user.user_id)})
        self._by_id[user.user_id] = user
        self._by_email[user.email.strip().casefold()] = user.user_id
        return user

    async def get_membership(
        self,
        *,
        user_id: UUID,
        tenant_id: UUID,
    ) -> TenantMembershipRecord | None:
        return self._memberships.get((user_id, tenant_id))
