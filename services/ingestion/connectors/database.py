"""Database connector for PostgreSQL and MySQL.

This module provides a connector for ingesting documents from relational
databases using async operations with server-side cursors for efficient
streaming of large result sets.
"""

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from services.ingestion.connectors.base import (
    BaseConnector,
    DocumentMetadata,
    RawDocument,
)


class DatabaseConnectorConfig(BaseModel):
    """Configuration for the database connector.

    Supports PostgreSQL (via asyncpg) and MySQL (via aiomysql).
    """

    connection_string: str = Field(
        ...,
        description="Database connection string (DSN format)",
    )
    db_type: Literal["postgresql", "mysql"] = Field(
        ...,
        description="Type of database",
    )
    query: str = Field(
        ...,
        description="SQL query to fetch documents",
    )
    content_column: str = Field(
        ...,
        description="Column name containing document content",
    )
    id_column: str = Field(
        ...,
        description="Column name for unique document identifier",
    )
    metadata_columns: list[str] = Field(
        default_factory=list,
        description="Additional columns to include in metadata",
    )
    batch_size: int = Field(
        default=1000,
        ge=1,
        le=10000,
        description="Number of rows to fetch per batch",
    )
    pool_min_size: int = Field(
        default=1,
        ge=1,
        description="Minimum connection pool size",
    )
    pool_max_size: int = Field(
        default=10,
        ge=1,
        description="Maximum connection pool size",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "connection_string": "postgresql://user:pass@localhost:5432/mydb",
                    "db_type": "postgresql",
                    "query": "SELECT id, content, title, created_at FROM documents",
                    "content_column": "content",
                    "id_column": "id",
                    "metadata_columns": ["title", "created_at"],
                    "batch_size": 1000,
                },
                {
                    "connection_string": "mysql://user:pass@localhost:3306/mydb",
                    "db_type": "mysql",
                    "query": "SELECT doc_id, body, author FROM articles",
                    "content_column": "body",
                    "id_column": "doc_id",
                    "metadata_columns": ["author"],
                },
            ],
        },
    }


class DatabaseConnector(BaseConnector):
    """Connector for PostgreSQL and MySQL databases.

    Uses connection pooling and server-side cursors to efficiently
    stream large result sets without loading everything into memory.

    Example:
        ```python
        # PostgreSQL
        config = DatabaseConnectorConfig(
            connection_string="postgresql://user:pass@localhost:5432/db",
            db_type="postgresql",
            query="SELECT id, content, title FROM documents WHERE active = true",
            content_column="content",
            id_column="id",
            metadata_columns=["title"]
        )
        async with DatabaseConnector(config) as connector:
            async for doc in connector.stream_documents():
                print(f"Document ID: {doc.metadata.source_id}")

        # MySQL
        config = DatabaseConnectorConfig(
            connection_string="mysql://user:pass@localhost:3306/db",
            db_type="mysql",
            query="SELECT id, body FROM articles",
            content_column="body",
            id_column="id"
        )
        async with DatabaseConnector(config) as connector:
            async for doc in connector.stream_documents():
                process(doc)
        ```
    """

    def __init__(self, config: DatabaseConnectorConfig):
        """Initialize the database connector.

        Args:
            config: Configuration for the connector.
        """
        self.config = config
        self._pool: Any = None
        self._connected = False

    async def connect(self) -> None:
        """Establish connection to the database.

        Creates a connection pool for efficient connection reuse.

        Raises:
            ConnectionError: If the database is not accessible.
            ImportError: If the required database driver is not installed.
        """
        try:
            if self.config.db_type == "postgresql":
                await self._connect_postgresql()
            else:
                await self._connect_mysql()
            self._connected = True
        except ImportError as e:
            raise ImportError(
                f"Required database driver not installed: {e}. "
                f"Install with 'pip install asyncpg' for PostgreSQL "
                f"or 'pip install aiomysql' for MySQL.",
            ) from e
        except Exception as e:
            raise ConnectionError(f"Failed to connect to database: {e}") from e

    async def _connect_postgresql(self) -> None:
        """Create PostgreSQL connection pool."""
        import asyncpg

        self._pool = await asyncpg.create_pool(
            self.config.connection_string,
            min_size=self.config.pool_min_size,
            max_size=self.config.pool_max_size,
        )

    async def _connect_mysql(self) -> None:
        """Create MySQL connection pool."""
        from urllib.parse import urlparse

        import aiomysql

        # Parse connection string
        parsed = urlparse(self.config.connection_string)

        self._pool = await aiomysql.create_pool(
            host=parsed.hostname or "localhost",
            port=parsed.port or 3306,
            user=parsed.username or "root",
            password=parsed.password or "",
            db=parsed.path.lstrip("/") if parsed.path else "",
            minsize=self.config.pool_min_size,
            maxsize=self.config.pool_max_size,
        )

    async def disconnect(self) -> None:
        """Close connection to the database.

        Properly closes the connection pool.
        """
        if self._pool is not None:
            if self.config.db_type == "postgresql":
                await self._pool.close()
            else:
                self._pool.close()
                await self._pool.wait_closed()
            self._pool = None
        self._connected = False

    def _generate_source_id(self, row_id: Any) -> str:
        """Generate a consistent source ID from a row identifier.

        Args:
            row_id: The row's unique identifier.

        Returns:
            String representation suitable for use as source_id.
        """
        return str(row_id)

    def _extract_content(self, row: Any, column_index: int) -> bytes:
        """Extract content from a database row.

        Handles both TEXT and BLOB/BYTEA content types.

        Args:
            row: Database row.
            column_index: Index of the content column.

        Returns:
            Content as bytes.
        """
        content = row[column_index]

        if content is None:
            return b""
        if isinstance(content, bytes):
            return content
        if isinstance(content, (bytearray, memoryview)):
            return bytes(content)
        # Text content
        return str(content).encode("utf-8")

    def _build_metadata(
        self,
        row: Any,
        columns: list[str],
        source_id: str,
        content_size: int,
    ) -> DocumentMetadata:
        """Build document metadata from a database row.

        Args:
            row: Database row.
            columns: List of column names in the result.
            source_id: Generated source ID.
            content_size: Size of the content in bytes.

        Returns:
            DocumentMetadata instance.
        """
        extra: dict[str, Any] = {}

        # Extract metadata columns
        for col_name in self.config.metadata_columns:
            if col_name in columns:
                col_idx = columns.index(col_name)
                value = row[col_idx]

                # Convert datetime to ISO format for JSON serialization
                if isinstance(value, datetime):
                    extra[col_name] = value.isoformat()
                elif value is not None:
                    extra[col_name] = value

        return DocumentMetadata(
            source_id=source_id,
            source_type=self.config.db_type,
            size_bytes=content_size,
            extra=extra,
        )

    async def _stream_postgresql(self) -> AsyncIterator[tuple[Any, list[str]]]:
        """Stream rows from PostgreSQL using server-side cursor.

        Yields:
            Tuple of (row, column_names).
        """
        async with self._pool.acquire() as conn:
            # Use a transaction for server-side cursor
            async with conn.transaction():
                # Get column names from the query
                stmt = await conn.prepare(self.config.query)
                columns = [attr.name for attr in stmt.get_attributes()]

                # Stream rows using cursor with prefetch
                async for row in stmt.cursor(prefetch=self.config.batch_size):
                    yield row, columns

    async def _stream_mysql(self) -> AsyncIterator[tuple[Any, list[str]]]:
        """Stream rows from MySQL.

        Uses server-side cursors for memory-efficient streaming.

        Yields:
            Tuple of (row, column_names).
        """
        import aiomysql

        async with self._pool.acquire() as conn:
            # Use SSCursor for server-side cursor (unbuffered)
            async with conn.cursor(aiomysql.SSCursor) as cursor:
                await cursor.execute(self.config.query)
                columns = [col[0] for col in cursor.description]

                while True:
                    rows = await cursor.fetchmany(self.config.batch_size)
                    if not rows:
                        break
                    for row in rows:
                        yield row, columns

    async def list_documents(
        self,
        path: str | None = None,
    ) -> AsyncIterator[DocumentMetadata]:
        """List available documents from the query result.

        Note: For databases, the query is executed and metadata is
        extracted without fetching the full content. This is less
        efficient than stream_documents() which fetches everything in one pass.

        Args:
            path: Ignored for database connector (query is in config).

        Yields:
            DocumentMetadata for each row in the query result.

        Raises:
            ConnectionError: If not connected to the database.
        """
        if not self._connected:
            raise ConnectionError("Connector is not connected. Call connect() first.")

        if self.config.db_type == "postgresql":
            stream = self._stream_postgresql()
        else:
            stream = self._stream_mysql()

        async for row, columns in stream:
            # Find column indices
            try:
                id_idx = columns.index(self.config.id_column)
                content_idx = columns.index(self.config.content_column)
            except ValueError as e:
                raise ValueError(
                    f"Configured column not found in query result: {e}",
                ) from e

            source_id = self._generate_source_id(row[id_idx])
            content = self._extract_content(row, content_idx)

            yield self._build_metadata(row, columns, source_id, len(content))

    async def fetch_document(self, source_id: str) -> RawDocument:
        """Fetch a single document by its source ID.

        Note: This requires a separate query execution, which may not be
        efficient for all use cases. Consider using stream_documents()
        instead when processing multiple documents.

        Args:
            source_id: The document's unique identifier from id_column.

        Returns:
            RawDocument containing the document content and metadata.

        Raises:
            ConnectionError: If not connected to the database.
            FileNotFoundError: If the document does not exist.
        """
        if not self._connected:
            raise ConnectionError("Connector is not connected. Call connect() first.")

        # Build a filtered query
        # Note: This is a simple implementation; in production you'd want
        # proper query building with parameterization

        if self.config.db_type == "postgresql":
            return await self._fetch_postgresql(source_id)
        return await self._fetch_mysql(source_id)

    async def _fetch_postgresql(self, source_id: str) -> RawDocument:
        """Fetch a single document from PostgreSQL."""
        async with self._pool.acquire() as conn:
            # Wrap original query to filter by ID
            wrapped_query = f"""
                SELECT * FROM ({self.config.query}) AS subq
                WHERE {self.config.id_column}::text = $1
            """

            row = await conn.fetchrow(wrapped_query, source_id)

            if row is None:
                raise FileNotFoundError(f"Document not found: {source_id}")

            columns = list(row.keys())
            content_idx = columns.index(self.config.content_column)
            content = self._extract_content(row, content_idx)

            metadata = self._build_metadata(row, columns, source_id, len(content))
            return RawDocument(content=content, metadata=metadata)

    async def _fetch_mysql(self, source_id: str) -> RawDocument:
        """Fetch a single document from MySQL."""
        async with self._pool.acquire() as conn, conn.cursor() as cursor:
            # Wrap original query to filter by ID
            wrapped_query = f"""
                    SELECT * FROM ({self.config.query}) AS subq
                    WHERE {self.config.id_column} = %s
                """

            await cursor.execute(wrapped_query, (source_id,))
            row = await cursor.fetchone()

            if row is None:
                raise FileNotFoundError(f"Document not found: {source_id}")

            columns = [col[0] for col in cursor.description]
            content_idx = columns.index(self.config.content_column)
            content = self._extract_content(row, content_idx)

            metadata = self._build_metadata(row, columns, source_id, len(content))
            return RawDocument(content=content, metadata=metadata)

    async def stream_documents(
        self,
        path: str | None = None,
    ) -> AsyncIterator[RawDocument]:
        """Stream all documents from the query result.

        This is the most efficient way to process database documents,
        as it executes the query once and streams results directly.

        Args:
            path: Ignored for database connector (query is in config).

        Yields:
            RawDocument for each row in the query result.

        Raises:
            ConnectionError: If not connected to the database.
        """
        if not self._connected:
            raise ConnectionError("Connector is not connected. Call connect() first.")

        if self.config.db_type == "postgresql":
            stream = self._stream_postgresql()
        else:
            stream = self._stream_mysql()

        async for row, columns in stream:
            try:
                id_idx = columns.index(self.config.id_column)
                content_idx = columns.index(self.config.content_column)
            except ValueError as e:
                raise ValueError(
                    f"Configured column not found in query result: {e}",
                ) from e

            source_id = self._generate_source_id(row[id_idx])
            content = self._extract_content(row, content_idx)
            metadata = self._build_metadata(row, columns, source_id, len(content))

            yield RawDocument(content=content, metadata=metadata)
