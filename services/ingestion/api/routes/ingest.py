"""Ingestion API routes."""

import logging
from uuid import UUID, uuid4

from api.dependencies import get_current_user, get_job_tracker
from api.schemas import (
    ActiveJobsResponse,
    CancelJobResponse,
    IngestRequest,
    IngestResponse,
    JobProgress,
    JobStatus,
    JobStatusResponse,
    ReembedRequest,
    ReembedResponse,
    SingleIngestRequest,
    SyncRequest,
    SyncResponse,
)
from fastapi import APIRouter, Depends, HTTPException
from tasks.ingest import batch_ingest, process_document
from tasks.models import JobStatus as TaskJobStatus
from tasks.reembed import reembed_collection

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "",
    response_model=IngestResponse,
    status_code=202,
    summary="Start ingestion job",
    description="Trigger an async ingestion job for documents from the specified source.",
)
async def start_ingestion(
    request: IngestRequest,
    current_user: dict = Depends(get_current_user),
) -> IngestResponse:
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
            detail="Cannot ingest documents for another tenant",
        )

    # Generate job ID
    job_id = uuid4()

    # Start async job
    task = batch_ingest.delay(
        job_id=str(job_id),
        source_type=request.source_type.value,
        source_config=request.source_config,
        processing_config=request.processing.model_dump(),
        acl_context=request.acl.model_dump(),
    )

    logger.info(
        f"Started ingestion job {job_id}",
        extra={
            "job_id": str(job_id),
            "source_type": request.source_type.value,
            "tenant_id": request.acl.tenant_id,
        },
    )

    return IngestResponse(
        job_id=UUID(task.id),
        status="pending",
        message="Ingestion job started",
    )


@router.post(
    "/single",
    response_model=IngestResponse,
    status_code=202,
    summary="Ingest single document",
    description="Ingest a single document by source ID.",
)
async def ingest_single_document(
    request: SingleIngestRequest,
    current_user: dict = Depends(get_current_user),
) -> IngestResponse:
    """
    Ingest a single document.

    Useful for incremental ingestion or re-processing specific documents.
    """
    # Validate tenant access
    if request.acl.tenant_id != current_user.get("tenant_id"):
        raise HTTPException(
            status_code=403,
            detail="Cannot ingest documents for another tenant",
        )

    task = process_document.delay(
        document_source_id=request.source_id,
        source_type=request.source_type,
        source_config=request.source_config,
        processing_config=request.processing.model_dump(),
        acl_context=request.acl.model_dump(),
    )

    return IngestResponse(
        job_id=UUID(task.id),
        status="pending",
        message="Document ingestion started",
    )


@router.get(
    "/{job_id}",
    response_model=JobStatusResponse,
    summary="Get job status",
    description="Get the current status and progress of an ingestion job.",
)
async def get_job_status(
    job_id: UUID,
    job_tracker=Depends(get_job_tracker),
) -> JobStatusResponse:
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
            detail=f"Job {job_id} not found",
        )

    # Map task status to API status
    status_map = {
        TaskJobStatus.PENDING: JobStatus.PENDING,
        TaskJobStatus.STARTED: JobStatus.STARTED,
        TaskJobStatus.PROGRESS: JobStatus.PROGRESS,
        TaskJobStatus.SUCCESS: JobStatus.SUCCESS,
        TaskJobStatus.FAILURE: JobStatus.FAILURE,
        TaskJobStatus.REVOKED: JobStatus.REVOKED,
    }
    api_status = status_map.get(status.status, JobStatus.PENDING)

    # Calculate percentage if in progress
    progress = None
    if status.progress and status.progress.total > 0:
        progress = JobProgress(
            current=status.progress.current,
            total=status.progress.total,
            stage=status.progress.stage,
            percentage=round(status.progress.current / status.progress.total * 100, 1),
        )

    return JobStatusResponse(
        job_id=job_id,
        status=api_status,
        progress=progress,
        documents_processed=status.documents_processed,
        chunks_created=status.chunks_created,
        started_at=status.started_at,
        completed_at=status.completed_at,
        duration_seconds=status.duration_seconds,
        error_message=status.error_message,
        errors=status.errors,
    )


@router.delete(
    "/{job_id}",
    response_model=CancelJobResponse,
    summary="Cancel job",
    description="Cancel a running or pending ingestion job.",
)
async def cancel_job(
    job_id: UUID,
    current_user: dict = Depends(get_current_user),
    job_tracker=Depends(get_job_tracker),
) -> CancelJobResponse:
    """
    Cancel an ingestion job.

    Only pending and running jobs can be cancelled.
    """
    status = await job_tracker.get_job_status(str(job_id))

    if status is None:
        raise HTTPException(
            status_code=404,
            detail=f"Job {job_id} not found",
        )

    if status.status in [TaskJobStatus.SUCCESS, TaskJobStatus.FAILURE]:
        raise HTTPException(
            status_code=400,
            detail="Cannot cancel a completed job",
        )

    success = await job_tracker.cancel_job(str(job_id))

    return CancelJobResponse(job_id=job_id, cancelled=success)


@router.get(
    "",
    response_model=ActiveJobsResponse,
    summary="List active jobs",
    description="List all active ingestion jobs.",
)
async def list_active_jobs(
    job_tracker=Depends(get_job_tracker),
    current_user: dict = Depends(get_current_user),
) -> ActiveJobsResponse:
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
            # Map task status to API status
            status_map = {
                TaskJobStatus.PENDING: JobStatus.PENDING,
                TaskJobStatus.STARTED: JobStatus.STARTED,
                TaskJobStatus.PROGRESS: JobStatus.PROGRESS,
                TaskJobStatus.SUCCESS: JobStatus.SUCCESS,
                TaskJobStatus.FAILURE: JobStatus.FAILURE,
                TaskJobStatus.REVOKED: JobStatus.REVOKED,
            }
            api_status = status_map.get(status.status, JobStatus.PENDING)

            jobs.append(
                JobStatusResponse(
                    job_id=UUID(job_id),
                    status=api_status,
                    documents_processed=status.documents_processed,
                    chunks_created=status.chunks_created,
                    started_at=status.started_at,
                    completed_at=status.completed_at,
                    duration_seconds=status.duration_seconds,
                    error_message=status.error_message,
                    errors=status.errors,
                ),
            )

    return ActiveJobsResponse(jobs=jobs, total=len(jobs))


@router.post(
    "/sync",
    response_model=SyncResponse,
    status_code=202,
    summary="Trigger incremental sync",
    description="Start an incremental sync job for a source with updated_since filter.",
)
async def start_sync(
    request: SyncRequest,
    current_user: dict = Depends(get_current_user),
) -> SyncResponse:
    """
    Start an incremental sync for a source.

    This endpoint triggers a sync job that only processes documents
    updated since the specified timestamp. Useful for keeping the
    index up-to-date with source changes.

    **Source Types:**
    - `DATABASE`: Sync from database table with updated_since filter
    - `FILESYSTEM`: Sync modified files from path
    - `WEB`: Re-crawl pages with changes
    - `API`: Sync new/modified records from API
    """
    # Validate tenant access
    if request.tenant_id != current_user.get("tenant_id"):
        raise HTTPException(
            status_code=403,
            detail="Cannot sync documents for another tenant",
        )

    # Generate job ID
    job_id = uuid4()

    # Build source config with updated_since filter
    source_config = request.source_config.model_dump(exclude_none=True)

    # Start async sync job (uses existing batch_ingest with sync mode)
    task = batch_ingest.delay(
        job_id=str(job_id),
        source_type=request.source_type.value,
        source_config=source_config,
        processing_config={"mode": "incremental_sync"},
        acl_context={"tenant_id": request.tenant_id},
    )

    logger.info(
        f"Started sync job {job_id}",
        extra={
            "job_id": str(job_id),
            "source_type": request.source_type.value,
            "tenant_id": request.tenant_id,
            "updated_since": str(request.source_config.updated_since),
        },
    )

    return SyncResponse(
        job_id=UUID(task.id),
        status="queued",
        message="Incremental sync job started",
    )


@router.post(
    "/reembed",
    response_model=ReembedResponse,
    status_code=202,
    summary="Start re-embedding job",
    description="Start a re-embedding job with a new embedding model.",
)
async def start_reembed(
    request: ReembedRequest,
    current_user: dict = Depends(get_current_user),
) -> ReembedResponse:
    """
    Start a re-embedding job with a new model.

    This endpoint triggers a job to re-embed documents with a new
    embedding model. Useful for model migrations when upgrading
    to newer, better performing models.

    **Use Cases:**
    - Upgrading from bge-base to bge-large
    - Switching from English-only to multilingual model
    - Re-embedding after fixing preprocessing issues
    """
    # Validate tenant access if scope specifies tenant
    scope_tenant = request.target_scope.tenant_id
    if scope_tenant and scope_tenant != current_user.get("tenant_id"):
        raise HTTPException(
            status_code=403,
            detail="Cannot re-embed documents for another tenant",
        )

    # If no tenant specified in scope, use current user's tenant
    tenant_id = scope_tenant or current_user.get("tenant_id")

    # Generate IDs
    job_id = uuid4()
    embedding_job_id = uuid4()

    # Start async reembed job
    task = reembed_collection.delay(
        collection_name="rag_chunks",  # Default collection
        new_model=request.embedding_model,
        batch_size=request.batch_size,
        tenant_id=tenant_id,
    )

    logger.info(
        f"Started re-embedding job {embedding_job_id}",
        extra={
            "job_id": str(job_id),
            "embedding_job_id": str(embedding_job_id),
            "embedding_model": request.embedding_model,
            "tenant_id": tenant_id,
        },
    )

    return ReembedResponse(
        job_id=UUID(task.id),
        embedding_job_id=embedding_job_id,
        status="pending",
        message=f"Re-embedding job started with model {request.embedding_model}",
    )
