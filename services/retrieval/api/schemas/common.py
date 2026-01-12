"""Common shared schemas for the Retrieval API."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str
    detail: str | None = None
    code: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PaginationParams(BaseModel):
    """Pagination parameters."""

    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=10, ge=1, le=100)


class HealthResponse(BaseModel):
    """Health check response."""

    status: Literal["healthy", "degraded", "unhealthy"]
    version: str
    components: dict[str, bool]
    timestamp: datetime


class ComponentHealth(BaseModel):
    """Health status for a single component."""

    name: str
    healthy: bool
    latency_ms: float | None = None
    error: str | None = None


class MetadataFilter(BaseModel):
    """Metadata filter for search."""

    field: str
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte", "in", "contains"] = "eq"
    value: Any
