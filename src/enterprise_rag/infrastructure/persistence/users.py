"""User repository adapters (Postgres + in-memory)."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from enterprise_rag.domain.auth.models import UserRecord
from enterprise_rag.domain.ids import new_id
from enterprise_rag.infrastructure.persistence.postgres.models.users import UserModel
from enterprise_rag.shared.exceptions import ConflictError


def _to_record(model: UserModel) -> UserRecord:
    return UserRecord(
        user_id=model.user_id,
        tenant_id=model.tenant_id,
        email=model.email,
        password_hash=model.password_hash,
        display_name=model.display_name,
        role=model.role,
        is_active=model.is_active,
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

    async def create(self, user: UserRecord) -> UserRecord:
        existing = await self.get_by_email(user.email)
        if existing is not None:
            raise ConflictError(
                "User already exists",
                details={"email": user.email},
            )
        model = UserModel(
            user_id=user.user_id or new_id(),
            tenant_id=user.tenant_id,
            email=user.email.strip().casefold(),
            password_hash=user.password_hash,
            display_name=user.display_name,
            role=user.role,
            is_active=user.is_active,
        )
        self._session.add(model)
        await self._session.flush()
        return _to_record(model)


class InMemoryUserRepository:
    """Process-local user store for memory metadata backend."""

    def __init__(self) -> None:
        self._by_id: dict[UUID, UserRecord] = {}
        self._by_email: dict[str, UUID] = {}

    async def get_by_email(self, email: str) -> UserRecord | None:
        user_id = self._by_email.get(email.strip().casefold())
        if user_id is None:
            return None
        return self._by_id.get(user_id)

    async def get_by_id(self, user_id: UUID) -> UserRecord | None:
        return self._by_id.get(user_id)

    async def count_users(self) -> int:
        return len(self._by_id)

    async def create(self, user: UserRecord) -> UserRecord:
        key = user.email.strip().casefold()
        if key in self._by_email:
            raise ConflictError("User already exists", details={"email": user.email})
        record = user.model_copy(
            update={
                "user_id": user.user_id or new_id(),
                "email": key,
            }
        )
        self._by_id[record.user_id] = record
        self._by_email[key] = record.user_id
        return record
