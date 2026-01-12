"""Base classes and models for document parsers."""

from abc import ABC, abstractmethod
from enum import Enum

from pydantic import BaseModel, Field


class ContentType(str, Enum):
    """Types of content blocks that can be extracted from documents."""

    TEXT = "text"
    TABLE = "table"
    IMAGE = "image"
    CODE = "code"


class ContentBlock(BaseModel):
    """A block of content extracted from a document."""

    content_type: ContentType
    content: str
    page_number: int | None = None
    position: int | None = None  # Position in document
    metadata: dict = Field(default_factory=dict)


class TableContent(BaseModel):
    """Represents an extracted table from a document."""

    headers: list[str]
    rows: list[list[str]]
    caption: str | None = None


class ParsedDocument(BaseModel):
    """Result of parsing a document."""

    text: str  # Full extracted text
    blocks: list[ContentBlock]  # Structured content blocks
    tables: list[TableContent]  # Extracted tables
    title: str | None = None
    author: str | None = None
    created_date: str | None = None
    modified_date: str | None = None
    page_count: int | None = None
    language: str | None = None
    metadata: dict = Field(default_factory=dict)


class BaseParser(ABC):
    """Abstract base class for document parsers."""

    @property
    @abstractmethod
    def supported_mime_types(self) -> list[str]:
        """Return list of MIME types this parser handles."""

    @abstractmethod
    async def parse(
        self,
        content: bytes,
        metadata: dict | None = None,
    ) -> ParsedDocument:
        """Parse document content and return structured output.

        Args:
            content: Raw document bytes.
            metadata: Optional metadata to include in the result.

        Returns:
            ParsedDocument with extracted text, blocks, and tables.
        """

    def can_parse(self, mime_type: str) -> bool:
        """Check if this parser can handle the given MIME type.

        Args:
            mime_type: The MIME type to check.

        Returns:
            True if this parser supports the MIME type.
        """
        return mime_type in self.supported_mime_types
