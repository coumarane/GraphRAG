"""Authorization service protocol."""

from __future__ import annotations

from typing import Protocol

from graph_rag.domain.authorization.models import (
    Action,
    AuthorizationDecision,
    EnvironmentContext,
    ResourceContext,
    SubjectContext,
)


class AuthorizationService(Protocol):
    """Deny-by-default ABAC evaluator."""

    def authorize(
        self,
        *,
        subject: SubjectContext,
        action: Action,
        resource: ResourceContext | None = None,
        environment: EnvironmentContext | None = None,
    ) -> AuthorizationDecision:
        """Evaluate policies; raise AuthorizationError on deny when require=True."""
        ...

    def require(
        self,
        *,
        subject: SubjectContext,
        action: Action,
        resource: ResourceContext | None = None,
        environment: EnvironmentContext | None = None,
    ) -> AuthorizationDecision:
        """Authorize or raise AuthorizationError."""
        ...
