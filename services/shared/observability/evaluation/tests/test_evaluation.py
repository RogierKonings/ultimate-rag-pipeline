"""
Tests for the Evaluation Module.

Tests covering:
- EvaluationConfig
- EvaluationDataset
- RagasEvaluator
- EvaluationPipeline
- Reporters
"""

import json
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import tempfile

from ..config import EvaluationConfig, SamplingStrategy
from ..datasets import EvaluationSample, EvaluationDataset
from ..ragas_evaluator import RagasEvaluator, EvaluationResult, AggregatedResults
from ..pipeline import EvaluationPipeline, EvaluationRun, RAGClient, RAGResponse
from ..reporters import (
    JSONFileReporter,
    PostgreSQLReporter,
    GrafanaAnnotationReporter,
    SlackReporter,
    CompositeReporter,
)


# ============================================================================
# EvaluationConfig Tests
# ============================================================================

class TestEvaluationConfig:
    """Tests for EvaluationConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = EvaluationConfig()

        assert config.evaluator_model == "gpt-4"
        assert config.batch_size == 10
        assert config.timeout_seconds == 300
        assert len(config.metrics) == 4
        assert "faithfulness" in config.metrics

    def test_config_from_env(self, monkeypatch):
        """Test configuration from environment variables."""
        monkeypatch.setenv("EVAL_MODEL", "claude-3-opus")
        monkeypatch.setenv("EVAL_API_KEY", "test-key")
        monkeypatch.setenv("EVAL_METRICS", "faithfulness,answer_relevancy")
        monkeypatch.setenv("EVAL_SAMPLE_SIZE", "50")
        monkeypatch.setenv("EVAL_SAMPLING_STRATEGY", "STRATIFIED")
        monkeypatch.setenv("EVAL_BATCH_SIZE", "20")

        config = EvaluationConfig.from_env()

        assert config.evaluator_model == "claude-3-opus"
        assert config.evaluator_api_key == "test-key"
        assert config.metrics == ["faithfulness", "answer_relevancy"]
        assert config.sample_size == 50
        assert config.sampling_strategy == SamplingStrategy.STRATIFIED
        assert config.batch_size == 20

    def test_config_validation_missing_api_key(self):
        """Test validation catches missing API key."""
        config = EvaluationConfig(evaluator_api_key=None)
        errors = config.validate()

        assert len(errors) > 0
        assert any("api_key" in e for e in errors)

    def test_config_validation_postgres_required(self):
        """Test validation catches missing postgres URL."""
        config = EvaluationConfig(
            evaluator_api_key="test",
            result_storage=["postgres"],
            postgres_url=None,
        )
        errors = config.validate()

        assert any("postgres_url" in e for e in errors)

    def test_config_validation_invalid_metric(self):
        """Test validation catches invalid metrics."""
        config = EvaluationConfig(
            evaluator_api_key="test",
            metrics=["faithfulness", "invalid_metric"],
        )
        errors = config.validate()

        assert any("invalid_metric" in e for e in errors)


# ============================================================================
# EvaluationDataset Tests
# ============================================================================

class TestEvaluationSample:
    """Tests for EvaluationSample."""

    def test_sample_creation(self):
        """Test creating an evaluation sample."""
        sample = EvaluationSample(
            question="What is Python?",
            contexts=["Python is a programming language."],
            answer="Python is a high-level programming language.",
            ground_truth="Python is a programming language.",
        )

        assert sample.question == "What is Python?"
        assert len(sample.contexts) == 1
        assert sample.id is not None

    def test_sample_from_dict(self):
        """Test creating sample from dictionary."""
        data = {
            "question": "Test question",
            "contexts": ["context1", "context2"],
            "answer": "Test answer",
            "ground_truth": "Expected answer",
            "metadata": {"category": "test"},
        }

        sample = EvaluationSample.from_dict(data)

        assert sample.question == "Test question"
        assert len(sample.contexts) == 2
        assert sample.metadata["category"] == "test"

    def test_sample_to_dict(self):
        """Test converting sample to dictionary."""
        sample = EvaluationSample(
            question="Test",
            contexts=["ctx"],
            answer="ans",
        )

        data = sample.to_dict()

        assert "id" in data
        assert data["question"] == "Test"
        assert data["contexts"] == ["ctx"]

    def test_sample_content_hash(self):
        """Test content hash for deduplication."""
        sample1 = EvaluationSample(
            question="Same question",
            contexts=["Same context"],
            answer="Different answer 1",
        )
        sample2 = EvaluationSample(
            question="Same question",
            contexts=["Same context"],
            answer="Different answer 2",
        )

        # Same question + contexts = same hash
        assert sample1.content_hash() == sample2.content_hash()


class TestEvaluationDataset:
    """Tests for EvaluationDataset."""

    def test_dataset_creation(self):
        """Test creating a dataset."""
        samples = [
            EvaluationSample(question="Q1", contexts=["C1"], answer="A1"),
            EvaluationSample(question="Q2", contexts=["C2"], answer="A2"),
        ]
        dataset = EvaluationDataset(name="test", samples=samples)

        assert len(dataset) == 2
        assert dataset.name == "test"

    def test_dataset_iteration(self):
        """Test iterating over dataset."""
        samples = [
            EvaluationSample(question=f"Q{i}", contexts=["C"], answer=f"A{i}")
            for i in range(5)
        ]
        dataset = EvaluationDataset(name="test", samples=samples)

        questions = [s.question for s in dataset]
        assert questions == ["Q0", "Q1", "Q2", "Q3", "Q4"]

    def test_dataset_sampling_random(self):
        """Test random sampling from dataset."""
        samples = [
            EvaluationSample(question=f"Q{i}", contexts=["C"], answer=f"A{i}")
            for i in range(100)
        ]
        dataset = EvaluationDataset(name="test", samples=samples)

        sampled = dataset.sample(n=10, strategy=SamplingStrategy.RANDOM, seed=42)

        assert len(sampled) == 10
        assert sampled.name == "test_sampled"

    def test_dataset_sampling_sequential(self):
        """Test sequential sampling from dataset."""
        samples = [
            EvaluationSample(question=f"Q{i}", contexts=["C"], answer=f"A{i}")
            for i in range(100)
        ]
        dataset = EvaluationDataset(name="test", samples=samples)

        sampled = dataset.sample(n=10, strategy=SamplingStrategy.SEQUENTIAL)

        assert len(sampled) == 10
        assert sampled[0].question == "Q0"
        assert sampled[9].question == "Q9"

    def test_dataset_sampling_stratified(self):
        """Test stratified sampling from dataset."""
        samples = []
        for i in range(50):
            samples.append(
                EvaluationSample(
                    question=f"Q{i}",
                    contexts=["C"],
                    answer=f"A{i}",
                    metadata={"category": "A" if i < 25 else "B"},
                )
            )
        dataset = EvaluationDataset(name="test", samples=samples)

        sampled = dataset.sample(
            n=10,
            strategy=SamplingStrategy.STRATIFIED,
            stratify_by="category",
            seed=42,
        )

        assert len(sampled) == 10
        # Should have samples from both categories
        categories = [s.metadata.get("category") for s in sampled]
        assert "A" in categories
        assert "B" in categories

    def test_dataset_remove_duplicates(self):
        """Test removing duplicate samples."""
        samples = [
            EvaluationSample(question="Same Q", contexts=["Same C"], answer="A1"),
            EvaluationSample(question="Same Q", contexts=["Same C"], answer="A2"),
            EvaluationSample(question="Different Q", contexts=["C"], answer="A3"),
        ]
        dataset = EvaluationDataset(name="test", samples=samples)

        removed = dataset.remove_duplicates()

        assert removed == 1
        assert len(dataset) == 2

    def test_dataset_json_roundtrip(self):
        """Test JSON serialization and deserialization."""
        samples = [
            EvaluationSample(
                question="Q1",
                contexts=["C1"],
                answer="A1",
                ground_truth="GT1",
            )
        ]
        dataset = EvaluationDataset(
            name="test",
            samples=samples,
            version="1.0.0",
            description="Test dataset",
        )

        json_str = dataset.to_json()
        restored = EvaluationDataset.from_json(json_str)

        assert restored.name == dataset.name
        assert len(restored) == len(dataset)
        assert restored[0].question == dataset[0].question

    def test_dataset_save_load(self):
        """Test saving and loading dataset from file."""
        samples = [
            EvaluationSample(question="Q1", contexts=["C1"], answer="A1")
        ]
        dataset = EvaluationDataset(name="test", samples=samples)

        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "dataset.json"
            dataset.save(path)

            loaded = EvaluationDataset.load(path)

            assert loaded.name == dataset.name
            assert len(loaded) == 1

    def test_dataset_statistics(self):
        """Test computing dataset statistics."""
        samples = [
            EvaluationSample(
                question="Short?",
                contexts=["C1"],
                answer="A1",
                ground_truth="GT1",
                metadata={"category": "A"},
            ),
            EvaluationSample(
                question="Longer question here?",
                contexts=["C1", "C2"],
                answer="A2",
                metadata={"category": "B"},
            ),
        ]
        dataset = EvaluationDataset(name="test", samples=samples)

        stats = dataset.statistics()

        assert stats["total_samples"] == 2
        assert stats["samples_with_ground_truth"] == 1
        assert stats["avg_contexts_per_sample"] == 1.5
        assert "A" in stats["categories"]
        assert "B" in stats["categories"]

    def test_dataset_get_by_category(self):
        """Test filtering dataset by category."""
        samples = [
            EvaluationSample(
                question="Q1",
                contexts=["C"],
                answer="A",
                metadata={"category": "A"},
            ),
            EvaluationSample(
                question="Q2",
                contexts=["C"],
                answer="A",
                metadata={"category": "B"},
            ),
        ]
        dataset = EvaluationDataset(name="test", samples=samples)

        filtered = dataset.get_by_category("A")

        assert len(filtered) == 1
        assert filtered[0].question == "Q1"


# ============================================================================
# RagasEvaluator Tests
# ============================================================================

class TestRagasEvaluator:
    """Tests for RagasEvaluator."""

    def test_evaluator_creation(self):
        """Test creating evaluator with config."""
        config = EvaluationConfig(
            evaluator_model="gpt-4",
            evaluator_api_key="test-key",
        )
        evaluator = RagasEvaluator(config)

        assert evaluator.config == config

    @pytest.mark.asyncio
    async def test_evaluate_single_mock(self):
        """Test single evaluation with mocked Ragas."""
        config = EvaluationConfig(
            evaluator_api_key="test-key",
            metrics=["faithfulness", "answer_relevancy"],
        )
        evaluator = RagasEvaluator(config)

        # Mock the ragas evaluate function
        with patch.object(evaluator, "_setup_metrics") as mock_metrics, \
             patch.object(evaluator, "_setup_llm") as mock_llm, \
             patch.object(evaluator, "_setup_embeddings") as mock_emb:

            mock_metrics.return_value = []
            mock_llm.return_value = MagicMock()
            mock_emb.return_value = MagicMock()

            # Patch ragas.evaluate
            with patch("services.shared.observability.evaluation.ragas_evaluator.evaluate") as mock_eval:
                mock_eval.return_value = {
                    "faithfulness": [0.9],
                    "answer_relevancy": [0.85],
                }

                result = await evaluator.evaluate_single(
                    question="What is Python?",
                    contexts=["Python is a programming language."],
                    answer="Python is a high-level programming language.",
                    ground_truth="Python is a programming language.",
                )

                assert isinstance(result, EvaluationResult)
                assert result.question == "What is Python?"

    def test_aggregate_results(self):
        """Test aggregating evaluation results."""
        config = EvaluationConfig(
            evaluator_api_key="test",
            metrics=["faithfulness"],
        )
        evaluator = RagasEvaluator(config)

        results = [
            EvaluationResult(
                question="Q1",
                contexts=["C"],
                answer="A",
                ground_truth=None,
                metrics={"faithfulness": 0.9},
                metadata={},
            ),
            EvaluationResult(
                question="Q2",
                contexts=["C"],
                answer="A",
                ground_truth=None,
                metrics={"faithfulness": 0.8},
                metadata={},
            ),
        ]

        aggregated = evaluator.aggregate_results(results)

        assert isinstance(aggregated, AggregatedResults)
        assert aggregated.total_samples == 2
        assert aggregated.successful_samples == 2
        assert aggregated.aggregated_metrics["faithfulness"]["mean"] == 0.85


# ============================================================================
# EvaluationPipeline Tests
# ============================================================================

class TestEvaluationPipeline:
    """Tests for EvaluationPipeline."""

    def test_pipeline_creation(self):
        """Test creating evaluation pipeline."""
        config = EvaluationConfig(evaluator_api_key="test")
        pipeline = EvaluationPipeline(config=config)

        assert pipeline.config == config
        assert pipeline.evaluator is not None

    @pytest.mark.asyncio
    async def test_pipeline_evaluate(self):
        """Test running evaluation pipeline."""
        config = EvaluationConfig(
            evaluator_api_key="test",
            sample_size=2,
            batch_size=2,
        )

        # Create mock evaluator
        mock_evaluator = MagicMock()
        mock_evaluator.evaluate_batch = AsyncMock(
            return_value=[
                EvaluationResult(
                    question="Q1",
                    contexts=["C"],
                    answer="A",
                    ground_truth=None,
                    metrics={"faithfulness": 0.9},
                    metadata={},
                ),
                EvaluationResult(
                    question="Q2",
                    contexts=["C"],
                    answer="A",
                    ground_truth=None,
                    metrics={"faithfulness": 0.8},
                    metadata={},
                ),
            ]
        )
        mock_evaluator.aggregate_results = MagicMock(
            return_value=AggregatedResults(
                individual_results=[],
                aggregated_metrics={"faithfulness": {"mean": 0.85, "std": 0.05, "min": 0.8, "max": 0.9, "median": 0.85}},
                total_samples=2,
                successful_samples=2,
                failed_samples=0,
                metadata={},
            )
        )

        pipeline = EvaluationPipeline(evaluator=mock_evaluator, config=config)

        # Create test dataset
        samples = [
            EvaluationSample(question="Q1", contexts=["C"], answer="A"),
            EvaluationSample(question="Q2", contexts=["C"], answer="A"),
        ]
        dataset = EvaluationDataset(name="test", samples=samples)

        results = await pipeline.evaluate(dataset, run_name="test_run")

        assert results.total_samples == 2
        assert results.successful_samples == 2
        mock_evaluator.evaluate_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_pipeline_compare_runs(self):
        """Test comparing evaluation runs."""
        config = EvaluationConfig(evaluator_api_key="test")
        pipeline = EvaluationPipeline(config=config)

        current = AggregatedResults(
            individual_results=[],
            aggregated_metrics={
                "faithfulness": {"mean": 0.9, "std": 0.05, "min": 0.85, "max": 0.95, "median": 0.9},
            },
            total_samples=10,
            successful_samples=10,
            failed_samples=0,
            metadata={},
        )

        baseline = AggregatedResults(
            individual_results=[],
            aggregated_metrics={
                "faithfulness": {"mean": 0.8, "std": 0.05, "min": 0.75, "max": 0.85, "median": 0.8},
            },
            total_samples=10,
            successful_samples=10,
            failed_samples=0,
            metadata={},
        )

        comparison = await pipeline.compare_runs(current, baseline)

        assert "metrics" in comparison
        assert "faithfulness" in comparison["metrics"]
        assert comparison["metrics"]["faithfulness"]["delta"] == pytest.approx(0.1)
        assert "improved" in comparison["summary"]


# ============================================================================
# Reporter Tests
# ============================================================================

class TestJSONFileReporter:
    """Tests for JSONFileReporter."""

    @pytest.mark.asyncio
    async def test_json_reporter(self):
        """Test JSON file reporter."""
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = JSONFileReporter(output_dir=tmpdir)

            run = EvaluationRun(
                id="test-id",
                name="test-run",
                config=EvaluationConfig(evaluator_api_key="test"),
                dataset_name="test-dataset",
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
                status="completed",
                results=AggregatedResults(
                    individual_results=[],
                    aggregated_metrics={"faithfulness": {"mean": 0.9, "std": 0.05, "min": 0.85, "max": 0.95, "median": 0.9}},
                    total_samples=10,
                    successful_samples=10,
                    failed_samples=0,
                    metadata={},
                ),
            )

            await reporter.report(run)

            # Check files were created
            files = list(Path(tmpdir).glob("*.json"))
            assert len(files) == 2  # Main file + summary


class TestCompositeReporter:
    """Tests for CompositeReporter."""

    @pytest.mark.asyncio
    async def test_composite_reporter(self):
        """Test composite reporter delegates to all reporters."""
        mock_reporter1 = MagicMock()
        mock_reporter1.report = AsyncMock()

        mock_reporter2 = MagicMock()
        mock_reporter2.report = AsyncMock()

        composite = CompositeReporter([mock_reporter1, mock_reporter2])

        run = MagicMock()
        await composite.report(run)

        mock_reporter1.report.assert_called_once_with(run)
        mock_reporter2.report.assert_called_once_with(run)

    @pytest.mark.asyncio
    async def test_composite_reporter_handles_errors(self):
        """Test composite reporter continues on errors."""
        mock_reporter1 = MagicMock()
        mock_reporter1.report = AsyncMock(side_effect=Exception("Error"))

        mock_reporter2 = MagicMock()
        mock_reporter2.report = AsyncMock()

        composite = CompositeReporter([mock_reporter1, mock_reporter2])

        run = MagicMock()
        await composite.report(run)

        # Second reporter should still be called
        mock_reporter2.report.assert_called_once_with(run)


# ============================================================================
# RAGClient Tests
# ============================================================================

class TestRAGClient:
    """Tests for RAGClient."""

    @pytest.mark.asyncio
    async def test_rag_client_query(self):
        """Test RAG client query."""
        client = RAGClient(
            base_url="http://localhost:8003",
            api_key="test-key",
        )

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.json.return_value = {
                "answer": "Test answer",
                "contexts": ["Context 1", "Context 2"],
                "model": "gpt-4",
            }
            mock_response.raise_for_status = MagicMock()

            mock_client_instance = AsyncMock()
            mock_client_instance.post = AsyncMock(return_value=mock_response)
            mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_instance.__aexit__ = AsyncMock()
            mock_client.return_value = mock_client_instance

            response = await client.query("Test question")

            assert isinstance(response, RAGResponse)
            assert response.answer == "Test answer"
            assert len(response.contexts) == 2
