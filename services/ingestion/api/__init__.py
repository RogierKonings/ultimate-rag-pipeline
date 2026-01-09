"""API module for the ingestion service."""

from .routes import documents_router, ingest_router, migrations_router

__all__ = ["migrations_router", "ingest_router", "documents_router"]


