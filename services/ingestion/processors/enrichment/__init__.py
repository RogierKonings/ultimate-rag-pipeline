# Metadata Enrichment Module
# ==========================
# Provides document metadata enrichment including:
# - Language detection
# - PII detection and anonymization
# - Metadata extraction utilities
# - Enrichment pipeline orchestration

from .enrichment import EnrichmentPipeline
from .language_detector import LanguageDetector
from .metadata_extractor import MetadataExtractor
from .models import (
    DocumentMetadataEnriched,
    EnrichmentConfig,
    EnrichmentContext,
    LanguageResult,
    PIIEntity,
    PIIResult,
    PIIType,
)
from .pii_detector import PIIAnonymizer, PIIDetector, PIIDetectorConfig

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
