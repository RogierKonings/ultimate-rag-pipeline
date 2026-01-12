"""Plain text parser with encoding detection."""

import logging
import re

from .base import BaseParser, ContentBlock, ContentType, ParsedDocument

logger = logging.getLogger(__name__)


class TextParser(BaseParser):
    """Parser for plain text documents.

    Auto-detects encoding and handles various line endings.
    """

    @property
    def supported_mime_types(self) -> list[str]:
        """Return list of supported MIME types."""
        return ["text/plain"]

    async def parse(
        self, content: bytes, metadata: dict | None = None,
    ) -> ParsedDocument:
        """Parse plain text document.

        Args:
            content: Raw text bytes.
            metadata: Optional metadata to include.

        Returns:
            ParsedDocument with extracted content.
        """
        import chardet

        metadata = metadata or {}

        # Detect encoding
        detected = chardet.detect(content)
        encoding = detected.get("encoding") or "utf-8"
        confidence = detected.get("confidence", 0)

        logger.debug(f"Detected encoding: {encoding} (confidence: {confidence})")

        # Decode content
        try:
            text = content.decode(encoding, errors="replace")
        except (UnicodeDecodeError, LookupError):
            # Fallback to utf-8 with replacement
            logger.warning(f"Failed to decode with {encoding}, falling back to utf-8")
            text = content.decode("utf-8", errors="replace")

        # Normalize line endings (CRLF, CR -> LF)
        text = text.replace("\r\n", "\n").replace("\r", "\n")

        # Try to detect language (simple heuristic)
        language = self._detect_language(text)

        # Build result metadata
        result_metadata = {
            **metadata,
            "detected_encoding": encoding,
            "encoding_confidence": confidence,
        }

        return ParsedDocument(
            text=text,
            blocks=[
                ContentBlock(
                    content_type=ContentType.TEXT,
                    content=text,
                    position=0,
                ),
            ],
            tables=[],
            language=language,
            metadata=result_metadata,
        )

    def _detect_language(self, text: str) -> str | None:
        """Simple language detection heuristic.

        Args:
            text: Text to analyze.

        Returns:
            ISO language code or None.
        """
        # This is a simple heuristic - for production, consider using
        # langdetect or similar library
        text_lower = text.lower()

        # Check for common English words
        english_words = {"the", "and", "is", "in", "to", "of", "a", "for", "that"}
        words = set(re.findall(r"\b\w+\b", text_lower))

        if len(words.intersection(english_words)) >= 3:
            return "en"

        return None
