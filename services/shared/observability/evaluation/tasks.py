"""
Celery Tasks for Scheduled Evaluation.

Provides background tasks for running RAG evaluations:
- Scheduled daily/weekly evaluations
- On-demand evaluation runs
- Result reporting and notifications

OpenTelemetry instrumentation is included for distributed tracing.
"""

import logging
import time
from datetime import UTC
from typing import Any

from celery import shared_task
from opentelemetry import trace
from opentelemetry.trace import SpanKind, Status, StatusCode

from .config import EvaluationConfig
from .datasets import EvaluationDataset
from .pipeline import EvaluationPipeline, ScheduledEvaluationRunner
from .ragas_evaluator import RagasEvaluator
from .reporters import (
    GrafanaAnnotationReporter,
    JSONFileReporter,
    PostgreSQLReporter,
    SlackReporter,
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__, "1.0.0")


def _get_reporters(config: EvaluationConfig) -> list:
    """Create reporters based on configuration."""
    reporters = []

    if "json" in config.result_storage:
        reporters.append(
            JSONFileReporter(
                output_dir=config.result_dir,
                include_individual=True,
            ),
        )

    if "postgres" in config.result_storage and config.postgres_url:
        reporters.append(
            PostgreSQLReporter(
                connection_url=config.postgres_url,
            ),
        )

    if "grafana" in config.result_storage and config.grafana_url and config.grafana_api_key:
        reporters.append(
            GrafanaAnnotationReporter(
                grafana_url=config.grafana_url,
                api_key=config.grafana_api_key,
            ),
        )

    if config.slack_webhook_url:
        reporters.append(
            SlackReporter(
                webhook_url=config.slack_webhook_url,
                mention_on_failure="@oncall",
            ),
        )

    return reporters


@shared_task(
    name="evaluation.run_scheduled",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
)
def run_scheduled_evaluation(
    self,
    dataset_path: str | None = None,
    run_name: str | None = None,
    live_rag: bool = True,
    config_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Run a scheduled evaluation task.

    Args:
        dataset_path: Path to evaluation dataset
        run_name: Optional name for the run
        live_rag: Whether to query live RAG pipeline
        config_overrides: Optional config overrides

    Returns:
        Evaluation results summary
    """
    import asyncio

    with tracer.start_as_current_span(
        "celery.evaluation.run_scheduled",
        kind=SpanKind.CONSUMER,
        attributes={
            "celery.task_id": self.request.id,
            "celery.task_name": "evaluation.run_scheduled",
            "evaluation.live_rag": live_rag,
            "evaluation.dataset_path": dataset_path or "",
        },
    ) as span:
        start_time = time.perf_counter()

        logger.info(f"Starting scheduled evaluation task {self.request.id}")

        try:
            # Load configuration
            config = EvaluationConfig.from_env()
            if config_overrides:
                for key, value in config_overrides.items():
                    if hasattr(config, key):
                        setattr(config, key, value)

            # Override dataset path if provided
            if dataset_path:
                config.dataset_path = dataset_path

            # Validate configuration
            errors = config.validate()
            if errors:
                span.set_status(Status(StatusCode.ERROR, f"Invalid configuration: {errors}"))
                span.add_event("config_validation_failed", {"errors": str(errors)})
                raise ValueError(f"Invalid configuration: {errors}")

            span.set_attribute("evaluation.sample_size", config.sample_size or 0)
            span.set_attribute("evaluation.metrics", ",".join(config.metrics))

            # Create pipeline with reporters
            evaluator = RagasEvaluator(config)
            pipeline = EvaluationPipeline(evaluator=evaluator, config=config)

            reporters = _get_reporters(config)
            for reporter in reporters:
                pipeline.add_reporter(reporter)

            span.set_attribute("evaluation.reporter_count", len(reporters))

            # Create runner
            runner = ScheduledEvaluationRunner(pipeline, config.dataset_path)

            # Run evaluation
            async def _run():
                return await runner.run_scheduled_evaluation(
                    run_name=run_name or f"scheduled_{self.request.id}",
                    live_rag=live_rag,
                )

            results = asyncio.run(_run())

            duration_ms = (time.perf_counter() - start_time) * 1000
            span.set_attribute("evaluation.duration_ms", duration_ms)
            span.set_attribute("evaluation.total_samples", results.total_samples)
            span.set_attribute("evaluation.successful_samples", results.successful_samples)
            span.set_attribute("evaluation.failed_samples", results.failed_samples)

            # Record metrics as span attributes
            for metric_name, stats in results.aggregated_metrics.items():
                span.set_attribute(f"evaluation.metric.{metric_name}.mean", stats["mean"])

            span.set_status(Status(StatusCode.OK))
            span.add_event("evaluation_completed", {
                "total_samples": results.total_samples,
                "successful_samples": results.successful_samples,
            })

            logger.info(f"Completed scheduled evaluation task {self.request.id}")

            return {
                "task_id": self.request.id,
                "total_samples": results.total_samples,
                "successful_samples": results.successful_samples,
                "failed_samples": results.failed_samples,
                "metrics": {
                    metric: stats["mean"]
                    for metric, stats in results.aggregated_metrics.items()
                },
            }

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            span.set_attribute("evaluation.duration_ms", duration_ms)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            span.add_event("evaluation_failed", {"error": str(e)})
            logger.error(f"Scheduled evaluation task {self.request.id} failed: {e}")
            raise


@shared_task(
    name="evaluation.run_on_demand",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 2},
)
def run_on_demand_evaluation(
    self,
    samples: list[dict[str, Any]],
    run_name: str | None = None,
    metrics: list[str] | None = None,
) -> dict[str, Any]:
    """
    Run an on-demand evaluation on provided samples.

    Args:
        samples: List of sample dicts with question, contexts, answer, ground_truth
        run_name: Optional name for the run
        metrics: Optional list of metrics to compute

    Returns:
        Evaluation results
    """
    import asyncio
    from datetime import datetime

    with tracer.start_as_current_span(
        "celery.evaluation.run_on_demand",
        kind=SpanKind.CONSUMER,
        attributes={
            "celery.task_id": self.request.id,
            "celery.task_name": "evaluation.run_on_demand",
            "evaluation.sample_count": len(samples),
            "evaluation.metrics": ",".join(metrics) if metrics else "",
        },
    ) as span:
        start_time = time.perf_counter()

        logger.info(f"Starting on-demand evaluation task {self.request.id}")

        try:
            # Load configuration
            config = EvaluationConfig.from_env()
            if metrics:
                config.metrics = metrics

            # Create dataset from samples
            from .datasets import EvaluationSample

            eval_samples = [EvaluationSample.from_dict(s) for s in samples]
            dataset = EvaluationDataset(
                name=f"on_demand_{datetime.now(tz=UTC).strftime('%Y%m%d_%H%M%S')}",
                samples=eval_samples,
                description="On-demand evaluation dataset",
            )

            span.set_attribute("evaluation.dataset_name", dataset.name)

            # Create pipeline
            evaluator = RagasEvaluator(config)
            pipeline = EvaluationPipeline(evaluator=evaluator, config=config)

            # Add JSON reporter for on-demand runs
            pipeline.add_reporter(
                JSONFileReporter(
                    output_dir=config.result_dir,
                    include_individual=True,
                ),
            )

            # Run evaluation
            async def _run():
                return await pipeline.evaluate(
                    dataset=dataset,
                    run_name=run_name or f"on_demand_{self.request.id}",
                    live_rag=False,  # Samples already have answers
                )

            results = asyncio.run(_run())

            duration_ms = (time.perf_counter() - start_time) * 1000
            span.set_attribute("evaluation.duration_ms", duration_ms)
            span.set_attribute("evaluation.total_samples", results.total_samples)
            span.set_attribute("evaluation.successful_samples", results.successful_samples)
            span.set_attribute("evaluation.failed_samples", results.failed_samples)

            # Record metrics as span attributes
            for metric_name, stats in results.aggregated_metrics.items():
                span.set_attribute(f"evaluation.metric.{metric_name}.mean", stats["mean"])
                span.set_attribute(f"evaluation.metric.{metric_name}.std", stats["std"])

            span.set_status(Status(StatusCode.OK))
            span.add_event("evaluation_completed", {
                "total_samples": results.total_samples,
                "successful_samples": results.successful_samples,
            })

            logger.info(f"Completed on-demand evaluation task {self.request.id}")

            return {
                "task_id": self.request.id,
                "total_samples": results.total_samples,
                "successful_samples": results.successful_samples,
                "failed_samples": results.failed_samples,
                "metrics": {
                    metric: {
                        "mean": stats["mean"],
                        "std": stats["std"],
                        "min": stats["min"],
                        "max": stats["max"],
                    }
                    for metric, stats in results.aggregated_metrics.items()
                },
                "individual_results": [
                    {
                        "question": r.question[:100],
                        "metrics": r.metrics,
                    }
                    for r in results.individual_results
                ],
            }

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            span.set_attribute("evaluation.duration_ms", duration_ms)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            span.add_event("evaluation_failed", {"error": str(e)})
            logger.error(f"On-demand evaluation task {self.request.id} failed: {e}")
            raise


@shared_task(name="evaluation.compare_runs")
def compare_evaluation_runs(
    current_run_id: str,
    baseline_run_id: str,
) -> dict[str, Any]:
    """
    Compare two evaluation runs.

    Args:
        current_run_id: ID of current run
        baseline_run_id: ID of baseline run

    Returns:
        Comparison results
    """
    import asyncio

    with tracer.start_as_current_span(
        "celery.evaluation.compare_runs",
        kind=SpanKind.CONSUMER,
        attributes={
            "evaluation.current_run_id": current_run_id,
            "evaluation.baseline_run_id": baseline_run_id,
        },
    ) as span:
        start_time = time.perf_counter()

        logger.info(f"Comparing runs {current_run_id} vs {baseline_run_id}")

        try:
            config = EvaluationConfig.from_env()

            if not config.postgres_url:
                span.set_status(Status(StatusCode.ERROR, "PostgreSQL URL required"))
                raise ValueError("PostgreSQL URL required for run comparison")

            async def _compare():
                reporter = PostgreSQLReporter(connection_url=config.postgres_url)

                # Get runs from database
                pool = await reporter._get_pool()

                async with pool.acquire() as conn:
                    current_row = await conn.fetchrow(
                        "SELECT * FROM eval_runs WHERE id = $1", current_run_id,
                    )
                    baseline_row = await conn.fetchrow(
                        "SELECT * FROM eval_runs WHERE id = $1", baseline_run_id,
                    )

                    if not current_row or not baseline_row:
                        raise ValueError("One or both runs not found")

                    # Get metrics for both runs
                    current_metrics = await conn.fetch(
                        "SELECT * FROM eval_metrics WHERE run_id = $1", current_run_id,
                    )
                    baseline_metrics = await conn.fetch(
                        "SELECT * FROM eval_metrics WHERE run_id = $1", baseline_run_id,
                    )

                # Build comparison
                comparison = {
                    "current_run": {
                        "id": current_run_id,
                        "name": current_row["name"],
                        "started_at": current_row["started_at"].isoformat(),
                    },
                    "baseline_run": {
                        "id": baseline_run_id,
                        "name": baseline_row["name"],
                        "started_at": baseline_row["started_at"].isoformat(),
                    },
                    "metrics": {},
                    "summary": {"improved": [], "degraded": [], "unchanged": []},
                }

                # Compare metrics
                baseline_dict = {m["metric_name"]: m for m in baseline_metrics}

                for metric in current_metrics:
                    name = metric["metric_name"]
                    current_mean = metric["mean"]
                    current_std = metric["std"]

                    if name in baseline_dict:
                        baseline_mean = baseline_dict[name]["mean"]
                        baseline_std = baseline_dict[name]["std"]

                        delta = current_mean - baseline_mean
                        percent_change = (delta / baseline_mean * 100) if baseline_mean else 0
                        significant = abs(delta) > (baseline_std + current_std) / 2

                        comparison["metrics"][name] = {
                            "current": current_mean,
                            "baseline": baseline_mean,
                            "delta": delta,
                            "percent_change": percent_change,
                            "significant": significant,
                        }

                        if significant:
                            if delta > 0:
                                comparison["summary"]["improved"].append(name)
                            else:
                                comparison["summary"]["degraded"].append(name)
                        else:
                            comparison["summary"]["unchanged"].append(name)

                return comparison

            result = asyncio.run(_compare())

            duration_ms = (time.perf_counter() - start_time) * 1000
            span.set_attribute("evaluation.duration_ms", duration_ms)
            span.set_attribute("evaluation.improved_count", len(result["summary"]["improved"]))
            span.set_attribute("evaluation.degraded_count", len(result["summary"]["degraded"]))
            span.set_attribute("evaluation.unchanged_count", len(result["summary"]["unchanged"]))
            span.set_status(Status(StatusCode.OK))

            return result

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000
            span.set_attribute("evaluation.duration_ms", duration_ms)
            span.set_status(Status(StatusCode.ERROR, str(e)))
            span.record_exception(e)
            logger.error(f"Run comparison failed: {e}")
            raise


# Celery Beat schedule configuration
# Add to your celery config:
#
# CELERY_BEAT_SCHEDULE = {
#     'daily-evaluation': {
#         'task': 'evaluation.run_scheduled',
#         'schedule': crontab(hour=2, minute=0),  # 2 AM daily
#         'kwargs': {
#             'run_name': 'daily_evaluation',
#             'live_rag': True,
#         },
#     },
#     'weekly-comprehensive-evaluation': {
#         'task': 'evaluation.run_scheduled',
#         'schedule': crontab(hour=3, minute=0, day_of_week=0),  # Sunday 3 AM
#         'kwargs': {
#             'run_name': 'weekly_comprehensive',
#             'live_rag': True,
#             'config_overrides': {'sample_size': None},  # Full dataset
#         },
#     },
# }
