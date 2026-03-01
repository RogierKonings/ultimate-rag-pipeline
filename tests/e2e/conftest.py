"""
E2E pytest configuration for RAG Pipeline smoke tests.

This module provides fixtures and configuration for running E2E tests
that validate the entire pipeline from ingestion through generation.
"""

import asyncio
import os

import pytest
import pytest_asyncio


# Mark all tests in the e2e directory as requiring the --e2e flag
def pytest_configure(config):
    """Configure custom pytest markers for E2E tests."""
    config.addinivalue_line(
        "markers",
        "e2e: mark test as an end-to-end test requiring running infrastructure",
    )
    config.addinivalue_line("markers", "asyncio: mark test as async")


def pytest_collection_modifyitems(config, items):
    """Skip E2E tests unless --e2e flag is provided."""
    if not config.getoption("--e2e", default=False):
        skip_e2e = pytest.mark.skip(reason="need --e2e option to run E2E tests")
        for item in items:
            if "e2e" in item.keywords or "e2e" in str(item.fspath):
                item.add_marker(skip_e2e)


def pytest_addoption(parser):
    """Add custom command line options for E2E tests."""
    parser.addoption(
        "--e2e",
        action="store_true",
        default=False,
        help="run end-to-end tests (requires running infrastructure)",
    )


class E2EConfig:
    """Configuration for E2E tests, loaded from environment variables."""

    INGESTION_URL = os.getenv("INGESTION_URL", "http://localhost:8001")
    ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_URL", "http://localhost:8003")
    RETRIEVAL_URL = os.getenv("RETRIEVAL_URL", "http://localhost:8002")

    # Timeouts
    INGESTION_TIMEOUT = int(os.getenv("E2E_INGESTION_TIMEOUT", "60"))
    QUERY_TIMEOUT = int(os.getenv("E2E_QUERY_TIMEOUT", "30"))
    POLL_INTERVAL = int(os.getenv("E2E_POLL_INTERVAL", "2"))

    # Test tenant (use demo tenant by default)
    TEST_TENANT_ID = os.getenv(
        "E2E_TENANT_ID", "00000000-0000-0000-0000-000000000001"
    )


@pytest.fixture(scope="session")
def e2e_config():
    """Provide E2E configuration to tests."""
    return E2EConfig()


@pytest.fixture(scope="session")
def event_loop():
    """Create a session-scoped event loop for async fixtures."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def http_client():
    """Create async HTTP client for the session."""
    try:
        import httpx
    except ImportError:
        pytest.skip("httpx required for E2E tests. Install with: pip install httpx")

    async with httpx.AsyncClient(timeout=60.0) as client:
        yield client


@pytest.fixture(scope="session")
def auth_headers(e2e_config):
    """Generate authentication headers for API requests."""
    return {
        "Authorization": "Bearer e2e-test-token",
        "X-Tenant-ID": e2e_config.TEST_TENANT_ID,
        "Content-Type": "application/json",
    }
