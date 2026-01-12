"""Tests for document parsers."""

import pytest

from ..base import ContentType, ParsedDocument
from ..docx import DocxParser
from ..html import HTMLParser, HTMLParserConfig
from ..markdown import MarkdownParser
from ..pdf import PDFParser, PDFParserConfig
from ..registry import ParserRegistry, create_default_registry
from ..text import TextParser


class TestTextParser:
    """Tests for TextParser."""

    @pytest.fixture
    def parser(self) -> TextParser:
        return TextParser()

    @pytest.mark.asyncio
    async def test_parse_simple_text(self, parser: TextParser, sample_text: bytes):
        """Test parsing simple text content."""
        result = await parser.parse(sample_text)

        assert isinstance(result, ParsedDocument)
        assert "Sample Plain Text Document" in result.text
        assert len(result.blocks) == 1
        assert result.blocks[0].content_type == ContentType.TEXT
        assert result.tables == []

    @pytest.mark.asyncio
    async def test_parse_utf8_text(self, parser: TextParser):
        """Test parsing UTF-8 encoded text."""
        content = "Hello, 世界! Привет мир!".encode()
        result = await parser.parse(content)

        assert "Hello" in result.text
        assert "世界" in result.text
        assert "Привет" in result.text

    @pytest.mark.asyncio
    async def test_parse_with_metadata(self, parser: TextParser):
        """Test parsing with custom metadata."""
        content = b"Test content"
        metadata = {"source": "test", "custom_field": "value"}

        result = await parser.parse(content, metadata)

        assert result.metadata["source"] == "test"
        assert result.metadata["custom_field"] == "value"
        assert "detected_encoding" in result.metadata

    @pytest.mark.asyncio
    async def test_language_detection_english(self, parser: TextParser):
        """Test language detection for English text."""
        content = b"The quick brown fox jumps over the lazy dog."
        result = await parser.parse(content)

        assert result.language == "en"

    def test_supported_mime_types(self, parser: TextParser):
        """Test supported MIME types."""
        assert "text/plain" in parser.supported_mime_types

    def test_can_parse(self, parser: TextParser):
        """Test can_parse method."""
        assert parser.can_parse("text/plain")
        assert not parser.can_parse("application/pdf")


class TestHTMLParser:
    """Tests for HTMLParser."""

    @pytest.fixture
    def parser(self) -> HTMLParser:
        return HTMLParser()

    @pytest.mark.asyncio
    async def test_parse_html(self, parser: HTMLParser, sample_html: bytes):
        """Test parsing HTML content."""
        result = await parser.parse(sample_html)

        assert isinstance(result, ParsedDocument)
        assert result.title == "Sample HTML Document"
        assert "Sample HTML Document" in result.text
        assert len(result.blocks) > 0

    @pytest.mark.asyncio
    async def test_removes_scripts(self, parser: HTMLParser, sample_html: bytes):
        """Test that scripts are removed."""
        result = await parser.parse(sample_html)

        assert "console.log" not in result.text
        assert "This should be removed" not in result.text

    @pytest.mark.asyncio
    async def test_removes_styles(self, parser: HTMLParser, sample_html: bytes):
        """Test that styles are removed."""
        result = await parser.parse(sample_html)

        assert "font-family" not in result.text

    @pytest.mark.asyncio
    async def test_extracts_tables(self, parser: HTMLParser, html_with_table: bytes):
        """Test table extraction from HTML."""
        result = await parser.parse(html_with_table)

        assert len(result.tables) == 1
        table = result.tables[0]
        assert table.headers == ["Product", "Price", "Quantity"]
        assert len(table.rows) == 2
        assert table.rows[0] == ["Apple", "1.00", "10"]

    @pytest.mark.asyncio
    async def test_extracts_links(self, parser: HTMLParser, sample_html: bytes):
        """Test link extraction from HTML."""
        result = await parser.parse(sample_html)

        assert "links" in result.metadata
        links = result.metadata["links"]
        assert len(links) > 0
        assert any(link["href"] == "https://example.com" for link in links)

    @pytest.mark.asyncio
    async def test_convert_to_markdown(self, html_with_table: bytes):
        """Test HTML to Markdown conversion."""
        parser = HTMLParser(HTMLParserConfig(convert_to_markdown=True))
        result = await parser.parse(html_with_table)

        # Should contain markdown-style content
        assert result.text is not None

    def test_supported_mime_types(self, parser: HTMLParser):
        """Test supported MIME types."""
        assert "text/html" in parser.supported_mime_types
        assert "application/xhtml+xml" in parser.supported_mime_types


class TestMarkdownParser:
    """Tests for MarkdownParser."""

    @pytest.fixture
    def parser(self) -> MarkdownParser:
        return MarkdownParser()

    @pytest.mark.asyncio
    async def test_parse_markdown(self, parser: MarkdownParser, sample_markdown: bytes):
        """Test parsing Markdown content."""
        result = await parser.parse(sample_markdown)

        assert isinstance(result, ParsedDocument)
        assert result.title == "Sample Markdown Document"
        assert "Sample Markdown Document" in result.text

    @pytest.mark.asyncio
    async def test_extracts_code_blocks(
        self,
        parser: MarkdownParser,
        sample_markdown: bytes,
    ):
        """Test code block extraction."""
        result = await parser.parse(sample_markdown)

        code_blocks = [b for b in result.blocks if b.content_type == ContentType.CODE]
        assert len(code_blocks) > 0
        assert any("hello_world" in b.content for b in code_blocks)

    @pytest.mark.asyncio
    async def test_extracts_tables(
        self,
        parser: MarkdownParser,
        markdown_with_table: bytes,
    ):
        """Test table extraction from Markdown."""
        result = await parser.parse(markdown_with_table)

        assert len(result.tables) == 1
        table = result.tables[0]
        assert "Product" in table.headers
        assert "Price" in table.headers
        assert len(table.rows) == 2

    @pytest.mark.asyncio
    async def test_preserves_original_text(
        self,
        parser: MarkdownParser,
        sample_markdown: bytes,
    ):
        """Test that original Markdown is preserved."""
        result = await parser.parse(sample_markdown)

        # Original markdown syntax should be in the text
        assert "# Sample Markdown Document" in result.text
        assert "```python" in result.text

    def test_supported_mime_types(self, parser: MarkdownParser):
        """Test supported MIME types."""
        assert "text/markdown" in parser.supported_mime_types
        assert "text/x-markdown" in parser.supported_mime_types

    @pytest.mark.asyncio
    async def test_frontmatter_extraction(self, parser: MarkdownParser):
        """Test YAML frontmatter is extracted from markdown."""
        content = b"""---
title: My Document
author: John Doe
date: "2024-01-15"
tags:
  - python
  - docs
description: A sample document for testing
---

# Introduction

This is the content.
"""
        result = await parser.parse(content)

        assert result.metadata.get("title") == "My Document"
        assert result.metadata.get("author") == "John Doe"
        assert result.metadata.get("date") == "2024-01-15"
        assert result.metadata.get("tags") == ["python", "docs"]
        assert result.metadata.get("description") == "A sample document for testing"
        # Title should come from frontmatter
        assert result.title == "My Document"
        # Frontmatter should be removed from text
        assert "---" not in result.text
        assert "title: My Document" not in result.text
        # Content should still be present
        assert "Introduction" in result.text
        assert "This is the content." in result.text

    @pytest.mark.asyncio
    async def test_frontmatter_title_takes_precedence(self, parser: MarkdownParser):
        """Test that frontmatter title takes precedence over H1."""
        content = b"""---
title: Frontmatter Title
---

# Header Title

Content here.
"""
        result = await parser.parse(content)

        assert result.title == "Frontmatter Title"
        assert result.metadata.get("title") == "Frontmatter Title"

    @pytest.mark.asyncio
    async def test_malformed_frontmatter(self, parser: MarkdownParser):
        """Test malformed YAML frontmatter is handled gracefully."""
        content = b"""---
title: [invalid yaml unclosed
---

# Content

Some text here.
"""
        result = await parser.parse(content)

        # Should parse successfully, just without frontmatter metadata
        assert "Content" in result.text
        # Title should be extracted from H1 instead
        assert result.title == "Content"
        # Malformed frontmatter means original text is preserved
        assert "---" in result.text

    @pytest.mark.asyncio
    async def test_no_frontmatter(self, parser: MarkdownParser):
        """Test parsing markdown without frontmatter."""
        content = b"""# Regular Document

This is a document without frontmatter.
"""
        result = await parser.parse(content)

        assert result.title == "Regular Document"
        assert "# Regular Document" in result.text
        assert result.metadata == {}

    @pytest.mark.asyncio
    async def test_frontmatter_with_custom_metadata(self, parser: MarkdownParser):
        """Test frontmatter merges with passed metadata."""
        content = b"""---
title: Document Title
custom_field: from_frontmatter
---

Content.
"""
        custom_metadata = {"source": "test", "custom_field": "from_param"}
        result = await parser.parse(content, custom_metadata)

        # Frontmatter should take precedence
        assert result.metadata.get("custom_field") == "from_frontmatter"
        # Original metadata should be preserved for non-conflicting keys
        assert result.metadata.get("source") == "test"
        assert result.metadata.get("title") == "Document Title"

    @pytest.mark.asyncio
    async def test_frontmatter_non_dict(self, parser: MarkdownParser):
        """Test frontmatter that parses to non-dict is handled."""
        content = b"""---
- item1
- item2
---

# Content
"""
        result = await parser.parse(content)

        # Non-dict frontmatter should be ignored
        assert result.metadata == {}
        assert "Content" in result.text

    @pytest.mark.asyncio
    async def test_unclosed_frontmatter(self, parser: MarkdownParser):
        """Test unclosed frontmatter delimiter is handled."""
        content = b"""---
title: Unclosed

# Content

Text without closing delimiter.
"""
        result = await parser.parse(content)

        # Without closing delimiter, treat as regular content
        assert "---" in result.text
        assert "title: Unclosed" in result.text


class TestPDFParser:
    """Tests for PDFParser."""

    @pytest.fixture
    def parser(self) -> PDFParser:
        return PDFParser()

    @pytest.mark.asyncio
    async def test_parse_simple_pdf(
        self,
        parser: PDFParser,
        simple_pdf_content: bytes,
    ):
        """Test parsing a simple PDF."""
        result = await parser.parse(simple_pdf_content)

        assert isinstance(result, ParsedDocument)
        assert result.page_count == 1
        # Note: Text extraction depends on PDF structure
        assert result.text is not None

    @pytest.mark.asyncio
    async def test_parse_with_metadata(
        self,
        parser: PDFParser,
        simple_pdf_content: bytes,
    ):
        """Test parsing PDF with custom metadata."""
        metadata = {"source": "test"}
        result = await parser.parse(simple_pdf_content, metadata)

        assert result.metadata["source"] == "test"

    @pytest.mark.asyncio
    async def test_config_max_pages(self, simple_pdf_content: bytes):
        """Test max_pages configuration."""
        config = PDFParserConfig(max_pages=1)
        parser = PDFParser(config)
        result = await parser.parse(simple_pdf_content)

        assert result is not None

    def test_supported_mime_types(self, parser: PDFParser):
        """Test supported MIME types."""
        assert "application/pdf" in parser.supported_mime_types

    def test_can_parse(self, parser: PDFParser):
        """Test can_parse method."""
        assert parser.can_parse("application/pdf")
        assert not parser.can_parse("text/plain")


class TestDocxParser:
    """Tests for DocxParser."""

    @pytest.fixture
    def parser(self) -> DocxParser:
        return DocxParser()

    def test_supported_mime_types(self, parser: DocxParser):
        """Test supported MIME types."""
        assert (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            in parser.supported_mime_types
        )

    @pytest.mark.asyncio
    async def test_parse_invalid_content(self, parser: DocxParser):
        """Test parsing invalid content raises error."""
        with pytest.raises(ValueError, match="Failed to parse Word document"):
            await parser.parse(b"not a valid docx file")


class TestParserRegistry:
    """Tests for ParserRegistry."""

    @pytest.fixture
    def registry(self) -> ParserRegistry:
        return create_default_registry()

    def test_create_default_registry(self, registry: ParserRegistry):
        """Test default registry has all parsers registered."""
        assert registry.has_parser("application/pdf")
        assert registry.has_parser("text/html")
        assert registry.has_parser("text/markdown")
        assert registry.has_parser("text/plain")
        assert registry.has_parser(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

    def test_get_parser(self, registry: ParserRegistry):
        """Test getting parser by MIME type."""
        parser = registry.get_parser("text/plain")
        assert isinstance(parser, TextParser)

        parser = registry.get_parser("text/html")
        assert isinstance(parser, HTMLParser)

    def test_get_parser_not_found(self, registry: ParserRegistry):
        """Test getting parser for unregistered MIME type."""
        parser = registry.get_parser("application/unknown")
        assert parser is None

    def test_list_supported_types(self, registry: ParserRegistry):
        """Test listing supported MIME types."""
        types = registry.list_supported_types()
        assert "text/plain" in types
        assert "text/html" in types
        assert "application/pdf" in types

    @pytest.mark.asyncio
    async def test_parse_delegates_to_correct_parser(
        self,
        registry: ParserRegistry,
        sample_text: bytes,
    ):
        """Test that parse delegates to correct parser."""
        result = await registry.parse(sample_text, "text/plain")
        assert isinstance(result, ParsedDocument)

    @pytest.mark.asyncio
    async def test_parse_unknown_type_raises(self, registry: ParserRegistry):
        """Test parsing unknown MIME type raises error."""
        with pytest.raises(ValueError, match="No parser registered"):
            await registry.parse(b"content", "application/unknown")

    def test_register_custom_parser(self):
        """Test registering a custom parser."""
        registry = ParserRegistry()
        parser = TextParser()
        registry.register(parser)

        assert registry.has_parser("text/plain")
        assert registry.get_parser("text/plain") is parser

    def test_unregister_parser(self, registry: ParserRegistry):
        """Test unregistering a parser."""
        assert registry.has_parser("text/plain")
        registry.unregister("text/plain")
        assert not registry.has_parser("text/plain")
