"""PDF document parser using PyMuPDF with Unstructured fallback."""

import asyncio
import io
import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    import fitz

from pydantic import BaseModel

from .base import BaseParser, ContentBlock, ContentType, ParsedDocument, TableContent

logger = logging.getLogger(__name__)


class PDFParserConfig(BaseModel):
    """Configuration for PDF parser."""

    extract_images: bool = False
    extract_tables: bool = True
    ocr_enabled: bool = True
    ocr_language: str = "eng"
    use_unstructured_fallback: bool = True
    max_pages: Optional[int] = None


class PDFParser(BaseParser):
    """Parser for PDF documents.

    Uses PyMuPDF (fitz) as the primary parser with optional fallback
    to Unstructured for complex layouts.
    """

    def __init__(self, config: Optional[PDFParserConfig] = None):
        """Initialize PDF parser.

        Args:
            config: Parser configuration options.
        """
        self.config = config or PDFParserConfig()

    @property
    def supported_mime_types(self) -> list[str]:
        """Return list of supported MIME types."""
        return ["application/pdf"]

    async def parse(
        self, content: bytes, metadata: Optional[dict] = None
    ) -> ParsedDocument:
        """Parse PDF document.

        Attempts to parse using PyMuPDF first, falls back to Unstructured
        if configured and PyMuPDF fails.

        Args:
            content: Raw PDF bytes.
            metadata: Optional metadata to include.

        Returns:
            ParsedDocument with extracted content.

        Raises:
            ValueError: If PDF cannot be parsed.
        """
        metadata = metadata or {}

        try:
            return await self._parse_with_pymupdf(content, metadata)
        except Exception as e:
            logger.warning(f"PyMuPDF parsing failed: {e}")
            if self.config.use_unstructured_fallback:
                logger.info("Attempting fallback to Unstructured")
                return await self._parse_with_unstructured(content, metadata)
            raise ValueError(f"Failed to parse PDF: {e}") from e

    async def _parse_with_pymupdf(
        self, content: bytes, metadata: dict
    ) -> ParsedDocument:
        """Parse PDF using PyMuPDF (fitz).

        Args:
            content: Raw PDF bytes.
            metadata: Metadata to include.

        Returns:
            ParsedDocument with extracted content.
        """
        import fitz  # PyMuPDF

        doc = fitz.open(stream=content, filetype="pdf")

        try:
            blocks: list[ContentBlock] = []
            tables: list[TableContent] = []
            full_text: list[str] = []
            ocr_applied = False

            max_pages = self.config.max_pages or len(doc)
            pages_to_process = min(max_pages, len(doc))

            for page_num in range(pages_to_process):
                page = doc[page_num]

                # Extract text
                text = page.get_text("text")

                # If no text and OCR enabled, try OCR
                if not text.strip() and self.config.ocr_enabled:
                    logger.info(f"Page {page_num + 1} has no text, attempting OCR")
                    text = await self._ocr_page(page)
                    if text:
                        ocr_applied = True

                if text.strip():
                    full_text.append(text)
                    blocks.append(
                        ContentBlock(
                            content_type=ContentType.TEXT,
                            content=text,
                            page_number=page_num + 1,
                            position=len(blocks),
                        )
                    )

                # Extract tables if enabled
                if self.config.extract_tables:
                    try:
                        page_tables = page.find_tables()
                        for table in page_tables:
                            converted = self._convert_pymupdf_table(table)
                            if converted:
                                tables.append(converted)
                                # Also add table as a content block
                                blocks.append(
                                    ContentBlock(
                                        content_type=ContentType.TABLE,
                                        content=self._table_to_text(converted),
                                        page_number=page_num + 1,
                                        position=len(blocks),
                                    )
                                )
                    except Exception as e:
                        logger.warning(
                            f"Table extraction failed on page {page_num + 1}: {e}"
                        )

            # Extract document metadata
            pdf_metadata = doc.metadata or {}

            # Include OCR status in metadata
            result_metadata = metadata.copy()
            if ocr_applied:
                result_metadata["ocr_applied"] = True

            return ParsedDocument(
                text="\n\n".join(full_text),
                blocks=blocks,
                tables=tables,
                title=pdf_metadata.get("title") or None,
                author=pdf_metadata.get("author") or None,
                created_date=pdf_metadata.get("creationDate") or None,
                modified_date=pdf_metadata.get("modDate") or None,
                page_count=len(doc),
                metadata=result_metadata,
            )
        finally:
            doc.close()

    async def _parse_with_unstructured(
        self, content: bytes, metadata: dict
    ) -> ParsedDocument:
        """Parse PDF using Unstructured library.

        Args:
            content: Raw PDF bytes.
            metadata: Metadata to include.

        Returns:
            ParsedDocument with extracted content.
        """
        from unstructured.partition.pdf import partition_pdf

        elements = partition_pdf(file=io.BytesIO(content))

        blocks: list[ContentBlock] = []
        tables: list[TableContent] = []
        full_text: list[str] = []

        for i, element in enumerate(elements):
            element_type = type(element).__name__
            text = str(element)

            if text.strip():
                full_text.append(text)

                # Determine content type
                if element_type == "Table":
                    content_type = ContentType.TABLE
                    # Try to extract table structure
                    if hasattr(element, "metadata") and hasattr(
                        element.metadata, "text_as_html"
                    ):
                        table = self._parse_html_table(element.metadata.text_as_html)
                        if table:
                            tables.append(table)
                else:
                    content_type = ContentType.TEXT

                # Get page number if available
                page_num = None
                if hasattr(element, "metadata") and hasattr(
                    element.metadata, "page_number"
                ):
                    page_num = element.metadata.page_number

                blocks.append(
                    ContentBlock(
                        content_type=content_type,
                        content=text,
                        page_number=page_num,
                        position=i,
                        metadata={"element_type": element_type},
                    )
                )

        return ParsedDocument(
            text="\n\n".join(full_text),
            blocks=blocks,
            tables=tables,
            metadata=metadata,
        )

    async def _ocr_page(self, page: "fitz.Page") -> str:
        """Extract text from page using OCR.

        Uses Tesseract OCR via pytesseract to extract text from
        scanned PDF pages that have no extractable text.

        Args:
            page: PyMuPDF page object.

        Returns:
            OCR-extracted text, or empty string if OCR fails.
        """
        import fitz  # PyMuPDF

        try:
            import pytesseract
            from PIL import Image
        except ImportError as e:
            logger.warning(f"OCR dependencies not available: {e}")
            return ""

        try:
            # Render page to image at 2x zoom for better OCR quality
            mat = fitz.Matrix(2.0, 2.0)
            pix = page.get_pixmap(matrix=mat)

            # Convert to PIL Image
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            # Run OCR with configured language in a thread pool to avoid blocking
            # the event loop (pytesseract.image_to_string is CPU-bound)
            text = await asyncio.to_thread(
                pytesseract.image_to_string,
                img,
                lang=self.config.ocr_language
            )
            return text.strip()
        except Exception as e:
            logger.warning(f"OCR failed for page: {e}")
            return ""

    def _convert_pymupdf_table(self, table) -> Optional[TableContent]:
        """Convert PyMuPDF table to TableContent.

        Args:
            table: PyMuPDF table object.

        Returns:
            TableContent or None if conversion fails.
        """
        try:
            # Extract table data
            data = table.extract()
            if not data or len(data) < 1:
                return None

            # First row as headers
            headers = [str(cell) if cell else "" for cell in data[0]]

            # Remaining rows as data
            rows = []
            for row in data[1:]:
                rows.append([str(cell) if cell else "" for cell in row])

            return TableContent(headers=headers, rows=rows)
        except Exception as e:
            logger.warning(f"Failed to convert table: {e}")
            return None

    def _table_to_text(self, table: TableContent) -> str:
        """Convert TableContent to plain text representation.

        Args:
            table: TableContent to convert.

        Returns:
            Text representation of the table.
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

    def _parse_html_table(self, html: str) -> Optional[TableContent]:
        """Parse HTML table string into TableContent.

        Args:
            html: HTML table string.

        Returns:
            TableContent or None if parsing fails.
        """
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            table = soup.find("table")
            if not table:
                return None

            headers = []
            rows = []

            # Extract headers
            header_row = table.find("thead")
            if header_row:
                for th in header_row.find_all(["th", "td"]):
                    headers.append(th.get_text(strip=True))

            # Extract rows
            tbody = table.find("tbody") or table
            for tr in tbody.find_all("tr"):
                cells = tr.find_all(["td", "th"])
                if cells:
                    # If no headers yet, use first row as headers
                    if not headers:
                        headers = [c.get_text(strip=True) for c in cells]
                    else:
                        rows.append([c.get_text(strip=True) for c in cells])

            if headers:
                return TableContent(headers=headers, rows=rows)
            return None
        except Exception as e:
            logger.warning(f"Failed to parse HTML table: {e}")
            return None
