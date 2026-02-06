"""
Ragas Evaluator.

Wrapper around Ragas library for RAG evaluation.
"""

from dataclasses import dataclass
from typing import Any

import structlog

from .config import EvaluationConfig

logger = structlog.get_logger(__name__)


@dataclass
class EvaluationResult:
    """Result from a single evaluation."""

    question: str
    contexts: list[str]
    answer: str
    ground_truth: str | None
    metrics: dict[str, float]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "question": self.question,
            "contexts": self.contexts,
            "answer": self.answer,
            "ground_truth": self.ground_truth,
            "metrics": self.metrics,
            "metadata": self.metadata,
        }


@dataclass
class AggregatedResults:
    """Aggregated results from an evaluation run."""

    individual_results: list[EvaluationResult]
    aggregated_metrics: dict[str, dict[str, float]]  # metric -> {mean, std, min, max}
    total_samples: int
    successful_samples: int
    failed_samples: int
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "individual_results": [r.to_dict() for r in self.individual_results],
            "aggregated_metrics": self.aggregated_metrics,
            "total_samples": self.total_samples,
            "successful_samples": self.successful_samples,
            "failed_samples": self.failed_samples,
            "metadata": self.metadata,
        }


class RagasEvaluator:
    """
    Evaluator using Ragas library.

    Computes metrics like:
    - context_precision: How relevant is the retrieved context
    - context_recall: How much of the ground truth is covered
    - faithfulness: Is the answer grounded in context
    - answer_relevancy: Does the answer address the question
    """

    def __init__(self, config: EvaluationConfig | None = None):
        """
        Initialize the evaluator.

        Args:
            config: Evaluation configuration
        """
        self.config = config or EvaluationConfig.from_env()
        self._metrics = None
        self._llm = None
        self._embeddings = None

    def _setup_llm(self) -> Any:
        """Set up the LLM for evaluation."""
        if self._llm is not None:
            return self._llm

        try:
            from langchain_openai import ChatOpenAI

            self._llm = ChatOpenAI(
                model=self.config.evaluator_model,
                api_key=self.config.evaluator_api_key,
                base_url=self.config.evaluator_base_url,
                temperature=0,
            )
            return self._llm
        except ImportError:
            logger.error("langchain_openai not installed")
            raise

    def _setup_embeddings(self) -> Any:
        """Set up embeddings for evaluation."""
        if self._embeddings is not None:
            return self._embeddings

        try:
            from langchain_openai import OpenAIEmbeddings

            self._embeddings = OpenAIEmbeddings(
                api_key=self.config.evaluator_api_key,
                base_url=self.config.evaluator_base_url,
            )
            return self._embeddings
        except ImportError:
            logger.error("langchain_openai not installed")
            raise

    def _setup_metrics(self) -> list[Any]:
        """Set up Ragas metrics based on configuration."""
        if self._metrics is not None:
            return self._metrics

        try:
            from ragas.metrics import (
                answer_correctness,
                answer_relevancy,
                answer_similarity,
                context_entity_recall,
                context_precision,
                context_recall,
                faithfulness,
            )

            metric_map = {
                "context_precision": context_precision,
                "context_recall": context_recall,
                "faithfulness": faithfulness,
                "answer_relevancy": answer_relevancy,
                "context_entity_recall": context_entity_recall,
                "answer_similarity": answer_similarity,
                "answer_correctness": answer_correctness,
            }

            self._metrics = []
            for metric_name in self.config.metrics:
                if metric_name in metric_map:
                    self._metrics.append(metric_map[metric_name])
                else:
                    logger.warning(f"Unknown metric: {metric_name}")

            return self._metrics

        except ImportError:
            logger.error("ragas not installed")
            raise

    async def evaluate_single(
        self,
        question: str,
        contexts: list[str],
        answer: str,
        ground_truth: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> EvaluationResult:
        """
        Evaluate a single sample.

        Args:
            question: The question asked
            contexts: Retrieved contexts
            answer: Generated answer
            ground_truth: Expected answer (optional)
            metadata: Additional metadata

        Returns:
            EvaluationResult with computed metrics
        """
        try:
            from datasets import Dataset
            from ragas import evaluate

            # Prepare data for Ragas
            data = {
                "question": [question],
                "contexts": [contexts],
                "answer": [answer],
            }

            if ground_truth:
                data["ground_truth"] = [ground_truth]

            dataset = Dataset.from_dict(data)

            # Get metrics and LLM
            metrics = self._setup_metrics()
            llm = self._setup_llm()
            embeddings = self._setup_embeddings()

            # Run evaluation
            results = evaluate(
                dataset,
                metrics=metrics,
                llm=llm,
                embeddings=embeddings,
            )

            # Extract metric values
            metric_values = {}
            for metric_name in self.config.metrics:
                if metric_name in results:
                    value = results[metric_name]
                    # Handle both single values and lists
                    if isinstance(value, list):
                        metric_values[metric_name] = value[0] if value else 0.0
                    else:
                        metric_values[metric_name] = float(value)

            return EvaluationResult(
                question=question,
                contexts=contexts,
                answer=answer,
                ground_truth=ground_truth,
                metrics=metric_values,
                metadata=metadata or {},
            )

        except Exception as e:
            logger.error(f"Evaluation failed for question: {question[:50]}...: {e}")
            return EvaluationResult(
                question=question,
                contexts=contexts,
                answer=answer,
                ground_truth=ground_truth,
                metrics=dict.fromkeys(self.config.metrics, 0.0),
                metadata={"error": str(e), **(metadata or {})},
            )

    async def evaluate_batch(
        self,
        samples: list[dict[str, Any]],
    ) -> list[EvaluationResult]:
        """
        Evaluate a batch of samples.

        Args:
            samples: List of sample dicts with question, contexts, answer, ground_truth

        Returns:
            List of EvaluationResult objects
        """
        try:
            from datasets import Dataset
            from ragas import evaluate

            # Prepare data for Ragas
            data = {
                "question": [s["question"] for s in samples],
                "contexts": [s["contexts"] for s in samples],
                "answer": [s["answer"] for s in samples],
            }

            if all("ground_truth" in s for s in samples):
                data["ground_truth"] = [s.get("ground_truth", "") for s in samples]

            dataset = Dataset.from_dict(data)

            # Get metrics and LLM
            metrics = self._setup_metrics()
            llm = self._setup_llm()
            embeddings = self._setup_embeddings()

            # Run evaluation
            results = evaluate(
                dataset,
                metrics=metrics,
                llm=llm,
                embeddings=embeddings,
            )

            # Convert to EvaluationResult objects
            eval_results = []
            for i, sample in enumerate(samples):
                metric_values = {}
                for metric_name in self.config.metrics:
                    if metric_name in results:
                        values = results[metric_name]
                        if isinstance(values, list) and i < len(values):
                            metric_values[metric_name] = float(values[i])
                        elif not isinstance(values, list):
                            metric_values[metric_name] = float(values)

                eval_results.append(
                    EvaluationResult(
                        question=sample["question"],
                        contexts=sample["contexts"],
                        answer=sample["answer"],
                        ground_truth=sample.get("ground_truth"),
                        metrics=metric_values,
                        metadata=sample.get("metadata", {}),
                    ),
                )

            return eval_results

        except Exception as e:
            logger.error(f"Batch evaluation failed: {e}")
            # Return results with error metadata
            return [
                EvaluationResult(
                    question=s["question"],
                    contexts=s["contexts"],
                    answer=s["answer"],
                    ground_truth=s.get("ground_truth"),
                    metrics=dict.fromkeys(self.config.metrics, 0.0),
                    metadata={"error": str(e)},
                )
                for s in samples
            ]

    def aggregate_results(
        self,
        results: list[EvaluationResult],
        metadata: dict[str, Any] | None = None,
    ) -> AggregatedResults:
        """
        Aggregate evaluation results.

        Args:
            results: List of individual results
            metadata: Additional metadata for the run

        Returns:
            AggregatedResults with statistics
        """
        import statistics

        aggregated_metrics: dict[str, dict[str, float]] = {}

        for metric_name in self.config.metrics:
            values = [r.metrics.get(metric_name, 0.0) for r in results if "error" not in r.metadata]

            if values:
                aggregated_metrics[metric_name] = {
                    "mean": statistics.mean(values),
                    "std": statistics.stdev(values) if len(values) > 1 else 0.0,
                    "min": min(values),
                    "max": max(values),
                    "median": statistics.median(values),
                }
            else:
                aggregated_metrics[metric_name] = {
                    "mean": 0.0,
                    "std": 0.0,
                    "min": 0.0,
                    "max": 0.0,
                    "median": 0.0,
                }

        successful = sum(1 for r in results if "error" not in r.metadata)
        failed = len(results) - successful

        return AggregatedResults(
            individual_results=results,
            aggregated_metrics=aggregated_metrics,
            total_samples=len(results),
            successful_samples=successful,
            failed_samples=failed,
            metadata=metadata or {},
        )
