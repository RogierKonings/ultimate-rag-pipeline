# US-2.8: Ingestion API

> **Story ID:** US-2.8  
> **Epic:** Ingestion Service  
> **Priority:** Critical  
> **Estimated Effort:** 2 days  
> **Dependencies:** US-2.1 through US-2.7

## User Story

**As an** API consumer  
**I want** REST endpoints for ingestion  
**So that** I can trigger and monitor ingestion jobs

## Context

The Ingestion Service exposes a REST API on port 8001 (per architecture). The API allows users to trigger ingestion jobs, monitor their status, and manage documents. The architecture specifies FastAPI with Pydantic v2 for request/response validation and automatic OpenAPI documentation.

## Technical Requirements

### Directory Structure

```
ingestion-service/
├── api/
│   ├── __init__.py
│   ├── main.py           # FastAPI app
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── ingest.py     # Ingestion endpoints
│   │   └── documents.py  # Document management
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── ingest.py     # Request/response models
│   │   └── documents.py  # Document models
│   ├── dependencies.py   # Dependency injection
│   └── middleware.py     # Custom middleware
├── config.py             # Application configuration
└── __init__.py
```

### API Schemas

```python
# api/schemas/ingest.py
from pydantic import BaseModel, Field, field_validator
from typing import Optional, Any, Literal
from uuid import UUID, uuid4
from datetime import datetime
from enum import Enum

class SourceType(str, Enum):
    FILESYSTEM = "filesystem"
    DATABASE = "database"
    WEB = "web"
    API = "api"

class ChunkingStrategy(str, Enum):
    RECURSIVE = "recursive"
    SEMANTIC = "semantic"
    HIERARCHICAL = "hierarchical"

# --- Ingestion Request ---

class FilesystemSourceConfig(BaseModel):
    path: str
    storage_type: Literal["local", "s3"] = "local"
    s3_endpoint: Optional[str] = None
    s3_bucket: Optional[str] = None
    recursive: bool = True
    file_extensions: Optional[list[str]] = None

class DatabaseSourceConfig(BaseModel):
    connection_string: str
    db_type: Literal["postgresql", "mysql"]
    query: str
    content_column: str
    id_column: str
    metadata_columns: list[str] = []

class WebSourceConfig(BaseModel):
    start_urls: list[str]
    allowed_domains: Optional[list[str]] = None
    max_depth: int = 2
    max_pages: int = 100

class APISourceConfig(BaseModel):
    base_url: str
    list_endpoint: str
    fetch_endpoint: str
    auth_type: Literal["none", "bearer", "api_key", "basic"] = "none"
    auth_token: Optional[str] = None

class ProcessingOptions(BaseModel):
    chunking_strategy: ChunkingStrategy = ChunkingStrategy.SEMANTIC
    chunk_size: int = Field(default=512, ge=100, le=4096)
    chunk_overlap: int = Field(default=50, ge=0, le=500)
    enable_pii_detection: bool = True
    custom_metadata: dict[str, Any] = {}

class ACLContext(BaseModel):
    tenant_id: str
    visibility: Literal["public", "private", "group"] = "private"
    allowed_groups: list[str] = []
    allowed_users: list[str] = []

class IngestRequest(BaseModel):
    """Request to start an ingestion job."""
    source_type: SourceType
    source_config: dict[str, Any]  # Validated based on source_type
    processing: ProcessingOptions = ProcessingOptions()
    acl: ACLContext
    
    @field_validator("source_config")
    @classmethod
    def validate_source_config(cls, v, info):
        source_type = info.data.get("source_type")
        if source_type == SourceType.FILESYSTEM:
            FilesystemSourceConfig(**v)
        elif source_type == SourceType.DATABASE:
            DatabaseSourceConfig(**v)
        elif source_type == SourceType.WEB:
            WebSourceConfig(**v)
        elif source_type == SourceType.API:
            APISourceConfig(**v)
        return v

class IngestResponse(BaseModel):
    """Response after starting an ingestion job."""
    job_id: UUID
    status: str
    message: str
    created_at: datetime = Field(default_factory=datetime.utcnow)

# --- Job Status ---

class JobProgress(BaseModel):
    current: int = 0
    total: int = 0
    stage: str = ""
    percentage: float = 0.0

class JobStatus(str, Enum):
    PENDING = "pending"
    STARTED = "started"
    PROGRESS = "progress"
    SUCCESS = "success"
    FAILURE = "failure"
    REVOKED = "revoked"

class JobStatusResponse(BaseModel):
    """Response for job status query."""
    job_id: UUID
    status: JobStatus
    progress: Optional[JobProgress] = None
    documents_processed: int = 0
    chunks_created: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    error_message: Optional[str] = None
    errors: list[str] = []

# --- Document Schemas ---

class DocumentResponse(BaseModel):
    """Document metadata response."""
    document_id: UUID
    source_id: str
    source_type: str
    filename: Optional[str] = None
    mime_type: Optional[str] = None
    title: Optional[str] = None
    author: Optional[str] = None
    chunk_count: int
    total_tokens: int
    tenant_id: str
    visibility: str
    created_at: datetime
    updated_at: datetime
    indexed_at: Optional[datetime] = None
    status: str

class DocumentListResponse(BaseModel):
    """Paginated document list response."""
    documents: list[DocumentResponse]
    total: int
    page: int
    page_size: int
    pages: int

class DocumentDeleteResponse(BaseModel):
    """Response after deleting a document."""
    document_id: UUID
    deleted: bool
    chunks_deleted: int
    message: str
```

### FastAPI Application

```python
# api/main.py
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
import logging

from .routes import ingest, documents
from .middleware import RequestLoggingMiddleware, TenantMiddleware
from config import Settings

logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting Ingestion Service...")
    
    # Initialize connections
    await initialize_connections()
    
    yield
    
    # Shutdown
    logger.info("Shutting down Ingestion Service...")
    await close_connections()

def create_app(settings: Settings = None) -> FastAPI:
    """Create and configure FastAPI application."""
    settings = settings or Settings()
    
    app = FastAPI(
        title="RAG Pipeline Ingestion Service",
        description="Document ingestion and indexing API",
        version="1.0.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan
    )
    
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # Custom middleware
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(TenantMiddleware)
    
    # Include routers
    app.include_router(
        ingest.router,
        prefix="/ingest",
        tags=["Ingestion"]
    )
    app.include_router(
        documents.router,
        prefix="/documents",
        tags=["Documents"]
    )
    
    # Health check endpoint
    @app.get("/health", tags=["Health"])
    async def health_check():
        return {"status": "healthy", "service": "ingestion"}
    
    # Exception handlers
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception(f"Unhandled exception: {exc}")
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"}
        )
    
    return app

app = create_app()
```

### Ingestion Routes

```python
# api/routes/ingest.py
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from uuid import UUID
from typing import Optional

from ..schemas.ingest import (
    IngestRequest, IngestResponse,
    JobStatusResponse, JobStatus
)
from ..dependencies import get_job_tracker, get_current_user
from tasks.ingest import process_document, batch_ingest

router = APIRouter()

@router.post(
    "",
    response_model=IngestResponse,
    status_code=202,
    summary="Start ingestion job",
    description="Trigger an async ingestion job for documents from the specified source."
)
async def start_ingestion(
    request: IngestRequest,
    current_user: dict = Depends(get_current_user)
):
    """
    Start a new ingestion job.
    
    The job runs asynchronously and returns immediately with a job ID
    that can be used to track progress.
    
    **Source Types:**
    - `filesystem`: Ingest from local files or S3
    - `database`: Ingest from PostgreSQL or MySQL
    - `web`: Crawl and ingest web pages
    - `api`: Ingest from REST API
    
    **Returns:**
    - `job_id`: UUID to track the job
    - `status`: Initial status (always "pending")
    """
    # Validate tenant access
    if request.acl.tenant_id != current_user.get("tenant_id"):
        raise HTTPException(
            status_code=403,
            detail="Cannot ingest documents for another tenant"
        )
    
    # Start async job
    task = batch_ingest.delay(
        job_id=str(UUID()),
        source_type=request.source_type.value,
        source_config=request.source_config,
        processing_config=request.processing.model_dump(),
        acl_context=request.acl.model_dump()
    )
    
    return IngestResponse(
        job_id=UUID(task.id),
        status="pending",
        message="Ingestion job started"
    )


@router.post(
    "/single",
    response_model=IngestResponse,
    status_code=202,
    summary="Ingest single document",
    description="Ingest a single document by source ID."
)
async def ingest_single_document(
    source_type: str,
    source_id: str,
    source_config: dict,
    processing: ProcessingOptions = ProcessingOptions(),
    acl: ACLContext = Depends(),
    current_user: dict = Depends(get_current_user)
):
    """
    Ingest a single document.
    
    Useful for incremental ingestion or re-processing specific documents.
    """
    task = process_document.delay(
        document_source_id=source_id,
        source_type=source_type,
        source_config=source_config,
        processing_config=processing.model_dump(),
        acl_context=acl.model_dump()
    )
    
    return IngestResponse(
        job_id=UUID(task.id),
        status="pending",
        message="Document ingestion started"
    )


@router.get(
    "/{job_id}",
    response_model=JobStatusResponse,
    summary="Get job status",
    description="Get the current status and progress of an ingestion job."
)
async def get_job_status(
    job_id: UUID,
    job_tracker = Depends(get_job_tracker)
):
    """
    Get the status of an ingestion job.
    
    **Status Values:**
    - `pending`: Job is queued
    - `started`: Job has started processing
    - `progress`: Job is in progress (check `progress` field)
    - `success`: Job completed successfully
    - `failure`: Job failed (check `error_message`)
    - `revoked`: Job was cancelled
    """
    status = await job_tracker.get_job_status(str(job_id))
    
    if status is None:
        raise HTTPException(
            status_code=404,
            detail=f"Job {job_id} not found"
        )
    
    # Calculate percentage if in progress
    progress = None
    if status.progress and status.progress.total > 0:
        progress = JobProgress(
            current=status.progress.current,
            total=status.progress.total,
            stage=status.progress.stage,
            percentage=round(status.progress.current / status.progress.total * 100, 1)
        )
    
    return JobStatusResponse(
        job_id=job_id,
        status=status.status,
        progress=progress,
        documents_processed=status.documents_processed,
        chunks_created=status.chunks_created,
        started_at=status.started_at,
        completed_at=status.completed_at,
        duration_seconds=status.duration_seconds,
        error_message=status.error_message,
        errors=status.errors
    )


@router.delete(
    "/{job_id}",
    summary="Cancel job",
    description="Cancel a running or pending ingestion job."
)
async def cancel_job(
    job_id: UUID,
    job_tracker = Depends(get_job_tracker)
):
    """
    Cancel an ingestion job.
    
    Only pending and running jobs can be cancelled.
    """
    status = await job_tracker.get_job_status(str(job_id))
    
    if status is None:
        raise HTTPException(
            status_code=404,
            detail=f"Job {job_id} not found"
        )
    
    if status.status in [JobStatus.SUCCESS, JobStatus.FAILURE]:
        raise HTTPException(
            status_code=400,
            detail="Cannot cancel a completed job"
        )
    
    success = await job_tracker.cancel_job(str(job_id))
    
    return {"job_id": job_id, "cancelled": success}


@router.get(
    "",
    summary="List active jobs",
    description="List all active ingestion jobs."
)
async def list_active_jobs(
    job_tracker = Depends(get_job_tracker),
    current_user: dict = Depends(get_current_user)
):
    """
    List all currently active ingestion jobs.
    
    Returns job IDs that are pending, started, or in progress.
    """
    job_ids = await job_tracker.list_active_jobs()
    
    # Get status for each job
    jobs = []
    for job_id in job_ids:
        status = await job_tracker.get_job_status(job_id)
        if status:
            jobs.append(status)
    
    return {"jobs": jobs, "total": len(jobs)}
```

### Document Management Routes

```python
# api/routes/documents.py
from fastapi import APIRouter, HTTPException, Depends, Query
from uuid import UUID
from typing import Optional

from ..schemas.ingest import (
    DocumentResponse, DocumentListResponse, DocumentDeleteResponse
)
from ..dependencies import get_document_service, get_current_user

router = APIRouter()

@router.get(
    "",
    response_model=DocumentListResponse,
    summary="List documents",
    description="List all indexed documents with pagination and filtering."
)
async def list_documents(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    source_type: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
    document_service = Depends(get_document_service),
    current_user: dict = Depends(get_current_user)
):
    """
    List indexed documents.
    
    **Filters:**
    - `source_type`: Filter by source (filesystem, database, web, api)
    - `status`: Filter by status (pending, indexed, failed)
    - `search`: Search in title, filename, or source_id
    
    **Pagination:**
    - `page`: Page number (1-indexed)
    - `page_size`: Items per page (max 100)
    """
    tenant_id = current_user.get("tenant_id")
    
    result = await document_service.list_documents(
        tenant_id=tenant_id,
        page=page,
        page_size=page_size,
        source_type=source_type,
        status=status,
        search=search
    )
    
    return DocumentListResponse(
        documents=result.documents,
        total=result.total,
        page=page,
        page_size=page_size,
        pages=(result.total + page_size - 1) // page_size
    )


@router.get(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Get document",
    description="Get metadata for a specific document."
)
async def get_document(
    document_id: UUID,
    document_service = Depends(get_document_service),
    current_user: dict = Depends(get_current_user)
):
    """
    Get document metadata by ID.
    
    Returns document properties, chunk count, and indexing status.
    """
    tenant_id = current_user.get("tenant_id")
    
    document = await document_service.get_document(document_id, tenant_id)
    
    if document is None:
        raise HTTPException(
            status_code=404,
            detail=f"Document {document_id} not found"
        )
    
    return document


@router.delete(
    "/{document_id}",
    response_model=DocumentDeleteResponse,
    summary="Delete document",
    description="Delete a document and all its chunks from the index."
)
async def delete_document(
    document_id: UUID,
    hard_delete: bool = Query(default=True, description="If False, marks as deleted instead of removing"),
    document_service = Depends(get_document_service),
    current_user: dict = Depends(get_current_user)
):
    """
    Delete a document and all associated chunks (cascade delete).
    
    This removes the document from:
    - PostgreSQL (metadata and chunk records)
    - Qdrant (vector embeddings)
    - OpenSearch (keyword index)
    - MinIO/S3 (original document file, if stored)
    
    **Deletion Strategy:**
    - `hard_delete=True`: Permanently removes all data (default)
    - `hard_delete=False`: Soft delete - marks as deleted but retains data
    
    **Cascade Order:**
    1. Mark document as "deleting" in PostgreSQL (prevents queries)
    2. Delete vectors from Qdrant by document_id filter
    3. Delete keyword index entries from OpenSearch
    4. Delete chunk records from PostgreSQL
    5. Delete document record from PostgreSQL
    6. Delete raw file from object storage (if applicable)
    
    This operation cannot be undone for hard deletes.
    """
    tenant_id = current_user.get("tenant_id")
    
    # Verify document exists and belongs to tenant
    document = await document_service.get_document(document_id, tenant_id)
    
    if document is None:
        raise HTTPException(
            status_code=404,
            detail=f"Document {document_id} not found"
        )
    
    # Execute cascade delete
    result = await document_service.delete_document(
        document_id, 
        hard_delete=hard_delete
    )
    
    return DocumentDeleteResponse(
        document_id=document_id,
        deleted=result.success,
        chunks_deleted=result.chunks_deleted,
        message="Document deleted successfully" if result.success else f"Deletion failed: {result.error}"
    )
```

### Document Deletion Cascade Implementation

The `DocumentService.delete_document()` method implements a transactional cascade delete:

```python
# services/documents.py
from dataclasses import dataclass
from uuid import UUID
import logging
from typing import Optional

logger = logging.getLogger(__name__)

@dataclass
class DeleteResult:
    success: bool
    chunks_deleted: int
    vectors_deleted: int
    keyword_entries_deleted: int
    error: Optional[str] = None

class DocumentService:
    """Service for managing documents with cascade operations."""
    
    def __init__(
        self,
        db: AsyncSession,
        qdrant_client: QdrantClient,
        opensearch_client: OpenSearchClient,
        storage_client: StorageClient
    ):
        self.db = db
        self.qdrant = qdrant_client
        self.opensearch = opensearch_client
        self.storage = storage_client
    
    async def delete_document(
        self,
        document_id: UUID,
        hard_delete: bool = True
    ) -> DeleteResult:
        """
        Delete document with cascade to all data stores.
        
        Uses a transactional approach:
        1. If any step fails, attempt rollback where possible
        2. Log all operations for audit trail
        3. Return detailed result for observability
        """
        chunks_deleted = 0
        vectors_deleted = 0
        keyword_entries_deleted = 0
        
        try:
            # Step 1: Mark document as deleting (prevents new queries)
            await self._mark_document_deleting(document_id)
            logger.info(f"Document {document_id} marked as deleting")
            
            # Step 2: Get all chunk IDs for this document
            chunk_ids = await self._get_chunk_ids(document_id)
            logger.info(f"Found {len(chunk_ids)} chunks for document {document_id}")
            
            # Step 3: Delete vectors from Qdrant
            try:
                vectors_deleted = await self._delete_vectors(document_id, chunk_ids)
                logger.info(f"Deleted {vectors_deleted} vectors from Qdrant")
            except Exception as e:
                logger.error(f"Failed to delete vectors: {e}")
                # Continue with other deletions - vectors can be orphaned
            
            # Step 4: Delete keyword entries from OpenSearch
            try:
                keyword_entries_deleted = await self._delete_keyword_entries(
                    document_id, chunk_ids
                )
                logger.info(f"Deleted {keyword_entries_deleted} entries from OpenSearch")
            except Exception as e:
                logger.error(f"Failed to delete keyword entries: {e}")
                # Continue with other deletions
            
            # Step 5: Delete chunks from PostgreSQL
            if hard_delete:
                chunks_deleted = await self._hard_delete_chunks(document_id)
            else:
                chunks_deleted = await self._soft_delete_chunks(document_id)
            logger.info(f"Deleted {chunks_deleted} chunks from PostgreSQL")
            
            # Step 6: Delete document record from PostgreSQL
            if hard_delete:
                await self._hard_delete_document(document_id)
            else:
                await self._soft_delete_document(document_id)
            logger.info(f"Deleted document record {document_id}")
            
            # Step 7: Delete raw file from object storage (if exists)
            try:
                await self._delete_raw_file(document_id)
            except Exception as e:
                logger.warning(f"Failed to delete raw file (may not exist): {e}")
            
            # Commit transaction
            await self.db.commit()
            
            return DeleteResult(
                success=True,
                chunks_deleted=chunks_deleted,
                vectors_deleted=vectors_deleted,
                keyword_entries_deleted=keyword_entries_deleted
            )
            
        except Exception as e:
            logger.error(f"Document deletion failed: {e}")
            await self.db.rollback()
            
            # Attempt to restore document status
            try:
                await self._restore_document_status(document_id)
            except:
                pass
            
            return DeleteResult(
                success=False,
                chunks_deleted=0,
                vectors_deleted=0,
                keyword_entries_deleted=0,
                error=str(e)
            )
    
    async def _delete_vectors(
        self,
        document_id: UUID,
        chunk_ids: list[UUID]
    ) -> int:
        """Delete vectors from Qdrant using document_id filter."""
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        
        # Delete by document_id filter (more efficient than individual deletes)
        result = await self.qdrant.delete(
            collection_name="rag_chunks",
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="document_id",
                        match=MatchValue(value=str(document_id))
                    )
                ]
            )
        )
        
        return len(chunk_ids)  # Qdrant doesn't return count
    
    async def _delete_keyword_entries(
        self,
        document_id: UUID,
        chunk_ids: list[UUID]
    ) -> int:
        """Delete entries from OpenSearch index."""
        # Delete by query matching document_id
        response = await self.opensearch.delete_by_query(
            index="rag_chunks",
            body={
                "query": {
                    "term": {
                        "document_id": str(document_id)
                    }
                }
            }
        )
        
        return response.get("deleted", 0)
    
    async def _delete_raw_file(self, document_id: UUID):
        """Delete original document from object storage."""
        # Get document to find raw_storage_path
        doc = await self.db.execute(
            select(SourceDocument.raw_storage_path)
            .where(SourceDocument.id == document_id)
        )
        result = doc.scalar_one_or_none()
        
        if result:
            await self.storage.delete(result)
```

### Soft Delete Support

For compliance and audit requirements, soft delete preserves data:

```python
async def _soft_delete_document(self, document_id: UUID):
    """Mark document as deleted without removing data."""
    await self.db.execute(
        update(SourceDocument)
        .where(SourceDocument.id == document_id)
        .values(
            status="deleted",
            deleted_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
    )

async def _soft_delete_chunks(self, document_id: UUID) -> int:
    """Mark chunks as deleted without removing data."""
    result = await self.db.execute(
        update(Chunk)
        .where(Chunk.document_id == document_id)
        .values(
            status="deleted",
            deleted_at=datetime.utcnow()
        )
    )
    return result.rowcount
```


@router.post(
    "/{document_id}/reindex",
    response_model=IngestResponse,
    status_code=202,
    summary="Reindex document",
    description="Re-process and reindex an existing document."
)
async def reindex_document(
    document_id: UUID,
    processing: Optional[ProcessingOptions] = None,
    document_service = Depends(get_document_service),
    current_user: dict = Depends(get_current_user)
):
    """
    Reindex an existing document.
    
    Useful when:
    - Chunking strategy changed
    - Embedding model updated
    - Document content was updated at source
    
    The document is re-fetched, re-processed, and re-indexed.
    """
    tenant_id = current_user.get("tenant_id")
    
    document = await document_service.get_document(document_id, tenant_id)
    
    if document is None:
        raise HTTPException(
            status_code=404,
            detail=f"Document {document_id} not found"
        )
    
    # Start reindex job
    task = await document_service.reindex_document(
        document_id,
        processing.model_dump() if processing else None
    )
    
    return IngestResponse(
        job_id=UUID(task.id),
        status="pending",
        message="Reindexing started"
    )
```

### Dependencies

```python
# api/dependencies.py
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Optional
import jwt

from tasks.callbacks import JobStatusTracker
from services.documents import DocumentService
from config import Settings

settings = Settings()
security = HTTPBearer(auto_error=False)

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security)
) -> dict:
    """
    Extract and validate user from JWT token.
    
    Token structure (per architecture):
    {
        "sub": "user-uuid",
        "tenant_id": "tenant-uuid",
        "groups": ["group-1", "group-2"],
        "roles": ["user", "admin"],
        "permissions": ["read:documents", "write:documents"]
    }
    """
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required"
        )
    
    try:
        token = credentials.credentials
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"]
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Token has expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=401,
            detail="Invalid token"
        )


def require_permission(permission: str):
    """Dependency to require a specific permission."""
    def check_permission(user: dict = Depends(get_current_user)):
        if permission not in user.get("permissions", []):
            raise HTTPException(
                status_code=403,
                detail=f"Permission '{permission}' required"
            )
        return user
    return check_permission


async def get_job_tracker() -> JobStatusTracker:
    """Get job status tracker instance."""
    tracker = JobStatusTracker()
    await tracker.connect()
    return tracker


async def get_document_service() -> DocumentService:
    """Get document service instance."""
    return DocumentService()
```

### Configuration

```python
# config.py
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    # API Settings
    host: str = "0.0.0.0"
    port: int = 8001
    debug: bool = False
    
    # CORS
    cors_origins: list[str] = ["*"]
    
    # JWT
    jwt_secret: str = "your-secret-key"
    jwt_algorithm: str = "HS256"
    
    # Database URLs
    database_url: str = "postgresql://localhost:5432/rag_pipeline"
    redis_url: str = "redis://localhost:6379"
    qdrant_url: str = "http://localhost:6333"
    opensearch_url: str = "http://localhost:9200"
    
    # Celery
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"
    
    # LLM Gateway
    llm_gateway_url: str = "http://localhost:8004"
    
    class Config:
        env_file = ".env"
        env_prefix = "INGESTION_"
```

### Entry Point

```python
# run.py
#!/usr/bin/env python
"""Run the ingestion service."""

import uvicorn
from config import Settings

if __name__ == "__main__":
    settings = Settings()
    
    uvicorn.run(
        "api.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="info"
    )
```

## OpenAPI Documentation

The API automatically generates OpenAPI documentation at:
- Swagger UI: `http://localhost:8001/docs`
- ReDoc: `http://localhost:8001/redoc`
- OpenAPI JSON: `http://localhost:8001/openapi.json`

## Acceptance Criteria

- [ ] `POST /ingest` triggers async ingestion job
- [ ] `POST /ingest/single` ingests single document
- [ ] `GET /ingest/{job_id}` returns job status and progress
- [ ] `DELETE /ingest/{job_id}` cancels running job
- [ ] `GET /ingest` lists active jobs
- [ ] `GET /documents` lists documents with pagination
- [ ] `GET /documents/{id}` returns document metadata
- [ ] `DELETE /documents/{id}` deletes document from all stores
- [ ] `POST /documents/{id}/reindex` triggers reindexing
- [ ] JWT authentication validates tokens
- [ ] Tenant isolation enforced
- [ ] OpenAPI documentation generated
- [ ] Request validation with Pydantic
- [ ] Proper error responses with HTTP status codes

## Testing Requirements

```python
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from uuid import uuid4

@pytest.fixture
def client():
    from api.main import app
    return TestClient(app)

@pytest.fixture
def auth_headers():
    import jwt
    token = jwt.encode(
        {"sub": "user-1", "tenant_id": "tenant-1", "permissions": ["write:documents"]},
        "your-secret-key",
        algorithm="HS256"
    )
    return {"Authorization": f"Bearer {token}"}

def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

def test_start_ingestion_requires_auth(client):
    response = client.post("/ingest", json={})
    assert response.status_code == 401

def test_start_ingestion_success(client, auth_headers):
    with patch("api.routes.ingest.batch_ingest") as mock:
        mock.delay.return_value = MagicMock(id=str(uuid4()))
        
        response = client.post(
            "/ingest",
            json={
                "source_type": "filesystem",
                "source_config": {"path": "/data", "storage_type": "local"},
                "acl": {"tenant_id": "tenant-1"}
            },
            headers=auth_headers
        )
        
        assert response.status_code == 202
        assert "job_id" in response.json()

def test_get_job_status(client, auth_headers):
    job_id = uuid4()
    
    with patch("api.routes.ingest.get_job_tracker") as mock:
        tracker = MagicMock()
        tracker.get_job_status.return_value = MagicMock(
            status="progress",
            progress=MagicMock(current=5, total=10, stage="embedding"),
            documents_processed=5,
            chunks_created=50
        )
        mock.return_value = tracker
        
        response = client.get(f"/ingest/{job_id}", headers=auth_headers)
        
        assert response.status_code == 200
        assert response.json()["status"] == "progress"

def test_list_documents_pagination(client, auth_headers):
    with patch("api.routes.documents.get_document_service") as mock:
        service = MagicMock()
        service.list_documents.return_value = MagicMock(
            documents=[],
            total=100
        )
        mock.return_value = service
        
        response = client.get(
            "/documents?page=2&page_size=20",
            headers=auth_headers
        )
        
        assert response.status_code == 200
        assert response.json()["page"] == 2
        assert response.json()["pages"] == 5

def test_delete_document(client, auth_headers):
    doc_id = uuid4()
    
    with patch("api.routes.documents.get_document_service") as mock:
        service = MagicMock()
        service.get_document.return_value = MagicMock(document_id=doc_id)
        service.delete_document.return_value = MagicMock(success=True, chunks_deleted=10)
        mock.return_value = service
        
        response = client.delete(f"/documents/{doc_id}", headers=auth_headers)
        
        assert response.status_code == 200
        assert response.json()["deleted"] is True
        assert response.json()["chunks_deleted"] == 10
```

## Dependencies

- `fastapi>=0.104.0`
- `uvicorn>=0.24.0`
- `pydantic>=2.5.0`
- `pydantic-settings>=2.1.0`
- `python-jose[cryptography]>=3.3.0` (for JWT)
- `httpx>=0.25.0` (for testing)

## Run Commands

```bash
# Development
python run.py

# Production with uvicorn
uvicorn api.main:app --host 0.0.0.0 --port 8001 --workers 4

# Docker
docker run -p 8001:8001 rag-pipeline/ingestion-service
```

## Definition of Done

- [ ] All endpoints implemented and tested
- [ ] OpenAPI documentation complete and accurate
- [ ] JWT authentication working
- [ ] Tenant isolation enforced
- [ ] Pydantic validation on all requests
- [ ] Proper HTTP status codes
- [ ] Error responses follow consistent format
- [ ] >90% test coverage
- [ ] Health check endpoint functional
- [ ] Docstrings on all endpoints
- [ ] Type hints validated with mypy
