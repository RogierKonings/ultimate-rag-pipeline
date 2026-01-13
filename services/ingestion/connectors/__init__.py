"""Source connectors for ingesting documents from various data sources.

This module provides pluggable connectors for loading documents from:
- Filesystem (local and S3/MinIO)
- Databases (PostgreSQL, MySQL)
- Web (HTTP crawling)
- REST APIs

All connectors implement the BaseConnector interface for consistency.
"""

from .api import (
    APIConnector,
    APIConnectorConfig,
)
from .base import (
    BaseConnector,
    DocumentMetadata,
    RawDocument,
)
from .database import (
    DatabaseConnector,
    DatabaseConnectorConfig,
)
from .filesystem import (
    FilesystemConnector,
    FilesystemConnectorConfig,
)
from .web import (
    WebConnector,
    WebConnectorConfig,
)

__all__ = [
    # Base classes
    "BaseConnector",
    "DocumentMetadata",
    "RawDocument",
    # Filesystem
    "FilesystemConnector",
    "FilesystemConnectorConfig",
    # Database
    "DatabaseConnector",
    "DatabaseConnectorConfig",
    # Web
    "WebConnector",
    "WebConnectorConfig",
    # API
    "APIConnector",
    "APIConnectorConfig",
]
