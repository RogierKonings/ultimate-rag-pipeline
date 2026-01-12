"""Parser registry for automatic parser selection by MIME type."""

import logging

from .base import BaseParser, ParsedDocument

logger = logging.getLogger(__name__)


class ParserRegistry:
    """Registry for document parsers.

    Maps MIME types to parser instances for automatic parser selection.
    """

    def __init__(self):
        """Initialize empty parser registry."""
        self._parsers: dict[str, BaseParser] = {}

    def register(self, parser: BaseParser) -> None:
        """Register a parser for its supported MIME types.

        Args:
            parser: Parser instance to register.
        """
        for mime_type in parser.supported_mime_types:
            logger.debug(f"Registering parser {type(parser).__name__} for {mime_type}")
            self._parsers[mime_type] = parser

    def unregister(self, mime_type: str) -> None:
        """Unregister a parser for a MIME type.

        Args:
            mime_type: MIME type to unregister.
        """
        if mime_type in self._parsers:
            del self._parsers[mime_type]

    def get_parser(self, mime_type: str) -> BaseParser | None:
        """Get parser for a MIME type.

        Args:
            mime_type: MIME type to look up.

        Returns:
            Parser instance or None if not found.
        """
        return self._parsers.get(mime_type)

    def has_parser(self, mime_type: str) -> bool:
        """Check if a parser is registered for a MIME type.

        Args:
            mime_type: MIME type to check.

        Returns:
            True if a parser is registered.
        """
        return mime_type in self._parsers

    def list_supported_types(self) -> list[str]:
        """List all supported MIME types.

        Returns:
            List of registered MIME types.
        """
        return list(self._parsers.keys())

    async def parse(
        self, content: bytes, mime_type: str, metadata: dict | None = None,
    ) -> ParsedDocument:
        """Parse document content using the appropriate parser.

        Args:
            content: Raw document bytes.
            mime_type: MIME type of the document.
            metadata: Optional metadata to include.

        Returns:
            ParsedDocument with extracted content.

        Raises:
            ValueError: If no parser is registered for the MIME type.
        """
        parser = self.get_parser(mime_type)
        if not parser:
            raise ValueError(f"No parser registered for MIME type: {mime_type}")

        logger.debug(f"Parsing {mime_type} with {type(parser).__name__}")
        return await parser.parse(content, metadata)


def create_default_registry() -> ParserRegistry:
    """Create a registry with all default parsers registered.

    Returns:
        ParserRegistry with PDF, DOCX, HTML, JSON, Markdown, and Text parsers.
    """
    from .docx import DocxParser
    from .html import HTMLParser
    from .json_parser import JSONParser
    from .markdown import MarkdownParser
    from .pdf import PDFParser
    from .text import TextParser

    registry = ParserRegistry()
    registry.register(PDFParser())
    registry.register(DocxParser())
    registry.register(HTMLParser())
    registry.register(JSONParser())
    registry.register(MarkdownParser())
    registry.register(TextParser())

    return registry
