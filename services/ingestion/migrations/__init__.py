"""Embedding model migration module.

This module provides functionality for zero-downtime embedding model migrations,
including collection aliasing, progressive re-embedding, and rollback capabilities.
"""

from .models import (
    MigrationStatus,
    EmbeddingMigration,
    MigrationRequest,
    ValidationConfig,
    ValidationResult,
)
from .collection_manager import CollectionManager
from .progress_tracker import MigrationProgressStore
from .embedding_migrator import EmbeddingMigrator

__all__ = [
    "MigrationStatus",
    "EmbeddingMigration",
    "MigrationRequest",
    "ValidationConfig",
    "ValidationResult",
    "CollectionManager",
    "MigrationProgressStore",
    "EmbeddingMigrator",
]
