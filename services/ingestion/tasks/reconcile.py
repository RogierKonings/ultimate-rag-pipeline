"""Background index reconciliation task (US-10.1.2).

This module implements automated detection and repair of inconsistencies
between PostgreSQL (authoritative source), Qdrant (vector store), and
OpenSearch (keyword store).

The reconciliation process runs in three phases:
1. Find chunks in PostgreSQL that are missing from external stores
2. Find orphaned entries in external stores not present in PostgreSQL
3. Update document status fields in PostgreSQL

Usage:
    from tasks.reconcile import reconcile_index

    # Single tenant dry-run
    result = await reconcile_index.delay(tenant_id="tenant-123", dry_run=True)

    # Full repair
    result = await reconcile_index.delay(tenant_id="tenant-123", dry_run=False)
"""

import asyncio
import logging
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from celery.exceptions import Reject, SoftTimeLimitExceeded
from sqlalchemy import distinct, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .celery_app import celery_app

if TYPE_CHECKING:
    from shared.database.models.document import Chunk, Document
    from shared.search.opensearch_client import OpenSearchClient
    from shared.vectorstore.qdrant_client import QdrantVectorStore

logger = logging.getLogger(__name__)


class ReconciliationAction(str, Enum):
    """Actions taken during reconciliation."""

    REINDEX_QDRANT = "reindex_qdrant"
    REINDEX_OPENSEARCH = "reindex_opensearch"
    DELETE_ORPHAN_QDRANT = "delete_orphan_qdrant"
    DELETE_ORPHAN_OPENSEARCH = "delete_orphan_opensearch"
    UPDATE_STATUS = "update_status"
    SKIP_NO_ACTION = "skip_no_action"


@dataclass
class ReconciliationIssue:
    """A single inconsistency found during reconciliation."""

    document_id: str
    chunk_id: str | None
    issue_type: Literal[
        "missing_qdrant",
        "missing_opensearch",
        "orphan_qdrant",
        "orphan_opensearch",
        "status_mismatch",
    ]
    action_taken: ReconciliationAction
    success: bool
    error_message: str | None = None


@dataclass
class ReconciliationResult:
    """Result of a reconciliation run."""

    tenant_id: str
    document_id: str | None  # None for full tenant reconciliation
    dry_run: bool
    started_at: datetime
    completed_at: datetime
    documents_scanned: int = 0
    chunks_scanned: int = 0
    issues_found: int = 0
    issues_fixed: int = 0
    issues_failed: int = 0
    issues: list[ReconciliationIssue] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        """Calculate duration of the reconciliation run."""
        return (self.completed_at - self.started_at).total_seconds()

    @property
    def success_rate(self) -> float:
        """Calculate success rate of issue fixes."""
        if self.issues_found == 0:
            return 1.0
        return self.issues_fixed / self.issues_found


@celery_app.task(
    bind=True,
    name="tasks.reconcile.reconcile_index",
    queue="maintenance",
    max_retries=1,
    soft_time_limit=3600,  # 1 hour soft limit
    time_limit=3900,  # 1 hour 5 min hard limit
    acks_late=True,
)
def reconcile_index(
    self,
    tenant_id: str,
    document_id: str | None = None,
    dry_run: bool = False,
    batch_size: int = 100,
) -> dict[str, Any]:
    """Reconcile PostgreSQL authoritative state with Qdrant and OpenSearch.

    Args:
        tenant_id: Tenant to reconcile.
        document_id: Optional specific document (None = all tenant documents).
        dry_run: If True, report issues without fixing.
        batch_size: Number of documents to process per batch.

    Returns:
        ReconciliationResult as dict.
    """
    try:
        return asyncio.run(
            _reconcile_index_async(
                tenant_id=tenant_id,
                document_id=document_id,
                dry_run=dry_run,
                batch_size=batch_size,
            )
        )
    except SoftTimeLimitExceeded:
        logger.error(
            "Reconciliation task timed out",
            extra={"tenant_id": tenant_id, "document_id": document_id},
        )
        raise Reject("Task timed out", requeue=False) from None


async def _reconcile_index_async(
    tenant_id: str,
    document_id: str | None,
    dry_run: bool,
    batch_size: int,
) -> dict[str, Any]:
    """Async implementation of reconciliation logic."""
    from config import get_settings
    from shared.database.connection import get_session_factory
    from shared.search.opensearch_client import OpenSearchClient
    from shared.vectorstore.qdrant_client import QdrantVectorStore

    settings = get_settings()
    started_at = datetime.now(tz=UTC)

    result = ReconciliationResult(
        tenant_id=tenant_id,
        document_id=document_id,
        dry_run=dry_run,
        started_at=started_at,
        completed_at=started_at,  # Updated at end
    )

    logger.info(
        "Reconciliation started",
        extra={
            "tenant_id": tenant_id,
            "document_id": document_id,
            "dry_run": dry_run,
        },
    )

    # Initialize clients
    qdrant = QdrantVectorStore(url=settings.qdrant_url)
    opensearch = OpenSearchClient(url=settings.opensearch_url)

    # Get database session
    session_factory = get_session_factory()

    async with session_factory() as session:
        try:
            # Phase 1: Find missing chunks in external stores
            await _reconcile_missing_chunks(
                session=session,
                qdrant=qdrant,
                opensearch=opensearch,
                tenant_id=tenant_id,
                document_id=document_id,
                batch_size=batch_size,
                dry_run=dry_run,
                result=result,
            )

            # Phase 2: Find orphaned entries in external stores
            await _reconcile_orphaned_entries(
                session=session,
                qdrant=qdrant,
                opensearch=opensearch,
                tenant_id=tenant_id,
                document_id=document_id,
                batch_size=batch_size,
                dry_run=dry_run,
                result=result,
            )

            # Phase 3: Update PostgreSQL status fields
            await _update_document_statuses(
                session=session,
                tenant_id=tenant_id,
                document_id=document_id,
                dry_run=dry_run,
                result=result,
            )

        except Exception as e:
            logger.error(
                "Reconciliation failed",
                extra={"tenant_id": tenant_id, "error": str(e)},
                exc_info=True,
            )
            raise

    result.completed_at = datetime.now(tz=UTC)

    # Update Prometheus metrics
    _update_reconciliation_metrics(result)

    logger.info(
        "Reconciliation completed",
        extra={
            "tenant_id": tenant_id,
            "duration_seconds": result.duration_seconds,
            "documents_scanned": result.documents_scanned,
            "issues_found": result.issues_found,
            "issues_fixed": result.issues_fixed,
        },
    )

    return asdict(result)


async def _reconcile_missing_chunks(
    session: AsyncSession,
    qdrant: "QdrantVectorStore",
    opensearch: "OpenSearchClient",
    tenant_id: str,
    document_id: str | None,
    batch_size: int,
    dry_run: bool,
    result: ReconciliationResult,
) -> None:
    """Find chunks in PostgreSQL that are missing from external stores."""
    from shared.database.models.document import Document

    # Query active documents with their chunks
    stmt = (
        select(Document)
        .options(selectinload(Document.chunks))
        .where(
            Document.tenant_id == UUID(tenant_id),
            Document.status == "active",
        )
    )
    if document_id:
        stmt = stmt.where(Document.id == UUID(document_id))

    # Process in batches
    offset = 0
    while True:
        batch_stmt = stmt.limit(batch_size).offset(offset)
        docs_result = await session.execute(batch_stmt)
        docs = docs_result.scalars().all()

        if not docs:
            break

        for doc in docs:
            result.documents_scanned += 1
            result.chunks_scanned += len(doc.chunks)

            chunk_ids = [str(c.id) for c in doc.chunks if c.status == "active"]
            if not chunk_ids:
                continue

            # Check Qdrant
            qdrant_ids = await qdrant.get_existing_chunk_ids(
                tenant_id=tenant_id,
                chunk_ids=chunk_ids,
            )
            missing_qdrant = set(chunk_ids) - set(qdrant_ids)

            for chunk_id in missing_qdrant:
                chunk = next(c for c in doc.chunks if str(c.id) == chunk_id)
                issue = await _handle_missing_qdrant(
                    session=session,
                    qdrant=qdrant,
                    chunk=chunk,
                    tenant_id=tenant_id,
                    dry_run=dry_run,
                )
                result.issues.append(issue)
                result.issues_found += 1
                if issue.success and not dry_run:
                    result.issues_fixed += 1
                elif not issue.success and not dry_run:
                    result.issues_failed += 1

            # Check OpenSearch
            opensearch_ids = await opensearch.get_existing_chunk_ids(
                tenant_id=tenant_id,
                chunk_ids=chunk_ids,
            )
            missing_opensearch = set(chunk_ids) - set(opensearch_ids)

            for chunk_id in missing_opensearch:
                chunk = next(c for c in doc.chunks if str(c.id) == chunk_id)
                issue = await _handle_missing_opensearch(
                    opensearch=opensearch,
                    chunk=chunk,
                    doc=doc,
                    tenant_id=tenant_id,
                    dry_run=dry_run,
                )
                result.issues.append(issue)
                result.issues_found += 1
                if issue.success and not dry_run:
                    result.issues_fixed += 1
                elif not issue.success and not dry_run:
                    result.issues_failed += 1

        offset += batch_size


async def _reconcile_orphaned_entries(
    session: AsyncSession,
    qdrant: "QdrantVectorStore",
    opensearch: "OpenSearchClient",
    tenant_id: str,
    document_id: str | None,
    batch_size: int,
    dry_run: bool,
    result: ReconciliationResult,
) -> None:
    """Find entries in external stores that don't exist in PostgreSQL."""
    from shared.database.models.document import Chunk, Document

    # Get all active chunk IDs from PostgreSQL for this tenant
    stmt = (
        select(Chunk.id)
        .join(Document)
        .where(
            Document.tenant_id == UUID(tenant_id),
            Document.status == "active",
            Chunk.status == "active",
        )
    )
    if document_id:
        stmt = stmt.where(Document.id == UUID(document_id))

    chunks_result = await session.execute(stmt)
    pg_chunk_ids = {str(chunk_id) for chunk_id in chunks_result.scalars().all()}

    # Get all chunk IDs from Qdrant
    qdrant_chunk_ids = await qdrant.get_all_chunk_ids(tenant_id=tenant_id)
    orphaned_qdrant = set(qdrant_chunk_ids) - pg_chunk_ids

    for chunk_id in orphaned_qdrant:
        issue = await _handle_orphan_qdrant(
            qdrant=qdrant,
            chunk_id=chunk_id,
            tenant_id=tenant_id,
            dry_run=dry_run,
        )
        result.issues.append(issue)
        result.issues_found += 1
        if issue.success and not dry_run:
            result.issues_fixed += 1
        elif not issue.success and not dry_run:
            result.issues_failed += 1

    # Get all chunk IDs from OpenSearch
    opensearch_chunk_ids = await opensearch.get_all_chunk_ids(tenant_id=tenant_id)
    orphaned_opensearch = set(opensearch_chunk_ids) - pg_chunk_ids

    for chunk_id in orphaned_opensearch:
        issue = await _handle_orphan_opensearch(
            opensearch=opensearch,
            chunk_id=chunk_id,
            tenant_id=tenant_id,
            dry_run=dry_run,
        )
        result.issues.append(issue)
        result.issues_found += 1
        if issue.success and not dry_run:
            result.issues_fixed += 1
        elif not issue.success and not dry_run:
            result.issues_failed += 1


async def _update_document_statuses(
    session: AsyncSession,
    tenant_id: str,
    document_id: str | None,
    dry_run: bool,
    result: ReconciliationResult,
) -> None:
    """Update document status fields based on reconciliation results.

    After reconciliation, documents with all chunks successfully indexed
    should have their status set to OK.
    """
    from shared.database.models.document import Document, IndexStatus

    if dry_run:
        return

    # Find documents that were repaired (had issues fixed)
    repaired_doc_ids = {
        issue.document_id
        for issue in result.issues
        if issue.success
        and issue.action_taken
        in (
            ReconciliationAction.REINDEX_QDRANT,
            ReconciliationAction.REINDEX_OPENSEARCH,
        )
    }

    if not repaired_doc_ids:
        return

    # Update status for repaired documents
    for doc_id in repaired_doc_ids:
        try:
            stmt = (
                update(Document)
                .where(Document.id == UUID(doc_id))
                .values(
                    qdrant_status=IndexStatus.OK,
                    opensearch_status=IndexStatus.OK,
                    last_indexed_at=datetime.now(tz=UTC),
                    last_index_error=None,
                )
            )
            await session.execute(stmt)

            result.issues.append(
                ReconciliationIssue(
                    document_id=doc_id,
                    chunk_id=None,
                    issue_type="status_mismatch",
                    action_taken=ReconciliationAction.UPDATE_STATUS,
                    success=True,
                )
            )
        except Exception as e:
            logger.error(
                "Failed to update document status",
                extra={"document_id": doc_id, "error": str(e)},
            )
            result.issues.append(
                ReconciliationIssue(
                    document_id=doc_id,
                    chunk_id=None,
                    issue_type="status_mismatch",
                    action_taken=ReconciliationAction.UPDATE_STATUS,
                    success=False,
                    error_message=str(e),
                )
            )

    await session.commit()


async def _handle_missing_qdrant(
    session: AsyncSession,
    qdrant: "QdrantVectorStore",
    chunk: "Chunk",
    tenant_id: str,
    dry_run: bool,
) -> ReconciliationIssue:
    """Re-index a chunk missing from Qdrant."""
    issue = ReconciliationIssue(
        document_id=str(chunk.document_id),
        chunk_id=str(chunk.id),
        issue_type="missing_qdrant",
        action_taken=(
            ReconciliationAction.SKIP_NO_ACTION if dry_run else ReconciliationAction.REINDEX_QDRANT
        ),
        success=True,
    )

    if dry_run:
        return issue

    try:
        # Get or generate embedding
        embedding = await _get_or_create_embedding(chunk, tenant_id)

        # Upsert to Qdrant
        await qdrant.upsert(
            points=[
                {
                    "id": str(chunk.id),
                    "vector": embedding,
                    "payload": {
                        "document_id": str(chunk.document_id),
                        "tenant_id": tenant_id,
                        "chunk_index": chunk.chunk_index,
                        "content": chunk.content[:500],  # Truncate for payload
                    },
                }
            ]
        )

        logger.info(
            "Reindexed missing chunk to Qdrant",
            extra={"chunk_id": str(chunk.id)},
        )
    except Exception as e:
        issue.success = False
        issue.error_message = str(e)
        logger.error(
            "Failed to reindex chunk to Qdrant",
            extra={"chunk_id": str(chunk.id), "error": str(e)},
        )

    return issue


async def _handle_missing_opensearch(
    opensearch: "OpenSearchClient",
    chunk: "Chunk",
    doc: "Document",
    tenant_id: str,
    dry_run: bool,
) -> ReconciliationIssue:
    """Re-index a chunk missing from OpenSearch."""
    issue = ReconciliationIssue(
        document_id=str(chunk.document_id),
        chunk_id=str(chunk.id),
        issue_type="missing_opensearch",
        action_taken=(
            ReconciliationAction.SKIP_NO_ACTION
            if dry_run
            else ReconciliationAction.REINDEX_OPENSEARCH
        ),
        success=True,
    )

    if dry_run:
        return issue

    try:
        # Index to OpenSearch
        await opensearch.bulk_index(
            documents=[
                {
                    "chunk_id": str(chunk.id),
                    "document_id": str(chunk.document_id),
                    "tenant_id": tenant_id,
                    "content": chunk.content,
                    "title": doc.title or "",
                    "source_uri": doc.source_id,
                    "chunk_index": chunk.chunk_index,
                }
            ]
        )

        logger.info(
            "Reindexed missing chunk to OpenSearch",
            extra={"chunk_id": str(chunk.id)},
        )
    except Exception as e:
        issue.success = False
        issue.error_message = str(e)
        logger.error(
            "Failed to reindex chunk to OpenSearch",
            extra={"chunk_id": str(chunk.id), "error": str(e)},
        )

    return issue


async def _handle_orphan_qdrant(
    qdrant: "QdrantVectorStore",
    chunk_id: str,
    tenant_id: str,
    dry_run: bool,
) -> ReconciliationIssue:
    """Delete an orphaned entry from Qdrant."""
    issue = ReconciliationIssue(
        document_id="unknown",
        chunk_id=chunk_id,
        issue_type="orphan_qdrant",
        action_taken=(
            ReconciliationAction.SKIP_NO_ACTION
            if dry_run
            else ReconciliationAction.DELETE_ORPHAN_QDRANT
        ),
        success=True,
    )

    if dry_run:
        return issue

    try:
        await qdrant.delete_by_chunk_id(chunk_id, tenant_id)
        logger.info(
            "Deleted orphan from Qdrant",
            extra={"chunk_id": chunk_id},
        )
    except Exception as e:
        issue.success = False
        issue.error_message = str(e)
        logger.error(
            "Failed to delete orphan from Qdrant",
            extra={"chunk_id": chunk_id, "error": str(e)},
        )

    return issue


async def _handle_orphan_opensearch(
    opensearch: "OpenSearchClient",
    chunk_id: str,
    tenant_id: str,
    dry_run: bool,
) -> ReconciliationIssue:
    """Delete an orphaned entry from OpenSearch."""
    issue = ReconciliationIssue(
        document_id="unknown",
        chunk_id=chunk_id,
        issue_type="orphan_opensearch",
        action_taken=(
            ReconciliationAction.SKIP_NO_ACTION
            if dry_run
            else ReconciliationAction.DELETE_ORPHAN_OPENSEARCH
        ),
        success=True,
    )

    if dry_run:
        return issue

    try:
        await opensearch.delete_by_chunk_id(chunk_id, tenant_id)
        logger.info(
            "Deleted orphan from OpenSearch",
            extra={"chunk_id": chunk_id},
        )
    except Exception as e:
        issue.success = False
        issue.error_message = str(e)
        logger.error(
            "Failed to delete orphan from OpenSearch",
            extra={"chunk_id": chunk_id, "error": str(e)},
        )

    return issue


async def _get_or_create_embedding(chunk: "Chunk", tenant_id: str) -> list[float]:
    """Get embedding from cache or generate new one.

    Args:
        chunk: The chunk to get embedding for.
        tenant_id: Tenant ID for context.

    Returns:
        Embedding vector.
    """
    from embedding.models import EmbeddingCacheConfig, EmbeddingServiceConfig
    from embedding.service import create_embedding_service

    from config import get_settings

    settings = get_settings()

    # Create embedding service with caching
    service_config = EmbeddingServiceConfig(
        llm_gateway_url=settings.llm_gateway_url,
        model="nomic-embed-text",
        dimensions=768,
    )
    cache_config = EmbeddingCacheConfig(redis_url=settings.redis_url)

    embedding_service = await create_embedding_service(
        config=service_config,
        cache_config=cache_config,
    )

    try:
        # Embed the chunk content
        result = await embedding_service.embed_texts(
            texts=[chunk.content],
            chunk_ids=[chunk.id],
        )
        return result.results[0].embedding
    finally:
        await embedding_service.close()


def _update_reconciliation_metrics(result: ReconciliationResult) -> None:
    """Update Prometheus metrics from reconciliation result."""
    try:
        from telemetry import (
            RECONCILIATION_DURATION,
            RECONCILIATION_MISSING_REINDEXED,
            RECONCILIATION_ORPHANS_CLEANED,
            RECONCILIATION_RUNS,
        )

        if not RECONCILIATION_RUNS:
            return

        status = (
            "success"
            if result.issues_failed == 0
            else "partial"
            if result.issues_fixed > 0
            else "failure"
        )

        RECONCILIATION_RUNS.labels(
            tenant_id=result.tenant_id[:8],
            status=status,
        ).inc()

        if RECONCILIATION_DURATION:
            RECONCILIATION_DURATION.labels(
                tenant_id=result.tenant_id[:8],
            ).observe(result.duration_seconds)

        for issue in result.issues:
            if not issue.success:
                continue

            if RECONCILIATION_ORPHANS_CLEANED:
                if issue.action_taken == ReconciliationAction.DELETE_ORPHAN_QDRANT:
                    RECONCILIATION_ORPHANS_CLEANED.labels(store="qdrant").inc()
                elif issue.action_taken == ReconciliationAction.DELETE_ORPHAN_OPENSEARCH:
                    RECONCILIATION_ORPHANS_CLEANED.labels(store="opensearch").inc()

            if RECONCILIATION_MISSING_REINDEXED:
                if issue.action_taken == ReconciliationAction.REINDEX_QDRANT:
                    RECONCILIATION_MISSING_REINDEXED.labels(store="qdrant").inc()
                elif issue.action_taken == ReconciliationAction.REINDEX_OPENSEARCH:
                    RECONCILIATION_MISSING_REINDEXED.labels(store="opensearch").inc()

    except ImportError:
        # Metrics not configured
        pass
    except Exception as e:
        logger.warning(f"Failed to update reconciliation metrics: {e}")


@celery_app.task(
    name="tasks.reconcile.reconcile_all_tenants",
    queue="maintenance",
)
def reconcile_all_tenants(dry_run: bool = False) -> dict[str, Any]:
    """Run reconciliation for all active tenants.

    This is intended to be scheduled via Celery Beat for nightly runs.

    Args:
        dry_run: If True, report issues without fixing.

    Returns:
        Dict mapping tenant_id to reconciliation result.
    """
    return asyncio.run(_reconcile_all_tenants_async(dry_run=dry_run))


async def _reconcile_all_tenants_async(dry_run: bool) -> dict[str, Any]:
    """Async implementation of all-tenant reconciliation."""
    from shared.database.connection import get_session_factory
    from shared.database.models.document import Document

    session_factory = get_session_factory()

    async with session_factory() as session:
        # Get all distinct tenant IDs with active documents
        stmt = select(distinct(Document.tenant_id)).where(Document.status == "active")
        tenant_result = await session.execute(stmt)
        tenant_ids = [str(tid) for tid in tenant_result.scalars().all()]

    results: dict[str, Any] = {}

    for tenant_id in tenant_ids:
        try:
            result = await _reconcile_index_async(
                tenant_id=tenant_id,
                document_id=None,
                dry_run=dry_run,
                batch_size=100,
            )
            results[tenant_id] = result
        except Exception as e:
            logger.error(
                "Tenant reconciliation failed",
                extra={"tenant_id": tenant_id, "error": str(e)},
            )
            results[tenant_id] = {"error": str(e)}

    return results
