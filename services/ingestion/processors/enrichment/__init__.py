# Metadata Enrichment Module
# ==========================
# Provides document metadata enrichment including:
# - Language detection
# - PII detection and anonymization
# - Metadata extraction utilities
# - Enrichment pipeline orchestration

from .models import (
    PIIType,
    PIIEntity,
    PIIResult,
    LanguageResult,
    DocumentMetadataEnriched,
    EnrichmentContext,
    EnrichmentConfig,
)
from .language_detector import LanguageDetector
from .pii_detector import PIIDetector, PIIDetectorConfig, PIIAnonymizer
from .enrichment import EnrichmentPipeline
from .metadata_extractor import MetadataExtractor

__all__ = [
    # Data Models
    "PIIType",
    "PIIEntity",
    "PIIResult",
    "LanguageResult",
    "DocumentMetadataEnriched",
    "EnrichmentContext",
    "EnrichmentConfig",
    # Detectors
    "LanguageDetector",
    "PIIDetector",
    "PIIDetectorConfig",
    "PIIAnonymizer",
    # Pipeline
    "EnrichmentPipeline",
    # Utilities
    "MetadataExtractor",
]
