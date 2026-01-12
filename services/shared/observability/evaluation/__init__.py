"""
RAG Evaluation Module.

Provides automated RAG quality evaluation using Ragas metrics:
- Context precision and recall
- Faithfulness and answer relevancy
- Custom metrics support
- Scheduled evaluation runs
- Result persistence and reporting

Usage:
    from shared.observability.evaluation import (
        RagasEvaluator,
        EvaluationPipeline,
        EvaluationDataset,
    )

    # Create evaluator
    evaluator = RagasEvaluator()

    # Load dataset
    dataset = EvaluationDataset.from_json("eval_data.json")

    # Run evaluation
    pipeline = EvaluationPipeline(evaluator)
    results = await pipeline.evaluate(dataset)
"""

from .api import router as evaluation_router
from .config import EvaluationConfig, SamplingStrategy
from .datasets import EvaluationDataset, EvaluationSample
from .metrics import (
    EvaluationMetricsExporter,
    PrometheusMetricsReporter,
    get_metrics_exporter,
)
from .persistence import EvaluationRepository
from .pipeline import EvaluationPipeline, EvaluationRun, RAGClient, ScheduledEvaluationRunner
from .ragas_evaluator import AggregatedResults, EvaluationResult, RagasEvaluator
from .reporters import (
    BaseReporter,
    CompositeReporter,
    GrafanaAnnotationReporter,
    JSONFileReporter,
    PostgreSQLReporter,
    SlackReporter,
)

__all__ = [
    # Configuration
    "EvaluationConfig",
    "SamplingStrategy",
    # Evaluator
    "RagasEvaluator",
    "EvaluationResult",
    "AggregatedResults",
    # Datasets
    "EvaluationSample",
    "EvaluationDataset",
    # Pipeline
    "EvaluationPipeline",
    "EvaluationRun",
    "RAGClient",
    "ScheduledEvaluationRunner",
    # Reporters
    "BaseReporter",
    "JSONFileReporter",
    "PostgreSQLReporter",
    "GrafanaAnnotationReporter",
    "SlackReporter",
    "CompositeReporter",
    # Metrics
    "EvaluationMetricsExporter",
    "PrometheusMetricsReporter",
    "get_metrics_exporter",
    # Persistence
    "EvaluationRepository",
    # API
    "evaluation_router",
]
