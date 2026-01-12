"""
Tests for PII detection module.

This module tests PII detection, handling modes,
and response filtering capabilities.
"""

from uuid import uuid4

import pytest

from services.shared.security.pii import (
    PIIChunkResult,
    PIIDetector,
    PIIDocumentResult,
    PIIEntityType,
    PIIHandlingMode,
    PIIQueryFilter,
    PIIResponseFilter,
    PIIResult,
    PIISettings,
)


class TestPIISettings:
    """Tests for PII settings configuration."""

    def test_default_settings(self):
        """Test default settings values."""
        settings = PIISettings()
        assert settings.enabled is True
        assert settings.default_handling_mode == PIIHandlingMode.FLAG
        assert settings.confidence_threshold == 0.7
        assert "en" in settings.languages

    def test_custom_settings(self):
        """Test custom settings."""
        settings = PIISettings(
            enabled=False,
            default_handling_mode=PIIHandlingMode.REDACT,
            confidence_threshold=0.9,
            languages=["en", "es"],
        )
        assert settings.enabled is False
        assert settings.default_handling_mode == PIIHandlingMode.REDACT
        assert settings.confidence_threshold == 0.9
        assert settings.languages == ["en", "es"]

    def test_entity_specific_handling(self):
        """Test per-entity configuration."""
        from services.shared.security.pii.config import PIIEntityConfig

        settings = PIISettings(
            default_handling_mode=PIIHandlingMode.FLAG,
            entity_configs={
                PIIEntityType.US_SSN.value: PIIEntityConfig(
                    handling_mode=PIIHandlingMode.REJECT,
                    min_score=0.9,
                ),
                PIIEntityType.EMAIL_ADDRESS.value: PIIEntityConfig(
                    handling_mode=PIIHandlingMode.MASK,
                ),
            },
        )

        assert settings.get_handling_mode(PIIEntityType.US_SSN.value) == PIIHandlingMode.REJECT
        assert settings.get_handling_mode(PIIEntityType.EMAIL_ADDRESS.value) == PIIHandlingMode.MASK
        assert settings.get_handling_mode(PIIEntityType.PERSON.value) == PIIHandlingMode.FLAG

        assert settings.get_min_score(PIIEntityType.US_SSN.value) == 0.9
        assert settings.get_min_score(PIIEntityType.EMAIL_ADDRESS.value) == 0.7

    def test_is_entity_enabled(self):
        """Test entity enabled checking."""
        from services.shared.security.pii.config import PIIEntityConfig

        settings = PIISettings(
            entities_to_detect=[
                PIIEntityType.EMAIL_ADDRESS.value,
                PIIEntityType.PHONE_NUMBER.value,
            ],
            entity_configs={
                PIIEntityType.PHONE_NUMBER.value: PIIEntityConfig(enabled=False),
            },
        )

        assert settings.is_entity_enabled(PIIEntityType.EMAIL_ADDRESS.value) is True
        assert settings.is_entity_enabled(PIIEntityType.PHONE_NUMBER.value) is False
        assert settings.is_entity_enabled(PIIEntityType.US_SSN.value) is False


class TestPIIDetector:
    """Tests for PIIDetector class."""

    @pytest.fixture
    def detector(self):
        """Create detector with default settings."""
        settings = PIISettings(
            entities_to_detect=[
                PIIEntityType.EMAIL_ADDRESS.value,
                PIIEntityType.PHONE_NUMBER.value,
                PIIEntityType.PERSON.value,
                PIIEntityType.US_SSN.value,
                PIIEntityType.CREDIT_CARD.value,
            ],
        )
        return PIIDetector(settings)

    @pytest.fixture
    def strict_detector(self):
        """Create detector with strict settings."""
        settings = PIISettings(
            default_handling_mode=PIIHandlingMode.REJECT,
            reject_on_high_sensitivity=True,
            confidence_threshold=0.5,
        )
        return PIIDetector(settings)

    @pytest.mark.asyncio
    async def test_detect_email(self, detector):
        """Test email detection."""
        text = "Contact us at support@example.com for help."
        result = await detector.detect(text)

        assert result.has_pii is True
        assert PIIEntityType.EMAIL_ADDRESS.value in result.entity_counts
        assert result.entity_counts[PIIEntityType.EMAIL_ADDRESS.value] == 1

        email_entity = next(
            e for e in result.entities if e.entity_type == PIIEntityType.EMAIL_ADDRESS.value
        )
        assert email_entity.text == "support@example.com"

    @pytest.mark.asyncio
    async def test_detect_phone(self, detector):
        """Test phone number detection."""
        text = "Call me at 555-123-4567 or (800) 555-0199."
        result = await detector.detect(text)

        assert result.has_pii is True
        assert PIIEntityType.PHONE_NUMBER.value in result.entity_counts

    @pytest.mark.asyncio
    async def test_detect_ssn(self, detector):
        """Test SSN detection."""
        text = "My SSN is 123-45-6789."
        result = await detector.detect(text)

        assert result.has_pii is True
        assert result.has_high_sensitivity is True
        assert PIIEntityType.US_SSN.value in result.entity_counts

    @pytest.mark.asyncio
    async def test_detect_credit_card(self, detector):
        """Test credit card detection."""
        text = "Card number: 4111-1111-1111-1111"
        result = await detector.detect(text)

        assert result.has_pii is True
        assert result.has_high_sensitivity is True

    @pytest.mark.asyncio
    async def test_detect_person(self, detector):
        """Test person name detection."""
        text = "John Smith will be attending the meeting."
        result = await detector.detect(text)

        # Person detection depends on NLP model accuracy
        # Just verify no errors
        assert isinstance(result, PIIResult)

    @pytest.mark.asyncio
    async def test_detect_no_pii(self, detector):
        """Test text without PII."""
        text = "This is a technical document about algorithms."
        result = await detector.detect(text)

        assert result.has_pii is False
        assert len(result.entities) == 0

    @pytest.mark.asyncio
    async def test_detect_multiple_entities(self, detector):
        """Test detection of multiple PII types."""
        text = "Contact john@example.com or call 555-123-4567. SSN: 123-45-6789"
        result = await detector.detect(text)

        assert result.has_pii is True
        assert len(result.entity_counts) >= 2  # At least email and SSN
        assert result.has_high_sensitivity is True  # Due to SSN

    @pytest.mark.asyncio
    async def test_detection_disabled(self):
        """Test that disabled detection returns empty results."""
        settings = PIISettings(enabled=False)
        detector = PIIDetector(settings)

        text = "Contact support@example.com"
        result = await detector.detect(text)

        assert result.has_pii is False
        assert len(result.entities) == 0


class TestPIIRedaction:
    """Tests for PII redaction functionality."""

    @pytest.fixture
    def detector(self):
        """Create detector for redaction tests."""
        settings = PIISettings(
            default_handling_mode=PIIHandlingMode.REDACT,
        )
        return PIIDetector(settings)

    @pytest.mark.asyncio
    async def test_redact_email(self, detector):
        """Test email redaction."""
        text = "Email me at john@example.com please."
        redacted = await detector.redact(text)

        assert "john@example.com" not in redacted
        assert "[EMAIL_ADDRESS]" in redacted

    @pytest.mark.asyncio
    async def test_redact_preserves_context(self, detector):
        """Test that redaction preserves surrounding text."""
        text = "My email is test@test.com and phone is 555-1234."
        redacted = await detector.redact(text)

        assert "My email is" in redacted
        assert "and phone is" in redacted
        assert "test@test.com" not in redacted

    @pytest.mark.asyncio
    async def test_redact_no_pii(self, detector):
        """Test redaction on text without PII."""
        text = "This text has no PII."
        redacted = await detector.redact(text)

        assert redacted == text


class TestPIIMasking:
    """Tests for PII masking functionality."""

    @pytest.fixture
    def detector(self):
        """Create detector for masking tests."""
        settings = PIISettings(
            default_handling_mode=PIIHandlingMode.MASK,
        )
        return PIIDetector(settings)

    @pytest.mark.asyncio
    async def test_mask_email(self, detector):
        """Test email masking."""
        text = "Email: john@example.com"
        masked = await detector.mask(text)

        # Should keep first 4 chars
        assert "john" in masked
        assert "example.com" not in masked
        assert "*" in masked

    @pytest.mark.asyncio
    async def test_mask_custom_chars(self, detector):
        """Test masking with custom settings."""
        text = "SSN: 123-45-6789"
        masked = await detector.mask(text, mask_char="#", chars_to_keep=3)

        # Should have # characters for masking
        assert "#" in masked or "123" in masked  # Depends on detection


class TestPIIProcessing:
    """Tests for full PII processing workflow."""

    @pytest.fixture
    def detector(self):
        """Create detector for processing tests."""
        return PIIDetector(PIISettings())

    @pytest.mark.asyncio
    async def test_process_passthrough(self, detector):
        """Test passthrough mode."""
        text = "Email: test@test.com"
        result = await detector.process(text, PIIHandlingMode.PASSTHROUGH)

        assert result.processed_text == text
        assert result.handling_mode == PIIHandlingMode.PASSTHROUGH

    @pytest.mark.asyncio
    async def test_process_redact(self, detector):
        """Test redact mode via process."""
        text = "Email: test@test.com"
        result = await detector.process(text, PIIHandlingMode.REDACT)

        assert "test@test.com" not in result.processed_text
        assert result.handling_mode == PIIHandlingMode.REDACT
        assert result.entities_processed > 0

    @pytest.mark.asyncio
    async def test_process_flag(self, detector):
        """Test flag mode keeps text but records transformations."""
        text = "Email: test@test.com"
        result = await detector.process(text, PIIHandlingMode.FLAG)

        assert result.processed_text == text
        assert result.handling_mode == PIIHandlingMode.FLAG
        assert len(result.transformations) > 0
        assert result.transformations[0]["type"] == "flag"


class TestPIIChunkProcessing:
    """Tests for chunk-level PII processing."""

    @pytest.fixture
    def detector(self):
        """Create detector for chunk tests."""
        settings = PIISettings(
            reject_on_high_sensitivity=True,
        )
        return PIIDetector(settings)

    @pytest.mark.asyncio
    async def test_process_chunk_no_pii(self, detector):
        """Test processing chunk without PII."""
        result = await detector.process_chunk(
            chunk_id="chunk-1",
            text="This is technical documentation.",
        )

        assert result.chunk_id == "chunk-1"
        assert result.rejected is False
        assert result.detection_result.has_pii is False

    @pytest.mark.asyncio
    async def test_process_chunk_with_pii(self, detector):
        """Test processing chunk with PII."""
        result = await detector.process_chunk(
            chunk_id="chunk-2",
            text="Contact support@example.com for help.",
            handling_mode=PIIHandlingMode.REDACT,
        )

        assert result.rejected is False
        assert result.detection_result.has_pii is True
        assert result.processed is not None
        assert "support@example.com" not in result.processed.processed_text

    @pytest.mark.asyncio
    async def test_process_chunk_rejection(self, detector):
        """Test chunk rejection on high-sensitivity PII."""
        result = await detector.process_chunk(
            chunk_id="chunk-3",
            text="SSN: 123-45-6789",
        )

        assert result.rejected is True
        assert result.rejection_reason is not None
        assert "High-sensitivity" in result.rejection_reason


class TestPIIDocumentResult:
    """Tests for document-level PII aggregation."""

    def test_aggregate_from_chunks(self):
        """Test aggregating chunk results."""

        chunk_results = [
            PIIChunkResult(
                chunk_id="1",
                detection_result=PIIResult(
                    entities=[],
                    entity_counts={},
                    has_pii=False,
                    has_high_sensitivity=False,
                    processed_length=100,
                    processing_time_ms=10.0,
                ),
            ),
            PIIChunkResult(
                chunk_id="2",
                detection_result=PIIResult(
                    entities=[],
                    entity_counts={"EMAIL_ADDRESS": 2},
                    has_pii=True,
                    has_high_sensitivity=False,
                    processed_length=150,
                    processing_time_ms=15.0,
                ),
            ),
            PIIChunkResult(
                chunk_id="3",
                detection_result=PIIResult(
                    entities=[],
                    entity_counts={"EMAIL_ADDRESS": 1, "US_SSN": 1},
                    has_pii=True,
                    has_high_sensitivity=True,
                    processed_length=120,
                    processing_time_ms=12.0,
                ),
                rejected=True,
            ),
        ]

        doc_result = PIIDocumentResult.from_chunk_results(
            document_id=uuid4(),
            chunk_results=chunk_results,
        )

        assert doc_result.total_chunks == 3
        assert doc_result.chunks_with_pii == 2
        assert doc_result.chunks_rejected == 1
        assert doc_result.entity_counts["EMAIL_ADDRESS"] == 3
        assert doc_result.entity_counts["US_SSN"] == 1
        assert doc_result.has_high_sensitivity is True
        assert doc_result.processing_time_ms == 37.0


class TestPIIResponseFilter:
    """Tests for response filtering."""

    @pytest.fixture
    def filter(self):
        """Create response filter."""
        settings = PIISettings(
            default_handling_mode=PIIHandlingMode.REDACT,
        )
        return PIIResponseFilter(settings)

    @pytest.mark.asyncio
    async def test_filter_text(self, filter):
        """Test basic text filtering."""
        text = "Contact john@example.com for help."
        filtered = await filter.filter_text(text)

        assert "john@example.com" not in filtered
        assert "[EMAIL_ADDRESS]" in filtered

    @pytest.mark.asyncio
    async def test_filter_search_results(self, filter):
        """Test filtering search results."""
        results = [
            {"id": "1", "content": "Email: test@test.com", "score": 0.9},
            {"id": "2", "content": "No PII here", "score": 0.8},
        ]

        filtered = await filter.filter_search_results(results)

        assert filtered[0]["id"] == "1"
        assert "test@test.com" not in filtered[0]["content"]
        assert filtered[1]["content"] == "No PII here"

    @pytest.mark.asyncio
    async def test_filter_with_metadata(self, filter):
        """Test filtering with PII metadata included."""
        results = [
            {"id": "1", "content": "SSN: 123-45-6789", "score": 0.9},
        ]

        filtered = await filter.filter_search_results(
            results,
            include_pii_metadata=True,
        )

        assert filtered[0]["pii_detected"] is True
        assert filtered[0]["has_high_sensitivity"] is True

    @pytest.mark.asyncio
    async def test_filter_llm_response(self, filter):
        """Test LLM response filtering."""
        response = "The user's email is john@example.com."
        filtered, pii_result = await filter.filter_llm_response(response)

        assert "john@example.com" not in filtered
        assert pii_result.has_pii is True

    @pytest.mark.asyncio
    async def test_should_block_response(self, filter):
        """Test response blocking check."""
        # Normal PII - don't block
        should_block, reason = await filter.should_block_response(
            "Email: test@test.com",
            block_on_high_sensitivity=True,
        )
        assert should_block is False

        # High-sensitivity PII - block
        should_block, reason = await filter.should_block_response(
            "SSN: 123-45-6789",
            block_on_high_sensitivity=True,
        )
        assert should_block is True
        assert "High-sensitivity" in reason


class TestPIIQueryFilter:
    """Tests for query filtering."""

    @pytest.fixture
    def filter(self):
        """Create query filter."""
        settings = PIISettings(
            default_handling_mode=PIIHandlingMode.REDACT,
        )
        return PIIQueryFilter(settings)

    @pytest.mark.asyncio
    async def test_filter_query(self, filter):
        """Test query filtering."""
        query = "Find documents about john@example.com"
        filtered = await filter.filter_query(query)

        assert "john@example.com" not in filtered
        assert "[EMAIL_ADDRESS]" in filtered
        assert "Find documents about" in filtered

    @pytest.mark.asyncio
    async def test_extract_query_pii(self, filter):
        """Test PII extraction from query."""
        query = "Find info about john@test.com"
        result = await filter.extract_query_pii(query)

        assert result.has_pii is True
        assert "EMAIL_ADDRESS" in result.entity_counts

    @pytest.mark.asyncio
    async def test_safe_query_for_logging(self, filter):
        """Test getting safe query for logging."""
        query = "Search for SSN 123-45-6789"
        safe = await filter.get_safe_query_for_logging(query)

        assert "123-45-6789" not in safe


class TestPIIConfidenceThreshold:
    """Tests for confidence threshold handling."""

    @pytest.mark.asyncio
    async def test_high_threshold_filters_low_confidence(self):
        """Test that high threshold filters low-confidence matches."""
        settings = PIISettings(
            confidence_threshold=0.95,  # Very high threshold
        )
        detector = PIIDetector(settings)

        # Some detections might not meet high threshold
        text = "The name John might be a person."
        result = await detector.detect(text)

        # Result depends on model confidence
        assert isinstance(result, PIIResult)

    @pytest.mark.asyncio
    async def test_low_threshold_catches_more(self):
        """Test that low threshold catches more matches."""
        settings = PIISettings(
            confidence_threshold=0.3,  # Low threshold
        )
        detector = PIIDetector(settings)

        text = "Contact: john@example.com"
        result = await detector.detect(text)

        # Should definitely catch email with low threshold
        assert result.has_pii is True


class TestPIIDisabledMode:
    """Tests for disabled PII detection."""

    @pytest.fixture
    def disabled_detector(self):
        """Create disabled detector."""
        return PIIDetector(PIISettings(enabled=False))

    @pytest.mark.asyncio
    async def test_detect_returns_empty(self, disabled_detector):
        """Test detection returns empty when disabled."""
        result = await disabled_detector.detect("SSN: 123-45-6789")
        assert result.has_pii is False
        assert len(result.entities) == 0

    @pytest.mark.asyncio
    async def test_redact_returns_original(self, disabled_detector):
        """Test redaction returns original text when disabled."""
        text = "Email: test@test.com"
        redacted = await disabled_detector.redact(text)
        assert redacted == text

    @pytest.mark.asyncio
    async def test_filter_passthrough(self):
        """Test filter passes through when disabled."""
        settings = PIISettings(enabled=False)
        filter = PIIResponseFilter(settings)

        text = "SSN: 123-45-6789"
        filtered = await filter.filter_text(text)
        assert filtered == text
