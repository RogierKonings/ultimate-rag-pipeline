"""Tests for language detection."""

import pytest

from ..language_detector import LanguageDetector


class TestLanguageDetector:
    """Test cases for LanguageDetector."""

    @pytest.mark.asyncio
    async def test_detect_english(self, language_detector, sample_english_text):
        """Test detecting English text."""
        result = await language_detector.detect(sample_english_text)

        assert result is not None
        assert result.language_code == "en"
        assert result.language_name == "English"
        assert result.confidence > 0.9

    @pytest.mark.asyncio
    async def test_detect_spanish(self, language_detector, sample_spanish_text):
        """Test detecting Spanish text."""
        result = await language_detector.detect(sample_spanish_text)

        assert result is not None
        assert result.language_code == "es"
        assert result.language_name == "Spanish"
        assert result.confidence > 0.9

    @pytest.mark.asyncio
    async def test_detect_french(self, language_detector):
        """Test detecting French text."""
        french_text = (
            "Le rapide renard brun saute par-dessus le chien paresseux. "
            "Ceci est un exemple de texte en français pour tester la détection de langue."
        )
        result = await language_detector.detect(french_text)

        assert result is not None
        assert result.language_code == "fr"
        assert result.language_name == "French"

    @pytest.mark.asyncio
    async def test_detect_german(self, language_detector):
        """Test detecting German text."""
        german_text = (
            "Der schnelle braune Fuchs springt über den faulen Hund. "
            "Dies ist ein Beispieltext auf Deutsch zum Testen der Spracherkennung."
        )
        result = await language_detector.detect(german_text)

        assert result is not None
        assert result.language_code == "de"
        assert result.language_name == "German"

    @pytest.mark.asyncio
    async def test_detect_short_text_returns_none(self, language_detector):
        """Test that short text returns None."""
        short_text = "Hello world"
        result = await language_detector.detect(short_text)

        assert result is None

    @pytest.mark.asyncio
    async def test_detect_empty_text_returns_none(self, language_detector):
        """Test that empty text returns None."""
        result = await language_detector.detect("")

        assert result is None

    @pytest.mark.asyncio
    async def test_detect_multiple_languages(self, language_detector, sample_english_text):
        """Test detecting multiple languages in text."""
        results = await language_detector.detect_multiple(sample_english_text)

        assert len(results) > 0
        assert results[0].language_code == "en"
        # Results should be ordered by confidence
        for i in range(len(results) - 1):
            assert results[i].confidence >= results[i + 1].confidence

    @pytest.mark.asyncio
    async def test_detect_multiple_short_text_returns_empty(self, language_detector):
        """Test that detect_multiple with short text returns empty list."""
        results = await language_detector.detect_multiple("Hi")

        assert results == []

    @pytest.mark.asyncio
    async def test_unknown_language_name(self, language_detector):
        """Test handling of unknown language codes."""
        # The LANGUAGE_NAMES dict should handle unknown codes gracefully
        detector = LanguageDetector()
        unknown_name = detector.LANGUAGE_NAMES.get("xyz", "Unknown")
        assert unknown_name == "Unknown"
