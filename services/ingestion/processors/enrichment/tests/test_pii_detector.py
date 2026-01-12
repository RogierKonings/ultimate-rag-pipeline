"""Tests for PII detection."""

import pytest

from ..models import PIIType
from ..pii_detector import PIIAnonymizer, PIIDetector, PIIDetectorConfig


class TestPIIDetector:
    """Test cases for PIIDetector."""

    @pytest.mark.asyncio
    async def test_detect_email(self, pii_detector):
        """Test detecting email addresses."""
        text = "Contact me at john.doe@example.com for more information."
        result = await pii_detector.detect(text)

        assert result.has_pii
        assert "EMAIL_ADDRESS" in result.entity_counts
        assert any(e.text == "john.doe@example.com" for e in result.entities)
        assert any(e.entity_type == PIIType.EMAIL for e in result.entities)

    @pytest.mark.asyncio
    async def test_detect_phone_number(self, pii_detector):
        """Test detecting phone numbers."""
        text = "Call me at (555) 123-4567 to discuss the project."
        result = await pii_detector.detect(text)

        assert result.has_pii
        assert "PHONE_NUMBER" in result.entity_counts

    @pytest.mark.asyncio
    async def test_detect_person_name(self, pii_detector):
        """Test detecting person names."""
        text = "John Smith is the project manager for this initiative."
        result = await pii_detector.detect(text)

        assert result.has_pii
        assert "PERSON" in result.entity_counts

    @pytest.mark.asyncio
    async def test_detect_ssn_high_sensitivity(self, pii_detector):
        """Test detecting SSN and marking as high sensitivity."""
        text = "My SSN is 123-45-6789."
        result = await pii_detector.detect(text)

        assert result.has_pii
        assert result.high_sensitivity
        assert "US_SSN" in result.entity_counts

    @pytest.mark.asyncio
    async def test_detect_credit_card_high_sensitivity(self, pii_detector):
        """Test detecting credit card and marking as high sensitivity."""
        text = "My credit card number is 4111-1111-1111-1111."
        result = await pii_detector.detect(text)

        assert result.has_pii
        assert result.high_sensitivity
        assert "CREDIT_CARD" in result.entity_counts

    @pytest.mark.asyncio
    async def test_detect_multiple_pii(self, pii_detector, sample_pii_text):
        """Test detecting multiple PII types in text."""
        result = await pii_detector.detect(sample_pii_text)

        assert result.has_pii
        assert len(result.entities) > 1
        assert len(result.entity_counts) > 1

    @pytest.mark.asyncio
    async def test_detect_no_pii(self, pii_detector):
        """Test text with no PII."""
        text = "The weather is nice today. I like programming."
        result = await pii_detector.detect(text)

        assert not result.has_pii
        assert len(result.entities) == 0
        assert not result.high_sensitivity

    @pytest.mark.asyncio
    async def test_detect_confidence_scores(self, pii_detector):
        """Test that confidence scores are returned."""
        text = "Email john.doe@example.com for details."
        result = await pii_detector.detect(text)

        assert result.has_pii
        for entity in result.entities:
            assert 0.0 <= entity.score <= 1.0

    @pytest.mark.asyncio
    async def test_detect_entity_positions(self, pii_detector):
        """Test that entity positions are correct."""
        text = "Email test@example.com for info."
        result = await pii_detector.detect(text)

        assert result.has_pii
        for entity in result.entities:
            if entity.entity_type == PIIType.EMAIL:
                assert entity.start >= 0
                assert entity.end > entity.start
                assert text[entity.start:entity.end] == entity.text

    @pytest.mark.asyncio
    async def test_redact_pii(self, pii_detector):
        """Test redacting PII from text."""
        text = "Contact john.doe@example.com or call 555-123-4567"
        redacted = await pii_detector.redact(text)

        assert "john.doe@example.com" not in redacted
        assert "[EMAIL_ADDRESS]" in redacted

    @pytest.mark.asyncio
    async def test_redact_no_pii(self, pii_detector):
        """Test redacting text with no PII returns original."""
        text = "The weather is nice today."
        redacted = await pii_detector.redact(text)

        assert redacted == text

    @pytest.mark.asyncio
    async def test_custom_config(self):
        """Test PIIDetector with custom configuration."""
        config = PIIDetectorConfig(
            score_threshold=0.9,
            entities_to_detect=["EMAIL_ADDRESS"],
        )
        detector = PIIDetector(config)

        text = "Email john.doe@example.com or call John at 555-123-4567"
        result = await detector.detect(text)

        # Should only detect email due to config
        assert result.has_pii
        assert all(e.entity_type == PIIType.EMAIL for e in result.entities)


class TestPIIAnonymizer:
    """Test cases for PIIAnonymizer."""

    @pytest.mark.asyncio
    async def test_anonymize_replace_strategy(self, pii_detector):
        """Test anonymization with replace strategy."""
        text = "Contact john.doe@example.com for details."
        result = await pii_detector.detect(text)

        anonymizer = PIIAnonymizer()
        anonymized = await anonymizer.anonymize(text, result.entities, strategy="replace")

        assert "john.doe@example.com" not in anonymized
        assert "[REDACTED]" in anonymized

    @pytest.mark.asyncio
    async def test_anonymize_hash_strategy(self, pii_detector):
        """Test anonymization with hash strategy."""
        text = "Contact john.doe@example.com for details."
        result = await pii_detector.detect(text)

        anonymizer = PIIAnonymizer()
        anonymized = await anonymizer.anonymize(text, result.entities, strategy="hash")

        assert "john.doe@example.com" not in anonymized
        # Hash produces a hex string
        assert anonymized != text

    @pytest.mark.asyncio
    async def test_anonymize_mask_strategy(self, pii_detector):
        """Test anonymization with mask strategy."""
        text = "Contact john.doe@example.com for details."
        result = await pii_detector.detect(text)

        anonymizer = PIIAnonymizer()
        anonymized = await anonymizer.anonymize(text, result.entities, strategy="mask")

        assert "john.doe@example.com" not in anonymized
        assert "*" in anonymized  # Masking uses asterisks

    @pytest.mark.asyncio
    async def test_anonymize_empty_entities(self, pii_detector):
        """Test anonymization with no entities returns original."""
        text = "The weather is nice today."
        result = await pii_detector.detect(text)

        anonymizer = PIIAnonymizer()
        anonymized = await anonymizer.anonymize(text, result.entities)

        assert anonymized == text
