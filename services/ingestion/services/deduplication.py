"""
Deduplication and versioning service for document ingestion.

Provides content hash computation, duplicate detection, and version management
aligned with the source_documents/chunks schema.
"""

import hashlib
import logging
from dataclasses import dataclass
from enum import Enum
from uuid import UUID

import asyncpg

logger = logging.getLogger(__name__)

# Current schema version for chunks
CHUNK_SCHEMA_VERSION = "1.0"


class DeduplicationResult(Enum):
    """Result of deduplication check."""

    NEW_DOCUMENT = "new_document"  # First time seeing this source_uri
    DUPLICATE = "duplicate"  # Same content_hash exists, skip processing
    NEW_VERSION = "new_version"  # Same source_uri but different content_hash


@dataclass
class DeduplicationCheckResult:
    """Result of a deduplication check operation."""

    result: DeduplicationResult
    document_id: UUID | None = None  # Existing document ID if duplicate/new_version
    existing_version: int | None = None  # Current version if exists
    content_hash: str = ""  # Computed content hash


@dataclass
class VersionInfo:
    """Version information for chunk metadata."""

    schema_version: str
    embedding_model: str
    embedding_version: str


class DeduplicationService:
    """
    Service for document deduplication and versioning.

    Computes SHA-256 content hashes and manages document versions
    per tenant and source_uri.
    """

    def __init__(self, pool: asyncpg.Pool):
        """
        Initialize the deduplication service.

        Args:
            pool: asyncpg connection pool for database operations.
        """
        self._pool = pool

    @staticmethod
    def compute_content_hash(content: bytes) -> str:
        """
        Compute SHA-256 hash of raw document content.

        Args:
            content: Raw document bytes.

        Returns:
            Hexadecimal SHA-256 hash string (64 characters).
        """
        return hashlib.sha256(content).hexdigest()

    async def check_duplicate(
        self,
        tenant_id: UUID,
        source_uri: str,
        content_hash: str,
    ) -> DeduplicationCheckResult:
        """
        Check if a document is a duplicate or requires versioning.

        Args:
            tenant_id: Tenant identifier.
            source_uri: Canonical source URI for the document.
            content_hash: SHA-256 hash of document content.

        Returns:
            DeduplicationCheckResult with status and existing document info.
        """
        async with self._pool.acquire() as conn:
            # Check for exact match (same tenant, source_uri, content_hash)
            exact_match = await conn.fetchrow(
                """
                SELECT id, version
                FROM documents
                WHERE tenant_id = $1
                  AND source_uri = $2
                  AND content_hash = $3
                  AND status != 'deleted'
                """,
                tenant_id,
                source_uri,
                content_hash,
            )

            if exact_match:
                # Duplicate - same content already exists
                logger.info(
                    "Duplicate detected for tenant=%s source_uri=%s",
                    tenant_id,
                    source_uri,
                )
                return DeduplicationCheckResult(
                    result=DeduplicationResult.DUPLICATE,
                    document_id=exact_match["id"],
                    existing_version=exact_match["version"],
                    content_hash=content_hash,
                )

            # Check for existing document with same source_uri but different hash
            existing_doc = await conn.fetchrow(
                """
                SELECT id, version, content_hash
                FROM documents
                WHERE tenant_id = $1
                  AND source_uri = $2
                  AND status != 'deleted'
                ORDER BY version DESC
                LIMIT 1
                """,
                tenant_id,
                source_uri,
            )

            if existing_doc:
                # New version - same source but different content
                logger.info(
                    "New version detected for tenant=%s source_uri=%s (v%d -> v%d)",
                    tenant_id,
                    source_uri,
                    existing_doc["version"],
                    existing_doc["version"] + 1,
                )
                return DeduplicationCheckResult(
                    result=DeduplicationResult.NEW_VERSION,
                    document_id=existing_doc["id"],
                    existing_version=existing_doc["version"],
                    content_hash=content_hash,
                )

            # New document - never seen this source_uri
            logger.info(
                "New document for tenant=%s source_uri=%s",
                tenant_id,
                source_uri,
            )
            return DeduplicationCheckResult(
                result=DeduplicationResult.NEW_DOCUMENT,
                content_hash=content_hash,
            )

    async def get_next_version(
        self,
        tenant_id: UUID,
        source_uri: str,
    ) -> int:
        """
        Get the next version number for a document.

        Args:
            tenant_id: Tenant identifier.
            source_uri: Canonical source URI for the document.

        Returns:
            Next version number (1 for new documents).
        """
        async with self._pool.acquire() as conn:
            return await conn.fetchval(
                """
                SELECT COALESCE(MAX(version), 0) + 1
                FROM documents
                WHERE tenant_id = $1 AND source_uri = $2
                """,
                tenant_id,
                source_uri,
            )

    async def mark_previous_versions_superseded(
        self,
        tenant_id: UUID,
        source_uri: str,
        new_document_id: UUID,
    ) -> int:
        """
        Mark previous versions of a document as superseded.

        This soft-deletes old versions when a new version is ingested.

        Args:
            tenant_id: Tenant identifier.
            source_uri: Canonical source URI for the document.
            new_document_id: ID of the new document version.

        Returns:
            Number of documents marked as superseded.
        """
        async with self._pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE documents
                SET status = 'superseded',
                    updated_at = NOW()
                WHERE tenant_id = $1
                  AND source_uri = $2
                  AND id != $3
                  AND status NOT IN ('deleted', 'superseded')
                """,
                tenant_id,
                source_uri,
                new_document_id,
            )
            # Parse "UPDATE N" to get count
            count = int(result.split()[-1]) if result else 0
            if count > 0:
                logger.info(
                    "Marked %d previous versions as superseded for source_uri=%s",
                    count,
                    source_uri,
                )
            return count

    @staticmethod
    def get_version_info(
        embedding_model: str,
        embedding_version: str,
    ) -> VersionInfo:
        """
        Create version info for chunk metadata.

        Args:
            embedding_model: Name of the embedding model.
            embedding_version: Version of the embedding model.

        Returns:
            VersionInfo with schema and embedding versions.
        """
        return VersionInfo(
            schema_version=CHUNK_SCHEMA_VERSION,
            embedding_model=embedding_model,
            embedding_version=embedding_version,
        )


async def create_deduplication_service(
    database_url: str,
) -> DeduplicationService:
    """
    Factory function to create a deduplication service.

    Args:
        database_url: PostgreSQL connection URL.

    Returns:
        Configured DeduplicationService instance.
    """
    pool = await asyncpg.create_pool(database_url)
    return DeduplicationService(pool)
