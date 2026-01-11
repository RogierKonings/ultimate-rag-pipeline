"""
Tests for structured logging module.
"""

import json
import logging
import pytest
from unittest.mock import Mock, patch, MagicMock


class TestLoggingConfig:
    """Tests for LoggingConfig."""

    def test_default_values(self):
        """Test default configuration values."""
        from shared.observability.logging.config import LoggingConfig

        config = LoggingConfig(service_name="test-service")

        assert config.service_name == "test-service"
        assert config.service_version == "0.0.0"
        assert config.environment == "development"
        assert config.log_level == "INFO"
        assert config.json_format is True
        assert config.include_trace_context is True
        assert "password" in config.sensitive_fields
        assert "/health" in config.excluded_paths

    def test_from_env(self):
        """Test loading config from environment."""
        from shared.observability.logging.config import LoggingConfig

        with patch.dict("os.environ", {
            "SERVICE_NAME": "env-service",
            "SERVICE_VERSION": "1.2.3",
            "ENVIRONMENT": "production",
            "LOG_LEVEL": "DEBUG",
            "LOG_JSON": "true",
            "LOG_PRETTY": "false",
        }):
            config = LoggingConfig.from_env()

            assert config.service_name == "env-service"
            assert config.service_version == "1.2.3"
            assert config.environment == "production"
            assert config.log_level == "DEBUG"

    def test_get_log_level_int(self):
        """Test converting log level to int."""
        from shared.observability.logging.config import LoggingConfig

        config = LoggingConfig(service_name="test", log_level="DEBUG")
        assert config.get_log_level_int() == logging.DEBUG

        config = LoggingConfig(service_name="test", log_level="WARNING")
        assert config.get_log_level_int() == logging.WARNING


class TestJSONFormatter:
    """Tests for JSONFormatter."""

    def test_format_basic_message(self):
        """Test formatting a basic log message."""
        from shared.observability.logging.formatters import JSONFormatter

        formatter = JSONFormatter(
            service_name="test-service",
            service_version="1.0.0",
            environment="test",
        )

        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="/test/file.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        data = json.loads(output)

        assert data["message"] == "Test message"
        assert data["level"] == "INFO"
        assert data["logger"] == "test.logger"
        assert data["service"]["name"] == "test-service"
        assert data["service"]["version"] == "1.0.0"
        assert data["source"]["line"] == 42

    def test_format_with_exception(self):
        """Test formatting with exception info."""
        from shared.observability.logging.formatters import JSONFormatter

        formatter = JSONFormatter(service_name="test")

        try:
            raise ValueError("Test error")
        except ValueError:
            import sys
            exc_info = sys.exc_info()

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="/test.py",
            lineno=1,
            msg="Error occurred",
            args=(),
            exc_info=exc_info,
        )

        output = formatter.format(record)
        data = json.loads(output)

        assert "exception" in data
        assert data["exception"]["type"] == "ValueError"
        assert "Test error" in data["exception"]["message"]
        assert "stacktrace" in data["exception"]

    def test_format_with_extra_fields(self):
        """Test formatting with extra fields."""
        from shared.observability.logging.formatters import JSONFormatter

        formatter = JSONFormatter(service_name="test")

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="/test.py",
            lineno=1,
            msg="Message",
            args=(),
            exc_info=None,
        )
        record.user_id = "user123"
        record.request_id = "req456"

        output = formatter.format(record)
        data = json.loads(output)

        assert data["extra"]["user_id"] == "user123"
        assert data["extra"]["request_id"] == "req456"


class TestTextFormatter:
    """Tests for TextFormatter."""

    def test_format_basic_message(self):
        """Test text formatting."""
        from shared.observability.logging.formatters import TextFormatter

        formatter = TextFormatter(include_trace_context=False)

        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="/test/file.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )
        record.filename = "file.py"

        output = formatter.format(record)

        assert "INFO" in output
        assert "test.logger" in output
        assert "Test message" in output
        assert "file.py:42" in output


class TestSensitiveDataFilter:
    """Tests for SensitiveDataFilter."""

    def test_mask_password_field(self):
        """Test masking password field."""
        from shared.observability.logging.filters import SensitiveDataFilter

        filter_ = SensitiveDataFilter()

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="/test.py",
            lineno=1,
            msg="User login",
            args=(),
            exc_info=None,
        )
        record.password = "secret123"

        filter_.filter(record)

        assert record.password == "***REDACTED***"

    def test_mask_jwt_token(self):
        """Test masking JWT tokens in message."""
        from shared.observability.logging.filters import SensitiveDataFilter

        filter_ = SensitiveDataFilter()

        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="/test.py",
            lineno=1,
            msg=f"Token: {jwt}",
            args=(),
            exc_info=None,
        )

        filter_.filter(record)

        assert "eyJ" not in record.msg
        assert "***REDACTED***" in record.msg

    def test_mask_api_key_pattern(self):
        """Test masking API key patterns."""
        from shared.observability.logging.filters import SensitiveDataFilter

        filter_ = SensitiveDataFilter()

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="/test.py",
            lineno=1,
            msg="api_key=sk_test_1234567890abcdefghijklmnopqr",
            args=(),
            exc_info=None,
        )

        filter_.filter(record)

        assert "sk_live" not in record.msg

    def test_mask_dict_values(self):
        """Test masking values in dict args."""
        from shared.observability.logging.filters import SensitiveDataFilter

        filter_ = SensitiveDataFilter()

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="/test.py",
            lineno=1,
            msg="Data: %s",
            args=({"password": "secret", "username": "john"},),
            exc_info=None,
        )

        filter_.filter(record)

        # Args should be a tuple with masked dict
        assert record.args[0]["password"] == "***REDACTED***"
        assert record.args[0]["username"] == "john"


class TestContextManagement:
    """Tests for logging context management."""

    def test_set_request_context(self):
        """Test setting request context."""
        from shared.observability.logging.context import (
            set_request_context,
            get_request_context,
            clear_request_context,
        )

        set_request_context(
            request_id="req123",
            tenant_id="tenant456",
            user_id="user789",
        )

        ctx = get_request_context()
        assert ctx.request_id == "req123"
        assert ctx.tenant_id == "tenant456"
        assert ctx.user_id == "user789"

        clear_request_context()
        assert get_request_context() is None

    def test_context_to_dict(self):
        """Test converting context to dict."""
        from shared.observability.logging.context import RequestContext

        ctx = RequestContext(
            request_id="req123",
            tenant_id="tenant456",
            method="GET",
            path="/api/query",
        )

        data = ctx.to_dict()

        assert data["request_id"] == "req123"
        assert data["tenant_id"] == "tenant456"
        assert data["method"] == "GET"
        assert "user_id" not in data  # None values excluded

    def test_context_injector_filter(self):
        """Test ContextInjectorFilter."""
        from shared.observability.logging.context import (
            ContextInjectorFilter,
            set_request_context,
            clear_request_context,
        )

        filter_ = ContextInjectorFilter()

        set_request_context(request_id="req123", tenant_id="tenant456")

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="/test.py",
            lineno=1,
            msg="Test",
            args=(),
            exc_info=None,
        )

        filter_.filter(record)

        assert record.request_id == "req123"
        assert record.tenant_id == "tenant456"

        clear_request_context()


class TestLoggerAdapter:
    """Tests for LoggerAdapter."""

    def test_adapter_includes_context(self):
        """Test that adapter includes request context."""
        from shared.observability.logging.context import (
            LoggerAdapter,
            set_request_context,
            clear_request_context,
        )

        logger = logging.getLogger("test.adapter")
        adapter = LoggerAdapter(logger)

        set_request_context(request_id="req123")

        msg, kwargs = adapter.process("Test message", {})

        assert kwargs["extra"]["request_id"] == "req123"

        clear_request_context()

    def test_adapter_with_context_method(self):
        """Test with_context creates new adapter."""
        from shared.observability.logging.context import LoggerAdapter

        logger = logging.getLogger("test.adapter2")
        adapter = LoggerAdapter(logger)

        new_adapter = adapter.with_context(component="retrieval")

        assert new_adapter.extra["component"] == "retrieval"
        assert adapter is not new_adapter


class TestStructuredLogger:
    """Tests for StructuredLogger."""

    def test_request_started_logging(self):
        """Test request_started method."""
        from shared.observability.logging.context import LoggerAdapter, StructuredLogger

        mock_logger = Mock(spec=logging.Logger)
        adapter = LoggerAdapter(mock_logger)
        structured = StructuredLogger(adapter)

        structured.request_started("GET", "/api/query", user_id="user123")

        mock_logger.info.assert_called()
        call_args = mock_logger.info.call_args
        assert "GET" in call_args[0][0]
        assert "/api/query" in call_args[0][0]

    def test_request_completed_logging(self):
        """Test request_completed method."""
        from shared.observability.logging.context import LoggerAdapter, StructuredLogger

        mock_logger = Mock(spec=logging.Logger)
        adapter = LoggerAdapter(mock_logger)
        structured = StructuredLogger(adapter)

        structured.request_completed("POST", "/api/ingest", 200, 150.5)

        mock_logger.info.assert_called()


class TestSetupLogging:
    """Tests for setup_logging function."""

    def test_setup_logging_initializes(self):
        """Test that setup_logging initializes correctly."""
        from shared.observability.logging.logger import setup_logging
        from shared.observability.logging.config import LoggingConfig

        # Reset global state
        import shared.observability.logging.logger as logger_module
        logger_module._logging_initialized = False
        logger_module._logging_config = None

        config = LoggingConfig(
            service_name="test-setup",
            json_format=False,
            async_logging=False,
        )

        result = setup_logging(config)

        assert result.service_name == "test-setup"
        assert logger_module._logging_initialized is True

    def test_get_logger_returns_adapter(self):
        """Test get_logger returns LoggerAdapter."""
        from shared.observability.logging.logger import get_logger
        from shared.observability.logging.context import LoggerAdapter

        # Reset global state
        import shared.observability.logging.logger as logger_module
        logger_module._logging_initialized = False
        logger_module._logging_config = None

        logger = get_logger("test.module")

        assert isinstance(logger, LoggerAdapter)


class TestExcludePathFilter:
    """Tests for ExcludePathFilter."""

    def test_excludes_health_paths(self):
        """Test that health paths are excluded."""
        from shared.observability.logging.filters import ExcludePathFilter

        filter_ = ExcludePathFilter(excluded_paths=["/health", "/metrics"])

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="/test.py",
            lineno=1,
            msg="Test",
            args=(),
            exc_info=None,
        )
        record.path = "/health"

        assert filter_.filter(record) is False

        record.path = "/api/query"
        assert filter_.filter(record) is True


class TestRateLimitFilter:
    """Tests for RateLimitFilter."""

    def test_allows_initial_messages(self):
        """Test that initial messages are allowed."""
        from shared.observability.logging.filters import RateLimitFilter

        filter_ = RateLimitFilter(rate_limit_seconds=60, max_duplicates=3)

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="/test.py",
            lineno=1,
            msg="Error occurred",
            args=(),
            exc_info=None,
        )

        # First 3 should pass
        assert filter_.filter(record) is True
        assert filter_.filter(record) is True
        assert filter_.filter(record) is True

    def test_suppresses_after_limit(self):
        """Test that messages are suppressed after limit."""
        from shared.observability.logging.filters import RateLimitFilter

        filter_ = RateLimitFilter(rate_limit_seconds=60, max_duplicates=2)

        record = logging.LogRecord(
            name="test",
            level=logging.ERROR,
            pathname="/test.py",
            lineno=1,
            msg="Error occurred",
            args=(),
            exc_info=None,
        )

        assert filter_.filter(record) is True
        assert filter_.filter(record) is True
        # Third message should add suppression note and pass
        assert filter_.filter(record) is True
        assert "suppressed" in record.msg
        # Fourth should be filtered
        record.msg = "Error occurred"  # Reset
        assert filter_.filter(record) is False
