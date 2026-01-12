"""Tests for enrichment pipeline."""

from datetime import datetime
from unittest.mock import Mock

import pytest

from ..enrichment import EnrichmentPipeline
from ..models import EnrichmentConfig, EnrichmentContext


class TestEnrichmentPipeline:
    """Test cases for EnrichmentPipeline."""

    @pytest.fixture
    def mock_parsed_doc(self):
        """Create a mock ParsedDocument for testing."""
        doc = Mock()
        doc.text = (
            "Hello, I am John Doe and my email is john@example.com. "
            "This document was written in English and contains important information."
        )
        doc.title = "Test Document"
        doc.author = "Jane Smith"
        doc.created_date = "2024-01-15"
        doc.modified_date = "2024-01-20"
        return doc

    @pytest.fixture
    def enrichment_context(self):
        """Create an EnrichmentContext for testing."""
        return EnrichmentContext(
            tenant_id="tenant-123",
            visibility="group",
            allowed_groups=["engineering", "product"],
            allowed_users=["user-1", "user-2"],
            custom_metadata={"project": "test-project"},
        )

    @pytest.mark.asyncio
    async def test_enrich_full_pipeline(
        self, enrichment_pipeline, mock_parsed_doc, enrichment_context,
    ):
        """Test full enrichment pipeline."""
        result = await enrichment_pipeline.enrich(mock_parsed_doc, enrichment_context)

        # Document properties
        assert result.title == "Test Document"
        assert result.author == "Jane Smith"
        assert result.created_date is not None
        assert result.modified_date is not None

        # Language detection
        assert result.language is not None
        assert result.language.language_code == "en"

        # PII detection
        assert result.pii is not None
        assert result.pii.has_pii

        # ACL metadata
        assert result.tenant_id == "tenant-123"
        assert result.visibility == "group"
        assert "engineering" in result.allowed_groups
        assert "user-1" in result.allowed_users

        # Custom metadata
        assert result.custom["project"] == "test-project"

        # Processing timestamp
        assert result.enriched_at is not None

    @pytest.mark.asyncio
    async def test_enrich_without_pii_detection(
        self, enrichment_pipeline_no_pii, mock_parsed_doc, enrichment_context,
    ):
        """Test enrichment with PII detection disabled."""
        result = await enrichment_pipeline_no_pii.enrich(
            mock_parsed_doc, enrichment_context,
        )

        assert result.pii is None
        assert result.language is not None  # Language detection still works

    @pytest.mark.asyncio
    async def test_enrich_without_language_detection(
        self, mock_parsed_doc, enrichment_context,
    ):
        """Test enrichment with language detection disabled."""
        config = EnrichmentConfig(enable_language_detection=False)
        pipeline = EnrichmentPipeline(config)

        result = await pipeline.enrich(mock_parsed_doc, enrichment_context)

        assert result.language is None
        assert result.pii is not None  # PII detection still works

    @pytest.mark.asyncio
    async def test_enrich_extracts_title_from_text(self, enrichment_context):
        """Test that title is extracted from text if not provided."""
        doc = Mock()
        doc.text = "# My Document Title\n\nThis is the document content."
        doc.title = None
        doc.author = None
        doc.created_date = None
        doc.modified_date = None

        pipeline = EnrichmentPipeline()
        result = await pipeline.enrich(doc, enrichment_context)

        assert result.title == "My Document Title"

    @pytest.mark.asyncio
    async def test_enrich_empty_text(self, enrichment_context):
        """Test enrichment with empty text."""
        doc = Mock()
        doc.text = ""
        doc.title = "Title"
        doc.author = None
        doc.created_date = None
        doc.modified_date = None

        pipeline = EnrichmentPipeline()
        result = await pipeline.enrich(doc, enrichment_context)

        assert result.title == "Title"
        assert result.language is None  # Can't detect language from empty text
        assert result.pii is None  # No PII in empty text

    @pytest.mark.asyncio
    async def test_enrich_text_convenience_method(self, enrichment_context):
        """Test enrich_text convenience method."""
        text = (
            "This is a test document about programming. "
            "Contact support@example.com for help."
        )

        pipeline = EnrichmentPipeline()
        result = await pipeline.enrich_text(
            text=text,
            context=enrichment_context,
            title="Custom Title",
            author="Test Author",
        )

        assert result.title == "Custom Title"
        assert result.author == "Test Author"
        assert result.language is not None
        assert result.pii is not None
        assert result.pii.has_pii
        assert result.tenant_id == "tenant-123"

    @pytest.mark.asyncio
    async def test_enrich_text_extracts_title(self, enrichment_context):
        """Test that enrich_text extracts title from text if not provided."""
        text = "Important Document\n\nThis is the content of the document."

        pipeline = EnrichmentPipeline()
        result = await pipeline.enrich_text(text=text, context=enrichment_context)

        assert result.title == "Important Document"

    @pytest.mark.asyncio
    async def test_enrich_parses_dates(self, enrichment_context):
        """Test that dates are properly parsed."""
        doc = Mock()
        doc.text = "Test content for language detection purposes here."
        doc.title = "Test"
        doc.author = None
        doc.created_date = "January 15, 2024"
        doc.modified_date = "2024-01-20T10:30:00Z"

        pipeline = EnrichmentPipeline()
        result = await pipeline.enrich(doc, enrichment_context)

        assert result.created_date is not None
        assert isinstance(result.created_date, datetime)
        assert result.created_date.month == 1
        assert result.created_date.day == 15

    @pytest.mark.asyncio
    async def test_enrich_handles_invalid_dates(self, enrichment_context):
        """Test that invalid dates are handled gracefully."""
        doc = Mock()
        doc.text = "Test content for language detection purposes here."
        doc.title = "Test"
        doc.author = None
        doc.created_date = "not-a-valid-date"
        doc.modified_date = None

        pipeline = EnrichmentPipeline()
        result = await pipeline.enrich(doc, enrichment_context)

        assert result.created_date is None  # Should be None for invalid date

    @pytest.mark.asyncio
    async def test_enrich_default_context_values(self):
        """Test enrichment with default context values."""
        context = EnrichmentContext(tenant_id="tenant-1")
        doc = Mock()
        doc.text = "Simple test document content for testing purposes."
        doc.title = "Test"
        doc.author = None
        doc.created_date = None
        doc.modified_date = None

        pipeline = EnrichmentPipeline()
        result = await pipeline.enrich(doc, context)

        assert result.tenant_id == "tenant-1"
        assert result.visibility == "private"  # Default
        assert result.allowed_groups == []  # Default
        assert result.allowed_users == []  # Default
        assert result.custom == {}  # Default
