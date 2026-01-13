"""Document ingestion tasks.

This module provides Celery tasks for document ingestion:
- process_document: Process a single document through the full pipeline
- batch_ingest: Process multiple documents in parallel

The pipeline stages are:
1. Fetch document from source
2. Parse document content
3. Enrich with metadata
4. Chunk document
5. Generate embeddings
6. Index to stores (Qdrant, OpenSearch, PostgreSQL)
"""

import asyncio
import logging
import traceback
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from celery import group
from celery.exceptions import Reject, SoftTimeLimitExceeded

from .callbacks import send_to_dlq
from .celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    bind=True,
    name="tasks.ingest.process_document",
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=600,  # Max 10 min between retries
    acks_late=True,  # Acknowledge after completion
)
def process_document(
    self,
    document_source_id: str,
    source_type: str,
    source_config: dict[str, Any],
    processing_config: dict[str, Any],
    acl_context: dict[str, Any],
) -> dict[str, Any]:
    """Process a single document through the ingestion pipeline.

    Args:
        document_source_id: Unique ID of the document in the source.
        source_type: Type of source (filesystem, database, web, api).
        source_config: Configuration for the source connector.
        processing_config: Configuration for processing (chunking, etc).
        acl_context: Access control context (tenant_id, visibility, etc).

    Returns:
        Dict with processing results including document_id, chunks_created, etc.

    Raises:
        Reject: If task times out.
        Exception: On unrecoverable errors after max retries.
    """
    try:
        # Update task state to STARTED
        self.update_state(
            state="STARTED",
            meta={"stage": "initializing", "message": "Starting document processing..."},
        )

        # Run async pipeline
        return asyncio.run(
            _process_document_async(
                task=self,
                document_source_id=document_source_id,
                source_type=source_type,
                source_config=source_config,
                processing_config=processing_config,
                acl_context=acl_context,
            ),
        )

    except SoftTimeLimitExceeded:
        # Task taking too long
        logger.error(f"Task timed out for document: {document_source_id}")
        self.update_state(
            state="FAILURE",
            meta={"error": "Task timed out", "document_source_id": document_source_id},
        )
        raise Reject("Task timed out", requeue=False) from None

    except Exception as e:
        error_info = {
            "error": str(e),
            "traceback": traceback.format_exc(),
            "document_source_id": document_source_id,
        }

        logger.error(f"Error processing document {document_source_id}: {e}")

        if self.request.retries < self.max_retries:
            # Retry with exponential backoff
            raise self.retry(exc=e) from e
        # Max retries exceeded, send to DLQ
        send_to_dlq.delay(
            {
                "task_name": "process_document",
                "args": [document_source_id, source_type, source_config],
                "kwargs": {
                    "processing_config": processing_config,
                    "acl_context": acl_context,
                },
                "error": error_info,
                "retries": self.request.retries,
            },
        )
        raise


async def _process_document_async(
    task,
    document_source_id: str,
    source_type: str,
    source_config: dict[str, Any],
    processing_config: dict[str, Any],
    acl_context: dict[str, Any],
) -> dict[str, Any]:
    """Async implementation of document processing pipeline.

    Implements idempotent ingestion with deduplication (US-2.11):
    - Computes SHA-256 content hash for deduplication
    - Skips processing if identical content already exists
    - Increments version if same source_uri has different content

    Args:
        task: Celery task instance for state updates.
        document_source_id: Source identifier for the document (used as source_uri).
        source_type: Type of source connector.
        source_config: Configuration for the connector.
        processing_config: Processing options.
        acl_context: Access control context.

    Returns:
        Processing results dict with deduplication status.
    """
    # Import pipeline components
    from config import get_settings
    from embedding.service import create_embedding_service
    from indexing.coordinator import IndexCoordinator
    from indexing.models import DocumentRecord, IndexedChunk
    from indexing.opensearch import OpenSearchWriter, OpenSearchWriterConfig
    from indexing.postgres import PostgresWriter, PostgresWriterConfig
    from indexing.qdrant import QdrantWriter, QdrantWriterConfig
    from processors import ChunkingConfig, ChunkingEngine
    from processors.enrichment import EnrichmentContext, EnrichmentPipeline
    from processors.parsers import create_default_registry
    from services.deduplication import (
        CHUNK_SCHEMA_VERSION,
        DeduplicationResult,
        DeduplicationService,
    )

    settings = get_settings()
    start_time = datetime.now(tz=UTC)

    # Stage 1: Fetch document
    task.update_state(
        state="PROGRESS",
        meta={"stage": "fetching", "progress": 10, "message": "Fetching document..."},
    )

    connector = _get_connector(source_type, source_config)
    async with connector:
        raw_doc = await connector.fetch_document(document_source_id)

    # Stage 2: Compute content hash and check for duplicates (US-2.11)
    task.update_state(
        state="PROGRESS",
        meta={"stage": "deduplicating", "progress": 15, "message": "Checking for duplicates..."},
    )

    content_hash = DeduplicationService.compute_content_hash(raw_doc.content)
    tenant_id = (
        UUID(acl_context["tenant_id"])
        if isinstance(acl_context["tenant_id"], str)
        else acl_context["tenant_id"]
    )

    # Create deduplication service and check
    import asyncpg

    pool = await asyncpg.create_pool(settings.database_url)
    try:
        dedup_service = DeduplicationService(pool)
        dedup_result = await dedup_service.check_duplicate(
            tenant_id=tenant_id,
            source_uri=document_source_id,
            content_hash=content_hash,
        )

        # Handle duplicate - skip processing and return existing document ID
        if dedup_result.result == DeduplicationResult.DUPLICATE:
            logger.info(
                "Duplicate content detected, skipping processing for source_uri=%s",
                document_source_id,
            )
            end_time = datetime.now(tz=UTC)
            return {
                "document_id": str(dedup_result.document_id),
                "source_uri": document_source_id,
                "status": "duplicate",
                "existing_version": dedup_result.existing_version,
                "content_hash": content_hash,
                "chunks_created": 0,
                "tokens_processed": 0,
                "duration_seconds": (end_time - start_time).total_seconds(),
                "completed_at": end_time.isoformat(),
                "message": "Document already exists with identical content",
            }

        # Determine version for new/updated document
        if dedup_result.result == DeduplicationResult.NEW_VERSION:
            version = dedup_result.existing_version + 1
            logger.info(
                "New version detected for source_uri=%s (v%d)",
                document_source_id,
                version,
            )
        else:
            version = 1

        document_id = uuid4()

        # Stage 3: Parse document
        task.update_state(
            state="PROGRESS",
            meta={"stage": "parsing", "progress": 25, "message": "Parsing document..."},
        )

        parser_registry = create_default_registry()
        parsed_doc = await parser_registry.parse(raw_doc.content, raw_doc.metadata.mime_type)

        # Stage 4: Enrich metadata
        task.update_state(
            state="PROGRESS",
            meta={"stage": "enriching", "progress": 35, "message": "Enriching metadata..."},
        )

        enrichment = EnrichmentPipeline()
        context = EnrichmentContext(
            tenant_id=acl_context["tenant_id"],
            visibility=acl_context.get("visibility", "private"),
            allowed_groups=acl_context.get("allowed_groups", []),
            allowed_users=acl_context.get("allowed_users", []),
            custom_metadata=acl_context.get("custom_metadata", {}),
        )
        metadata = await enrichment.enrich(parsed_doc, context)

        # Stage 5: Chunk document
        task.update_state(
            state="PROGRESS",
            meta={"stage": "chunking", "progress": 50, "message": "Chunking document..."},
        )

        chunking_config = ChunkingConfig(
            target_tokens=processing_config.get("chunk_size", 300),
            chunk_overlap=processing_config.get("chunk_overlap", 50),
        )
        # Map strategy names from API to internal names
        strategy_mapping = {
            "recursive": "recursive_character",
            "semantic": "semantic_sentence",
            "hierarchical": "hierarchical",
        }
        raw_strategy = processing_config.get("chunking_strategy", "recursive")
        chunking_strategy = strategy_mapping.get(raw_strategy, raw_strategy)
        chunking_engine = ChunkingEngine()
        chunking_result = chunking_engine.chunk(
            text=parsed_doc.text,
            document_id=document_id,
            strategy=chunking_strategy,
            metadata={"source_uri": document_source_id, **metadata.model_dump()},
            config=chunking_config,
        )
        chunks = chunking_result.chunks

        # Stage 6: Generate embeddings
        task.update_state(
            state="PROGRESS",
            meta={
                "stage": "embedding",
                "progress": 70,
                "message": f"Generating embeddings for {len(chunks)} chunks...",
            },
        )

        from embedding.models import EmbeddingCacheConfig, EmbeddingServiceConfig

        # Use nomic-embed-text for Ollama (768 dimensions)
        service_config = EmbeddingServiceConfig(
            llm_gateway_url=settings.llm_gateway_url,
            model="nomic-embed-text",
            dimensions=768,
        )
        cache_config = EmbeddingCacheConfig(redis_url=settings.redis_url)
        embedding_service = await create_embedding_service(
            config=service_config, cache_config=cache_config
        )
        try:
            embedding_results = await embedding_service.embed_texts(
                texts=[c.content for c in chunks],
                chunk_ids=[c.chunk_id for c in chunks],
            )
        finally:
            await embedding_service.close()

        # Combine chunks with embeddings and versioning metadata (US-2.11)
        indexed_chunks = []
        for chunk, emb_result in zip(chunks, embedding_results.results, strict=True):
            indexed_chunks.append(
                IndexedChunk(
                    chunk_id=chunk.chunk_id,
                    document_id=document_id,
                    content=chunk.content,
                    embedding=emb_result.embedding,
                    chunk_index=chunk.chunk_index,
                    token_count=chunk.token_count,
                    parent_chunk_id=chunk.parent_chunk_id,
                    schema_version=CHUNK_SCHEMA_VERSION,
                    embedding_model=embedding_service.config.model,
                    embedding_version="1.0",  # TODO: Get from embedding service config
                    metadata=chunk.metadata,
                    tenant_id=acl_context["tenant_id"],
                    visibility=acl_context.get("visibility", "private"),
                    allowed_groups=acl_context.get("allowed_groups", []),
                    allowed_users=acl_context.get("allowed_users", []),
                ),
            )

        # Stage 7: Index to stores
        task.update_state(
            state="PROGRESS",
            meta={"stage": "indexing", "progress": 90, "message": "Indexing to stores..."},
        )

        document_record = DocumentRecord(
            document_id=document_id,
            source_uri=document_source_id,
            source_type=source_type,
            filename=raw_doc.metadata.filename,
            mime_type=raw_doc.metadata.mime_type,
            title=metadata.title,
            author=metadata.author,
            chunk_count=len(indexed_chunks),
            total_tokens=sum(c.token_count for c in indexed_chunks),
            content_hash=content_hash,
            version=version,
            tenant_id=acl_context["tenant_id"],
            visibility=acl_context.get("visibility", "private"),
            allowed_groups=acl_context.get("allowed_groups", []),
            allowed_users=acl_context.get("allowed_users", []),
        )

        # Use coordinator to write to all stores
        qdrant_config = QdrantWriterConfig(
            url=settings.qdrant_url,
            vector_size=768,  # nomic-embed-text dimensions
        )
        opensearch_config = OpenSearchWriterConfig(hosts=[settings.opensearch_url])
        postgres_config = PostgresWriterConfig(
            connection_string=settings.database_url,
            table_name="indexed_documents",  # Separate from migration-managed 'documents' table
        )

        qdrant_writer = QdrantWriter(qdrant_config)
        opensearch_writer = OpenSearchWriter(opensearch_config)
        postgres_writer = PostgresWriter(postgres_config)

        coordinator = IndexCoordinator(qdrant_writer, opensearch_writer, postgres_writer)
        async with coordinator:
            await coordinator.ensure_indices()
            await coordinator.index_document(document_record, indexed_chunks)

        # Mark previous versions as superseded if this is a new version
        if dedup_result.result == DeduplicationResult.NEW_VERSION:
            await dedup_service.mark_previous_versions_superseded(
                tenant_id=tenant_id,
                source_uri=document_source_id,
                new_document_id=document_id,
            )

    finally:
        await pool.close()

    # Calculate duration
    end_time = datetime.now(tz=UTC)
    duration = (end_time - start_time).total_seconds()

    status = "new_version" if version > 1 else "created"

    return {
        "document_id": str(document_id),
        "source_uri": document_source_id,
        "status": status,
        "version": version,
        "content_hash": content_hash,
        "chunks_created": len(indexed_chunks),
        "tokens_processed": sum(c.token_count for c in indexed_chunks),
        "duration_seconds": duration,
        "completed_at": end_time.isoformat(),
    }


def _get_connector(source_type: str, source_config: dict[str, Any]):
    """Get the appropriate connector for a source type.

    Args:
        source_type: Type of source (filesystem, database, web, api).
        source_config: Configuration dict for the connector.

    Returns:
        Configured connector instance.

    Raises:
        ValueError: If source_type is not recognized.
    """
    from connectors import (
        APIConnector,
        APIConnectorConfig,
        DatabaseConnector,
        DatabaseConnectorConfig,
        FilesystemConnector,
        FilesystemConnectorConfig,
        WebConnector,
        WebConnectorConfig,
    )

    connectors = {
        "filesystem": (FilesystemConnector, FilesystemConnectorConfig),
        "database": (DatabaseConnector, DatabaseConnectorConfig),
        "web": (WebConnector, WebConnectorConfig),
        "api": (APIConnector, APIConnectorConfig),
    }

    if source_type not in connectors:
        raise ValueError(f"Unknown source type: {source_type}")

    connector_class, config_class = connectors[source_type]

    # Map API schema field names to connector config field names
    mapped_config = source_config.copy()
    if source_type == "filesystem" and "path" in mapped_config:
        # API uses 'path', connector uses 'base_path'
        mapped_config["base_path"] = mapped_config.pop("path")

    config = config_class(**mapped_config)
    return connector_class(config)


@celery_app.task(
    bind=True,
    name="tasks.ingest.batch_ingest",
    max_retries=1,
)
def batch_ingest(
    self,
    job_id: str,
    source_type: str,
    source_config: dict[str, Any],
    processing_config: dict[str, Any],
    acl_context: dict[str, Any],
) -> dict[str, Any]:
    """Ingest multiple documents from a source.

    For single document ingestion, processes synchronously.
    For multiple documents, dispatches subtasks and returns immediately.

    Args:
        job_id: Unique identifier for this batch job.
        source_type: Type of source connector.
        source_config: Configuration for the connector.
        processing_config: Processing options.
        acl_context: Access control context.

    Returns:
        Processing results (immediate for single doc, status for batch).
    """
    # Get list of documents from source
    documents = asyncio.run(_list_documents(source_type, source_config))

    total = len(documents)
    self.update_state(
        state="PROGRESS",
        meta={
            "stage": "scheduling",
            "total": total,
            "scheduled": 0,
            "message": f"Found {total} documents to process",
        },
    )

    if total == 0:
        return {
            "job_id": job_id,
            "documents_processed": 0,
            "documents_failed": 0,
            "total_chunks": 0,
            "results": [],
        }

    # For single document, process directly in this task (no subtask deadlock)
    if total == 1:
        doc_id = documents[0]
        logger.info(f"Processing single document directly: {doc_id}")

        self.update_state(
            state="PROGRESS",
            meta={
                "stage": "processing",
                "total": 1,
                "processed": 0,
                "message": f"Processing document: {doc_id}",
            },
        )

        try:
            # Run the document processing directly (not as a subtask)
            result = asyncio.run(
                _process_document_async(
                    task=self,
                    document_source_id=doc_id,
                    source_type=source_type,
                    source_config=source_config,
                    processing_config=processing_config,
                    acl_context=acl_context,
                )
            )

            chunks_created = result.get("chunks_created", 0)
            success = chunks_created > 0 or result.get("status") == "duplicate"

            logger.info(f"Batch job {job_id} completed: document processed with {chunks_created} chunks")

            return {
                "job_id": job_id,
                "documents_processed": 1 if success else 0,
                "documents_failed": 0 if success else 1,
                "total_chunks": chunks_created,
                "results": [result],
            }
        except Exception as e:
            logger.error(f"Failed to process document {doc_id}: {e}")
            return {
                "job_id": job_id,
                "documents_processed": 0,
                "documents_failed": 1,
                "total_chunks": 0,
                "results": [{"error": str(e), "document_source_id": doc_id}],
            }

    # For multiple documents, dispatch subtasks (fire and forget)
    # The caller should track individual task IDs for status
    task_ids = []
    for i, doc_id in enumerate(documents):
        async_result = process_document.apply_async(
            kwargs={
                "document_source_id": doc_id,
                "source_type": source_type,
                "source_config": source_config,
                "processing_config": processing_config,
                "acl_context": acl_context,
            }
        )
        task_ids.append(async_result.id)
        logger.info(f"Dispatched task {async_result.id} for document: {doc_id}")

        # Update progress periodically
        if (i + 1) % 10 == 0 or i + 1 == total:
            self.update_state(
                state="PROGRESS",
                meta={
                    "stage": "scheduling",
                    "total": total,
                    "scheduled": i + 1,
                    "message": f"Scheduled {i + 1}/{total} documents",
                },
            )

    logger.info(f"Batch job {job_id} dispatched {total} subtasks")

    # Return immediately with subtask IDs - caller should poll for completion
    return {
        "job_id": job_id,
        "documents_processed": 0,  # Will be updated as subtasks complete
        "documents_failed": 0,
        "total_chunks": 0,
        "subtask_ids": task_ids,
        "status": "dispatched",
        "message": f"Dispatched {total} document processing tasks",
    }


async def _list_documents(source_type: str, source_config: dict[str, Any]) -> list[str]:
    """List all documents from a source.

    Args:
        source_type: Type of source connector.
        source_config: Configuration for the connector.

    Returns:
        List of document source IDs.
    """
    connector = _get_connector(source_type, source_config)
    documents = []

    async with connector:
        async for doc_meta in connector.list_documents():
            documents.append(doc_meta.source_id)

    return documents
