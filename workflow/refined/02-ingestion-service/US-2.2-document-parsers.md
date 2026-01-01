# US-2.2: Document Parsers

> **Story ID:** US-2.2  
> **Epic:** Ingestion Service  
> **Priority:** Critical  
> **Estimated Effort:** 3-4 days  
> **Dependencies:** US-2.1 (Source Connectors)

## User Story

**As a** data engineer  
**I want** parsers for different document types  
**So that** I can extract text from various formats

## Context

After documents are fetched by connectors, they need to be parsed to extract text content and structural information. Each parser handles a specific document format and produces a consistent output structure. The parsers must handle edge cases gracefully and extract as much useful information as possible, including tables.

## Technical Requirements

### Directory Structure

```
ingestion-service/
└── processors/
    └── parsers/
        ├── __init__.py
        ├── base.py           # Abstract base class
        ├── pdf.py            # PDF parser
        ├── docx.py           # Word document parser
        ├── html.py           # HTML parser
        ├── markdown.py       # Markdown parser
        ├── text.py           # Plain text parser
        └── registry.py       # Parser registry by MIME type
```

### Base Parser Interface

```python
from abc import ABC, abstractmethod
from typing import Optional
from pydantic import BaseModel
from enum import Enum

class ContentType(str, Enum):
    TEXT = "text"
    TABLE = "table"
    IMAGE = "image"
    CODE = "code"

class ContentBlock(BaseModel):
    content_type: ContentType
    content: str
    page_number: Optional[int] = None
    position: Optional[int] = None  # Position in document
    metadata: dict = {}

class TableContent(BaseModel):
    headers: list[str]
    rows: list[list[str]]
    caption: Optional[str] = None

class ParsedDocument(BaseModel):
    text: str  # Full extracted text
    blocks: list[ContentBlock]  # Structured content blocks
    tables: list[TableContent]  # Extracted tables
    title: Optional[str] = None
    author: Optional[str] = None
    created_date: Optional[str] = None
    modified_date: Optional[str] = None
    page_count: Optional[int] = None
    language: Optional[str] = None
    metadata: dict = {}

class BaseParser(ABC):
    """Abstract base class for document parsers."""
    
    @property
    @abstractmethod
    def supported_mime_types(self) -> list[str]:
        """Return list of MIME types this parser handles."""
        pass
    
    @abstractmethod
    async def parse(self, content: bytes, metadata: dict = {}) -> ParsedDocument:
        """Parse document content and return structured output."""
        pass
    
    @abstractmethod
    def can_parse(self, mime_type: str) -> bool:
        """Check if this parser can handle the given MIME type."""
        pass
```

### 1. PDF Parser

Primary parser using PyMuPDF with Unstructured fallback:

```python
import fitz  # PyMuPDF
from unstructured.partition.pdf import partition_pdf

class PDFParserConfig(BaseModel):
    extract_images: bool = False
    extract_tables: bool = True
    ocr_enabled: bool = True
    ocr_language: str = "eng"
    use_unstructured_fallback: bool = True
    max_pages: Optional[int] = None

class PDFParser(BaseParser):
    supported_mime_types = ["application/pdf"]
    
    def __init__(self, config: PDFParserConfig = PDFParserConfig()):
        self.config = config
    
    async def parse(self, content: bytes, metadata: dict = {}) -> ParsedDocument:
        """
        Parse PDF using PyMuPDF (fitz).
        Falls back to Unstructured for complex layouts.
        """
        try:
            return await self._parse_with_pymupdf(content, metadata)
        except Exception as e:
            if self.config.use_unstructured_fallback:
                return await self._parse_with_unstructured(content, metadata)
            raise
    
    async def _parse_with_pymupdf(self, content: bytes, metadata: dict) -> ParsedDocument:
        doc = fitz.open(stream=content, filetype="pdf")
        blocks = []
        tables = []
        full_text = []
        
        for page_num, page in enumerate(doc):
            # Extract text blocks
            text = page.get_text("text")
            full_text.append(text)
            blocks.append(ContentBlock(
                content_type=ContentType.TEXT,
                content=text,
                page_number=page_num + 1
            ))
            
            # Extract tables if enabled
            if self.config.extract_tables:
                page_tables = page.find_tables()
                for table in page_tables:
                    tables.append(self._convert_table(table))
        
        return ParsedDocument(
            text="\n\n".join(full_text),
            blocks=blocks,
            tables=tables,
            title=doc.metadata.get("title"),
            author=doc.metadata.get("author"),
            page_count=len(doc),
            metadata=metadata
        )
    
    async def _parse_with_unstructured(self, content: bytes, metadata: dict) -> ParsedDocument:
        # Use unstructured for complex PDF layouts
        elements = partition_pdf(file=io.BytesIO(content))
        # Convert elements to ParsedDocument structure
        ...
```

**Requirements:**
- Use `PyMuPDF` (fitz) as primary PDF parser
- Fall back to `unstructured` for complex layouts
- Extract text while preserving reading order
- Extract tables using PyMuPDF's table detection
- Support OCR via `pytesseract` for scanned PDFs
- Extract PDF metadata (title, author, dates)

### 2. Word Document Parser

Parse .docx files:

```python
from docx import Document
from docx.table import Table

class DocxParser(BaseParser):
    supported_mime_types = [
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ]
    
    async def parse(self, content: bytes, metadata: dict = {}) -> ParsedDocument:
        doc = Document(io.BytesIO(content))
        blocks = []
        tables = []
        full_text = []
        
        for para in doc.paragraphs:
            if para.text.strip():
                full_text.append(para.text)
                blocks.append(ContentBlock(
                    content_type=ContentType.TEXT,
                    content=para.text,
                    metadata={"style": para.style.name}
                ))
        
        for table in doc.tables:
            tables.append(self._extract_table(table))
        
        # Extract core properties
        core_props = doc.core_properties
        
        return ParsedDocument(
            text="\n\n".join(full_text),
            blocks=blocks,
            tables=tables,
            title=core_props.title,
            author=core_props.author,
            created_date=str(core_props.created) if core_props.created else None,
            metadata=metadata
        )
```

**Requirements:**
- Use `python-docx` library
- Extract paragraphs with style information
- Extract tables preserving structure
- Extract document properties (title, author, dates)
- Handle embedded images (extract alt text)

### 3. HTML Parser

Parse HTML documents:

```python
from bs4 import BeautifulSoup
from markdownify import markdownify
import html2text

class HTMLParserConfig(BaseModel):
    remove_scripts: bool = True
    remove_styles: bool = True
    remove_comments: bool = True
    extract_links: bool = True
    convert_to_markdown: bool = False

class HTMLParser(BaseParser):
    supported_mime_types = ["text/html", "application/xhtml+xml"]
    
    def __init__(self, config: HTMLParserConfig = HTMLParserConfig()):
        self.config = config
    
    async def parse(self, content: bytes, metadata: dict = {}) -> ParsedDocument:
        html = content.decode("utf-8", errors="replace")
        soup = BeautifulSoup(html, "html.parser")
        
        # Remove unwanted elements
        if self.config.remove_scripts:
            for script in soup.find_all("script"):
                script.decompose()
        if self.config.remove_styles:
            for style in soup.find_all("style"):
                style.decompose()
        
        # Extract title
        title = soup.find("title")
        title_text = title.get_text() if title else None
        
        # Extract text content
        blocks = []
        for element in soup.find_all(["p", "h1", "h2", "h3", "h4", "h5", "h6", "li"]):
            blocks.append(ContentBlock(
                content_type=ContentType.TEXT,
                content=element.get_text(strip=True),
                metadata={"tag": element.name}
            ))
        
        # Extract tables
        tables = []
        for table in soup.find_all("table"):
            tables.append(self._extract_html_table(table))
        
        # Get full text
        full_text = soup.get_text(separator="\n", strip=True)
        
        if self.config.convert_to_markdown:
            full_text = markdownify(str(soup))
        
        return ParsedDocument(
            text=full_text,
            blocks=blocks,
            tables=tables,
            title=title_text,
            metadata=metadata
        )
```

**Requirements:**
- Use `beautifulsoup4` for HTML parsing
- Remove scripts, styles, and comments
- Extract semantic structure (headings, paragraphs, lists)
- Extract tables preserving structure
- Optionally convert to Markdown using `markdownify`
- Handle encoding issues gracefully

### 4. Markdown Parser

Parse Markdown files:

```python
import markdown
from markdown.extensions import tables, fenced_code

class MarkdownParser(BaseParser):
    supported_mime_types = ["text/markdown", "text/x-markdown"]
    
    async def parse(self, content: bytes, metadata: dict = {}) -> ParsedDocument:
        text = content.decode("utf-8", errors="replace")
        
        # Extract title from first H1
        lines = text.split("\n")
        title = None
        for line in lines:
            if line.startswith("# "):
                title = line[2:].strip()
                break
        
        # Parse code blocks
        blocks = self._extract_blocks(text)
        
        # Convert to HTML then extract tables
        md = markdown.Markdown(extensions=["tables", "fenced_code"])
        html = md.convert(text)
        soup = BeautifulSoup(html, "html.parser")
        tables = [self._extract_html_table(t) for t in soup.find_all("table")]
        
        return ParsedDocument(
            text=text,
            blocks=blocks,
            tables=tables,
            title=title,
            metadata=metadata
        )
```

**Requirements:**
- Parse Markdown syntax
- Extract code blocks with language hints
- Extract tables (both pipe and HTML style)
- Preserve the original Markdown text
- Extract title from first heading

### 5. Plain Text Parser

Parse plain text files:

```python
import chardet

class TextParser(BaseParser):
    supported_mime_types = ["text/plain"]
    
    async def parse(self, content: bytes, metadata: dict = {}) -> ParsedDocument:
        # Detect encoding
        detected = chardet.detect(content)
        encoding = detected.get("encoding", "utf-8")
        
        text = content.decode(encoding, errors="replace")
        
        return ParsedDocument(
            text=text,
            blocks=[ContentBlock(
                content_type=ContentType.TEXT,
                content=text
            )],
            tables=[],
            metadata=metadata
        )
```

**Requirements:**
- Auto-detect encoding using `chardet`
- Handle various line endings (CRLF, LF, CR)
- Simple structure (single block)

### Parser Registry

Register parsers by MIME type for automatic selection:

```python
class ParserRegistry:
    def __init__(self):
        self._parsers: dict[str, BaseParser] = {}
    
    def register(self, parser: BaseParser) -> None:
        for mime_type in parser.supported_mime_types:
            self._parsers[mime_type] = parser
    
    def get_parser(self, mime_type: str) -> Optional[BaseParser]:
        return self._parsers.get(mime_type)
    
    def parse(self, content: bytes, mime_type: str, metadata: dict = {}) -> ParsedDocument:
        parser = self.get_parser(mime_type)
        if not parser:
            raise ValueError(f"No parser registered for MIME type: {mime_type}")
        return parser.parse(content, metadata)

# Default registry with all parsers
def create_default_registry() -> ParserRegistry:
    registry = ParserRegistry()
    registry.register(PDFParser())
    registry.register(DocxParser())
    registry.register(HTMLParser())
    registry.register(MarkdownParser())
    registry.register(TextParser())
    return registry
```

## Acceptance Criteria

- [ ] Abstract `BaseParser` class defined with all required methods
- [ ] `PDFParser` extracts text and tables with Unstructured fallback
- [ ] `DocxParser` extracts paragraphs, tables, and metadata
- [ ] `HTMLParser` extracts content, removes scripts/styles, extracts tables
- [ ] `MarkdownParser` preserves structure and extracts code blocks
- [ ] `TextParser` handles encoding detection
- [ ] `ParserRegistry` maps MIME types to parsers
- [ ] All parsers return consistent `ParsedDocument` structure
- [ ] Table extraction works for all supported formats
- [ ] Unit tests with sample documents of each type
- [ ] Error handling for malformed documents

## Testing Requirements

```python
import pytest
from pathlib import Path

SAMPLE_DOCS = Path(__file__).parent / "fixtures"

@pytest.fixture
def pdf_parser():
    return PDFParser()

@pytest.mark.asyncio
async def test_pdf_parser_extracts_text(pdf_parser):
    content = (SAMPLE_DOCS / "sample.pdf").read_bytes()
    result = await pdf_parser.parse(content)
    
    assert result.text
    assert len(result.blocks) > 0
    assert result.page_count > 0

@pytest.mark.asyncio
async def test_pdf_parser_extracts_tables(pdf_parser):
    content = (SAMPLE_DOCS / "with_tables.pdf").read_bytes()
    result = await pdf_parser.parse(content)
    
    assert len(result.tables) > 0
    assert result.tables[0].headers
    assert result.tables[0].rows
```

## Sample Documents Required

Create fixtures directory with sample documents:
- `sample.pdf` - Simple text PDF
- `with_tables.pdf` - PDF with tables
- `scanned.pdf` - Scanned document (for OCR testing)
- `sample.docx` - Word document with tables
- `sample.html` - HTML page with various elements
- `sample.md` - Markdown with code and tables
- `sample.txt` - Plain text file

## Dependencies

- `PyMuPDF>=1.23.0`
- `unstructured>=0.11.0`
- `python-docx>=1.1.0`
- `beautifulsoup4>=4.12.0`
- `markdownify>=0.11.0`
- `markdown>=3.5.0`
- `chardet>=5.2.0`
- `pytesseract>=0.3.10` (optional, for OCR)
- `pydantic>=2.0.0`

## Definition of Done

- [ ] All parsers implemented and passing tests
- [ ] >90% test coverage for parsers module
- [ ] Sample documents created for each format
- [ ] Edge cases handled (empty docs, malformed content)
- [ ] Docstrings on all public methods
- [ ] Type hints validated with mypy
