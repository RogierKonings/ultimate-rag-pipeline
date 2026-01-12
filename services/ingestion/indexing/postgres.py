"""PostgreSQL writer for metadata store."""

import time
from datetime import UTC, datetime
from uuid import UUID

import asyncpg
from pydantic import BaseModel

from .base import BaseIndexWriter
from .models import DocumentRecord, WriteResult


class PostgresWriterConfig(BaseModel):
    """Configuration for PostgresWriter."""

    connection_string: str = "postgresql://localhost:5432/rag_pipeline"
    min_pool_size: int = 2
    max_pool_size: int = 10
    table_name: str = "documents"


class PostgresWriter(BaseIndexWriter):
    """Write document metadata to PostgreSQL.

    Provides ACID transactions for document management.
    Uses ON CONFLICT for idempotent upserts.
    """

    def __init__(self, config: PostgresWriterConfig | None = None):
        """Initialize PostgresWriter.

        Args:
            config: Configuration for the writer. Uses defaults if not provided.
        """
        self.config = config or PostgresWriterConfig()
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        """Establish connection pool to PostgreSQL."""
        self._pool = await asyncpg.create_pool(
            self.config.connection_string,
            min_size=self.config.min_pool_size,
            max_size=self.config.max_pool_size,
        )

    async def disconnect(self) -> None:
        """Close connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def ensure_index(self) -> None:
        """Create table and indices if they don't exist."""
        if not self._pool:
            raise RuntimeError("Pool not connected. Call connect() first.")

        async with self._pool.acquire() as conn:
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.config.table_name} (
                    document_id UUID PRIMARY KEY,
                    source_uri TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    filename TEXT,
                    mime_type TEXT,
                    title TEXT,
                    author TEXT,
                    chunk_count INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
                    content_hash VARCHAR(64) NOT NULL,
                    version INTEGER DEFAULT 1,
                    tenant_id TEXT NOT NULL,
                    visibility TEXT DEFAULT 'private',
                    allowed_groups TEXT[] DEFAULT ARRAY[]::TEXT[],
                    allowed_users TEXT[] DEFAULT ARRAY[]::TEXT[],
                    created_at TIMESTAMPTZ DEFAULT NOW(),
                    updated_at TIMESTAMPTZ DEFAULT NOW(),
                    indexed_at TIMESTAMPTZ,
                    status TEXT DEFAULT 'pending',
                    error_message TEXT,
                    metadata JSONB DEFAULT '{{}}'::JSONB
                )
            """)

            # Create indices for efficient querying
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self.config.table_name}_tenant
                ON {self.config.table_name}(tenant_id)
            """)
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self.config.table_name}_source_uri
                ON {self.config.table_name}(source_uri)
            """)
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self.config.table_name}_status
                ON {self.config.table_name}(status)
            """)
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self.config.table_name}_source_type
                ON {self.config.table_name}(source_type)
            """)
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self.config.table_name}_content_hash
                ON {self.config.table_name}(content_hash)
            """)
            # Unique constraint for deduplication (US-2.11)
            await conn.execute(f"""
                CREATE UNIQUE INDEX IF NOT EXISTS uq_{self.config.table_name}_tenant_source_hash
                ON {self.config.table_name}(tenant_id, source_uri, content_hash)
            """)

    async def write(self, documents: list[DocumentRecord]) -> WriteResult:
        """Upsert document records.

        Uses INSERT ... ON CONFLICT for idempotency.

        Args:
            documents: List of DocumentRecord objects to write.

        Returns:
            WriteResult with success status and counts.
        """
        if not self._pool:
            raise RuntimeError("Pool not connected. Call connect() first.")

        start = time.time()
        errors: list[str] = []
        items_written = 0

        async with self._pool.acquire() as conn, conn.transaction():
            for doc in documents:
                try:
                    await conn.execute(
                        f"""
                        INSERT INTO {self.config.table_name} (
                            document_id, source_uri, source_type, filename,
                            mime_type, title, author, chunk_count, total_tokens,
                            content_hash, version,
                            tenant_id, visibility, allowed_groups, allowed_users,
                            created_at, updated_at, indexed_at, status, error_message
                        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18, $19, $20)
                        ON CONFLICT (document_id) DO UPDATE SET
                            source_uri = EXCLUDED.source_uri,
                            source_type = EXCLUDED.source_type,
                            filename = EXCLUDED.filename,
                            mime_type = EXCLUDED.mime_type,
                            title = EXCLUDED.title,
                            author = EXCLUDED.author,
                            chunk_count = EXCLUDED.chunk_count,
                            total_tokens = EXCLUDED.total_tokens,
                            content_hash = EXCLUDED.content_hash,
                            version = EXCLUDED.version,
                            visibility = EXCLUDED.visibility,
                            allowed_groups = EXCLUDED.allowed_groups,
                            allowed_users = EXCLUDED.allowed_users,
                            updated_at = NOW(),
                            indexed_at = EXCLUDED.indexed_at,
                            status = EXCLUDED.status,
                            error_message = EXCLUDED.error_message
                    """,
                        doc.document_id,
                        doc.source_uri,
                        doc.source_type,
                        doc.filename,
                        doc.mime_type,
                        doc.title,
                        doc.author,
                        doc.chunk_count,
                        doc.total_tokens,
                        doc.content_hash,
                        doc.version,
                        doc.tenant_id,
                        doc.visibility,
                        doc.allowed_groups,
                        doc.allowed_users,
                        doc.created_at,
                        doc.updated_at,
                        doc.indexed_at,
                        doc.status,
                        doc.error_message,
                    )
                    items_written += 1
                except Exception as e:
                    errors.append(f"Document {doc.document_id}: {str(e)}")

        duration = (time.time() - start) * 1000

        return WriteResult(
            success=len(errors) == 0,
            items_written=items_written,
            items_failed=len(documents) - items_written,
            errors=errors,
            duration_ms=duration,
        )

    async def delete(self, document_ids: list[UUID]) -> WriteResult:
        """Delete documents by ID.

        Args:
            document_ids: List of document UUIDs to delete.

        Returns:
            WriteResult with success status.
        """
        if not self._pool:
            raise RuntimeError("Pool not connected. Call connect() first.")

        start = time.time()

        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    f"""
                    DELETE FROM {self.config.table_name}
                    WHERE document_id = ANY($1)
                """,
                    document_ids,
                )

            return WriteResult(
                success=True,
                items_written=0,
                items_failed=0,
                duration_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return WriteResult(
                success=False,
                items_written=0,
                items_failed=len(document_ids),
                errors=[str(e)],
                duration_ms=(time.time() - start) * 1000,
            )

    async def delete_by_document(self, document_id: UUID) -> WriteResult:
        """Delete single document.

        Args:
            document_id: UUID of the document to delete.

        Returns:
            WriteResult with success status.
        """
        return await self.delete([document_id])

    async def update_status(
        self,
        document_id: UUID,
        status: str,
        error_message: str | None = None,
    ) -> None:
        """Update document indexing status.

        Args:
            document_id: UUID of the document to update.
            status: New status (pending, indexed, failed).
            error_message: Optional error message if status is 'failed'.
        """
        if not self._pool:
            raise RuntimeError("Pool not connected. Call connect() first.")

        async with self._pool.acquire() as conn:
            await conn.execute(
                f"""
                UPDATE {self.config.table_name}
                SET status = $1,
                    error_message = $2,
                    indexed_at = CASE WHEN $1 = 'indexed' THEN $3 ELSE indexed_at END,
                    updated_at = $3
                WHERE document_id = $4
            """,
                status,
                error_message,
                datetime.now(tz=UTC),
                document_id,
            )

    async def get_document(self, document_id: UUID) -> DocumentRecord | None:
        """Retrieve a document by ID.

        Args:
            document_id: UUID of the document to retrieve.

        Returns:
            DocumentRecord if found, None otherwise.
        """
        if not self._pool:
            raise RuntimeError("Pool not connected. Call connect() first.")

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                f"""
                SELECT document_id, source_uri, source_type, filename, mime_type,
                       title, author, chunk_count, total_tokens, content_hash, version,
                       tenant_id, visibility, allowed_groups, allowed_users, created_at,
                       updated_at, indexed_at, status, error_message
                FROM {self.config.table_name}
                WHERE document_id = $1
            """,
                document_id,
            )

            if row:
                return DocumentRecord(
                    document_id=row["document_id"],
                    source_uri=row["source_uri"],
                    source_type=row["source_type"],
                    filename=row["filename"],
                    mime_type=row["mime_type"],
                    title=row["title"],
                    author=row["author"],
                    chunk_count=row["chunk_count"],
                    total_tokens=row["total_tokens"],
                    content_hash=row["content_hash"],
                    version=row["version"],
                    tenant_id=row["tenant_id"],
                    visibility=row["visibility"],
                    allowed_groups=list(row["allowed_groups"]) if row["allowed_groups"] else [],
                    allowed_users=list(row["allowed_users"]) if row["allowed_users"] else [],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                    indexed_at=row["indexed_at"],
                    status=row["status"],
                    error_message=row["error_message"],
                )
            return None
