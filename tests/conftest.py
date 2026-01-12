"""
Pytest configuration for RAG Pipeline tests.
"""

import sys

import pytest

# Check if spacy is available (it may fail on Python 3.14+ due to pydantic v1 incompatibility)
try:
    import spacy  # noqa: F401

    SPACY_AVAILABLE = True
except Exception:
    SPACY_AVAILABLE = False


def pytest_configure(config):
    """Configure custom pytest markers."""
    config.addinivalue_line(
        "markers", "requires_spacy: mark test as requiring spacy to be available"
    )


def pytest_collection_modifyitems(config, items):
    """Skip tests that require spacy if it's not available."""
    if SPACY_AVAILABLE:
        return

    skip_spacy = pytest.mark.skip(
        reason=f"spacy not available on Python {sys.version_info.major}.{sys.version_info.minor} "
        "(pydantic v1 compatibility issue)"
    )
    for item in items:
        # Skip tests in test_pii_detection.py that require spacy
        if "test_pii_detection" in str(item.fspath):
            # Only skip tests that actually use the detector (not config tests)
            if "TestPIISettings" not in item.nodeid:
                item.add_marker(skip_spacy)
