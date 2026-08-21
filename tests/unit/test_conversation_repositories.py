"""Chat project/conversation repository unit tests using in-memory SQLite.

Parametrized over both the SQLAlchemy and in-memory implementations to
guarantee behavioral parity, mirroring how InMemoryDocumentRepository and
SqlAlchemyDocumentRepository are relied on elsewhere as interchangeable.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from enterprise_rag.domain.auth.models import UserRecord
from enterprise_rag.domain.conversation.records import (
    ChatConversationRecord,
    ChatMessageRecord,
    ChatProjectRecord,
)
from enterprise_rag.domain.ids import new_id
from enterprise_rag.domain.ingestion.records import TenantRecord
from enterprise_rag.domain.tenant import TenantContext
from enterprise_rag.infrastructure.persistence.memory.conversations import (
    InMemoryChatConversationRepository,
    InMemoryChatProjectRepository,
)
from enterprise_rag.infrastructure.persistence.postgres.base import Base
from enterprise_rag.infrastructure.persistence.postgres.repositories.conversations import (
    SqlAlchemyChatConversationRepository,
    SqlAlchemyChatProjectRepository,
)
from enterprise_rag.infrastructure.persistence.postgres.repositories.documents import (
    SqlAlchemyTenantRepository,
)
from enterprise_rag.infrastructure.persistence.users import SqlAlchemyUserRepository
from enterprise_rag.shared.exceptions import PermanentError


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")

    # Enable FK enforcement so ON DELETE CASCADE/SET NULL behave the same as
    # they will against real Postgres (SQLite ignores them by default).
    @event.listens_for(engine.sync_engine, "connect")
    def _enable_fk(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _project_repos(session: AsyncSession):
    return [SqlAlchemyChatProjectRepository(session), InMemoryChatProjectRepository()]


def _conversation_repos(session: AsyncSession):
    return [SqlAlchemyChatConversationRepository(session), InMemoryChatConversationRepository()]


def _linked_repo_pairs(session: AsyncSession):
    """(project_repo, conversation_repo) pairs, matching production wiring.

    The in-memory project repo needs a live reference to its paired
    conversation repo to un-file conversations on project delete (see
    InMemoryChatProjectRepository) — build_local_container wires them this
    way; a bare InMemoryChatProjectRepository() here would silently skip
    that behavior and not exercise what production actually does.
    """
    in_memory_conversations = InMemoryChatConversationRepository()
    return [
        (SqlAlchemyChatProjectRepository(session), SqlAlchemyChatConversationRepository(session)),
        (InMemoryChatProjectRepository(in_memory_conversations), in_memory_conversations),
    ]


@pytest.mark.asyncio
async def test_conversation_repository_enforces_tenant_scope(session: AsyncSession) -> None:
    for conversations in _conversation_repos(session):
        tenant_a = TenantContext(tenant_id=new_id(), tenant_key="alpha")
        tenant_b = TenantContext(tenant_id=new_id(), tenant_key="bravo")

        conversation = ChatConversationRecord(
            conversation_id=new_id(),
            tenant_id=tenant_a.tenant_id,
            title="Alpha chat",
        )
        await conversations.create_conversation(tenant_a, conversation)

        found_a = await conversations.get_conversation(tenant_a, conversation.conversation_id)
        found_b = await conversations.get_conversation(tenant_b, conversation.conversation_id)
        assert found_a is not None
        assert found_b is None

        # SQL raises TenantError (rls.require_matching_tenant); in-memory
        # raises AuthorizationError (mirrors InMemoryDocumentRepository) —
        # both are PermanentError, the two implementations aren't meant to
        # match exception type exactly, just fail closed either way.
        with pytest.raises(PermanentError):
            await conversations.create_conversation(
                tenant_b,
                ChatConversationRecord(
                    conversation_id=new_id(),
                    tenant_id=tenant_a.tenant_id,
                    title="leak",
                ),
            )


@pytest.mark.asyncio
async def test_conversation_repository_enforces_owner_scope(session: AsyncSession) -> None:
    for conversations in _conversation_repos(session):
        tenant_id = new_id()
        user_1_id, user_2_id = new_id(), new_id()
        # owner_user_id has a real FK to users.user_id (ON DELETE SET NULL),
        # which itself FKs to tenants.tenant_id; seed both so the SQLAlchemy
        # repo path doesn't violate either constraint.
        await SqlAlchemyTenantRepository(session).upsert(
            TenantRecord(tenant_id=tenant_id, tenant_key=f"tenant-{tenant_id}")
        )
        users = SqlAlchemyUserRepository(session)
        for uid in (user_1_id, user_2_id):
            await users.create(
                UserRecord(
                    user_id=uid,
                    tenant_id=tenant_id,
                    email=f"{uid}@example.com",
                    password_hash="x",
                )
            )
        user_1 = TenantContext(tenant_id=tenant_id, tenant_key="demo", user_id=user_1_id)
        user_2 = TenantContext(tenant_id=tenant_id, tenant_key="demo", user_id=user_2_id)

        conversation = ChatConversationRecord(
            conversation_id=new_id(),
            tenant_id=tenant_id,
            title="User 1's chat",
        )
        await conversations.create_conversation(user_1, conversation)

        # Same tenant, different user: must not see it via get or list.
        assert await conversations.get_conversation(user_2, conversation.conversation_id) is None
        items, total = await conversations.list_conversations(user_2)
        assert items == []
        assert total == 0

        items, total = await conversations.list_conversations(user_1)
        assert total == 1
        assert items[0].conversation_id == conversation.conversation_id


@pytest.mark.asyncio
async def test_message_ordering_and_jsonb_roundtrip(session: AsyncSession) -> None:
    for conversations in _conversation_repos(session):
        tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
        conversation = ChatConversationRecord(
            conversation_id=new_id(),
            tenant_id=tenant.tenant_id,
        )
        await conversations.create_conversation(tenant, conversation)

        user_message = ChatMessageRecord(
            message_id=new_id(),
            tenant_id=tenant.tenant_id,
            conversation_id=conversation.conversation_id,
            role="user",
            content="What is the composition?",
        )
        await conversations.add_message(tenant, user_message)

        assistant_message = ChatMessageRecord(
            message_id=new_id(),
            tenant_id=tenant.tenant_id,
            conversation_id=conversation.conversation_id,
            role="assistant",
            content="It is 100% OCTYLDODECETH-20 [C1].",
            citations=[{"citation_id": "C1", "document_name": "spec.pdf", "page_start": 1}],
            warnings=["weak_evidence"],
            retrieval_mode="mix",
            retrieval_trace_id=new_id(),
            graph_paths=[{"nodes": ["A", "B"], "relationships": ["mentions"]}],
        )
        await conversations.add_message(tenant, assistant_message)

        messages = await conversations.list_messages(tenant, conversation.conversation_id)
        assert [m.role for m in messages] == ["user", "assistant"]
        assert messages[0].content == user_message.content
        second = messages[1]
        assert second.citations == assistant_message.citations
        assert second.warnings == ["weak_evidence"]
        assert second.retrieval_mode == "mix"
        assert second.retrieval_trace_id == assistant_message.retrieval_trace_id
        assert second.graph_paths == assistant_message.graph_paths


@pytest.mark.asyncio
async def test_deleting_conversation_cascades_messages(session: AsyncSession) -> None:
    for conversations in _conversation_repos(session):
        tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
        conversation = ChatConversationRecord(
            conversation_id=new_id(),
            tenant_id=tenant.tenant_id,
        )
        await conversations.create_conversation(tenant, conversation)
        await conversations.add_message(
            tenant,
            ChatMessageRecord(
                message_id=new_id(),
                tenant_id=tenant.tenant_id,
                conversation_id=conversation.conversation_id,
                role="user",
                content="hello",
            ),
        )

        await conversations.delete_conversation(tenant, conversation.conversation_id)

        assert await conversations.get_conversation(tenant, conversation.conversation_id) is None
        assert await conversations.list_messages(tenant, conversation.conversation_id) == []


@pytest.mark.asyncio
async def test_deleting_project_unfiles_conversations_without_deleting_them(
    session: AsyncSession,
) -> None:
    for projects, conversations in _linked_repo_pairs(session):
        tenant = TenantContext(tenant_id=new_id(), tenant_key="demo")
        project = ChatProjectRecord(
            project_id=new_id(),
            tenant_id=tenant.tenant_id,
            name="Research",
        )
        await projects.create_project(tenant, project)

        conversation = ChatConversationRecord(
            conversation_id=new_id(),
            tenant_id=tenant.tenant_id,
            project_id=project.project_id,
        )
        await conversations.create_conversation(tenant, conversation)

        await projects.delete_project(tenant, project.project_id)

        still_there = await conversations.get_conversation(tenant, conversation.conversation_id)
        assert still_there is not None
        assert still_there.project_id is None
