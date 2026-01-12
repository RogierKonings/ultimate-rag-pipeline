"""Language detection using langdetect."""


from langdetect import detect_langs
from langdetect.lang_detect_exception import LangDetectException

from .models import LanguageResult


class LanguageDetector:
    """
    Detect document language using langdetect.

    The langdetect library uses a naive Bayesian filter trained on
    Wikipedia data to detect the language of text.
    """

    # ISO 639-1 code to language name mapping
    LANGUAGE_NAMES: dict[str, str] = {
        "en": "English",
        "es": "Spanish",
        "fr": "French",
        "de": "German",
        "it": "Italian",
        "pt": "Portuguese",
        "nl": "Dutch",
        "ru": "Russian",
        "zh-cn": "Chinese (Simplified)",
        "zh-tw": "Chinese (Traditional)",
        "ja": "Japanese",
        "ko": "Korean",
        "ar": "Arabic",
        "hi": "Hindi",
        "bn": "Bengali",
        "pa": "Punjabi",
        "te": "Telugu",
        "mr": "Marathi",
        "ta": "Tamil",
        "ur": "Urdu",
        "gu": "Gujarati",
        "kn": "Kannada",
        "ml": "Malayalam",
        "th": "Thai",
        "vi": "Vietnamese",
        "tr": "Turkish",
        "pl": "Polish",
        "uk": "Ukrainian",
        "ro": "Romanian",
        "el": "Greek",
        "cs": "Czech",
        "sv": "Swedish",
        "hu": "Hungarian",
        "fi": "Finnish",
        "no": "Norwegian",
        "da": "Danish",
        "he": "Hebrew",
        "id": "Indonesian",
        "ms": "Malay",
        "fa": "Persian",
    }

    # Minimum text length for reliable detection
    MIN_TEXT_LENGTH = 50

    async def detect(self, text: str) -> LanguageResult | None:
        """
        Detect the primary language of the text.

        Args:
            text: Text to analyze (should be at least 50 characters)

        Returns:
            LanguageResult with code, name, and confidence, or None if
            text is too short or detection fails
        """
        if len(text) < self.MIN_TEXT_LENGTH:
            return None

        try:
            # Get top language with probabilities
            results = detect_langs(text)
            if not results:
                return None

            top = results[0]
            return LanguageResult(
                language_code=top.lang,
                language_name=self.LANGUAGE_NAMES.get(top.lang, "Unknown"),
                confidence=top.prob,
            )
        except LangDetectException:
            return None

    async def detect_multiple(self, text: str) -> list[LanguageResult]:
        """
        Detect all languages in text with probabilities.

        Useful for multilingual documents where content may be in
        multiple languages.

        Args:
            text: Text to analyze

        Returns:
            List of LanguageResult objects ordered by confidence
        """
        if len(text) < self.MIN_TEXT_LENGTH:
            return []

        try:
            results = detect_langs(text)
            return [
                LanguageResult(
                    language_code=r.lang,
                    language_name=self.LANGUAGE_NAMES.get(r.lang, "Unknown"),
                    confidence=r.prob,
                )
                for r in results
            ]
        except LangDetectException:
            return []
