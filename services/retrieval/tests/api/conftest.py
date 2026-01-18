"""Pytest configuration for API tests.

This conftest mocks problematic modules before they are imported to allow
testing the API routes without requiring all dependencies to be present.
"""

import sys
from unittest.mock import MagicMock


def _create_mock_module():
    """Create a mock module that returns mocks for any attribute access."""
    mock = MagicMock()
    mock.__path__ = []  # Required for packages
    mock.__file__ = __file__
    mock.VideoRetriever = MagicMock()
    mock.VideoRetrieverConfig = MagicMock()
    mock.VideoSearchMode = MagicMock()
    mock.ClipCacheService = MagicMock()
    mock.ClipCacheConfig = MagicMock()
    mock.ClipGenerator = MagicMock()
    mock.get_tenant_config_service = MagicMock(return_value=MagicMock())
    mock.TenantConfigService = MagicMock()
    mock.TenantIndexConfig = MagicMock()
    return mock


def _create_structlog_mock():
    """Create a mock for structlog with the expected interface."""
    mock = MagicMock()
    mock.__path__ = []
    mock.__file__ = __file__

    # structlog needs a types submodule with Processor
    types_mock = MagicMock()
    types_mock.Processor = MagicMock()
    mock.types = types_mock

    # Common structlog functions
    mock.get_logger = MagicMock(return_value=MagicMock())
    mock.configure = MagicMock()
    mock.wrap_logger = MagicMock()
    mock.make_filtering_bound_logger = MagicMock()
    mock.stdlib = MagicMock()
    mock.processors = MagicMock()
    mock.dev = MagicMock()
    mock.dev.ConsoleRenderer = MagicMock()
    mock.processors.JSONRenderer = MagicMock()
    mock.processors.TimeStamper = MagicMock()
    mock.processors.add_log_level = MagicMock()
    mock.processors.StackInfoRenderer = MagicMock()
    mock.processors.format_exc_info = MagicMock()
    mock.contextvars = MagicMock()
    mock.contextvars.merge_contextvars = MagicMock()
    mock.stdlib.add_logger_name = MagicMock()
    mock.stdlib.PositionalArgumentsFormatter = MagicMock()
    mock.stdlib.ProcessorFormatter = MagicMock()
    return mock


# Mock structlog first as it's needed by many modules
if "structlog" not in sys.modules:
    structlog_mock = _create_structlog_mock()
    sys.modules["structlog"] = structlog_mock
    sys.modules["structlog.types"] = structlog_mock.types
    sys.modules["structlog.stdlib"] = structlog_mock.stdlib
    sys.modules["structlog.processors"] = structlog_mock.processors
    sys.modules["structlog.dev"] = structlog_mock.dev
    sys.modules["structlog.contextvars"] = structlog_mock.contextvars

# Only mock if not already present
if "retrieval" not in sys.modules:
    sys.modules["retrieval"] = _create_mock_module()
    sys.modules["retrieval.video"] = _create_mock_module()
    sys.modules["retrieval.video.retriever"] = _create_mock_module()
    sys.modules["retrieval.video.models"] = _create_mock_module()
    sys.modules["retrieval.video.clip_cache"] = _create_mock_module()
    sys.modules["retrieval.video.clip_generator"] = _create_mock_module()
    sys.modules["retrieval.video.exceptions"] = _create_mock_module()

if "tenant" not in sys.modules:
    sys.modules["tenant"] = _create_mock_module()
    sys.modules["tenant.config_service"] = _create_mock_module()
