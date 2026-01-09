# US-2.7: Async Processing

> **Story ID:** US-2.7  
> **Epic:** Ingestion Service  
> **Priority:** Critical  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** US-2.1 through US-2.6

## User Story

**As a** developer  
**I want** background job processing  
**So that** large ingestion jobs don't block the API

## Context

Document ingestion can be time-consuming for large files or batch operations. The architecture specifies Celery with Redis as the message broker for async task processing. This enables:
- Non-blocking API responses
- Parallel processing of multiple documents
- Retry handling for transient failures
- Job status tracking
- Dead letter queue for failed jobs

## Technical Requirements

### Directory Structure

```
ingestion-service/
├── tasks/
│   ├── __init__.py
│   ├── celery_app.py     # Celery configuration
│   ├── ingest.py         # Ingestion tasks
│   ├── reembed.py        # Re-embedding tasks
│   └── callbacks.py      # Task callbacks
├── worker.py             # Worker entry point
└── config.py             # Configuration
```

### Celery Configuration

```python
from celery import Celery
from kombu import Queue, Exchange
from pydantic import BaseModel
from typing import Optional

class CeleryConfig(BaseModel):
    broker_url: str = "redis://localhost:6379/0"
    result_backend: str = "redis://localhost:6379/1"
    
    # Task settings
    task_serializer: str = "json"
    result_serializer: str = "json"
    accept_content: list[str] = ["json"]
    task_track_started: bool = True
    task_time_limit: int = 3600  # 1 hour max
    task_soft_time_limit: int = 3300  # Soft limit 55 min
    
    # Worker settings
    worker_prefetch_multiplier: int = 1  # Disable prefetch for long tasks
    worker_concurrency: int = 4
    
    # Retry settings
    task_default_retry_delay: int = 60  # 1 minute
    task_max_retries: int = 3
    
    # Result expiration
    result_expires: int = 86400  # 24 hours
    
    # Queue configuration
    task_default_queue: str = "ingestion"

# celery_app.py
def create_celery_app(config: CeleryConfig = CeleryConfig()) -> Celery:
    """Create and configure Celery application."""
    
    app = Celery("ingestion")
    
    app.conf.update(
        broker_url=config.broker_url,
        result_backend=config.result_backend,
        task_serializer=config.task_serializer,
        result_serializer=config.result_serializer,
        accept_content=config.accept_content,
        task_track_started=config.task_track_started,
        task_time_limit=config.task_time_limit,
        task_soft_time_limit=config.task_soft_time_limit,
        worker_prefetch_multiplier=config.worker_prefetch_multiplier,
        worker_concurrency=config.worker_concurrency,
        result_expires=config.result_expires,
        task_default_queue=config.task_default_queue,
    )
    
    # Define queues
    app.conf.task_queues = (
        Queue("ingestion", Exchange("ingestion"), routing_key="ingestion"),
        Queue("embedding", Exchange("embedding"), routing_key="embedding"),
        Queue("reembed", Exchange("reembed"), routing_key="reembed"),
        Queue("dlq", Exchange("dlq"), routing_key="dlq"),  # Dead letter queue
    )
    
    # Route tasks to queues
    app.conf.task_routes = {
        "tasks.ingest.*": {"queue": "ingestion"},
        "tasks.embedding.*": {"queue": "embedding"},
        "tasks.reembed.*": {"queue": "reembed"},
    }
    
    # Configure dead letter queue
    app.conf.task_reject_on_worker_lost = True
    
    return app

# Singleton app instance
celery_app = create_celery_app()
```

### Job Status Model

```python
from pydantic import BaseModel, Field
from typing import Optional, Any
from uuid import UUID, uuid4
from datetime import datetime
from enum import Enum

class JobStatus(str, Enum):
    PENDING = "pending"
    STARTED = "started"
    PROGRESS = "progress"
    SUCCESS = "success"
    FAILURE = "failure"
    RETRY = "retry"
    REVOKED = "revoked"

class JobProgress(BaseModel):
    current: int = 0
    total: int = 0
    stage: str = ""
    message: str = ""

class IngestJobResult(BaseModel):
    job_id: str
    status: JobStatus
    progress: Optional[JobProgress] = None
    
    # Results
    documents_processed: int = 0
    chunks_created: int = 0
    errors: list[str] = []
    
    # Timing
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None
    
    # Error info
    error_message: Optional[str] = None
    traceback: Optional[str] = None

class IngestJobRequest(BaseModel):
    job_id: UUID = Field(default_factory=uuid4)
    
    # Source configuration
    source_type: str  # filesystem, database, web, api
    source_config: dict[str, Any]
    
    # Processing options
    chunking_strategy: str = "semantic_sentence"
    chunk_size: int = 512
    chunk_overlap: int = 50
    
    # ACL context
    tenant_id: str
    visibility: str = "private"
    allowed_groups: list[str] = []
    allowed_users: list[str] = []
    
    # Options
    enable_pii_detection: bool = True
    custom_metadata: dict[str, Any] = {}
```

### Ingestion Task

```python
from celery import shared_task, current_task
from celery.exceptions import SoftTimeLimitExceeded, Reject
from typing import Any
import traceback
import asyncio
from datetime import datetime

from .celery_app import celery_app

@celery_app.task(
    bind=True,
    name="tasks.ingest.process_document",
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=600,  # Max 10 min between retries
    acks_late=True  # Acknowledge after completion
)
def process_document(
    self,
    document_source_id: str,
    source_type: str,
    source_config: dict,
    processing_config: dict,
    acl_context: dict
) -> dict:
    """
    Process a single document through the ingestion pipeline.
    
    Stages:
    1. Fetch document from source
    2. Parse document
    3. Enrich with metadata
    4. Chunk document
    5. Generate embeddings
    6. Index to stores
    """
    try:
        # Update task state to STARTED
        self.update_state(
            state="STARTED",
            meta={"stage": "fetching", "message": "Fetching document..."}
        )
        
        # Run async pipeline
        result = asyncio.run(
            _process_document_async(
                task=self,
                document_source_id=document_source_id,
                source_type=source_type,
                source_config=source_config,
                processing_config=processing_config,
                acl_context=acl_context
            )
        )
        
        return result
        
    except SoftTimeLimitExceeded:
        # Task taking too long, save state for potential resume
        self.update_state(
            state="FAILURE",
            meta={"error": "Task timed out"}
        )
        raise Reject("Task timed out", requeue=False)
        
    except Exception as e:
        # Log error and potentially retry
        error_info = {
            "error": str(e),
            "traceback": traceback.format_exc()
        }
        
        if self.request.retries < self.max_retries:
            # Retry with exponential backoff
            raise self.retry(exc=e)
        else:
            # Max retries exceeded, send to DLQ
            send_to_dlq.delay({
                "task_name": "process_document",
                "args": [document_source_id, source_type, source_config],
                "error": error_info,
                "retries": self.request.retries
            })
            raise


async def _process_document_async(
    task,
    document_source_id: str,
    source_type: str,
    source_config: dict,
    processing_config: dict,
    acl_context: dict
) -> dict:
    """Async implementation of document processing pipeline."""
    from uuid import uuid4
    from datetime import datetime
    
    # Import pipeline components
    from connectors import get_connector
    from processors.parsers import ParserRegistry
    from processors.chunking import ChunkingEngine
    from processors.enrichment import EnrichmentPipeline, EnrichmentContext
    from embedding.service import EmbeddingService
    from indexing.coordinator import IndexCoordinator
    
    document_id = uuid4()
    start_time = datetime.utcnow()
    
    # Stage 1: Fetch document
    task.update_state(
        state="PROGRESS",
        meta={"stage": "fetching", "progress": 10}
    )
    
    connector = get_connector(source_type, source_config)
    async with connector:
        raw_doc = await connector.fetch_document(document_source_id)
    
    # Stage 2: Parse document
    task.update_state(
        state="PROGRESS",
        meta={"stage": "parsing", "progress": 25}
    )
    
    parser_registry = ParserRegistry()
    parsed_doc = await parser_registry.parse(
        raw_doc.content,
        raw_doc.metadata.mime_type
    )
    
    # Stage 3: Enrich metadata
    task.update_state(
        state="PROGRESS",
        meta={"stage": "enriching", "progress": 35}
    )
    
    enrichment = EnrichmentPipeline()
    context = EnrichmentContext(**acl_context)
    metadata = await enrichment.enrich(parsed_doc, context)
    
    # Stage 4: Chunk document
    task.update_state(
        state="PROGRESS",
        meta={"stage": "chunking", "progress": 50}
    )
    
    chunking_engine = ChunkingEngine()
    chunking_result = chunking_engine.chunk(
        text=parsed_doc.text,
        document_id=document_id,
        strategy=processing_config.get("chunking_strategy", "semantic_sentence"),
        metadata=metadata.model_dump()
    )
    
    # Stage 5: Generate embeddings
    task.update_state(
        state="PROGRESS",
        meta={"stage": "embedding", "progress": 70, "chunks": len(chunking_result.chunks)}
    )
    
    embedding_service = EmbeddingService()
    embedding_results = await embedding_service.embed_texts(
        texts=[c.content for c in chunking_result.chunks],
        chunk_ids=[c.chunk_id for c in chunking_result.chunks]
    )
    
    # Combine chunks with embeddings
    indexed_chunks = []
    for chunk, emb_result in zip(chunking_result.chunks, embedding_results.results):
        indexed_chunks.append(IndexedChunk(
            chunk_id=chunk.chunk_id,
            document_id=document_id,
            content=chunk.content,
            embedding=emb_result.embedding,
            chunk_index=chunk.chunk_index,
            token_count=chunk.token_count,
            parent_chunk_id=chunk.parent_chunk_id,
            metadata=chunk.metadata,
            tenant_id=acl_context["tenant_id"],
            visibility=acl_context.get("visibility", "private"),
            allowed_groups=acl_context.get("allowed_groups", []),
            allowed_users=acl_context.get("allowed_users", [])
        ))
    
    # Stage 6: Index to stores
    task.update_state(
        state="PROGRESS",
        meta={"stage": "indexing", "progress": 90}
    )
    
    document_record = DocumentRecord(
        document_id=document_id,
        source_id=document_source_id,
        source_type=source_type,
        filename=raw_doc.metadata.filename,
        mime_type=raw_doc.metadata.mime_type,
        title=metadata.title,
        author=metadata.author,
        chunk_count=len(indexed_chunks),
        total_tokens=sum(c.token_count for c in indexed_chunks),
        tenant_id=acl_context["tenant_id"],
        visibility=acl_context.get("visibility", "private"),
        allowed_groups=acl_context.get("allowed_groups", []),
        allowed_users=acl_context.get("allowed_users", [])
    )
    
    coordinator = IndexCoordinator()
    index_results = await coordinator.index_document(document_record, indexed_chunks)
    
    # Calculate duration
    end_time = datetime.utcnow()
    duration = (end_time - start_time).total_seconds()
    
    return {
        "document_id": str(document_id),
        "source_id": document_source_id,
        "chunks_created": len(indexed_chunks),
        "tokens_processed": sum(c.token_count for c in indexed_chunks),
        "index_results": {k: v.model_dump() for k, v in index_results.items()},
        "duration_seconds": duration,
        "completed_at": end_time.isoformat()
    }


@celery_app.task(
    bind=True,
    name="tasks.ingest.batch_ingest",
    max_retries=1
)
def batch_ingest(
    self,
    job_id: str,
    source_type: str,
    source_config: dict,
    processing_config: dict,
    acl_context: dict
) -> dict:
    """
    Ingest multiple documents from a source.
    
    Creates subtasks for each document.
    """
    from celery import group
    
    # Get list of documents from source
    connector = get_connector(source_type, source_config)
    documents = asyncio.run(list_documents(connector))
    
    total = len(documents)
    self.update_state(
        state="PROGRESS",
        meta={"stage": "scheduling", "total": total, "scheduled": 0}
    )
    
    # Create group of subtasks
    tasks = []
    for i, doc_id in enumerate(documents):
        task = process_document.s(
            document_source_id=doc_id,
            source_type=source_type,
            source_config=source_config,
            processing_config=processing_config,
            acl_context=acl_context
        )
        tasks.append(task)
        
        # Update progress
        self.update_state(
            state="PROGRESS",
            meta={"stage": "scheduling", "total": total, "scheduled": i + 1}
        )
    
    # Execute group and wait for results
    job = group(tasks)
    result = job.apply_async()
    
    # Wait for all tasks to complete
    results = result.get(timeout=7200)  # 2 hour timeout for batch
    
    # Aggregate results
    success_count = sum(1 for r in results if r.get("chunks_created", 0) > 0)
    total_chunks = sum(r.get("chunks_created", 0) for r in results)
    
    return {
        "job_id": job_id,
        "documents_processed": success_count,
        "documents_failed": total - success_count,
        "total_chunks": total_chunks,
        "results": results
    }
```

### Re-embedding Task

```python
@celery_app.task(
    bind=True,
    name="tasks.reembed.reembed_collection",
    max_retries=3
)
def reembed_collection(
    self,
    collection_name: str,
    new_model: str,
    batch_size: int = 100
) -> dict:
    """
    Re-embed all documents in a collection with a new model.
    
    Use case: Upgrading embedding model while preserving documents.
    """
    # Get all chunks from PostgreSQL
    chunks = asyncio.run(get_all_chunks(collection_name))
    total = len(chunks)
    
    self.update_state(
        state="PROGRESS",
        meta={"stage": "re-embedding", "total": total, "processed": 0}
    )
    
    # Process in batches
    embedding_service = EmbeddingService(model=new_model)
    processed = 0
    
    for i in range(0, total, batch_size):
        batch = chunks[i:i + batch_size]
        
        # Generate new embeddings
        new_embeddings = asyncio.run(
            embedding_service.embed_texts(
                texts=[c.content for c in batch],
                chunk_ids=[c.chunk_id for c in batch]
            )
        )
        
        # Update vector store
        asyncio.run(update_embeddings_in_qdrant(batch, new_embeddings))
        
        processed += len(batch)
        self.update_state(
            state="PROGRESS",
            meta={"stage": "re-embedding", "total": total, "processed": processed}
        )
    
    return {
        "collection": collection_name,
        "new_model": new_model,
        "chunks_reembedded": processed
    }
```

### Dead Letter Queue Handler

```python
@celery_app.task(
    name="tasks.dlq.send_to_dlq",
    queue="dlq"
)
def send_to_dlq(failure_info: dict):
    """
    Store failed task info in dead letter queue for manual review.
    """
    import json
    from datetime import datetime
    
    # Store in Redis for DLQ dashboard
    dlq_key = f"dlq:{failure_info['task_name']}:{datetime.utcnow().isoformat()}"
    
    redis_client = get_redis_client()
    redis_client.setex(
        dlq_key,
        86400 * 7,  # Keep for 7 days
        json.dumps(failure_info)
    )
    
    # Log for alerting
    logger.error(f"Task sent to DLQ: {failure_info['task_name']}", extra=failure_info)
```

### Job Status Tracker

```python
from celery.result import AsyncResult
import redis.asyncio as redis

class JobStatusTracker:
    """
    Track and query job status.
    """
    
    def __init__(self, redis_url: str = "redis://localhost:6379/2"):
        self.redis_url = redis_url
        self._redis: Optional[redis.Redis] = None
    
    async def connect(self):
        self._redis = redis.from_url(self.redis_url)
    
    async def get_job_status(self, job_id: str) -> IngestJobResult:
        """Get current status of an ingestion job."""
        result = AsyncResult(job_id, app=celery_app)
        
        status_map = {
            "PENDING": JobStatus.PENDING,
            "STARTED": JobStatus.STARTED,
            "PROGRESS": JobStatus.PROGRESS,
            "SUCCESS": JobStatus.SUCCESS,
            "FAILURE": JobStatus.FAILURE,
            "RETRY": JobStatus.RETRY,
            "REVOKED": JobStatus.REVOKED
        }
        
        status = status_map.get(result.status, JobStatus.PENDING)
        
        # Get task info
        info = result.info or {}
        
        if status == JobStatus.PROGRESS:
            progress = JobProgress(
                current=info.get("processed", 0),
                total=info.get("total", 0),
                stage=info.get("stage", ""),
                message=info.get("message", "")
            )
        else:
            progress = None
        
        return IngestJobResult(
            job_id=job_id,
            status=status,
            progress=progress,
            documents_processed=info.get("documents_processed", 0),
            chunks_created=info.get("chunks_created", 0),
            errors=info.get("errors", []),
            started_at=info.get("started_at"),
            completed_at=info.get("completed_at"),
            duration_seconds=info.get("duration_seconds"),
            error_message=info.get("error") if status == JobStatus.FAILURE else None,
            traceback=info.get("traceback") if status == JobStatus.FAILURE else None
        )
    
    async def cancel_job(self, job_id: str) -> bool:
        """Cancel a running job."""
        result = AsyncResult(job_id, app=celery_app)
        result.revoke(terminate=True)
        return True
    
    async def list_active_jobs(self) -> list[str]:
        """List all active job IDs."""
        inspect = celery_app.control.inspect()
        active = inspect.active() or {}
        
        job_ids = []
        for worker, tasks in active.items():
            for task in tasks:
                job_ids.append(task["id"])
        
        return job_ids
    
    async def list_dlq_entries(self, limit: int = 100) -> list[dict]:
        """List entries in dead letter queue."""
        pattern = "dlq:*"
        cursor = 0
        entries = []
        
        while True:
            cursor, keys = await self._redis.scan(cursor, match=pattern, count=100)
            for key in keys[:limit - len(entries)]:
                data = await self._redis.get(key)
                if data:
                    entries.append(json.loads(data))
            
            if cursor == 0 or len(entries) >= limit:
                break
        
        return entries
```

### Worker Entry Point

```python
# worker.py
#!/usr/bin/env python
"""Celery worker entry point."""

from tasks.celery_app import celery_app
import tasks.ingest  # Register tasks
import tasks.reembed
import tasks.callbacks

if __name__ == "__main__":
    celery_app.start()

# Run with:
# celery -A worker worker --loglevel=info --queues=ingestion,embedding,reembed
```

## Acceptance Criteria

- [ ] Celery configured with Redis broker (per architecture)
- [ ] `process_document` task handles full ingestion pipeline
- [ ] `batch_ingest` task processes multiple documents in parallel
- [ ] `reembed_collection` task supports model upgrades
- [ ] Task progress tracking via `update_state`
- [ ] Retry logic with exponential backoff (3 retries, 1-10min wait)
- [ ] Dead letter queue captures failed tasks
- [ ] `JobStatusTracker` queries job status
- [ ] Jobs can be cancelled
- [ ] Proper error handling and logging

## Testing Requirements

```python
import pytest
from unittest.mock import patch, MagicMock
from celery.exceptions import Retry

@pytest.fixture
def celery_config():
    return {
        "broker_url": "memory://",
        "result_backend": "cache+memory://",
        "task_always_eager": True  # Sync execution for tests
    }

@pytest.fixture
def celery_app(celery_config):
    from tasks.celery_app import create_celery_app
    app = create_celery_app()
    app.conf.update(celery_config)
    return app

def test_process_document_success(celery_app):
    with patch("tasks.ingest._process_document_async") as mock:
        mock.return_value = {
            "document_id": "123",
            "chunks_created": 10
        }
        
        result = process_document.delay(
            document_source_id="test.pdf",
            source_type="filesystem",
            source_config={"path": "/tmp"},
            processing_config={},
            acl_context={"tenant_id": "t1"}
        )
        
        assert result.get()["chunks_created"] == 10

def test_process_document_retry_on_connection_error(celery_app):
    with patch("tasks.ingest._process_document_async") as mock:
        mock.side_effect = ConnectionError("DB connection failed")
        
        with pytest.raises(Retry):
            process_document.delay(
                document_source_id="test.pdf",
                source_type="filesystem",
                source_config={"path": "/tmp"},
                processing_config={},
                acl_context={"tenant_id": "t1"}
            )

def test_batch_ingest_creates_subtasks(celery_app):
    with patch("tasks.ingest.list_documents") as mock_list:
        mock_list.return_value = ["doc1.pdf", "doc2.pdf", "doc3.pdf"]
        
        with patch("tasks.ingest.process_document") as mock_process:
            mock_process.s = MagicMock()
            
            result = batch_ingest.delay(
                job_id="job-123",
                source_type="filesystem",
                source_config={"path": "/docs"},
                processing_config={},
                acl_context={"tenant_id": "t1"}
            )
            
            # Verify subtasks were created
            assert mock_process.s.call_count == 3

@pytest.mark.asyncio
async def test_job_status_tracker():
    tracker = JobStatusTracker()
    await tracker.connect()
    
    # Submit a task
    result = process_document.delay(...)
    
    status = await tracker.get_job_status(result.id)
    assert status.job_id == result.id
    assert status.status in [JobStatus.PENDING, JobStatus.STARTED]
```

## Dependencies

- `celery>=5.3.0`
- `redis>=5.0.0`
- `kombu>=5.3.0`
- `pydantic>=2.0.0`

## Worker Commands

```bash
# Start worker for all queues
celery -A tasks.celery_app worker --loglevel=info --queues=ingestion,embedding,reembed

# Start worker for specific queue
celery -A tasks.celery_app worker --loglevel=info --queues=ingestion --concurrency=4

# Start Celery beat for scheduled tasks (if needed)
celery -A tasks.celery_app beat --loglevel=info

# Monitor with Flower (optional)
celery -A tasks.celery_app flower --port=5555
```

## Definition of Done

- [ ] Celery app configured and workers start correctly
- [ ] All tasks implemented with proper retry logic
- [ ] Progress tracking works through task lifecycle
- [ ] Dead letter queue captures failures after max retries
- [ ] Job status queryable via tracker
- [ ] Jobs can be cancelled
- [ ] Integration tests pass with Redis
- [ ] >90% test coverage
- [ ] Worker deployment documented
- [ ] Docstrings on all public functions
