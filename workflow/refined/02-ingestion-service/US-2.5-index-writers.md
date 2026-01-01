# US-2.5: Index Writers

> **Story ID:** US-2.5  
> **Epic:** Ingestion Service  
> **Priority:** Critical  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** US-2.4 (Embedding Service)

## User Story

**As a** developer  
**I want** writers for vector and keyword stores  
**So that** documents are searchable

## Context

After chunks are embedded, they must be indexed into the storage layer for retrieval. The architecture specifies three stores:
- **Qdrant** (port 6333): Vector store for semantic search
- **OpenSearch** (port 9200): Keyword store for BM25 search
- **PostgreSQL** (port 5432): Metadata store for document management

All writers must support idempotent operations (upsert), bulk operations for efficiency, and transaction support for consistency.

## Technical Requirements

### Directory Structure

```
ingestion-service/
└── indexing/
    ├── __init__.py
    ├── base.py           # Abstract base class
    ├── qdrant.py         # Vector store writer
    ├── opensearch.py     # Keyword index writer
    ├── postgres.py       # Metadata store writer
    └── coordinator.py    # Coordinates all writers
```

### Data Models

```python
from pydantic import BaseModel, Field
from typing import Optional, Any
from uuid import UUID
from datetime import datetime
from enum import Enum

class IndexedChunk(BaseModel):
    """Chunk ready for indexing with embedding."""
    chunk_id: UUID
    document_id: UUID
    content: str
    embedding: list[float]
    chunk_index: int
    token_count: int
    
    # Parent-child for hierarchical retrieval
    parent_chunk_id: Optional[UUID] = None
    
    # Source tracking
    source_page: Optional[int] = None
    source_section: Optional[str] = None
    
    # Metadata for filtering
    metadata: dict = {}
    
    # ACL fields (architecture requirement)
    tenant_id: str
    visibility: str = "private"  # public, private, group
    allowed_groups: list[str] = []
    allowed_users: list[str] = []

class DocumentRecord(BaseModel):
    """Document metadata for PostgreSQL."""
    document_id: UUID
    source_id: str
    source_type: str
    filename: Optional[str] = None
    mime_type: Optional[str] = None
    title: Optional[str] = None
    author: Optional[str] = None
    
    chunk_count: int = 0
    total_tokens: int = 0
    
    # ACL
    tenant_id: str
    visibility: str = "private"
    allowed_groups: list[str] = []
    allowed_users: list[str] = []
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    indexed_at: Optional[datetime] = None
    
    # Status
    status: str = "pending"  # pending, indexed, failed
    error_message: Optional[str] = None

class WriteResult(BaseModel):
    """Result of a write operation."""
    success: bool
    items_written: int
    items_failed: int
    errors: list[str] = []
    duration_ms: float
```

### Base Writer Interface

```python
from abc import ABC, abstractmethod
from typing import Optional

class BaseIndexWriter(ABC):
    """Abstract base class for index writers."""
    
    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the store."""
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to the store."""
        pass
    
    @abstractmethod
    async def ensure_index(self) -> None:
        """Create index/collection if it doesn't exist."""
        pass
    
    @abstractmethod
    async def write(self, items: list[Any]) -> WriteResult:
        """Write items to the store (upsert)."""
        pass
    
    @abstractmethod
    async def delete(self, ids: list[UUID]) -> WriteResult:
        """Delete items by ID."""
        pass
    
    @abstractmethod
    async def delete_by_document(self, document_id: UUID) -> WriteResult:
        """Delete all chunks belonging to a document."""
        pass
    
    async def __aenter__(self):
        await self.connect()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.disconnect()
```

### 1. Qdrant Writer

Write vectors to Qdrant for semantic search:

```python
from qdrant_client import QdrantClient, AsyncQdrantClient
from qdrant_client.models import (
    Distance, VectorParams, PointStruct,
    Filter, FieldCondition, MatchValue,
    OptimizersConfigDiff, HnswConfigDiff
)

class QdrantWriterConfig(BaseModel):
    url: str = "http://localhost:6333"
    api_key: Optional[str] = None
    collection_name: str = "documents"
    vector_size: int = 1024  # BGE-large dimensions
    distance: str = "Cosine"
    
    # HNSW parameters for quality/speed tradeoff
    hnsw_m: int = 16
    hnsw_ef_construct: int = 100
    
    # Batch settings
    batch_size: int = 100
    
    # Timeout
    timeout: float = 60.0

class QdrantWriter(BaseIndexWriter):
    """
    Write vectors and metadata to Qdrant.
    
    Supports:
    - Upsert (idempotent writes)
    - Bulk operations
    - ACL filtering via payload
    """
    
    def __init__(self, config: QdrantWriterConfig = QdrantWriterConfig()):
        self.config = config
        self._client: Optional[AsyncQdrantClient] = None
    
    async def connect(self) -> None:
        self._client = AsyncQdrantClient(
            url=self.config.url,
            api_key=self.config.api_key,
            timeout=self.config.timeout
        )
    
    async def disconnect(self) -> None:
        if self._client:
            await self._client.close()
    
    async def ensure_index(self) -> None:
        """Create collection if it doesn't exist."""
        collections = await self._client.get_collections()
        collection_names = [c.name for c in collections.collections]
        
        if self.config.collection_name not in collection_names:
            await self._client.create_collection(
                collection_name=self.config.collection_name,
                vectors_config=VectorParams(
                    size=self.config.vector_size,
                    distance=Distance[self.config.distance.upper()]
                ),
                hnsw_config=HnswConfigDiff(
                    m=self.config.hnsw_m,
                    ef_construct=self.config.hnsw_ef_construct
                ),
                optimizers_config=OptimizersConfigDiff(
                    indexing_threshold=20000
                )
            )
            
            # Create payload indices for filtering
            await self._create_payload_indices()
    
    async def _create_payload_indices(self):
        """Create indices on filterable fields."""
        filterable_fields = [
            "document_id",
            "tenant_id",
            "visibility",
            "allowed_groups",
            "allowed_users",
            "source_type"
        ]
        
        for field in filterable_fields:
            await self._client.create_payload_index(
                collection_name=self.config.collection_name,
                field_name=field,
                field_schema="keyword"
            )
    
    async def write(self, chunks: list[IndexedChunk]) -> WriteResult:
        """
        Upsert chunks to Qdrant.
        
        Uses upsert for idempotency - same chunk_id will be updated.
        """
        import time
        start = time.time()
        
        points = []
        for chunk in chunks:
            payload = {
                "document_id": str(chunk.document_id),
                "content": chunk.content,
                "chunk_index": chunk.chunk_index,
                "token_count": chunk.token_count,
                "tenant_id": chunk.tenant_id,
                "visibility": chunk.visibility,
                "allowed_groups": chunk.allowed_groups,
                "allowed_users": chunk.allowed_users,
                **chunk.metadata
            }
            
            if chunk.parent_chunk_id:
                payload["parent_chunk_id"] = str(chunk.parent_chunk_id)
            if chunk.source_page:
                payload["source_page"] = chunk.source_page
            if chunk.source_section:
                payload["source_section"] = chunk.source_section
            
            points.append(PointStruct(
                id=str(chunk.chunk_id),
                vector=chunk.embedding,
                payload=payload
            ))
        
        # Batch upsert
        errors = []
        items_written = 0
        
        for i in range(0, len(points), self.config.batch_size):
            batch = points[i:i + self.config.batch_size]
            try:
                await self._client.upsert(
                    collection_name=self.config.collection_name,
                    points=batch,
                    wait=True
                )
                items_written += len(batch)
            except Exception as e:
                errors.append(f"Batch {i // self.config.batch_size}: {str(e)}")
        
        duration = (time.time() - start) * 1000
        
        return WriteResult(
            success=len(errors) == 0,
            items_written=items_written,
            items_failed=len(chunks) - items_written,
            errors=errors,
            duration_ms=duration
        )
    
    async def delete(self, chunk_ids: list[UUID]) -> WriteResult:
        """Delete chunks by ID."""
        import time
        start = time.time()
        
        try:
            await self._client.delete(
                collection_name=self.config.collection_name,
                points_selector=[str(id) for id in chunk_ids],
                wait=True
            )
            
            return WriteResult(
                success=True,
                items_written=0,
                items_failed=0,
                duration_ms=(time.time() - start) * 1000
            )
        except Exception as e:
            return WriteResult(
                success=False,
                items_written=0,
                items_failed=len(chunk_ids),
                errors=[str(e)],
                duration_ms=(time.time() - start) * 1000
            )
    
    async def delete_by_document(self, document_id: UUID) -> WriteResult:
        """Delete all chunks for a document."""
        import time
        start = time.time()
        
        try:
            await self._client.delete(
                collection_name=self.config.collection_name,
                points_selector=Filter(
                    must=[
                        FieldCondition(
                            key="document_id",
                            match=MatchValue(value=str(document_id))
                        )
                    ]
                ),
                wait=True
            )
            
            return WriteResult(
                success=True,
                items_written=0,
                items_failed=0,
                duration_ms=(time.time() - start) * 1000
            )
        except Exception as e:
            return WriteResult(
                success=False,
                items_written=0,
                items_failed=1,
                errors=[str(e)],
                duration_ms=(time.time() - start) * 1000
            )
```

### 2. OpenSearch Writer

Write to OpenSearch for BM25 keyword search:

```python
from opensearchpy import AsyncOpenSearch

class OpenSearchWriterConfig(BaseModel):
    hosts: list[str] = ["http://localhost:9200"]
    username: Optional[str] = None
    password: Optional[str] = None
    index_name: str = "documents"
    
    # Index settings
    number_of_shards: int = 1
    number_of_replicas: int = 1
    
    # Bulk settings
    batch_size: int = 500
    
    # Timeout
    timeout: int = 30

class OpenSearchWriter(BaseIndexWriter):
    """
    Write chunks to OpenSearch for keyword search.
    
    Uses bulk API for efficient indexing.
    """
    
    def __init__(self, config: OpenSearchWriterConfig = OpenSearchWriterConfig()):
        self.config = config
        self._client: Optional[AsyncOpenSearch] = None
    
    async def connect(self) -> None:
        auth = None
        if self.config.username and self.config.password:
            auth = (self.config.username, self.config.password)
        
        self._client = AsyncOpenSearch(
            hosts=self.config.hosts,
            http_auth=auth,
            timeout=self.config.timeout
        )
    
    async def disconnect(self) -> None:
        if self._client:
            await self._client.close()
    
    async def ensure_index(self) -> None:
        """Create index with appropriate mappings."""
        exists = await self._client.indices.exists(index=self.config.index_name)
        
        if not exists:
            mappings = {
                "settings": {
                    "number_of_shards": self.config.number_of_shards,
                    "number_of_replicas": self.config.number_of_replicas,
                    "analysis": {
                        "analyzer": {
                            "default": {
                                "type": "standard"
                            }
                        }
                    }
                },
                "mappings": {
                    "properties": {
                        "chunk_id": {"type": "keyword"},
                        "document_id": {"type": "keyword"},
                        "content": {
                            "type": "text",
                            "analyzer": "standard"
                        },
                        "chunk_index": {"type": "integer"},
                        "token_count": {"type": "integer"},
                        "tenant_id": {"type": "keyword"},
                        "visibility": {"type": "keyword"},
                        "allowed_groups": {"type": "keyword"},
                        "allowed_users": {"type": "keyword"},
                        "source_type": {"type": "keyword"},
                        "source_page": {"type": "integer"},
                        "source_section": {"type": "keyword"},
                        "created_at": {"type": "date"}
                    }
                }
            }
            
            await self._client.indices.create(
                index=self.config.index_name,
                body=mappings
            )
    
    async def write(self, chunks: list[IndexedChunk]) -> WriteResult:
        """
        Bulk index chunks to OpenSearch.
        
        Uses index action (upsert) for idempotency.
        """
        import time
        from datetime import datetime
        
        start = time.time()
        
        # Prepare bulk actions
        actions = []
        for chunk in chunks:
            action = {"index": {"_index": self.config.index_name, "_id": str(chunk.chunk_id)}}
            doc = {
                "chunk_id": str(chunk.chunk_id),
                "document_id": str(chunk.document_id),
                "content": chunk.content,
                "chunk_index": chunk.chunk_index,
                "token_count": chunk.token_count,
                "tenant_id": chunk.tenant_id,
                "visibility": chunk.visibility,
                "allowed_groups": chunk.allowed_groups,
                "allowed_users": chunk.allowed_users,
                "created_at": datetime.utcnow().isoformat(),
                **chunk.metadata
            }
            
            if chunk.parent_chunk_id:
                doc["parent_chunk_id"] = str(chunk.parent_chunk_id)
            if chunk.source_page:
                doc["source_page"] = chunk.source_page
            if chunk.source_section:
                doc["source_section"] = chunk.source_section
            
            actions.append(action)
            actions.append(doc)
        
        # Execute bulk in batches
        errors = []
        items_written = 0
        items_per_batch = self.config.batch_size * 2  # action + doc pairs
        
        for i in range(0, len(actions), items_per_batch):
            batch = actions[i:i + items_per_batch]
            try:
                response = await self._client.bulk(body=batch, refresh=True)
                
                if response.get("errors"):
                    for item in response["items"]:
                        if "error" in item.get("index", {}):
                            errors.append(str(item["index"]["error"]))
                        else:
                            items_written += 1
                else:
                    items_written += len(batch) // 2
                    
            except Exception as e:
                errors.append(f"Batch {i // items_per_batch}: {str(e)}")
        
        duration = (time.time() - start) * 1000
        
        return WriteResult(
            success=len(errors) == 0,
            items_written=items_written,
            items_failed=len(chunks) - items_written,
            errors=errors,
            duration_ms=duration
        )
    
    async def delete(self, chunk_ids: list[UUID]) -> WriteResult:
        """Delete chunks by ID using bulk delete."""
        import time
        start = time.time()
        
        actions = []
        for chunk_id in chunk_ids:
            actions.append({"delete": {"_index": self.config.index_name, "_id": str(chunk_id)}})
        
        try:
            response = await self._client.bulk(body=actions, refresh=True)
            
            errors = []
            if response.get("errors"):
                for item in response["items"]:
                    if "error" in item.get("delete", {}):
                        errors.append(str(item["delete"]["error"]))
            
            return WriteResult(
                success=len(errors) == 0,
                items_written=0,
                items_failed=len(errors),
                errors=errors,
                duration_ms=(time.time() - start) * 1000
            )
        except Exception as e:
            return WriteResult(
                success=False,
                items_written=0,
                items_failed=len(chunk_ids),
                errors=[str(e)],
                duration_ms=(time.time() - start) * 1000
            )
    
    async def delete_by_document(self, document_id: UUID) -> WriteResult:
        """Delete all chunks for a document using delete by query."""
        import time
        start = time.time()
        
        try:
            response = await self._client.delete_by_query(
                index=self.config.index_name,
                body={
                    "query": {
                        "term": {"document_id": str(document_id)}
                    }
                },
                refresh=True
            )
            
            return WriteResult(
                success=True,
                items_written=0,
                items_failed=0,
                duration_ms=(time.time() - start) * 1000
            )
        except Exception as e:
            return WriteResult(
                success=False,
                items_written=0,
                items_failed=1,
                errors=[str(e)],
                duration_ms=(time.time() - start) * 1000
            )
```

### 3. PostgreSQL Writer

Write document metadata to PostgreSQL:

```python
import asyncpg
from typing import Optional

class PostgresWriterConfig(BaseModel):
    connection_string: str = "postgresql://localhost:5432/rag_pipeline"
    min_pool_size: int = 2
    max_pool_size: int = 10
    table_name: str = "documents"

class PostgresWriter(BaseIndexWriter):
    """
    Write document metadata to PostgreSQL.
    
    Provides ACID transactions for document management.
    """
    
    def __init__(self, config: PostgresWriterConfig = PostgresWriterConfig()):
        self.config = config
        self._pool: Optional[asyncpg.Pool] = None
    
    async def connect(self) -> None:
        self._pool = await asyncpg.create_pool(
            self.config.connection_string,
            min_size=self.config.min_pool_size,
            max_size=self.config.max_pool_size
        )
    
    async def disconnect(self) -> None:
        if self._pool:
            await self._pool.close()
    
    async def ensure_index(self) -> None:
        """Create table and indices if they don't exist."""
        async with self._pool.acquire() as conn:
            await conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {self.config.table_name} (
                    document_id UUID PRIMARY KEY,
                    source_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    filename TEXT,
                    mime_type TEXT,
                    title TEXT,
                    author TEXT,
                    chunk_count INTEGER DEFAULT 0,
                    total_tokens INTEGER DEFAULT 0,
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
            
            # Create indices
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self.config.table_name}_tenant 
                ON {self.config.table_name}(tenant_id)
            """)
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self.config.table_name}_source 
                ON {self.config.table_name}(source_id)
            """)
            await conn.execute(f"""
                CREATE INDEX IF NOT EXISTS idx_{self.config.table_name}_status 
                ON {self.config.table_name}(status)
            """)
    
    async def write(self, documents: list[DocumentRecord]) -> WriteResult:
        """
        Upsert document records.
        
        Uses INSERT ... ON CONFLICT for idempotency.
        """
        import time
        import json
        
        start = time.time()
        errors = []
        items_written = 0
        
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for doc in documents:
                    try:
                        await conn.execute(f"""
                            INSERT INTO {self.config.table_name} (
                                document_id, source_id, source_type, filename,
                                mime_type, title, author, chunk_count, total_tokens,
                                tenant_id, visibility, allowed_groups, allowed_users,
                                created_at, updated_at, indexed_at, status, error_message
                            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15, $16, $17, $18)
                            ON CONFLICT (document_id) DO UPDATE SET
                                source_id = EXCLUDED.source_id,
                                source_type = EXCLUDED.source_type,
                                filename = EXCLUDED.filename,
                                mime_type = EXCLUDED.mime_type,
                                title = EXCLUDED.title,
                                author = EXCLUDED.author,
                                chunk_count = EXCLUDED.chunk_count,
                                total_tokens = EXCLUDED.total_tokens,
                                visibility = EXCLUDED.visibility,
                                allowed_groups = EXCLUDED.allowed_groups,
                                allowed_users = EXCLUDED.allowed_users,
                                updated_at = NOW(),
                                indexed_at = EXCLUDED.indexed_at,
                                status = EXCLUDED.status,
                                error_message = EXCLUDED.error_message
                        """,
                            doc.document_id,
                            doc.source_id,
                            doc.source_type,
                            doc.filename,
                            doc.mime_type,
                            doc.title,
                            doc.author,
                            doc.chunk_count,
                            doc.total_tokens,
                            doc.tenant_id,
                            doc.visibility,
                            doc.allowed_groups,
                            doc.allowed_users,
                            doc.created_at,
                            doc.updated_at,
                            doc.indexed_at,
                            doc.status,
                            doc.error_message
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
            duration_ms=duration
        )
    
    async def delete(self, document_ids: list[UUID]) -> WriteResult:
        """Delete documents by ID."""
        import time
        start = time.time()
        
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(f"""
                    DELETE FROM {self.config.table_name}
                    WHERE document_id = ANY($1)
                """, document_ids)
            
            return WriteResult(
                success=True,
                items_written=0,
                items_failed=0,
                duration_ms=(time.time() - start) * 1000
            )
        except Exception as e:
            return WriteResult(
                success=False,
                items_written=0,
                items_failed=len(document_ids),
                errors=[str(e)],
                duration_ms=(time.time() - start) * 1000
            )
    
    async def delete_by_document(self, document_id: UUID) -> WriteResult:
        """Delete single document."""
        return await self.delete([document_id])
    
    async def update_status(
        self,
        document_id: UUID,
        status: str,
        error_message: Optional[str] = None
    ):
        """Update document indexing status."""
        from datetime import datetime
        
        async with self._pool.acquire() as conn:
            await conn.execute(f"""
                UPDATE {self.config.table_name}
                SET status = $1,
                    error_message = $2,
                    indexed_at = CASE WHEN $1 = 'indexed' THEN $3 ELSE indexed_at END,
                    updated_at = $3
                WHERE document_id = $4
            """, status, error_message, datetime.utcnow(), document_id)
```

### 4. Index Coordinator

Coordinate writes across all stores:

```python
import asyncio
from typing import Optional

class IndexCoordinator:
    """
    Coordinates writes to all index stores.
    
    Ensures consistency across Qdrant, OpenSearch, and PostgreSQL.
    """
    
    def __init__(
        self,
        qdrant: QdrantWriter,
        opensearch: OpenSearchWriter,
        postgres: PostgresWriter
    ):
        self.qdrant = qdrant
        self.opensearch = opensearch
        self.postgres = postgres
    
    async def ensure_indices(self):
        """Create all indices/tables."""
        await asyncio.gather(
            self.qdrant.ensure_index(),
            self.opensearch.ensure_index(),
            self.postgres.ensure_index()
        )
    
    async def index_document(
        self,
        document: DocumentRecord,
        chunks: list[IndexedChunk]
    ) -> dict[str, WriteResult]:
        """
        Index a document and its chunks to all stores.
        
        Writes to all stores in parallel, then updates document status.
        """
        # Write to all stores in parallel
        qdrant_result, opensearch_result, postgres_result = await asyncio.gather(
            self.qdrant.write(chunks),
            self.opensearch.write(chunks),
            self.postgres.write([document]),
            return_exceptions=True
        )
        
        results = {
            "qdrant": qdrant_result if not isinstance(qdrant_result, Exception) 
                      else WriteResult(success=False, items_written=0, items_failed=len(chunks), 
                                       errors=[str(qdrant_result)], duration_ms=0),
            "opensearch": opensearch_result if not isinstance(opensearch_result, Exception)
                          else WriteResult(success=False, items_written=0, items_failed=len(chunks),
                                           errors=[str(opensearch_result)], duration_ms=0),
            "postgres": postgres_result if not isinstance(postgres_result, Exception)
                        else WriteResult(success=False, items_written=0, items_failed=1,
                                         errors=[str(postgres_result)], duration_ms=0)
        }
        
        # Update document status based on results
        all_success = all(r.success for r in results.values())
        status = "indexed" if all_success else "failed"
        error_msg = None if all_success else "; ".join(
            f"{store}: {r.errors}" for store, r in results.items() if not r.success
        )
        
        await self.postgres.update_status(document.document_id, status, error_msg)
        
        return results
    
    async def delete_document(self, document_id: UUID) -> dict[str, WriteResult]:
        """Delete document from all stores."""
        qdrant_result, opensearch_result, postgres_result = await asyncio.gather(
            self.qdrant.delete_by_document(document_id),
            self.opensearch.delete_by_document(document_id),
            self.postgres.delete([document_id]),
            return_exceptions=True
        )
        
        return {
            "qdrant": qdrant_result if not isinstance(qdrant_result, Exception)
                      else WriteResult(success=False, items_written=0, items_failed=1,
                                       errors=[str(qdrant_result)], duration_ms=0),
            "opensearch": opensearch_result if not isinstance(opensearch_result, Exception)
                          else WriteResult(success=False, items_written=0, items_failed=1,
                                           errors=[str(opensearch_result)], duration_ms=0),
            "postgres": postgres_result if not isinstance(postgres_result, Exception)
                        else WriteResult(success=False, items_written=0, items_failed=1,
                                         errors=[str(postgres_result)], duration_ms=0)
        }
```

## Acceptance Criteria

- [ ] `QdrantWriter` upserts vectors with ACL payload fields
- [ ] `QdrantWriter` creates payload indices for filtering
- [ ] `OpenSearchWriter` uses bulk API for efficient indexing
- [ ] `OpenSearchWriter` index has appropriate text mappings
- [ ] `PostgresWriter` creates table with all required columns
- [ ] `PostgresWriter` uses ON CONFLICT for idempotent upserts
- [ ] All writers support delete by chunk ID and document ID
- [ ] `IndexCoordinator` writes to all stores in parallel
- [ ] `IndexCoordinator` updates document status after indexing
- [ ] Transaction support for consistency (PostgreSQL)
- [ ] Error handling with detailed error messages

## Testing Requirements

```python
import pytest
from testcontainers.qdrant import QdrantContainer
from testcontainers.opensearch import OpenSearchContainer
from testcontainers.postgres import PostgresContainer
from uuid import uuid4

@pytest.fixture
async def qdrant_writer(qdrant_container):
    config = QdrantWriterConfig(url=qdrant_container.get_url())
    writer = QdrantWriter(config)
    await writer.connect()
    await writer.ensure_index()
    yield writer
    await writer.disconnect()

@pytest.mark.asyncio
async def test_qdrant_upsert_is_idempotent(qdrant_writer):
    chunk = IndexedChunk(
        chunk_id=uuid4(),
        document_id=uuid4(),
        content="Test content",
        embedding=[0.1] * 1024,
        chunk_index=0,
        token_count=10,
        tenant_id="tenant-1"
    )
    
    # Write twice
    result1 = await qdrant_writer.write([chunk])
    result2 = await qdrant_writer.write([chunk])
    
    assert result1.success
    assert result2.success
    assert result1.items_written == 1
    assert result2.items_written == 1  # Upsert, not duplicate

@pytest.mark.asyncio
async def test_opensearch_bulk_write(opensearch_writer):
    chunks = [
        IndexedChunk(
            chunk_id=uuid4(),
            document_id=uuid4(),
            content=f"Test content {i}",
            embedding=[0.1] * 1024,
            chunk_index=i,
            token_count=10,
            tenant_id="tenant-1"
        )
        for i in range(100)
    ]
    
    result = await opensearch_writer.write(chunks)
    
    assert result.success
    assert result.items_written == 100

@pytest.mark.asyncio
async def test_coordinator_parallel_writes(index_coordinator):
    document = DocumentRecord(
        document_id=uuid4(),
        source_id="test.pdf",
        source_type="filesystem",
        tenant_id="tenant-1",
        chunk_count=1,
        total_tokens=10
    )
    
    chunks = [IndexedChunk(
        chunk_id=uuid4(),
        document_id=document.document_id,
        content="Test",
        embedding=[0.1] * 1024,
        chunk_index=0,
        token_count=10,
        tenant_id="tenant-1"
    )]
    
    results = await index_coordinator.index_document(document, chunks)
    
    assert results["qdrant"].success
    assert results["opensearch"].success
    assert results["postgres"].success
```

## Dependencies

- `qdrant-client>=1.7.0`
- `opensearch-py>=2.4.0`
- `asyncpg>=0.29.0`
- `pydantic>=2.0.0`

## Definition of Done

- [ ] All writers implemented with upsert support
- [ ] Bulk operations for efficiency
- [ ] ACL fields indexed for filtering
- [ ] Delete operations work correctly
- [ ] Coordinator handles parallel writes
- [ ] Status tracking in PostgreSQL
- [ ] >90% test coverage
- [ ] Integration tests with real services
- [ ] Docstrings on all public methods
- [ ] Type hints validated with mypy
