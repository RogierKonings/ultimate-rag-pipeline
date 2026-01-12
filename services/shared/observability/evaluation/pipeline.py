"""
Evaluation Pipeline.

Orchestrates the evaluation process including:
- Sample selection
- RAG execution against live pipeline
- Evaluation execution with timeout
- Result aggregation
- Trend comparison

OpenTelemetry instrumentation is included for distributed tracing.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from .config import EvaluationConfig
from .datasets import EvaluationDataset, EvaluationSample
from .ragas_evaluator import AggregatedResults, EvaluationResult, RagasEvaluator

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__, "1.0.0")


@dataclass
class RAGResponse:
    """Response from the RAG pipeline."""

    answer: str
    contexts: list[str]
    latency_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvaluationRun:
    """A complete evaluation run."""

    id: str
    name: str
    config: EvaluationConfig
    dataset_name: str
    started_at: datetime
    completed_at: datetime | None = None
    results: AggregatedResults | None = None
    status: str = "pending"  # pending, running, completed, failed
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "dataset_name": self.dataset_name,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "results": self.results.to_dict() if self.results else None,
            "status": self.status,
            "error": self.error,
            "metadata": self.metadata,
        }


class RAGClient:
    """Client for interacting with the RAG pipeline API."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        timeout: float = 30.0,
    ):
        """
        Initialize RAG client.

        Args:
            base_url: RAG API base URL
            api_key: Optional API key
            timeout: Request timeout in seconds
        """
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    async def query(
        self,
        question: str,
        tenant_id: str = "default",
        user_id: str | None = None,
    ) -> RAGResponse:
        """
        Send a query to the RAG pipeline.

        Args:
            question: The question to ask
            tenant_id: Tenant identifier
            user_id: Optional user identifier

        Returns:
            RAGResponse with answer and contexts
        """
        with tracer.start_as_current_span(
            "rag_client.query",
            kind=SpanKind.CLIENT,
            attributes={
                "rag.tenant_id": tenant_id,
                "rag.question_length": len(question),
            },
        ) as span:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            # Inject trace context into headers for distributed tracing
            from opentelemetry.propagate import inject
            inject(headers)

            payload = {
                "query": question,
                "tenant_id": tenant_id,
            }
            if user_id:
                payload["user_id"] = user_id
                span.set_attribute("rag.user_id", user_id)

            start_time = time.perf_counter()

            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.post(
                        f"{self.base_url}/api/v1/orchestrate/query",
                        json=payload,
                        headers=headers,
                    )
                    response.raise_for_status()

                end_time = time.perf_counter()
                latency_ms = (end_time - start_time) * 1000

                span.set_attribute("rag.latency_ms", latency_ms)
                span.set_attribute("http.status_code", response.status_code)

                data = response.json()

                span.set_attribute("rag.num_contexts", len(data.get("contexts", [])))
                span.set_status(Status(StatusCode.OK))

                return RAGResponse(
                    answer=data.get("answer", ""),
                    contexts=data.get("contexts", []),
                    latency_ms=latency_ms,
                    metadata={
                        "model": data.get("model"),
                        "retrieval_strategy": data.get("retrieval_strategy"),
                        "num_contexts": len(data.get("contexts", [])),
                    },
                )

            except httpx.HTTPStatusError as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                raise

            except Exception as e:
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                raise


class EvaluationPipeline:
    """
    Main evaluation pipeline orchestrator.

    Coordinates the evaluation process including:
    - Dataset sampling
    - Live RAG pipeline queries (optional)
    - Ragas evaluation
    - Result aggregation and reporting
    """

    def __init__(
        self,
        evaluator: RagasEvaluator | None = None,
        config: EvaluationConfig | None = None,
        rag_client: RAGClient | None = None,
    ):
        """
        Initialize the evaluation pipeline.

        Args:
            evaluator: RagasEvaluator instance
            config: Evaluation configuration
            rag_client: Client for live RAG queries (optional)
        """
        self.config = config or EvaluationConfig.from_env()
        self.evaluator = evaluator or RagasEvaluator(self.config)
        self.rag_client = rag_client
        self._reporters: list[Any] = []

    def add_reporter(self, reporter: Any) -> None:
        """Add a reporter for results."""
        self._reporters.append(reporter)

    async def evaluate(
        self,
        dataset: EvaluationDataset,
        run_name: str | None = None,
        live_rag: bool = False,
        tenant_id: str = "default",
    ) -> AggregatedResults:
        """
        Run evaluation on a dataset.

        Args:
            dataset: Dataset to evaluate
            run_name: Optional name for the run
            live_rag: Whether to query live RAG pipeline for answers
            tenant_id: Tenant ID for live RAG queries

        Returns:
            AggregatedResults with metrics
        """
        from uuid import uuid4

        run_id = str(uuid4())
        run_name = run_name or f"eval_{datetime.now(tz=UTC).strftime('%Y%m%d_%H%M%S')}"

        # Create the parent span for the entire evaluation run
        with tracer.start_as_current_span(
            "evaluation.run",
            kind=SpanKind.INTERNAL,
            attributes={
                "evaluation.run_id": run_id,
                "evaluation.run_name": run_name,
                "evaluation.dataset_name": dataset.name,
                "evaluation.dataset_size": len(dataset),
                "evaluation.live_rag": live_rag,
                "evaluation.sample_size": self.config.sample_size,
                "evaluation.sampling_strategy": self.config.sampling_strategy.value,
            },
        ) as span:
            run = EvaluationRun(
                id=run_id,
                name=run_name,
                config=self.config,
                dataset_name=dataset.name,
                started_at=datetime.now(tz=UTC),
                status="running",
                metadata={
                    "sample_size": self.config.sample_size,
                    "sampling_strategy": self.config.sampling_strategy.value,
                    "live_rag": live_rag,
                    "trace_id": format(span.get_span_context().trace_id, "032x"),
                },
            )

            logger.info(
                f"Starting evaluation run {run_id}: {run_name} "
                f"on dataset {dataset.name} ({len(dataset)} samples)",
            )

            start_time = time.perf_counter()

            try:
                # Sample dataset if configured
                with tracer.start_as_current_span(
                    "evaluation.sample_dataset",
                    attributes={"evaluation.original_size": len(dataset)},
                ) as sample_span:
                    sampled_dataset = self._sample_dataset(dataset)
                    sample_span.set_attribute("evaluation.sampled_size", len(sampled_dataset))
                    logger.info(f"Sampled {len(sampled_dataset)} samples for evaluation")

                span.set_attribute("evaluation.sampled_size", len(sampled_dataset))

                # Get answers from live RAG if requested
                if live_rag:
                    with tracer.start_as_current_span(
                        "evaluation.live_rag",
                        attributes={"evaluation.sample_count": len(sampled_dataset)},
                    ) as rag_span:
                        rag_start = time.perf_counter()
                        sampled_dataset = await self._run_live_rag(
                            sampled_dataset, tenant_id,
                        )
                        rag_duration_ms = (time.perf_counter() - rag_start) * 1000
                        rag_span.set_attribute("evaluation.rag_duration_ms", rag_duration_ms)

                # Run evaluation
                with tracer.start_as_current_span(
                    "evaluation.ragas_evaluate",
                    attributes={"evaluation.sample_count": len(sampled_dataset)},
                ) as eval_span:
                    eval_start = time.perf_counter()
                    results = await self._run_evaluation(sampled_dataset)
                    eval_duration_ms = (time.perf_counter() - eval_start) * 1000
                    eval_span.set_attribute("evaluation.ragas_duration_ms", eval_duration_ms)
                    eval_span.set_attribute("evaluation.result_count", len(results))

                # Aggregate results
                with tracer.start_as_current_span("evaluation.aggregate_results"):
                    aggregated = self.evaluator.aggregate_results(
                        results,
                        metadata={
                            "run_id": run_id,
                            "run_name": run_name,
                            "dataset_name": dataset.name,
                            "live_rag": live_rag,
                        },
                    )

                # Record metrics as span attributes
                for metric_name, metric_data in aggregated.aggregated_metrics.items():
                    span.set_attribute(f"evaluation.metric.{metric_name}.mean", metric_data["mean"])
                    span.set_attribute(f"evaluation.metric.{metric_name}.std", metric_data["std"])

                run.results = aggregated
                run.status = "completed"
                run.completed_at = datetime.now(tz=UTC)

                total_duration_ms = (time.perf_counter() - start_time) * 1000
                span.set_attribute("evaluation.total_duration_ms", total_duration_ms)
                span.set_attribute("evaluation.successful_samples", aggregated.successful_samples)
                span.set_attribute("evaluation.failed_samples", aggregated.failed_samples)
                span.set_status(Status(StatusCode.OK))

                # Report results
                await self._report_results(run)

                logger.info(
                    f"Evaluation run {run_id} completed: "
                    f"{aggregated.successful_samples}/{aggregated.total_samples} successful",
                )

                return aggregated

            except Exception as e:
                logger.error(f"Evaluation run {run_id} failed: {e}")
                run.status = "failed"
                run.error = str(e)
                run.completed_at = datetime.now(tz=UTC)

                total_duration_ms = (time.perf_counter() - start_time) * 1000
                span.set_attribute("evaluation.total_duration_ms", total_duration_ms)
                span.set_status(Status(StatusCode.ERROR, str(e)))
                span.record_exception(e)
                span.add_event("evaluation_failed", {"error": str(e)})

                # Still report the failure
                await self._report_results(run)

                raise

    def _sample_dataset(self, dataset: EvaluationDataset) -> EvaluationDataset:
        """Sample from dataset based on configuration."""
        return dataset.sample(
            n=self.config.sample_size,
            strategy=self.config.sampling_strategy,
            seed=self.config.random_seed,
        )

    async def _run_live_rag(
        self,
        dataset: EvaluationDataset,
        tenant_id: str,
    ) -> EvaluationDataset:
        """Query live RAG pipeline for each sample."""
        if not self.rag_client:
            if not self.config.rag_api_url:
                logger.warning("No RAG client configured, skipping live RAG")
                return dataset

            self.rag_client = RAGClient(
                base_url=self.config.rag_api_url,
                api_key=self.config.rag_api_key,
            )

        updated_samples = []
        total = len(dataset)

        for i, sample in enumerate(dataset):
            try:
                logger.debug(f"Querying RAG for sample {i+1}/{total}")

                response = await asyncio.wait_for(
                    self.rag_client.query(sample.question, tenant_id),
                    timeout=self.config.timeout_seconds,
                )

                # Update sample with RAG response
                updated_sample = EvaluationSample(
                    id=sample.id,
                    question=sample.question,
                    contexts=response.contexts,
                    answer=response.answer,
                    ground_truth=sample.ground_truth,
                    metadata={
                        **sample.metadata,
                        "rag_latency_ms": response.latency_ms,
                        **response.metadata,
                    },
                )
                updated_samples.append(updated_sample)

            except TimeoutError:
                logger.warning(f"Timeout querying RAG for sample {sample.id}")
                # Keep original sample with error metadata
                sample.metadata["rag_error"] = "timeout"
                updated_samples.append(sample)

            except Exception as e:
                logger.warning(f"Error querying RAG for sample {sample.id}: {e}")
                sample.metadata["rag_error"] = str(e)
                updated_samples.append(sample)

        return EvaluationDataset(
            name=f"{dataset.name}_with_rag",
            samples=updated_samples,
            version=dataset.version,
            metadata={**dataset.metadata, "live_rag": True},
        )

    async def _run_evaluation(
        self,
        dataset: EvaluationDataset,
    ) -> list[EvaluationResult]:
        """Run Ragas evaluation on samples."""
        results = []

        # Process in batches
        batch_size = self.config.batch_size
        samples = list(dataset)
        total_batches = (len(samples) + batch_size - 1) // batch_size

        for batch_num in range(total_batches):
            start_idx = batch_num * batch_size
            end_idx = min(start_idx + batch_size, len(samples))
            batch = samples[start_idx:end_idx]

            logger.info(f"Evaluating batch {batch_num + 1}/{total_batches}")

            batch_dicts = [
                {
                    "question": s.question,
                    "contexts": s.contexts,
                    "answer": s.answer,
                    "ground_truth": s.ground_truth,
                    "metadata": s.metadata,
                }
                for s in batch
            ]

            batch_results = await self.evaluator.evaluate_batch(batch_dicts)
            results.extend(batch_results)

        return results

    async def _report_results(self, run: EvaluationRun) -> None:
        """Send results to all registered reporters."""
        for reporter in self._reporters:
            try:
                await reporter.report(run)
            except Exception as e:
                logger.error(f"Reporter {reporter.__class__.__name__} failed: {e}")

    async def compare_runs(
        self,
        current: AggregatedResults,
        baseline: AggregatedResults,
    ) -> dict[str, Any]:
        """
        Compare two evaluation runs.

        Args:
            current: Current run results
            baseline: Baseline run results

        Returns:
            Comparison with deltas and significance
        """
        comparison = {
            "metrics": {},
            "summary": {
                "improved": [],
                "degraded": [],
                "unchanged": [],
            },
        }

        for metric_name in current.aggregated_metrics:
            current_mean = current.aggregated_metrics[metric_name]["mean"]
            current_std = current.aggregated_metrics[metric_name]["std"]

            if metric_name in baseline.aggregated_metrics:
                baseline_mean = baseline.aggregated_metrics[metric_name]["mean"]
                baseline_std = baseline.aggregated_metrics[metric_name]["std"]

                delta = current_mean - baseline_mean
                percent_change = (
                    (delta / baseline_mean * 100) if baseline_mean != 0 else 0
                )

                # Simple significance check (> 1 std deviation)
                significant = abs(delta) > (baseline_std + current_std) / 2

                comparison["metrics"][metric_name] = {
                    "current": current_mean,
                    "baseline": baseline_mean,
                    "delta": delta,
                    "percent_change": percent_change,
                    "significant": significant,
                }

                if significant:
                    if delta > 0:
                        comparison["summary"]["improved"].append(metric_name)
                    else:
                        comparison["summary"]["degraded"].append(metric_name)
                else:
                    comparison["summary"]["unchanged"].append(metric_name)

        return comparison


class ScheduledEvaluationRunner:
    """Runner for scheduled evaluation jobs."""

    def __init__(
        self,
        pipeline: EvaluationPipeline,
        dataset_path: str | None = None,
    ):
        """
        Initialize scheduled runner.

        Args:
            pipeline: EvaluationPipeline instance
            dataset_path: Path to dataset file
        """
        self.pipeline = pipeline
        self.dataset_path = dataset_path or pipeline.config.dataset_path

    async def run_scheduled_evaluation(
        self,
        run_name: str | None = None,
        live_rag: bool = True,
    ) -> AggregatedResults:
        """
        Run a scheduled evaluation.

        Args:
            run_name: Optional name for the run
            live_rag: Whether to query live RAG pipeline

        Returns:
            AggregatedResults
        """
        if not self.dataset_path:
            raise ValueError("No dataset path configured")

        logger.info(f"Loading dataset from {self.dataset_path}")
        dataset = EvaluationDataset.load(self.dataset_path)

        return await self.pipeline.evaluate(
            dataset=dataset,
            run_name=run_name,
            live_rag=live_rag,
        )
