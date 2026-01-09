"""Pytest fixtures for enrichment tests."""

import pytest

from ..language_detector import LanguageDetector
from ..pii_detector import PIIDetector, PIIDetectorConfig
from ..enrichment import EnrichmentPipeline
from ..models import EnrichmentConfig


@pytest.fixture
def language_detector():
    """Provide a LanguageDetector instance."""
    return LanguageDetector()


@pytest.fixture
def pii_detector():
    """Provide a PIIDetector instance with default config."""
    return PIIDetector()


@pytest.fixture
def pii_detector_config():
    """Provide a PIIDetectorConfig instance."""
    return PIIDetectorConfig()


@pytest.fixture
def enrichment_config():
    """Provide an EnrichmentConfig instance."""
    return EnrichmentConfig()


@pytest.fixture
def enrichment_pipeline():
    """Provide an EnrichmentPipeline instance."""
    return EnrichmentPipeline()


@pytest.fixture
def enrichment_pipeline_no_pii():
    """Provide an EnrichmentPipeline with PII detection disabled."""
    config = EnrichmentConfig(enable_pii_detection=False)
    return EnrichmentPipeline(config)


@pytest.fixture
def sample_english_text():
    """Sample English text for testing."""
    return (
        "The quick brown fox jumps over the lazy dog. "
        "This is a sample English text for testing language detection. "
        "It needs to be long enough for accurate detection."
    )


@pytest.fixture
def sample_spanish_text():
    """Sample Spanish text for testing."""
    return (
        "El rápido zorro marrón salta sobre el perro perezoso. "
        "Este es un texto de ejemplo en español para probar la detección de idioma. "
        "Debe ser lo suficientemente largo para una detección precisa."
    )


@pytest.fixture
def sample_pii_text():
    """Sample text containing PII for testing."""
    return (
        "Contact John Doe at john.doe@example.com or call (555) 123-4567. "
        "His SSN is 123-45-6789 and credit card is 4111-1111-1111-1111."
    )
