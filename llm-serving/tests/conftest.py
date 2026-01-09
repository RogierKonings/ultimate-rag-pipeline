"""
Pytest configuration for LLM Serving Layer tests.
"""

import os

import pytest


def pytest_configure(config):
    """Add custom markers."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test (requires running services)"
    )


@pytest.fixture(scope="session")
def vllm_url():
    """Get vLLM service URL."""
    return os.environ.get("VLLM_URL", "http://localhost:8000")


@pytest.fixture(scope="session")
def embedding_url():
    """Get embedding service URL."""
    return os.environ.get("EMBEDDING_URL", "http://localhost:8001")


@pytest.fixture(scope="session")
def reranker_url():
    """Get reranker service URL."""
    return os.environ.get("RERANKER_URL", "http://localhost:8002")
