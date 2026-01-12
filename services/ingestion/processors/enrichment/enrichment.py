"""Enrichment pipeline for document metadata."""

from typing import TYPE_CHECKING

from .language_detector import LanguageDetector
from .metadata_extractor import MetadataExtractor
from .models import (
    DocumentMetadataEnriched,
    EnrichmentConfig,
    EnrichmentContext,
    LanguageResult,
    PIIResult,
)
from .pii_detector import PIIDetector, PIIDetectorConfig

if TYPE_CHECKING:
    from ..parsers.base import ParsedDocument


class EnrichmentPipeline:
    """
    Pipeline for enriching documents with metadata.

    Stages:
    1. Extract document properties (from parser output)
    2. Detect language
    3. Detect PII
    4. Inject ACL metadata

    The pipeline processes each stage sequentially and combines
    all results into a single enriched metadata object.
    """

    def __init__(self, config: EnrichmentConfig | None = None):
        """
        Initialize the enrichment pipeline.

        Args:
            config: Configuration for enrichment. If None, uses defaults.
        """
        self.config = config or EnrichmentConfig()
        self._language_detector = LanguageDetector()
        self._pii_detector: PIIDetector | None = None

        if self.config.enable_pii_detection:
            pii_config = PIIDetectorConfig(
                languages=self.config.pii_languages,
                score_threshold=self.config.pii_score_threshold,
            )
            self._pii_detector = PIIDetector(pii_config)

    async def enrich(
        self,
        parsed_doc: "ParsedDocument",
        context: EnrichmentContext,
    ) -> DocumentMetadataEnriched:
        """
        Enrich a parsed document with metadata.

        Args:
            parsed_doc: Output from document parser
            context: Enrichment context with tenant/ACL info

        Returns:
            Enriched metadata
        """
        # Extract document properties from parser output
        title = self._extract_title(parsed_doc)
        author = parsed_doc.author
        created_date = MetadataExtractor.parse_date(parsed_doc.created_date)
        modified_date = MetadataExtractor.parse_date(parsed_doc.modified_date)

        # Detect language
        language: LanguageResult | None = None
        if self.config.enable_language_detection and parsed_doc.text:
            language = await self._language_detector.detect(parsed_doc.text)

        # Detect PII
        pii: PIIResult | None = None
        if self._pii_detector and parsed_doc.text:
            pii = await self._pii_detector.detect(parsed_doc.text)

        return DocumentMetadataEnriched(
            title=title,
            author=author,
            created_date=created_date,
            modified_date=modified_date,
            language=language,
            pii=pii,
            tenant_id=context.tenant_id,
            visibility=context.visibility,
            allowed_groups=context.allowed_groups,
            allowed_users=context.allowed_users,
            custom=context.custom_metadata,
        )

    def _extract_title(self, parsed_doc: "ParsedDocument") -> str | None:
        """
        Extract title from parsed document.

        Falls back to extracting from text if not provided by parser.

        Args:
            parsed_doc: Parsed document

        Returns:
            Document title or None
        """
        if parsed_doc.title:
            return parsed_doc.title

        # Try to extract from text content
        if parsed_doc.text:
            return MetadataExtractor.extract_title_from_text(parsed_doc.text)

        return None

    async def enrich_text(
        self,
        text: str,
        context: EnrichmentContext,
        title: str | None = None,
        author: str | None = None,
    ) -> DocumentMetadataEnriched:
        """
        Enrich raw text with metadata.

        Convenience method when you don't have a ParsedDocument.

        Args:
            text: Raw text content
            context: Enrichment context with tenant/ACL info
            title: Optional document title
            author: Optional document author

        Returns:
            Enriched metadata
        """
        # Detect language
        language: LanguageResult | None = None
        if self.config.enable_language_detection and text:
            language = await self._language_detector.detect(text)

        # Detect PII
        pii: PIIResult | None = None
        if self._pii_detector and text:
            pii = await self._pii_detector.detect(text)

        # Extract title from text if not provided
        extracted_title = title
        if not extracted_title and text:
            extracted_title = MetadataExtractor.extract_title_from_text(text)

        return DocumentMetadataEnriched(
            title=extracted_title,
            author=author,
            created_date=None,
            modified_date=None,
            language=language,
            pii=pii,
            tenant_id=context.tenant_id,
            visibility=context.visibility,
            allowed_groups=context.allowed_groups,
            allowed_users=context.allowed_users,
            custom=context.custom_metadata,
        )
