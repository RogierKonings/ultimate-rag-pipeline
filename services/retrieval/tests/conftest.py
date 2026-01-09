"""Test fixtures for Retrieval Service tests."""

import sys
from pathlib import Path
from uuid import uuid4

import pytest

# Add service root to path for imports
service_root = Path(__file__).parent.parent
sys.path.insert(0, str(service_root))


@pytest.fixture
def user_id():
    """Generate a unique user ID."""
    return uuid4()


@pytest.fixture
def tenant_id():
    """Generate a unique tenant ID."""
    return uuid4()


@pytest.fixture
def jwt_secret():
    """Test JWT secret key."""
    return "test-secret-key-for-jwt-validation"
