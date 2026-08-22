"""Authentication domain."""

from graph_rag.domain.auth.models import (
    AuthTenantView,
    AuthUserView,
    CreateUserRequest,
    LoginRequest,
    SessionClaims,
    TenantMembershipRecord,
    UserRecord,
    UserStatus,
)
from graph_rag.domain.auth.passwords import (
    hash_password,
    is_weak_jwt_secret,
    validate_password_strength,
    verify_password,
)
from graph_rag.domain.auth.protocols import UserRepository
from graph_rag.domain.auth.tokens import issue_access_token, parse_access_token

__all__ = [
    "AuthTenantView",
    "AuthUserView",
    "CreateUserRequest",
    "LoginRequest",
    "SessionClaims",
    "TenantMembershipRecord",
    "UserRecord",
    "UserRepository",
    "UserStatus",
    "hash_password",
    "is_weak_jwt_secret",
    "issue_access_token",
    "parse_access_token",
    "validate_password_strength",
    "verify_password",
]
