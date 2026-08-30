"""RFC 9457 problem-details helpers and FastAPI exception handlers."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from graph_rag.domain.ids import new_id
from graph_rag.shared.exceptions import GraphRagError


def problem_details(
    *,
    status: int,
    title: str,
    detail: str,
    code: str,
    instance: str,
    correlation_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": f"https://graph-rag.local/errors/{code}",
        "title": title,
        "status": status,
        "detail": detail,
        "instance": instance,
        "code": code,
        "correlation_id": correlation_id or str(new_id()),
    }
    if metadata:
        payload["metadata"] = metadata
    return payload


def register_exception_handlers(app: FastAPI) -> None:
    async def _rollback_if_possible(request: Request) -> None:
        container = getattr(request.app.state, "container", None)
        rollback = getattr(container, "rollback_db", None)
        if callable(rollback):
            try:
                await rollback()
            except Exception:  # noqa: BLE001
                pass

    @app.exception_handler(GraphRagError)
    async def _graph_rag_error(request: Request, exc: GraphRagError) -> JSONResponse:
        await _rollback_if_possible(request)
        correlation = request.headers.get("X-Correlation-ID")
        body = problem_details(
            status=exc.http_status,
            title=exc.code.replace("_", " ").title(),
            detail=exc.message,
            code=exc.code,
            instance=str(request.url.path),
            correlation_id=correlation,
            metadata=exc.details or None,
        )
        return JSONResponse(status_code=exc.http_status, content=body)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        await _rollback_if_possible(request)
        correlation = request.headers.get("X-Correlation-ID")
        body = problem_details(
            status=422,
            title="Validation Error",
            detail="Request validation failed",
            code="validation_error",
            instance=str(request.url.path),
            correlation_id=correlation,
            # A model_validator's raised ValueError lands in errors()' ctx.error as a
            # live exception object -- jsonable_encoder (FastAPI's own default handler
            # uses this too) stringifies it instead of json.dumps choking on it.
            metadata={"errors": jsonable_encoder(exc.errors())},
        )
        return JSONResponse(status_code=422, content=body)

    @app.exception_handler(Exception)
    async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
        await _rollback_if_possible(request)
        correlation = request.headers.get("X-Correlation-ID")
        body = problem_details(
            status=500,
            title="Internal Server Error",
            detail="An unexpected error occurred",
            code="internal_error",
            instance=str(request.url.path),
            correlation_id=correlation,
            metadata={"error_type": type(exc).__name__},
        )
        return JSONResponse(status_code=500, content=body)


def parse_uuid(value: str, *, field_name: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        from graph_rag.shared.exceptions import ValidationError

        raise ValidationError(
            f"Invalid UUID for {field_name}",
            details={"value": value},
        ) from exc
