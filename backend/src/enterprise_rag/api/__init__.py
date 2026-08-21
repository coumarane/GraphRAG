"""HTTP API layer (FastAPI routes, dependencies, schemas)."""

from enterprise_rag.api.app import create_app, get_app

__all__ = ["create_app", "get_app"]
