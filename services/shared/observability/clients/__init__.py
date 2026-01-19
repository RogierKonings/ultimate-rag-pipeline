"""
Traced client wrappers for external services.

These wrappers add OpenTelemetry tracing to database and search clients,
creating proper span hierarchies for distributed tracing.
"""

from .traced_qdrant import TracedQdrantClient

__all__: list[str] = [
    "TracedQdrantClient",
]
