"""HTML document parser."""

import logging

from pydantic import BaseModel

from .base import BaseParser, ContentBlock, ContentType, ParsedDocument, TableContent

logger = logging.getLogger(__name__)


class HTMLParserConfig(BaseModel):
    """Configuration for HTML parser."""

    remove_scripts: bool = True
    remove_styles: bool = True
    remove_comments: bool = True
    extract_links: bool = True
    convert_to_markdown: bool = False


class HTMLParser(BaseParser):
    """Parser for HTML documents.

    Uses BeautifulSoup for HTML parsing with options for
    cleaning and content extraction.
    """

    def __init__(self, config: HTMLParserConfig | None = None):
        """Initialize HTML parser.

        Args:
            config: Parser configuration options.
        """
        self.config = config or HTMLParserConfig()

    @property
    def supported_mime_types(self) -> list[str]:
        """Return list of supported MIME types."""
        return ["text/html", "application/xhtml+xml"]

    async def parse(
        self,
        content: bytes,
        metadata: dict | None = None,
    ) -> ParsedDocument:
        """Parse HTML document.

        Args:
            content: Raw HTML bytes.
            metadata: Optional metadata to include.

        Returns:
            ParsedDocument with extracted content.

        Raises:
            ValueError: If HTML cannot be parsed.
        """
        from bs4 import BeautifulSoup, Comment

        metadata = metadata or {}

        try:
            # Decode content with fallback for encoding issues
            html = content.decode("utf-8", errors="replace")
            soup = BeautifulSoup(html, "html.parser")
        except Exception as e:
            raise ValueError(f"Failed to parse HTML: {e}") from e

        # Remove unwanted elements
        if self.config.remove_scripts:
            for script in soup.find_all("script"):
                script.decompose()

        if self.config.remove_styles:
            for style in soup.find_all("style"):
                style.decompose()

        if self.config.remove_comments:
            for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
                comment.extract()

        # Extract title
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else None

        # Extract structured content blocks
        blocks: list[ContentBlock] = []
        position = 0

        # Process semantic elements
        semantic_tags = ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote"]
        for element in soup.find_all(semantic_tags):
            text = element.get_text(strip=True)
            if text:
                blocks.append(
                    ContentBlock(
                        content_type=ContentType.TEXT,
                        content=text,
                        position=position,
                        metadata={"tag": element.name},
                    ),
                )
                position += 1

        # Extract code blocks
        for code in soup.find_all(["pre", "code"]):
            text = code.get_text(strip=True)
            if text:
                # Check if this is a standalone code block (pre) or inline
                if code.name == "pre":
                    blocks.append(
                        ContentBlock(
                            content_type=ContentType.CODE,
                            content=text,
                            position=position,
                            metadata={"tag": "pre"},
                        ),
                    )
                    position += 1

        # Extract tables
        tables: list[TableContent] = []
        for table_element in soup.find_all("table"):
            try:
                table = self._extract_html_table(table_element)
                if table:
                    tables.append(table)
                    blocks.append(
                        ContentBlock(
                            content_type=ContentType.TABLE,
                            content=self._table_to_text(table),
                            position=position,
                        ),
                    )
                    position += 1
            except Exception as e:
                logger.warning(f"Failed to extract table: {e}")

        # Get full text content
        if self.config.convert_to_markdown:
            try:
                from markdownify import markdownify

                full_text = markdownify(str(soup), heading_style="ATX")
            except ImportError:
                logger.warning("markdownify not available, using plain text")
                full_text = soup.get_text(separator="\n", strip=True)
        else:
            full_text = soup.get_text(separator="\n", strip=True)

        # Extract links if enabled
        links = []
        if self.config.extract_links:
            for link in soup.find_all("a", href=True):
                link_text = link.get_text(strip=True)
                href = link["href"]
                if href and not href.startswith("#"):
                    links.append({"text": link_text, "href": href})

        result_metadata = {**metadata}
        if links:
            result_metadata["links"] = links

        return ParsedDocument(
            text=full_text,
            blocks=blocks,
            tables=tables,
            title=title,
            metadata=result_metadata,
        )

    def _extract_html_table(self, table_element) -> TableContent | None:
        """Extract TableContent from an HTML table element.

        Args:
            table_element: BeautifulSoup table element.

        Returns:
            TableContent or None if extraction fails.
        """
        headers: list[str] = []
        rows: list[list[str]] = []
        caption = None

        # Get caption if present
        caption_element = table_element.find("caption")
        if caption_element:
            caption = caption_element.get_text(strip=True)

        # Try to get headers from thead
        thead = table_element.find("thead")
        if thead:
            header_row = thead.find("tr")
            if header_row:
                for cell in header_row.find_all(["th", "td"]):
                    headers.append(cell.get_text(strip=True))

        # Get body rows
        tbody = table_element.find("tbody")
        body = tbody if tbody else table_element

        for tr in body.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if cells:
                # If no headers yet and this looks like a header row
                if not headers and all(c.name == "th" for c in cells):
                    headers = [c.get_text(strip=True) for c in cells]
                else:
                    row_data = [c.get_text(strip=True) for c in cells]
                    rows.append(row_data)

        # If still no headers, use first row
        if not headers and rows:
            headers = rows.pop(0)

        if not headers:
            return None

        return TableContent(headers=headers, rows=rows, caption=caption)

    def _table_to_text(self, table: TableContent) -> str:
        """Convert TableContent to plain text.

        Args:
            table: TableContent to convert.

        Returns:
            Plain text representation of the table.
        """
        lines = []

        if table.caption:
            lines.append(table.caption)

        # Headers
        lines.append(" | ".join(table.headers))
        lines.append("-" * len(lines[-1]))

        # Rows
        for row in table.rows:
            lines.append(" | ".join(row))

        return "\n".join(lines)
