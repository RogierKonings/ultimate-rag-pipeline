"""
Evaluation API Endpoints.

Provides REST API for managing evaluation datasets and runs.
"""

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from .config import EvaluationConfig
from .datasets import EvaluationSample
from .persistence import EvaluationRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/eval", tags=["evaluation"])


# =============================================================================
# Pydantic Models
# =============================================================================

class DatasetCreate(BaseModel):
    """Request to create a dataset."""

    name: str = Field(..., min_length=1, max_length=255)
    description: str = ""
    version: str = "1.0.0"
    config: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DatasetResponse(BaseModel):
    """Dataset response model."""

    id: str
    name: str
    description: str
    version: str
    example_count: int
    config: dict[str, Any]
    metadata: dict[str, Any]
    created_at: str
    updated_at: str


class ExampleCreate(BaseModel):
    """Request to create an example."""

    question: str = Field(..., min_length=1)
    contexts: list[str] = Field(default_factory=list)
    answer: str = ""
    ground_truth: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExampleBulkCreate(BaseModel):
    """Request to create multiple examples."""

    examples: list[ExampleCreate]


class ExampleResponse(BaseModel):
    """Example response model."""

    id: str
    dataset_id: str
    question: str
    contexts: list[str]
    answer: str
    ground_truth: str | None
    metadata: dict[str, Any]
    created_at: str


class RunCreate(BaseModel):
    """Request to create a run."""

    name: str = Field(..., min_length=1, max_length=255)
    dataset_id: str | None = None
    dataset_name: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    pipeline_version: str | None = None
    model_version: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunResponse(BaseModel):
    """Run response model."""

    id: str
    name: str
    dataset_id: str | None
    dataset_name: str | None
    status: str
    total_samples: int
    successful_samples: int
    failed_samples: int
    aggregated_scores: dict[str, Any] | None
    pipeline_version: str | None
    model_version: str | None
    started_at: str
    completed_at: str | None
    error_message: str | None


class RunMetricsResponse(BaseModel):
    """Run metrics response model."""

    run_id: str
    metrics: list[dict[str, Any]]


class MetricTrendResponse(BaseModel):
    """Metric trend response model."""

    metric_name: str
    data_points: list[dict[str, Any]]


class RunCompareResponse(BaseModel):
    """Run comparison response model."""

    run1: dict[str, Any]
    run2: dict[str, Any]
    metrics: dict[str, dict[str, float]]


# =============================================================================
# Dependency
# =============================================================================

_repository: EvaluationRepository | None = None


async def get_repository() -> EvaluationRepository:
    """Get the evaluation repository."""
    global _repository

    if _repository is None:
        config = EvaluationConfig.from_env()
        if not config.postgres_url:
            raise HTTPException(
                status_code=500,
                detail="Database not configured",
            )
        _repository = EvaluationRepository(config.postgres_url)

    return _repository


# =============================================================================
# Dataset Endpoints
# =============================================================================

@router.post("/datasets", response_model=dict[str, str], status_code=201)
async def create_dataset(
    request: DatasetCreate,
    repo: EvaluationRepository = Depends(get_repository),
):
    """Create a new evaluation dataset."""
    try:
        dataset_id = await repo.create_dataset(
            name=request.name,
            description=request.description,
            version=request.version,
            config=request.config,
            metadata=request.metadata,
        )
        return {"id": dataset_id}
    except Exception as e:
        if "unique" in str(e).lower():
            raise HTTPException(status_code=409, detail="Dataset name already exists") from e
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/datasets", response_model=list[DatasetResponse])
async def list_datasets(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: EvaluationRepository = Depends(get_repository),
):
    """List all evaluation datasets."""
    datasets = await repo.list_datasets(limit=limit, offset=offset)

    return [
        DatasetResponse(
            id=str(d["id"]),
            name=d["name"],
            description=d.get("description", ""),
            version=d.get("version", "1.0.0"),
            example_count=d.get("example_count", 0),
            config=d.get("config", {}),
            metadata=d.get("metadata", {}),
            created_at=d["created_at"].isoformat() if d.get("created_at") else "",
            updated_at=d["updated_at"].isoformat() if d.get("updated_at") else "",
        )
        for d in datasets
    ]


@router.get("/datasets/{dataset_id}", response_model=DatasetResponse)
async def get_dataset(
    dataset_id: str,
    repo: EvaluationRepository = Depends(get_repository),
):
    """Get a dataset by ID."""
    dataset = await repo.get_dataset(dataset_id)

    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    return DatasetResponse(
        id=str(dataset["id"]),
        name=dataset["name"],
        description=dataset.get("description", ""),
        version=dataset.get("version", "1.0.0"),
        example_count=dataset.get("example_count", 0),
        config=dataset.get("config", {}),
        metadata=dataset.get("metadata", {}),
        created_at=dataset["created_at"].isoformat() if dataset.get("created_at") else "",
        updated_at=dataset["updated_at"].isoformat() if dataset.get("updated_at") else "",
    )


@router.delete("/datasets/{dataset_id}", status_code=204)
async def delete_dataset(
    dataset_id: str,
    repo: EvaluationRepository = Depends(get_repository),
):
    """Delete a dataset."""
    deleted = await repo.delete_dataset(dataset_id)

    if not deleted:
        raise HTTPException(status_code=404, detail="Dataset not found")


# =============================================================================
# Example Endpoints
# =============================================================================

@router.post("/datasets/{dataset_id}/examples", response_model=dict[str, str], status_code=201)
async def add_example(
    dataset_id: str,
    request: ExampleCreate,
    repo: EvaluationRepository = Depends(get_repository),
):
    """Add an example to a dataset."""
    # Verify dataset exists
    dataset = await repo.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    example_id = await repo.add_example(
        dataset_id=dataset_id,
        question=request.question,
        contexts=request.contexts,
        answer=request.answer,
        ground_truth=request.ground_truth,
        metadata=request.metadata,
    )

    return {"id": example_id}


@router.post("/datasets/{dataset_id}/examples/bulk", response_model=dict[str, int], status_code=201)
async def add_examples_bulk(
    dataset_id: str,
    request: ExampleBulkCreate,
    repo: EvaluationRepository = Depends(get_repository),
):
    """Add multiple examples to a dataset."""
    # Verify dataset exists
    dataset = await repo.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    samples = [
        EvaluationSample(
            question=ex.question,
            contexts=ex.contexts,
            answer=ex.answer,
            ground_truth=ex.ground_truth,
            metadata=ex.metadata,
        )
        for ex in request.examples
    ]

    count = await repo.add_examples_bulk(dataset_id, samples)

    return {"count": count}


@router.get("/datasets/{dataset_id}/examples", response_model=list[ExampleResponse])
async def list_examples(
    dataset_id: str,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    repo: EvaluationRepository = Depends(get_repository),
):
    """List examples in a dataset."""
    examples = await repo.get_examples(dataset_id, limit=limit, offset=offset)

    return [
        ExampleResponse(
            id=str(ex["id"]),
            dataset_id=str(ex["dataset_id"]),
            question=ex["question"],
            contexts=ex["contexts"] if isinstance(ex["contexts"], list) else [],
            answer=ex.get("answer", ""),
            ground_truth=ex.get("ground_truth"),
            metadata=ex.get("metadata", {}),
            created_at=ex["created_at"].isoformat() if ex.get("created_at") else "",
        )
        for ex in examples
    ]


# =============================================================================
# Run Endpoints
# =============================================================================

@router.post("/runs", response_model=dict[str, str], status_code=201)
async def create_run(
    request: RunCreate,
    repo: EvaluationRepository = Depends(get_repository),
):
    """Create a new evaluation run."""
    run_id = await repo.create_run(
        name=request.name,
        dataset_id=request.dataset_id,
        dataset_name=request.dataset_name,
        config=request.config,
        pipeline_version=request.pipeline_version,
        model_version=request.model_version,
        metadata=request.metadata,
    )

    return {"id": run_id}


@router.get("/runs", response_model=list[RunResponse])
async def list_runs(
    dataset_id: str | None = None,
    status: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: EvaluationRepository = Depends(get_repository),
):
    """List evaluation runs."""
    runs = await repo.list_runs(
        dataset_id=dataset_id,
        status=status,
        limit=limit,
        offset=offset,
    )

    return [
        RunResponse(
            id=str(r["id"]),
            name=r["name"],
            dataset_id=str(r["dataset_id"]) if r.get("dataset_id") else None,
            dataset_name=r.get("dataset_name"),
            status=r["status"],
            total_samples=r.get("total_samples", 0),
            successful_samples=r.get("successful_samples", 0),
            failed_samples=r.get("failed_samples", 0),
            aggregated_scores=r.get("aggregated_scores"),
            pipeline_version=r.get("pipeline_version"),
            model_version=r.get("model_version"),
            started_at=r["started_at"].isoformat() if r.get("started_at") else "",
            completed_at=r["completed_at"].isoformat() if r.get("completed_at") else None,
            error_message=r.get("error_message"),
        )
        for r in runs
    ]


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(
    run_id: str,
    repo: EvaluationRepository = Depends(get_repository),
):
    """Get a run by ID."""
    run = await repo.get_run(run_id)

    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    return RunResponse(
        id=str(run["id"]),
        name=run["name"],
        dataset_id=str(run["dataset_id"]) if run.get("dataset_id") else None,
        dataset_name=run.get("dataset_name"),
        status=run["status"],
        total_samples=run.get("total_samples", 0),
        successful_samples=run.get("successful_samples", 0),
        failed_samples=run.get("failed_samples", 0),
        aggregated_scores=run.get("aggregated_scores"),
        pipeline_version=run.get("pipeline_version"),
        model_version=run.get("model_version"),
        started_at=run["started_at"].isoformat() if run.get("started_at") else "",
        completed_at=run["completed_at"].isoformat() if run.get("completed_at") else None,
        error_message=run.get("error_message"),
    )


@router.get("/runs/{run_id}/metrics", response_model=RunMetricsResponse)
async def get_run_metrics(
    run_id: str,
    repo: EvaluationRepository = Depends(get_repository),
):
    """Get metrics for a run."""
    run = await repo.get_run(run_id)

    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    return RunMetricsResponse(
        run_id=run_id,
        metrics=run.get("metrics", []),
    )


@router.get("/metrics/{metric_name}/trend", response_model=MetricTrendResponse)
async def get_metric_trend(
    metric_name: str,
    dataset_id: str | None = None,
    limit: int = Query(30, ge=1, le=100),
    repo: EvaluationRepository = Depends(get_repository),
):
    """Get metric trend over time."""
    data_points = await repo.get_metric_trend(
        metric_name=metric_name,
        dataset_id=dataset_id,
        limit=limit,
    )

    return MetricTrendResponse(
        metric_name=metric_name,
        data_points=[
            {
                "timestamp": dp["started_at"].isoformat() if dp.get("started_at") else "",
                "mean": dp.get("mean", 0),
                "std": dp.get("std", 0),
                "run_name": dp.get("run_name", ""),
            }
            for dp in data_points
        ],
    )


@router.get("/runs/compare", response_model=RunCompareResponse)
async def compare_runs(
    run_id_1: str = Query(..., description="First run ID"),
    run_id_2: str = Query(..., description="Second run ID"),
    repo: EvaluationRepository = Depends(get_repository),
):
    """Compare two evaluation runs."""
    comparison = await repo.compare_runs(run_id_1, run_id_2)

    if "error" in comparison:
        raise HTTPException(status_code=404, detail=comparison["error"])

    return RunCompareResponse(**comparison)


@router.get("/datasets/{dataset_id}/runs", response_model=list[RunResponse])
async def list_dataset_runs(
    dataset_id: str,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    repo: EvaluationRepository = Depends(get_repository),
):
    """List runs for a specific dataset."""
    # Verify dataset exists
    dataset = await repo.get_dataset(dataset_id)
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found")

    runs = await repo.list_runs(dataset_id=dataset_id, limit=limit, offset=offset)

    return [
        RunResponse(
            id=str(r["id"]),
            name=r["name"],
            dataset_id=str(r["dataset_id"]) if r.get("dataset_id") else None,
            dataset_name=r.get("dataset_name"),
            status=r["status"],
            total_samples=r.get("total_samples", 0),
            successful_samples=r.get("successful_samples", 0),
            failed_samples=r.get("failed_samples", 0),
            aggregated_scores=r.get("aggregated_scores"),
            pipeline_version=r.get("pipeline_version"),
            model_version=r.get("model_version"),
            started_at=r["started_at"].isoformat() if r.get("started_at") else "",
            completed_at=r["completed_at"].isoformat() if r.get("completed_at") else None,
            error_message=r.get("error_message"),
        )
        for r in runs
    ]
