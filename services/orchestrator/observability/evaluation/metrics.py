"""
Evaluation Metrics Export.

Provides Prometheus metrics for evaluation runs, including:
- Evaluation run counters
- Metric gauges for RAG quality scores
- Latency histograms
- Sample counts
"""

import logging
from typing import Any

from prometheus_client import Counter, Gauge, Histogram, Info

logger = logging.getLogger(__name__)


# =============================================================================
# Counters
# =============================================================================

EVALUATION_RUNS_TOTAL = Counter(
    "rag_evaluation_runs_total",
    "Total number of evaluation runs",
    ["dataset_name", "status"],
)

EVALUATION_SAMPLES_TOTAL = Counter(
    "rag_evaluation_samples_total",
    "Total number of samples evaluated",
    ["dataset_name", "status"],
)

EVALUATION_ERRORS_TOTAL = Counter(
    "rag_evaluation_errors_total",
    "Total number of evaluation errors",
    ["dataset_name", "error_type"],
)


# =============================================================================
# Gauges - Current metric values
# =============================================================================

CONTEXT_PRECISION_GAUGE = Gauge(
    "rag_context_precision",
    "Context precision score from latest evaluation",
    ["dataset_name", "run_name"],
)

CONTEXT_RECALL_GAUGE = Gauge(
    "rag_context_recall",
    "Context recall score from latest evaluation",
    ["dataset_name", "run_name"],
)

FAITHFULNESS_GAUGE = Gauge(
    "rag_faithfulness",
    "Faithfulness score from latest evaluation",
    ["dataset_name", "run_name"],
)

ANSWER_RELEVANCY_GAUGE = Gauge(
    "rag_answer_relevancy",
    "Answer relevancy score from latest evaluation",
    ["dataset_name", "run_name"],
)

ANSWER_SIMILARITY_GAUGE = Gauge(
    "rag_answer_similarity",
    "Answer similarity score from latest evaluation",
    ["dataset_name", "run_name"],
)

ANSWER_CORRECTNESS_GAUGE = Gauge(
    "rag_answer_correctness",
    "Answer correctness score from latest evaluation",
    ["dataset_name", "run_name"],
)

# Generic metric gauge for custom metrics
EVALUATION_METRIC_GAUGE = Gauge(
    "rag_evaluation_metric",
    "Evaluation metric value",
    ["dataset_name", "run_name", "metric_name", "statistic"],
)


# =============================================================================
# Histograms
# =============================================================================

EVALUATION_DURATION_HISTOGRAM = Histogram(
    "rag_evaluation_duration_seconds",
    "Duration of evaluation runs in seconds",
    ["dataset_name", "live_rag"],
    buckets=[10, 30, 60, 120, 300, 600, 1200, 3600],
)

RAG_QUERY_LATENCY_HISTOGRAM = Histogram(
    "rag_evaluation_query_latency_ms",
    "Latency of RAG queries during evaluation in milliseconds",
    ["dataset_name"],
    buckets=[50, 100, 200, 500, 1000, 2000, 5000, 10000],
)

SAMPLE_EVALUATION_DURATION_HISTOGRAM = Histogram(
    "rag_sample_evaluation_duration_seconds",
    "Duration to evaluate a single sample",
    ["dataset_name", "metric_name"],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60],
)


# =============================================================================
# Info metrics
# =============================================================================

LATEST_EVALUATION_INFO = Info(
    "rag_latest_evaluation",
    "Information about the latest evaluation run",
)


# =============================================================================
# Metrics Registry Helper
# =============================================================================


class EvaluationMetricsExporter:
    """
    Exports evaluation results to Prometheus metrics.

    This class provides methods to record evaluation results as Prometheus
    metrics, which can then be scraped and visualized in Grafana.
    """

    # Mapping of Ragas metric names to gauge metrics
    METRIC_GAUGES = {
        "context_precision": CONTEXT_PRECISION_GAUGE,
        "context_recall": CONTEXT_RECALL_GAUGE,
        "faithfulness": FAITHFULNESS_GAUGE,
        "answer_relevancy": ANSWER_RELEVANCY_GAUGE,
        "answer_similarity": ANSWER_SIMILARITY_GAUGE,
        "answer_correctness": ANSWER_CORRECTNESS_GAUGE,
    }

    def __init__(self):
        """Initialize the metrics exporter."""
        self._last_run_info: dict[str, Any] = {}

    def record_run_start(
        self,
        run_id: str,
        run_name: str,
        dataset_name: str,
        sample_count: int,
        live_rag: bool = False,
    ) -> None:
        """
        Record the start of an evaluation run.

        Args:
            run_id: Unique run identifier
            run_name: Human-readable run name
            dataset_name: Name of the evaluation dataset
            sample_count: Number of samples to evaluate
            live_rag: Whether live RAG queries are used
        """
        self._last_run_info = {
            "run_id": run_id,
            "run_name": run_name,
            "dataset_name": dataset_name,
            "sample_count": str(sample_count),
            "live_rag": str(live_rag),
            "status": "running",
        }
        LATEST_EVALUATION_INFO.info(self._last_run_info)

        logger.debug(f"Recorded evaluation run start: {run_id}")

    def record_run_completion(
        self,
        run_id: str,
        run_name: str,
        dataset_name: str,
        duration_seconds: float,
        total_samples: int,
        successful_samples: int,
        failed_samples: int,
        aggregated_metrics: dict[str, dict[str, float]],
        live_rag: bool = False,
    ) -> None:
        """
        Record the completion of an evaluation run with metrics.

        Args:
            run_id: Unique run identifier
            run_name: Human-readable run name
            dataset_name: Name of the evaluation dataset
            duration_seconds: Total run duration
            total_samples: Total samples evaluated
            successful_samples: Successfully evaluated samples
            failed_samples: Failed sample evaluations
            aggregated_metrics: Dict of metric name -> stats (mean, std, etc.)
            live_rag: Whether live RAG queries were used
        """
        # Record run counter
        EVALUATION_RUNS_TOTAL.labels(
            dataset_name=dataset_name,
            status="completed",
        ).inc()

        # Record sample counters
        EVALUATION_SAMPLES_TOTAL.labels(
            dataset_name=dataset_name,
            status="successful",
        ).inc(successful_samples)

        EVALUATION_SAMPLES_TOTAL.labels(
            dataset_name=dataset_name,
            status="failed",
        ).inc(failed_samples)

        # Record duration histogram
        EVALUATION_DURATION_HISTOGRAM.labels(
            dataset_name=dataset_name,
            live_rag=str(live_rag),
        ).observe(duration_seconds)

        # Record metric gauges
        for metric_name, stats in aggregated_metrics.items():
            mean_value = stats.get("mean", 0.0)

            # Record in specific gauge if available
            if metric_name in self.METRIC_GAUGES:
                self.METRIC_GAUGES[metric_name].labels(
                    dataset_name=dataset_name,
                    run_name=run_name,
                ).set(mean_value)

            # Also record in generic gauge with all statistics
            for stat_name in ["mean", "std", "min", "max", "median"]:
                if stat_name in stats:
                    EVALUATION_METRIC_GAUGE.labels(
                        dataset_name=dataset_name,
                        run_name=run_name,
                        metric_name=metric_name,
                        statistic=stat_name,
                    ).set(stats[stat_name])

        # Update info metric
        self._last_run_info = {
            "run_id": run_id,
            "run_name": run_name,
            "dataset_name": dataset_name,
            "sample_count": str(total_samples),
            "successful_samples": str(successful_samples),
            "failed_samples": str(failed_samples),
            "live_rag": str(live_rag),
            "status": "completed",
            "duration_seconds": f"{duration_seconds:.2f}",
        }
        LATEST_EVALUATION_INFO.info(self._last_run_info)

        logger.info(
            f"Recorded evaluation metrics for run {run_id}: "
            f"{successful_samples}/{total_samples} successful, "
            f"duration={duration_seconds:.2f}s",
        )

    def record_run_failure(
        self,
        run_id: str,
        run_name: str,
        dataset_name: str,
        duration_seconds: float,
        error_type: str,
        error_message: str,
    ) -> None:
        """
        Record a failed evaluation run.

        Args:
            run_id: Unique run identifier
            run_name: Human-readable run name
            dataset_name: Name of the evaluation dataset
            duration_seconds: Duration before failure
            error_type: Type/class of the error
            error_message: Error message
        """
        EVALUATION_RUNS_TOTAL.labels(
            dataset_name=dataset_name,
            status="failed",
        ).inc()

        EVALUATION_ERRORS_TOTAL.labels(
            dataset_name=dataset_name,
            error_type=error_type,
        ).inc()

        # Update info metric
        self._last_run_info = {
            "run_id": run_id,
            "run_name": run_name,
            "dataset_name": dataset_name,
            "status": "failed",
            "error_type": error_type,
            "duration_seconds": f"{duration_seconds:.2f}",
        }
        LATEST_EVALUATION_INFO.info(self._last_run_info)

        logger.warning(
            f"Recorded failed evaluation run {run_id}: {error_type}",
        )

    def record_rag_query_latency(
        self,
        dataset_name: str,
        latency_ms: float,
    ) -> None:
        """
        Record the latency of a RAG query during evaluation.

        Args:
            dataset_name: Name of the evaluation dataset
            latency_ms: Query latency in milliseconds
        """
        RAG_QUERY_LATENCY_HISTOGRAM.labels(
            dataset_name=dataset_name,
        ).observe(latency_ms)

    def record_sample_evaluation_duration(
        self,
        dataset_name: str,
        metric_name: str,
        duration_seconds: float,
    ) -> None:
        """
        Record the duration to evaluate a single sample for a specific metric.

        Args:
            dataset_name: Name of the evaluation dataset
            metric_name: Name of the metric being computed
            duration_seconds: Evaluation duration in seconds
        """
        SAMPLE_EVALUATION_DURATION_HISTOGRAM.labels(
            dataset_name=dataset_name,
            metric_name=metric_name,
        ).observe(duration_seconds)

    def get_latest_run_info(self) -> dict[str, Any]:
        """Get information about the latest evaluation run."""
        return self._last_run_info.copy()


# =============================================================================
# Prometheus Metrics Reporter
# =============================================================================


class PrometheusMetricsReporter:
    """
    Reporter that exports evaluation results to Prometheus.

    Can be added to EvaluationPipeline to automatically export
    metrics after each evaluation run.
    """

    def __init__(self, exporter: EvaluationMetricsExporter | None = None):
        """
        Initialize the Prometheus metrics reporter.

        Args:
            exporter: Optional EvaluationMetricsExporter instance
        """
        self.exporter = exporter or EvaluationMetricsExporter()

    async def report(self, run: Any) -> None:
        """
        Report evaluation run results to Prometheus.

        Args:
            run: EvaluationRun instance with results
        """

        if run.status == "completed" and run.results:
            duration = 0.0
            if run.completed_at and run.started_at:
                duration = (run.completed_at - run.started_at).total_seconds()

            self.exporter.record_run_completion(
                run_id=run.id,
                run_name=run.name,
                dataset_name=run.dataset_name,
                duration_seconds=duration,
                total_samples=run.results.total_samples,
                successful_samples=run.results.successful_samples,
                failed_samples=run.results.failed_samples,
                aggregated_metrics=run.results.aggregated_metrics,
                live_rag=run.metadata.get("live_rag", False),
            )

        elif run.status == "failed":
            duration = 0.0
            if run.completed_at and run.started_at:
                duration = (run.completed_at - run.started_at).total_seconds()

            self.exporter.record_run_failure(
                run_id=run.id,
                run_name=run.name,
                dataset_name=run.dataset_name,
                duration_seconds=duration,
                error_type=type(run.error).__name__ if run.error else "Unknown",
                error_message=str(run.error) if run.error else "Unknown error",
            )


# Global exporter instance for convenience
_global_exporter: EvaluationMetricsExporter | None = None


def get_metrics_exporter() -> EvaluationMetricsExporter:
    """Get or create the global metrics exporter."""
    global _global_exporter
    if _global_exporter is None:
        _global_exporter = EvaluationMetricsExporter()
    return _global_exporter
