"""Tests for PDF OCR functionality."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ..pdf import PDFParser, PDFParserConfig


class TestPDFParserOCR:
    """Tests for PDF OCR functionality."""

    @pytest.fixture
    def ocr_enabled_parser(self) -> PDFParser:
        """Return a parser with OCR enabled."""
        return PDFParser(PDFParserConfig(ocr_enabled=True))

    @pytest.fixture
    def ocr_disabled_parser(self) -> PDFParser:
        """Return a parser with OCR disabled."""
        return PDFParser(PDFParserConfig(ocr_enabled=False))

    @pytest.fixture
    def minimal_pdf_no_text(self) -> bytes:
        """Return a minimal PDF with no extractable text (simulates scanned doc).

        This is a minimal valid PDF structure that contains an image placeholder
        but no text content. In a real scenario, this would be a scanned document.
        """
        # Minimal PDF with an empty page (no text objects)
        return b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << >> >>
endobj
xref
0 4
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
trailer
<< /Size 4 /Root 1 0 R >>
startxref
206
%%EOF"""

    @pytest.mark.asyncio
    async def test_ocr_disabled_returns_empty_for_no_text_pdf(
        self,
        ocr_disabled_parser: PDFParser,
        minimal_pdf_no_text: bytes,
    ):
        """Test that OCR-disabled parser returns empty text for scanned PDF."""
        result = await ocr_disabled_parser.parse(minimal_pdf_no_text)

        # Should have minimal/no text since OCR is disabled
        assert len(result.text.strip()) == 0
        assert result.metadata.get("ocr_applied") is None

    @pytest.mark.asyncio
    async def test_ocr_enabled_attempts_ocr_for_no_text_page(
        self,
        ocr_enabled_parser: PDFParser,
        minimal_pdf_no_text: bytes,
    ):
        """Test that OCR-enabled parser attempts OCR for pages with no text."""
        # Mock the _ocr_page method to verify it's called
        with patch.object(
            ocr_enabled_parser,
            "_ocr_page",
            new_callable=AsyncMock,
        ) as mock_ocr:
            mock_ocr.return_value = "OCR extracted text"

            result = await ocr_enabled_parser.parse(minimal_pdf_no_text)

            # OCR should have been called
            mock_ocr.assert_called_once()
            # Result should contain OCR text
            assert "OCR extracted text" in result.text
            assert result.metadata.get("ocr_applied") is True

    @pytest.mark.asyncio
    async def test_ocr_not_called_when_text_exists(
        self,
        ocr_enabled_parser: PDFParser,
        simple_pdf_content: bytes,
    ):
        """Test that OCR is not called when page already has text."""
        # Mock the _ocr_page method to verify it's NOT called
        with patch.object(
            ocr_enabled_parser,
            "_ocr_page",
            new_callable=AsyncMock,
        ) as mock_ocr:
            mock_ocr.return_value = "OCR text"

            result = await ocr_enabled_parser.parse(simple_pdf_content)

            # OCR should NOT have been called since the PDF has text
            mock_ocr.assert_not_called()
            # No OCR applied flag
            assert result.metadata.get("ocr_applied") is None

    @pytest.mark.asyncio
    async def test_ocr_page_method_uses_configured_language(self):
        """Test that _ocr_page uses the configured OCR language."""
        parser = PDFParser(PDFParserConfig(ocr_enabled=True, ocr_language="deu"))

        with patch("pytesseract.image_to_string") as mock_tesseract, patch("fitz.Matrix"):
            # Create a mock page object
            mock_page = MagicMock()
            mock_pixmap = MagicMock()
            mock_pixmap.width = 100
            mock_pixmap.height = 100
            mock_pixmap.samples = b"\x00" * (100 * 100 * 3)  # RGB data
            mock_page.get_pixmap.return_value = mock_pixmap

            mock_tesseract.return_value = "German text"

            await parser._ocr_page(mock_page)

            # Verify tesseract was called with German language
            mock_tesseract.assert_called_once()
            call_kwargs = mock_tesseract.call_args[1]
            assert call_kwargs["lang"] == "deu"

    @pytest.mark.asyncio
    async def test_ocr_failure_returns_empty_string(self, ocr_enabled_parser: PDFParser):
        """Test that OCR failure is handled gracefully."""
        with patch("pytesseract.image_to_string") as mock_tesseract, patch("fitz.Matrix"):
            mock_tesseract.side_effect = Exception("OCR engine error")

            # Create a mock page object
            mock_page = MagicMock()
            mock_pixmap = MagicMock()
            mock_pixmap.width = 100
            mock_pixmap.height = 100
            mock_pixmap.samples = b"\x00" * (100 * 100 * 3)
            mock_page.get_pixmap.return_value = mock_pixmap

            result = await ocr_enabled_parser._ocr_page(mock_page)

            # Should return empty string on failure
            assert result == ""

    @pytest.mark.asyncio
    async def test_ocr_missing_dependencies_returns_empty_string(
        self,
        ocr_enabled_parser: PDFParser,
    ):
        """Test that missing OCR dependencies are handled gracefully.

        When pytesseract or PIL is not available, _ocr_page should
        catch the ImportError and return an empty string.
        """
        import sys

        # Create a mock page object
        mock_page = MagicMock()

        # Save original modules
        original_pytesseract = sys.modules.get("pytesseract")
        original_pil = sys.modules.get("PIL")
        original_pil_image = sys.modules.get("PIL.Image")

        try:
            # Remove the modules to force ImportError on next import attempt
            sys.modules["pytesseract"] = None  # type: ignore
            sys.modules["PIL"] = None  # type: ignore
            sys.modules["PIL.Image"] = None  # type: ignore

            # The _ocr_page method imports pytesseract and PIL.Image at runtime
            # Setting modules to None causes ImportError on import
            result = await ocr_enabled_parser._ocr_page(mock_page)

            # Should return empty string when dependencies are missing
            assert result == ""
        finally:
            # Restore original modules
            if original_pytesseract is not None:
                sys.modules["pytesseract"] = original_pytesseract
            elif "pytesseract" in sys.modules:
                del sys.modules["pytesseract"]

            if original_pil is not None:
                sys.modules["PIL"] = original_pil
            elif "PIL" in sys.modules:
                del sys.modules["PIL"]

            if original_pil_image is not None:
                sys.modules["PIL.Image"] = original_pil_image
            elif "PIL.Image" in sys.modules:
                del sys.modules["PIL.Image"]

    @pytest.mark.asyncio
    async def test_ocr_applied_metadata_flag(
        self,
        ocr_enabled_parser: PDFParser,
        minimal_pdf_no_text: bytes,
    ):
        """Test that ocr_applied metadata flag is set correctly."""
        with patch.object(
            ocr_enabled_parser,
            "_ocr_page",
            new_callable=AsyncMock,
        ) as mock_ocr:
            mock_ocr.return_value = "Extracted via OCR"

            result = await ocr_enabled_parser.parse(minimal_pdf_no_text)

            assert result.metadata.get("ocr_applied") is True

    @pytest.mark.asyncio
    async def test_ocr_not_applied_flag_when_ocr_returns_empty(
        self,
        ocr_enabled_parser: PDFParser,
        minimal_pdf_no_text: bytes,
    ):
        """Test that ocr_applied flag is not set when OCR returns no text."""
        with patch.object(
            ocr_enabled_parser,
            "_ocr_page",
            new_callable=AsyncMock,
        ) as mock_ocr:
            mock_ocr.return_value = ""

            result = await ocr_enabled_parser.parse(minimal_pdf_no_text)

            # OCR was attempted but returned nothing, so flag should not be set
            assert result.metadata.get("ocr_applied") is None

    @pytest.mark.asyncio
    async def test_ocr_preserves_existing_metadata(
        self,
        ocr_enabled_parser: PDFParser,
        minimal_pdf_no_text: bytes,
    ):
        """Test that OCR doesn't overwrite existing metadata."""
        with patch.object(
            ocr_enabled_parser,
            "_ocr_page",
            new_callable=AsyncMock,
        ) as mock_ocr:
            mock_ocr.return_value = "OCR text"

            custom_metadata = {"source": "scanner", "scan_date": "2024-01-15"}
            result = await ocr_enabled_parser.parse(minimal_pdf_no_text, custom_metadata)

            # Original metadata should be preserved
            assert result.metadata.get("source") == "scanner"
            assert result.metadata.get("scan_date") == "2024-01-15"
            # OCR flag should also be present
            assert result.metadata.get("ocr_applied") is True

    @pytest.mark.asyncio
    async def test_config_ocr_language_default(self):
        """Test default OCR language is English."""
        config = PDFParserConfig()
        assert config.ocr_language == "eng"

    @pytest.mark.asyncio
    async def test_config_ocr_enabled_default(self):
        """Test OCR is enabled by default."""
        config = PDFParserConfig()
        assert config.ocr_enabled is True
