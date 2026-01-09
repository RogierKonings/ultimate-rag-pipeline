"""
Pytest configuration and fixtures for processor tests.
"""

import pytest
from uuid import uuid4


@pytest.fixture
def document_id():
    """Generate a unique document ID for each test."""
    return uuid4()


@pytest.fixture
def tenant_id():
    """Generate a unique tenant ID for each test."""
    return "test-tenant-001"


@pytest.fixture
def sample_metadata(tenant_id):
    """Sample metadata for testing."""
    return {
        "tenant_id": tenant_id,
        "source": "test",
        "content_type": "text/plain"
    }
