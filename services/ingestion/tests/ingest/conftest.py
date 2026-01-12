"""Pytest configuration for schema alignment tests."""

import sys
from pathlib import Path

import pytest

# Add service directories to path for imports
services_dir = Path(__file__).parent.parent.parent.parent
ingestion_dir = services_dir / "ingestion"
shared_dir = services_dir / "shared"

# Insert paths for imports
sys.path.insert(0, str(ingestion_dir))
sys.path.insert(0, str(shared_dir))


@pytest.fixture(autouse=True)
def reset_settings():
    """Reset global settings instance before each test."""
    import config

    # Reset the cached settings
    config._settings = None
    yield
    config._settings = None
