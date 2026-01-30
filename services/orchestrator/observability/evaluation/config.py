"""
Evaluation Configuration.

Provides configuration for RAG evaluation runs.
"""

import os
from dataclasses import dataclass, field
from enum import Enum


class EvaluatorModel(Enum):
    """Available evaluator models."""

    GPT4 = "gpt-4"
    GPT4_TURBO = "gpt-4-turbo"
    GPT35_TURBO = "gpt-3.5-turbo"
    CLAUDE_3_OPUS = "claude-3-opus"
    CLAUDE_3_SONNET = "claude-3-sonnet"
    LOCAL = "local"  # Use local LLM


class SamplingStrategy(Enum):
    """Dataset sampling strategies."""

    RANDOM = "random"
    STRATIFIED = "stratified"
    SEQUENTIAL = "sequential"
    ALL = "all"


@dataclass
class EvaluationConfig:
    """
    Configuration for RAG evaluation.

    Attributes:
        evaluator_model: Model to use for evaluation (e.g., gpt-4)
        evaluator_api_key: API key for evaluator model
        evaluator_base_url: Base URL for evaluator API
        metrics: List of metrics to compute
        dataset_path: Path to evaluation dataset
        sample_size: Number of samples to evaluate (None = all)
        sampling_strategy: How to sample from dataset
        timeout_seconds: Timeout per evaluation
        max_retries: Max retries on failure
        batch_size: Batch size for evaluation
        result_storage: Where to store results
        postgres_url: PostgreSQL connection URL
        grafana_url: Grafana URL for annotations
        slack_webhook_url: Slack webhook for notifications
    """

    evaluator_model: str = "gpt-4"
    evaluator_api_key: str | None = None
    evaluator_base_url: str | None = None

    metrics: list[str] = field(
        default_factory=lambda: [
            "context_precision",
            "context_recall",
            "faithfulness",
            "answer_relevancy",
        ],
    )

    dataset_path: str | None = None
    sample_size: int | None = None
    sampling_strategy: SamplingStrategy = SamplingStrategy.RANDOM
    random_seed: int = 42

    timeout_seconds: int = 300
    max_retries: int = 3
    batch_size: int = 10

    result_storage: list[str] = field(default_factory=lambda: ["json", "postgres"])
    result_dir: str = "./eval_results"

    postgres_url: str | None = None
    grafana_url: str | None = None
    grafana_api_key: str | None = None
    slack_webhook_url: str | None = None

    # RAG pipeline configuration for live evaluation
    rag_api_url: str | None = None
    rag_api_key: str | None = None

    @classmethod
    def from_env(cls) -> "EvaluationConfig":
        """
        Create configuration from environment variables.

        Environment variables:
            EVAL_MODEL: Evaluator model
            EVAL_API_KEY: API key for evaluator
            EVAL_BASE_URL: Base URL for evaluator API
            EVAL_METRICS: Comma-separated list of metrics
            EVAL_DATASET_PATH: Path to dataset
            EVAL_SAMPLE_SIZE: Number of samples
            EVAL_SAMPLING_STRATEGY: Sampling strategy
            EVAL_TIMEOUT: Timeout in seconds
            EVAL_BATCH_SIZE: Batch size
            EVAL_RESULT_DIR: Directory for results
            DATABASE_URL: PostgreSQL URL
            GRAFANA_URL: Grafana URL
            GRAFANA_API_KEY: Grafana API key
            SLACK_WEBHOOK_URL: Slack webhook
            RAG_API_URL: RAG pipeline API URL
            RAG_API_KEY: RAG pipeline API key

        Returns:
            EvaluationConfig instance
        """
        metrics_str = os.getenv("EVAL_METRICS")
        metrics = [m.strip() for m in metrics_str.split(",")] if metrics_str else None

        sample_size_str = os.getenv("EVAL_SAMPLE_SIZE")
        sample_size = int(sample_size_str) if sample_size_str else None

        sampling_str = os.getenv("EVAL_SAMPLING_STRATEGY", "random").upper()
        try:
            sampling = SamplingStrategy[sampling_str]
        except KeyError:
            sampling = SamplingStrategy.RANDOM

        config = cls(
            evaluator_model=os.getenv("EVAL_MODEL", "gpt-4"),
            evaluator_api_key=os.getenv("EVAL_API_KEY") or os.getenv("OPENAI_API_KEY"),
            evaluator_base_url=os.getenv("EVAL_BASE_URL"),
            dataset_path=os.getenv("EVAL_DATASET_PATH"),
            sample_size=sample_size,
            sampling_strategy=sampling,
            timeout_seconds=int(os.getenv("EVAL_TIMEOUT", "300")),
            batch_size=int(os.getenv("EVAL_BATCH_SIZE", "10")),
            result_dir=os.getenv("EVAL_RESULT_DIR", "./eval_results"),
            postgres_url=os.getenv("DATABASE_URL"),
            grafana_url=os.getenv("GRAFANA_URL"),
            grafana_api_key=os.getenv("GRAFANA_API_KEY"),
            slack_webhook_url=os.getenv("SLACK_WEBHOOK_URL"),
            rag_api_url=os.getenv("RAG_API_URL"),
            rag_api_key=os.getenv("RAG_API_KEY"),
        )

        if metrics:
            config.metrics = metrics

        return config

    def validate(self) -> list[str]:
        """
        Validate configuration.

        Returns:
            List of validation errors (empty if valid)
        """
        errors = []

        if not self.evaluator_api_key and self.evaluator_model != "local":
            errors.append("evaluator_api_key is required for non-local models")

        if "postgres" in self.result_storage and not self.postgres_url:
            errors.append("postgres_url is required for postgres result storage")

        if "grafana" in self.result_storage:
            if not self.grafana_url:
                errors.append("grafana_url is required for grafana annotations")
            if not self.grafana_api_key:
                errors.append("grafana_api_key is required for grafana annotations")

        valid_metrics = {
            "context_precision",
            "context_recall",
            "faithfulness",
            "answer_relevancy",
            "context_entity_recall",
            "answer_similarity",
            "answer_correctness",
        }
        for metric in self.metrics:
            if metric not in valid_metrics:
                errors.append(f"Unknown metric: {metric}")

        return errors
