"""Pytest configuration and fixtures for parser tests."""

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Return path to test fixtures directory."""
    return FIXTURES_DIR


@pytest.fixture
def sample_markdown(fixtures_dir: Path) -> bytes:
    """Return sample markdown content."""
    return (fixtures_dir / "sample.md").read_bytes()


@pytest.fixture
def sample_html(fixtures_dir: Path) -> bytes:
    """Return sample HTML content."""
    return (fixtures_dir / "sample.html").read_bytes()


@pytest.fixture
def sample_text(fixtures_dir: Path) -> bytes:
    """Return sample plain text content."""
    return (fixtures_dir / "sample.txt").read_bytes()


@pytest.fixture
def simple_pdf_content() -> bytes:
    """Return minimal PDF content for testing.

    This is a minimal valid PDF that contains the text "Hello World".
    For more comprehensive PDF testing, use actual PDF files.
    """
    # Minimal PDF with "Hello World" text
    return b"""%PDF-1.4
1 0 obj
<< /Type /Catalog /Pages 2 0 R >>
endobj
2 0 obj
<< /Type /Pages /Kids [3 0 R] /Count 1 >>
endobj
3 0 obj
<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]
   /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>
endobj
4 0 obj
<< /Length 44 >>
stream
BT /F1 12 Tf 100 700 Td (Hello World) Tj ET
endstream
endobj
5 0 obj
<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>
endobj
xref
0 6
0000000000 65535 f
0000000009 00000 n
0000000058 00000 n
0000000115 00000 n
0000000266 00000 n
0000000359 00000 n
trailer
<< /Size 6 /Root 1 0 R >>
startxref
434
%%EOF"""


@pytest.fixture
def html_with_table() -> bytes:
    """Return HTML content with a table."""
    return b"""<!DOCTYPE html>
<html>
<head><title>Table Test</title></head>
<body>
<h1>Table Test</h1>
<table>
    <thead>
        <tr><th>Product</th><th>Price</th><th>Quantity</th></tr>
    </thead>
    <tbody>
        <tr><td>Apple</td><td>1.00</td><td>10</td></tr>
        <tr><td>Banana</td><td>0.50</td><td>20</td></tr>
    </tbody>
</table>
</body>
</html>"""


@pytest.fixture
def markdown_with_table() -> bytes:
    """Return Markdown content with a table."""
    return b"""# Table Test

| Product | Price | Quantity |
|---------|-------|----------|
| Apple   | 1.00  | 10       |
| Banana  | 0.50  | 20       |
"""
