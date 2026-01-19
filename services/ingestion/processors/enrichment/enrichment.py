"""Enrichment pipeline for document metadata."""

from typing import TYPE_CHECKING

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
from .pii_detector import PIIDetector, PIIDetectorConfig

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from services.shared.security.pii import PIIDetector as SharedPIIDetector
    from services.shared.security.pii import TenantPIIConfigService

    from ..parsers.base import ParsedDocument


class EnrichmentPipeline:
    """
    Pipeline for enriching documents with metadata.

    Stages:
    1. Extract document properties (from parser output)
    2. Detect language
    3. Detect PII (using tenant-specific settings if available)
    4. Inject ACL metadata

    The pipeline processes each stage sequentially and combines
    all results into a single enriched metadata object.

    Supports tenant-specific PII configuration via TenantPIIConfigService.
    If a tenant config service is provided, PII detection will use the
    tenant's configured settings, entity configs, and custom patterns.
    """

    def __init__(
        self,
        config: EnrichmentConfig | None = None,
        tenant_pii_config_service: "TenantPIIConfigService | None" = None,
    ):
        """
        Initialize the enrichment pipeline.

        Args:
            config: Configuration for enrichment. If None, uses defaults.
            tenant_pii_config_service: Optional service for tenant-specific PII config.
                If provided, PII detection will use tenant settings instead of defaults.
        """
        self.config = config or EnrichmentConfig()
        self._language_detector = LanguageDetector()
        self._pii_detector: PIIDetector | None = None
        self._tenant_pii_config_service = tenant_pii_config_service

        # Only create default PII detector if no tenant config service is provided
        if self.config.enable_pii_detection and not tenant_pii_config_service:
            pii_config = PIIDetectorConfig(
                languages=self.config.pii_languages,
                score_threshold=self.config.pii_score_threshold,
            )
            self._pii_detector = PIIDetector(pii_config)

    async def _get_pii_detector_for_tenant(
        self,
        tenant_id: str,
        session: "AsyncSession",
    ) -> "SharedPIIDetector | PIIDetector | None":
        """
        Get PII detector for a specific tenant.

        Uses tenant-specific settings if a config service is available,
        otherwise falls back to the default detector.

        Args:
            tenant_id: The tenant ID
            session: Database session for loading tenant config

        Returns:
            PIIDetector configured for the tenant, or None if disabled
        """
        if self._tenant_pii_config_service:
            # Get tenant-specific settings
            settings = await self._tenant_pii_config_service.get_pii_settings(
                tenant_id, session
            )
            if not settings.enabled:
                return None
            # Get detector with tenant's settings
            return await self._tenant_pii_config_service.get_detector(
                tenant_id, session
            )
        # Fall back to default detector
        return self._pii_detector

    async def enrich(
        self,
        parsed_doc: "ParsedDocument",
        context: EnrichmentContext,
        session: "AsyncSession | None" = None,
    ) -> DocumentMetadataEnriched:
        """
        Enrich a parsed document with metadata.

        Args:
            parsed_doc: Output from document parser
            context: Enrichment context with tenant/ACL info
            session: Database session (required if using tenant PII config)

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

        # Detect PII using tenant-specific settings if available
        pii: PIIResult | None = None
        if self.config.enable_pii_detection and parsed_doc.text:
            pii = await self._detect_pii(
                text=parsed_doc.text,
                tenant_id=context.tenant_id,
                session=session,
            )

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

    async def _detect_pii(
        self,
        text: str,
        tenant_id: str,
        session: "AsyncSession | None" = None,
    ) -> PIIResult | None:
        """
        Detect PII in text using appropriate detector.

        Uses tenant-specific detector if config service is available
        and a session is provided.

        Args:
            text: Text to scan for PII
            tenant_id: Tenant ID for tenant-specific settings
            session: Database session (required for tenant config)

        Returns:
            PIIResult with detected entities, or None if detection disabled
        """
        if self._tenant_pii_config_service and session:
            detector = await self._get_pii_detector_for_tenant(tenant_id, session)
            if detector is None:
                return None
            # Shared PIIDetector returns shared PIIResult, convert to local model
            shared_result = await detector.detect(text)

            # Convert entities, skipping unknown types
            entities = []
            for e in shared_result.entities:
                try:
                    pii_type = PIIType(e.entity_type)
                    entities.append(
                        PIIEntity(
                            entity_type=pii_type,
                            text=e.text,
                            start=e.start,
                            end=e.end,
                            score=e.score,
                        )
                    )
                except ValueError:
                    # Unknown entity type from custom pattern, skip
                    pass

            return PIIResult(
                entities=entities,
                entity_counts=shared_result.entity_counts,
                has_pii=shared_result.has_pii,
                high_sensitivity=shared_result.has_high_sensitivity,
            )
        elif self._pii_detector:
            return await self._pii_detector.detect(text)
        return None

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
        session: "AsyncSession | None" = None,
    ) -> DocumentMetadataEnriched:
        """
        Enrich raw text with metadata.

        Convenience method when you don't have a ParsedDocument.

        Args:
            text: Raw text content
            context: Enrichment context with tenant/ACL info
            title: Optional document title
            author: Optional document author
            session: Database session (required if using tenant PII config)

        Returns:
            Enriched metadata
        """
        # Detect language
        language: LanguageResult | None = None
        if self.config.enable_language_detection and text:
            language = await self._language_detector.detect(text)

        # Detect PII using tenant-specific settings if available
        pii: PIIResult | None = None
        if self.config.enable_pii_detection and text:
            pii = await self._detect_pii(
                text=text,
                tenant_id=context.tenant_id,
                session=session,
            )

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
