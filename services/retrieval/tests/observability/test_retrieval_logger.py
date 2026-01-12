"""Tests for RetrievalLogger."""

import json
from uuid import uuid4

import pytest

# Import the module but handle missing structlog gracefully
from observability.retrieval_logger import (
    LogLevel,
    RetrievalLogEntry,
    RetrievalLogger,
)


class TestRetrievalLogEntry:
    """Tests for RetrievalLogEntry model."""

    def test_create_minimal_entry(self):
        """Test creating entry with minimal fields."""
        entry = RetrievalLogEntry(
            query_id=uuid4(),
            query="test query",
            mode="hybrid",
            tenant_id=uuid4(),
            result_count=5,
            total_ms=100.0,
            preprocessing_ms=10.0,
            search_ms=90.0,
        )

        assert entry.mode == "hybrid"
        assert entry.result_count == 5

    def test_create_full_entry(self):
        """Test creating entry with all fields."""
        entry = RetrievalLogEntry(
            query_id=uuid4(),
            trace_id="abc123",
            span_id="def456",
            query="test query",
            query_type="question",
            mode="hybrid",
            tenant_id=uuid4(),
            user_id_hash="hash123",
            result_count=10,
            top_scores=[0.9, 0.8, 0.7],
            total_ms=150.0,
            preprocessing_ms=20.0,
            search_ms=100.0,
            rerank_ms=30.0,
            used_semantic=True,
            used_keyword=True,
            used_reranking=True,
            error="Test error",
            error_type="ValueError",
        )

        assert entry.trace_id == "abc123"
        assert entry.used_semantic is True
        assert entry.error == "Test error"

    def test_entry_serialization(self):
        """Test that entry can be serialized to JSON."""
        entry = RetrievalLogEntry(
            query_id=uuid4(),
            query="test",
            mode="semantic",
            tenant_id=uuid4(),
            result_count=0,
            total_ms=50.0,
            preprocessing_ms=10.0,
            search_ms=40.0,
        )

        json_str = entry.model_dump_json()
        data = json.loads(json_str)

        assert data["mode"] == "semantic"
        assert data["result_count"] == 0


class TestLogLevel:
    """Tests for LogLevel enum."""

    def test_log_levels(self):
        """Test all log level values."""
        assert LogLevel.DEBUG.value == "debug"
        assert LogLevel.INFO.value == "info"
        assert LogLevel.WARNING.value == "warning"
        assert LogLevel.ERROR.value == "error"


class TestRetrievalLogger:
    """Tests for RetrievalLogger."""

    @pytest.fixture
    def logger(self):
        """Create logger instance."""
        return RetrievalLogger(
            service_name="test-service",
            log_level="DEBUG",
            output_format="json",
        )

    def test_logger_initialization(self, logger):
        """Test logger initializes correctly."""
        assert logger.service_name == "test-service"
        assert logger.log_level == "DEBUG"
        assert logger.output_format == "json"

    def test_logger_with_console_format(self):
        """Test logger with console output format."""
        logger = RetrievalLogger(
            service_name="test-service",
            log_level="INFO",
            output_format="console",
        )

        assert logger.output_format == "console"

    def test_log_retrieval(self, logger, capsys):
        """Test logging a retrieval operation."""
        query_id = uuid4()
        tenant_id = uuid4()
        user_id = uuid4()

        logger.log_retrieval(
            query_id=query_id,
            query="test query",
            mode="hybrid",
            tenant_id=tenant_id,
            user_id=user_id,
            result_count=5,
            top_scores=[0.9, 0.8, 0.7],
            total_ms=150.5,
            preprocessing_ms=20.0,
            search_ms=100.0,
            rerank_ms=30.5,
            used_semantic=True,
            used_keyword=True,
            used_reranking=True,
        )

        captured = capsys.readouterr()
        # Just verify something was logged
        assert len(captured.out) > 0 or len(captured.err) > 0

    def test_log_retrieval_with_error(self, logger, capsys):
        """Test logging a failed retrieval."""
        logger.log_retrieval(
            query_id=uuid4(),
            query="test query",
            mode="hybrid",
            tenant_id=uuid4(),
            user_id=None,
            result_count=0,
            top_scores=[],
            total_ms=50.0,
            preprocessing_ms=20.0,
            search_ms=30.0,
            error="Connection timeout",
        )

        captured = capsys.readouterr()
        # Verify something was logged
        assert len(captured.out) > 0 or len(captured.err) > 0

    def test_user_id_hashing(self, logger, capsys):
        """Test that user IDs are hashed for privacy."""
        user_id = uuid4()

        logger.log_retrieval(
            query_id=uuid4(),
            query="test",
            mode="hybrid",
            tenant_id=uuid4(),
            user_id=user_id,
            result_count=0,
            top_scores=[],
            total_ms=10,
            preprocessing_ms=5,
            search_ms=5,
        )

        captured = capsys.readouterr()
        output = captured.out + captured.err

        # User ID should not appear in raw form
        assert str(user_id) not in output

    def test_log_query_expansion(self, logger, capsys):
        """Test logging query expansion."""
        logger.log_query_expansion(
            query_id=uuid4(),
            original_query="machine learning",
            expanded_queries=["ML", "deep learning", "AI"],
            method="synonym",
            duration_ms=25.5,
        )

        captured = capsys.readouterr()
        assert len(captured.out) > 0 or len(captured.err) > 0

    def test_log_cache_operation(self, logger, capsys):
        """Test logging cache operation."""
        logger.log_cache_operation(
            operation="hit",
            cache_type="query",
            key_prefix="query:",
            duration_ms=1.5,
        )

        capsys.readouterr()
        # May not output if DEBUG level is filtered
        # Just verify no errors

    def test_log_error(self, logger, capsys):
        """Test logging an error with context."""
        try:
            raise ValueError("Test error message")
        except Exception as e:
            logger.log_error(
                error=e,
                context={"operation": "search", "component": "qdrant"},
                query_id=uuid4(),
            )

        captured = capsys.readouterr()
        assert len(captured.out) > 0 or len(captured.err) > 0

    def test_info_log(self, logger):
        """Test info level logging."""
        # Just verify method doesn't raise
        logger.info("Test info message", key="value")

    def test_debug_log(self, logger):
        """Test debug level logging."""
        # Just verify method doesn't raise
        logger.debug("Test debug message", key="value")

    def test_warning_log(self, logger):
        """Test warning level logging."""
        # Just verify method doesn't raise
        logger.warning("Test warning message", key="value")

    def test_error_log(self, logger):
        """Test error level logging."""
        # Just verify method doesn't raise
        logger.error("Test error message", key="value")

    def test_log_retrieval_no_user_id(self, logger, capsys):
        """Test logging without user_id."""
        logger.log_retrieval(
            query_id=uuid4(),
            query="test",
            mode="semantic",
            tenant_id=uuid4(),
            user_id=None,
            result_count=10,
            top_scores=[0.95],
            total_ms=100,
            preprocessing_ms=10,
            search_ms=90,
        )

        captured = capsys.readouterr()
        # Verify no errors - user_id_hash should be None
        assert len(captured.out) > 0 or len(captured.err) > 0

    def test_log_retrieval_with_trace_context(self, logger, capsys):
        """Test logging with trace context."""
        logger.log_retrieval(
            query_id=uuid4(),
            query="test",
            mode="hybrid",
            tenant_id=uuid4(),
            user_id=uuid4(),
            result_count=5,
            top_scores=[0.8],
            total_ms=100,
            preprocessing_ms=10,
            search_ms=90,
            trace_id="abc123def456",
            span_id="789xyz",
        )

        captured = capsys.readouterr()
        assert len(captured.out) > 0 or len(captured.err) > 0

    def test_log_retrieval_with_extra(self, logger, capsys):
        """Test logging with extra context."""
        logger.log_retrieval(
            query_id=uuid4(),
            query="test",
            mode="keyword",
            tenant_id=uuid4(),
            user_id=None,
            result_count=3,
            top_scores=[0.7, 0.6, 0.5],
            total_ms=50,
            preprocessing_ms=5,
            search_ms=45,
            extra={"custom_field": "custom_value"},
        )

        captured = capsys.readouterr()
        assert len(captured.out) > 0 or len(captured.err) > 0
