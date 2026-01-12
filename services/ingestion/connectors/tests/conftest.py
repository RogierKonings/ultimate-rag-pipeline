"""Pytest configuration for connector tests."""

import sys
from pathlib import Path

import pytest

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))


def pytest_configure(config):
    """Add custom markers for test categorization."""
    config.addinivalue_line(
        "markers",
        "integration: mark test as integration test (requires Docker)",
    )
    config.addinivalue_line(
        "markers",
        "slow: mark test as slow running",
    )
    config.addinivalue_line(
        "markers",
        "unit: mark test as unit test",
    )


def pytest_collection_modifyitems(config, items):
    """Automatically add markers based on test location and naming."""
    for item in items:
        # Add unit marker to tests not marked as integration
        if "integration" not in item.keywords:
            item.add_marker(pytest.mark.unit)

        # Skip integration tests by default unless explicitly requested
        if "integration" in item.keywords:
            if not config.getoption("-m") or "integration" not in config.getoption("-m"):
                item.add_marker(
                    pytest.mark.skip(reason="Integration tests require -m integration flag"),
                )


@pytest.fixture(scope="session")
def event_loop_policy():
    """Use default event loop policy."""
    import asyncio

    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture
def temp_directory(tmp_path):
    """Provide a temporary directory for tests."""
    return tmp_path
