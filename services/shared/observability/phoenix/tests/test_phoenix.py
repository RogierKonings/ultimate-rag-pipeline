"""
Tests for the Phoenix Module.

Tests covering:
- PhoenixConfig
- PhoenixTracer
- LangChainCallback
- FeedbackCollector
- ExperimentTracker
"""

import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import time

from ..config import PhoenixConfig
from ..tracer import PhoenixTracer, LLMSpan
from ..callbacks import LangChainCallback, LlamaIndexCallback
from ..feedback import FeedbackCollector, Feedback, FeedbackType
from ..experiments import ExperimentTracker, Experiment, ExperimentRun


# ============================================================================
# PhoenixConfig Tests
# ============================================================================

class TestPhoenixConfig:
    """Tests for PhoenixConfig."""

    def test_default_config(self):
        """Test default configuration values."""
        config = PhoenixConfig()

        assert config.phoenix_url == "http://localhost:6006"
        assert config.project_name == "rag-pipeline"
        assert config.enabled is True
        assert config.sample_rate == 1.0
        assert config.batch_size == 100

    def test_config_from_env(self, monkeypatch):
        """Test configuration from environment variables."""
        monkeypatch.setenv("PHOENIX_URL", "http://phoenix:6006")
        monkeypatch.setenv("PHOENIX_PROJECT", "test-project")
        monkeypatch.setenv("PHOENIX_ENABLED", "false")
        monkeypatch.setenv("PHOENIX_SAMPLE_RATE", "0.5")
        monkeypatch.setenv("PHOENIX_BATCH_SIZE", "50")

        config = PhoenixConfig.from_env()

        assert config.phoenix_url == "http://phoenix:6006"
        assert config.project_name == "test-project"
        assert config.enabled is False
        assert config.sample_rate == 0.5
        assert config.batch_size == 50

    def test_config_validation_valid(self):
        """Test validation passes for valid config."""
        config = PhoenixConfig(sample_rate=0.5, embedding_sample_rate=0.1)
        errors = config.validate()

        assert len(errors) == 0

    def test_config_validation_invalid_sample_rate(self):
        """Test validation catches invalid sample rate."""
        config = PhoenixConfig(sample_rate=1.5)
        errors = config.validate()

        assert any("sample_rate" in e for e in errors)

    def test_config_validation_invalid_batch_size(self):
        """Test validation catches invalid batch size."""
        config = PhoenixConfig(batch_size=0)
        errors = config.validate()

        assert any("batch_size" in e for e in errors)


# ============================================================================
# LLMSpan Tests
# ============================================================================

class TestLLMSpan:
    """Tests for LLMSpan."""

    def test_span_creation(self):
        """Test creating an LLM span."""
        span = LLMSpan(
            trace_id="trace-123",
            name="llm.gpt-4",
            span_type="llm",
            model="gpt-4",
            prompt="Hello",
        )

        assert span.trace_id == "trace-123"
        assert span.model == "gpt-4"
        assert span.id is not None
        assert span.status == "ok"

    def test_span_finish(self):
        """Test finishing a span."""
        span = LLMSpan(trace_id="trace-123", name="test")

        time.sleep(0.01)  # Small delay
        span.finish()

        assert span.end_time is not None
        assert span.latency_ms > 0
        assert span.status == "ok"

    def test_span_finish_with_error(self):
        """Test finishing a span with error."""
        span = LLMSpan(trace_id="trace-123", name="test")
        span.finish(error="Something went wrong")

        assert span.status == "error"
        assert span.error_message == "Something went wrong"

    def test_span_to_dict(self):
        """Test converting span to dictionary."""
        span = LLMSpan(
            trace_id="trace-123",
            name="llm.gpt-4",
            model="gpt-4",
            prompt="Hello",
            completion="Hi there",
            prompt_tokens=5,
            completion_tokens=3,
        )
        span.finish()

        data = span.to_dict()

        assert data["trace_id"] == "trace-123"
        assert data["model"] == "gpt-4"
        assert data["prompt"] == "Hello"
        assert data["completion"] == "Hi there"
        assert data["prompt_tokens"] == 5
        assert data["latency_ms"] >= 0


# ============================================================================
# PhoenixTracer Tests
# ============================================================================

class TestPhoenixTracer:
    """Tests for PhoenixTracer."""

    def test_tracer_creation(self):
        """Test creating a tracer."""
        config = PhoenixConfig(enabled=False)  # Disable for testing
        tracer = PhoenixTracer(config)

        assert tracer.config == config

    def test_start_trace(self):
        """Test starting a trace."""
        config = PhoenixConfig(enabled=False)
        tracer = PhoenixTracer(config)

        trace_id = tracer.start_trace("test_trace")

        assert trace_id is not None
        assert len(trace_id) > 0

    def test_start_span(self):
        """Test starting a span."""
        config = PhoenixConfig(enabled=False)
        tracer = PhoenixTracer(config)

        trace_id = tracer.start_trace()
        span = tracer.start_span(
            name="llm.gpt-4",
            trace_id=trace_id,
            span_type="llm",
            model="gpt-4",
        )

        assert span.trace_id == trace_id
        assert span.name == "llm.gpt-4"
        assert span.model == "gpt-4"

    def test_record_llm_call(self):
        """Test recording a complete LLM call."""
        config = PhoenixConfig(enabled=False)
        tracer = PhoenixTracer(config)

        trace_id = tracer.start_trace()
        span = tracer.record_llm_call(
            trace_id=trace_id,
            model="gpt-4",
            prompt="Hello, how are you?",
            completion="I'm doing well, thank you!",
            provider="openai",
            latency_ms=150.0,
        )

        assert span.model == "gpt-4"
        assert span.prompt == "Hello, how are you?"
        assert span.completion == "I'm doing well, thank you!"
        assert span.latency_ms == 150.0

    def test_record_embedding(self):
        """Test recording an embedding call."""
        config = PhoenixConfig(enabled=False)
        tracer = PhoenixTracer(config)

        trace_id = tracer.start_trace()
        span = tracer.record_embedding(
            trace_id=trace_id,
            model="text-embedding-ada-002",
            num_embeddings=10,
            dimensions=1536,
            latency_ms=50.0,
        )

        assert span.embedding_model == "text-embedding-ada-002"
        assert span.num_embeddings == 10
        assert span.embedding_dimensions == 1536

    def test_record_retrieval(self):
        """Test recording a retrieval operation."""
        config = PhoenixConfig(enabled=False)
        tracer = PhoenixTracer(config)

        trace_id = tracer.start_trace()
        span = tracer.record_retrieval(
            trace_id=trace_id,
            query="What is machine learning?",
            num_results=5,
            strategy="hybrid",
            latency_ms=30.0,
        )

        assert span.query == "What is machine learning?"
        assert span.num_results == 5
        assert span.retrieval_strategy == "hybrid"


# ============================================================================
# LangChainCallback Tests
# ============================================================================

class TestLangChainCallback:
    """Tests for LangChainCallback."""

    def test_callback_creation(self):
        """Test creating a callback."""
        config = PhoenixConfig(enabled=False)
        tracer = PhoenixTracer(config)
        callback = LangChainCallback(tracer)

        assert callback.tracer == tracer
        assert callback.trace_id is not None

    def test_callback_llm_lifecycle(self):
        """Test LLM start/end lifecycle."""
        config = PhoenixConfig(enabled=False)
        tracer = PhoenixTracer(config)
        callback = LangChainCallback(tracer)

        # Start LLM
        callback.on_llm_start(
            serialized={"name": "gpt-4", "id": ["openai", "gpt-4"]},
            prompts=["Hello"],
            run_id="run-123",
        )

        assert "run-123" in callback._spans

        # Create mock response
        mock_response = MagicMock()
        mock_response.generations = [[MagicMock(text="Hi there")]]
        mock_response.llm_output = {
            "token_usage": {
                "prompt_tokens": 5,
                "completion_tokens": 3,
                "total_tokens": 8,
            }
        }

        # End LLM
        callback.on_llm_end(response=mock_response, run_id="run-123")

        assert "run-123" not in callback._spans

    def test_callback_retriever_lifecycle(self):
        """Test retriever start/end lifecycle."""
        config = PhoenixConfig(enabled=False)
        tracer = PhoenixTracer(config)
        callback = LangChainCallback(tracer)

        # Start retriever
        callback.on_retriever_start(
            serialized={},
            query="What is AI?",
            run_id="ret-123",
        )

        assert "ret-123" in callback._spans

        # End retriever
        callback.on_retriever_end(
            documents=[MagicMock(), MagicMock()],
            run_id="ret-123",
        )

        assert "ret-123" not in callback._spans


# ============================================================================
# LlamaIndexCallback Tests
# ============================================================================

class TestLlamaIndexCallback:
    """Tests for LlamaIndexCallback."""

    def test_callback_creation(self):
        """Test creating a LlamaIndex callback."""
        config = PhoenixConfig(enabled=False)
        tracer = PhoenixTracer(config)
        callback = LlamaIndexCallback(tracer)

        assert callback.tracer == tracer

    def test_callback_event_lifecycle(self):
        """Test event start/end lifecycle."""
        config = PhoenixConfig(enabled=False)
        tracer = PhoenixTracer(config)
        callback = LlamaIndexCallback(tracer)

        # Start event
        event_id = callback.on_event_start(
            event_type="LLM",
            payload={"model_name": "gpt-4", "messages": "Hello"},
        )

        assert event_id in callback._spans

        # End event
        callback.on_event_end(
            event_type="LLM",
            payload={"response": "Hi there"},
            event_id=event_id,
        )

        assert event_id not in callback._spans


# ============================================================================
# Feedback Tests
# ============================================================================

class TestFeedback:
    """Tests for Feedback."""

    def test_feedback_creation(self):
        """Test creating feedback."""
        feedback = Feedback(
            trace_id="trace-123",
            feedback_type=FeedbackType.THUMBS_UP,
            score=1.0,
            user_id="user-1",
        )

        assert feedback.trace_id == "trace-123"
        assert feedback.feedback_type == FeedbackType.THUMBS_UP
        assert feedback.score == 1.0

    def test_feedback_to_dict(self):
        """Test converting feedback to dictionary."""
        feedback = Feedback(
            trace_id="trace-123",
            feedback_type=FeedbackType.RATING,
            score=0.8,
            label="good",
            comment="Nice response",
        )

        data = feedback.to_dict()

        assert data["trace_id"] == "trace-123"
        assert data["feedback_type"] == "rating"
        assert data["score"] == 0.8
        assert data["label"] == "good"

    def test_feedback_from_dict(self):
        """Test creating feedback from dictionary."""
        data = {
            "trace_id": "trace-123",
            "feedback_type": "thumbs_down",
            "score": 0.0,
            "correction": "The correct answer is...",
        }

        feedback = Feedback.from_dict(data)

        assert feedback.trace_id == "trace-123"
        assert feedback.feedback_type == FeedbackType.THUMBS_DOWN
        assert feedback.correction == "The correct answer is..."


class TestFeedbackCollector:
    """Tests for FeedbackCollector."""

    def test_collector_creation(self):
        """Test creating a feedback collector."""
        config = PhoenixConfig(postgres_url="postgresql://localhost/test")
        collector = FeedbackCollector(config)

        assert collector.config == config

    @pytest.mark.asyncio
    async def test_record_thumbs_up(self):
        """Test recording thumbs up."""
        config = PhoenixConfig(
            enabled=False,
            postgres_url="postgresql://localhost/test",
        )
        collector = FeedbackCollector(config)

        with patch.object(collector, "_store_feedback", new_callable=AsyncMock), \
             patch.object(collector, "_send_to_phoenix", new_callable=AsyncMock):

            feedback = await collector.record_thumbs_up(
                trace_id="trace-123",
                user_id="user-1",
                comment="Great answer!",
            )

            assert feedback.trace_id == "trace-123"
            assert feedback.feedback_type == FeedbackType.THUMBS_UP
            assert feedback.score == 1.0

    @pytest.mark.asyncio
    async def test_record_rating(self):
        """Test recording a rating."""
        config = PhoenixConfig(
            enabled=False,
            postgres_url="postgresql://localhost/test",
        )
        collector = FeedbackCollector(config)

        with patch.object(collector, "_store_feedback", new_callable=AsyncMock), \
             patch.object(collector, "_send_to_phoenix", new_callable=AsyncMock):

            feedback = await collector.record_rating(
                trace_id="trace-123",
                rating=4,
                max_rating=5,
                user_id="user-1",
            )

            assert feedback.score == 0.8  # 4/5
            assert feedback.label == "4/5"


# ============================================================================
# Experiment Tests
# ============================================================================

class TestExperimentRun:
    """Tests for ExperimentRun."""

    def test_run_creation(self):
        """Test creating an experiment run."""
        run = ExperimentRun(
            experiment_id="exp-123",
            name="baseline",
            config={"model": "gpt-4"},
        )

        assert run.experiment_id == "exp-123"
        assert run.name == "baseline"
        assert run.status == "running"

    def test_run_to_dict(self):
        """Test converting run to dictionary."""
        run = ExperimentRun(
            experiment_id="exp-123",
            name="test",
            config={"model": "gpt-4"},
            metrics={"accuracy": 0.9},
        )

        data = run.to_dict()

        assert data["experiment_id"] == "exp-123"
        assert data["config"]["model"] == "gpt-4"
        assert data["metrics"]["accuracy"] == 0.9


class TestExperiment:
    """Tests for Experiment."""

    def test_experiment_creation(self):
        """Test creating an experiment."""
        experiment = Experiment(
            name="Prompt Optimization",
            description="Testing different prompt templates",
            hypothesis="Template B will improve accuracy",
            experiment_type="prompt",
        )

        assert experiment.name == "Prompt Optimization"
        assert experiment.status == "active"
        assert len(experiment.runs) == 0

    def test_experiment_to_dict(self):
        """Test converting experiment to dictionary."""
        experiment = Experiment(
            name="Test Experiment",
            hypothesis="Test hypothesis",
        )
        experiment.runs.append(
            ExperimentRun(experiment_id=experiment.id, name="run-1")
        )

        data = experiment.to_dict()

        assert data["name"] == "Test Experiment"
        assert len(data["runs"]) == 1


class TestExperimentTracker:
    """Tests for ExperimentTracker."""

    def test_tracker_creation(self):
        """Test creating an experiment tracker."""
        config = PhoenixConfig(postgres_url="postgresql://localhost/test")
        tracker = ExperimentTracker(config)

        assert tracker.config == config

    @pytest.mark.asyncio
    async def test_create_experiment(self):
        """Test creating an experiment."""
        config = PhoenixConfig(postgres_url="postgresql://localhost/test")
        tracker = ExperimentTracker(config)

        with patch.object(tracker, "_store_experiment", new_callable=AsyncMock):
            experiment = await tracker.create_experiment(
                name="Test Experiment",
                description="Testing something",
                hypothesis="It will work",
                experiment_type="model",
            )

            assert experiment.name == "Test Experiment"
            assert experiment.hypothesis == "It will work"
            assert experiment.id in tracker._active_experiments

    @pytest.mark.asyncio
    async def test_start_run(self):
        """Test starting a run."""
        config = PhoenixConfig(postgres_url="postgresql://localhost/test")
        tracker = ExperimentTracker(config)

        # Create experiment first
        with patch.object(tracker, "_store_experiment", new_callable=AsyncMock):
            experiment = await tracker.create_experiment(
                name="Test",
                experiment_type="model",
            )

        # Start run
        with patch.object(tracker, "_store_run", new_callable=AsyncMock):
            run = await tracker.start_run(
                experiment_id=experiment.id,
                name="baseline",
                config={"model": "gpt-4"},
                is_baseline=True,
            )

            assert run.experiment_id == experiment.id
            assert run.name == "baseline"
            assert experiment.baseline_run_id == run.id
