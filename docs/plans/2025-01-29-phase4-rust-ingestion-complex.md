# Phase 4: Rust Ingestion Complex Components Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete the remaining Phase 4 components for the Rust ingestion pipeline: PDF Parser (HTTP client), DOCX Parser, Semantic Chunker, PII Detection, and Async Worker System.

**Architecture:** Each component follows the existing patterns in `crates/rag-ingestion/`. Parsers implement the `Parser` trait, chunkers implement `ChunkingStrategy` trait. The worker system uses Redis lists for job queues with tokio for async processing. PDF parsing delegates to the Python service via HTTP to avoid Rust PDF ecosystem immaturity.

**Tech Stack:**
- `quick-xml` for DOCX parsing (OOXML format)
- `unicode-segmentation` for sentence boundaries in semantic chunker
- `regex` for PII pattern matching
- `redis` (existing workspace dep) for job queues
- `reqwest` for PDF HTTP client

---

## Task 1: Add New Dependencies to Cargo.toml

**Files:**
- Modify: `crates/rag-ingestion/Cargo.toml`

**Step 1: Add the new dependencies**

```toml
# Add after line 20 (after serde_yaml = "0.9")

# DOCX parsing
quick-xml = "0.36"
zip = "2.2"

# Sentence segmentation for semantic chunking
unicode-segmentation = "1.11"

# PII detection patterns
regex = "1.10"
lazy_static = "1.5"
```

**Step 2: Verify compilation**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo check -p rag-ingestion`
Expected: Compilation succeeds

**Step 3: Commit**

```bash
git add crates/rag-ingestion/Cargo.toml
git commit -m "feat(rag-ingestion): add dependencies for phase 4 components

- quick-xml, zip: DOCX OOXML parsing
- unicode-segmentation: sentence boundary detection
- regex, lazy_static: PII pattern matching"
```

---

## Task 2: PDF Parser - HTTP Client Types

**Files:**
- Create: `crates/rag-ingestion/src/parsers/pdf.rs`
- Test: `crates/rag-ingestion/src/parsers/pdf.rs` (inline tests)

**Step 1: Write the failing test for PDF parser config**

```rust
// In crates/rag-ingestion/src/parsers/pdf.rs
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_pdf_parser_config_default() {
        let config = PdfParserConfig::default();
        assert_eq!(config.service_url, "http://localhost:8001/api/v1/parse/pdf");
        assert!(config.extract_tables);
        assert!(config.ocr_enabled);
    }
}
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion pdf_parser_config_default`
Expected: FAIL with "cannot find value `PdfParserConfig`"

**Step 3: Write minimal implementation for config**

```rust
//! PDF parser that delegates to Python PDF service via HTTP.
//!
//! This approach is recommended by the implementation plan because:
//! - Rust PDF ecosystem (pdf crate) is immature compared to PyMuPDF
//! - OCR integration (Tesseract) is complex in pure Rust
//! - HTTP delegation provides fallback to Unstructured library

use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::time::Duration;

use super::base::{ContentBlock, ContentType, ParsedDocument, Parser, TableContent};
use crate::{Error, Result};

/// Configuration for the PDF parser HTTP client.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PdfParserConfig {
    /// URL of the PDF parsing service.
    pub service_url: String,
    /// Whether to extract tables from PDFs.
    pub extract_tables: bool,
    /// Whether to enable OCR for scanned PDFs.
    pub ocr_enabled: bool,
    /// OCR language code (e.g., "eng").
    pub ocr_language: String,
    /// Maximum pages to process (None = all).
    pub max_pages: Option<u32>,
    /// Request timeout in seconds.
    pub timeout_secs: u64,
}

impl Default for PdfParserConfig {
    fn default() -> Self {
        Self {
            service_url: "http://localhost:8001/api/v1/parse/pdf".to_string(),
            extract_tables: true,
            ocr_enabled: true,
            ocr_language: "eng".to_string(),
            max_pages: None,
            timeout_secs: 60,
        }
    }
}
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion pdf_parser_config_default`
Expected: PASS

**Step 5: Commit**

```bash
git add crates/rag-ingestion/src/parsers/pdf.rs
git commit -m "feat(rag-ingestion): add PDF parser config types"
```

---

## Task 3: PDF Parser - Request/Response Types

**Files:**
- Modify: `crates/rag-ingestion/src/parsers/pdf.rs`

**Step 1: Write the failing test for request serialization**

```rust
// Add to tests module
#[test]
fn test_pdf_parse_request_serialization() {
    let request = PdfParseRequest {
        extract_tables: true,
        ocr_enabled: false,
        ocr_language: "eng".to_string(),
        max_pages: Some(10),
    };
    let json = serde_json::to_string(&request).unwrap();
    assert!(json.contains("\"extract_tables\":true"));
    assert!(json.contains("\"max_pages\":10"));
}
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion pdf_parse_request_serialization`
Expected: FAIL with "cannot find value `PdfParseRequest`"

**Step 3: Write the request/response types**

```rust
// Add after PdfParserConfig impl

/// Request body for PDF parsing service.
#[derive(Debug, Serialize)]
pub struct PdfParseRequest {
    pub extract_tables: bool,
    pub ocr_enabled: bool,
    pub ocr_language: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_pages: Option<u32>,
}

/// Response from PDF parsing service.
#[derive(Debug, Deserialize)]
pub struct PdfParseResponse {
    pub text: String,
    #[serde(default)]
    pub blocks: Vec<PdfContentBlock>,
    #[serde(default)]
    pub tables: Vec<PdfTable>,
    pub title: Option<String>,
    pub author: Option<String>,
    pub created_date: Option<String>,
    pub modified_date: Option<String>,
    pub page_count: Option<u32>,
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,
}

/// Content block from PDF service response.
#[derive(Debug, Deserialize)]
pub struct PdfContentBlock {
    pub content_type: String,
    pub content: String,
    pub page_number: Option<u32>,
    pub position: Option<u32>,
}

/// Table from PDF service response.
#[derive(Debug, Deserialize)]
pub struct PdfTable {
    pub headers: Vec<String>,
    pub rows: Vec<Vec<String>>,
    pub caption: Option<String>,
}
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion pdf_parse_request_serialization`
Expected: PASS

**Step 5: Commit**

```bash
git add crates/rag-ingestion/src/parsers/pdf.rs
git commit -m "feat(rag-ingestion): add PDF parser request/response types"
```

---

## Task 4: PDF Parser - Client Implementation

**Files:**
- Modify: `crates/rag-ingestion/src/parsers/pdf.rs`

**Step 1: Write the failing test for parser creation**

```rust
// Add to tests module
#[test]
fn test_pdf_parser_new() {
    let parser = PdfParser::new(PdfParserConfig::default());
    assert!(parser.is_ok());
}

#[test]
fn test_pdf_parser_supported_mime_types() {
    let parser = PdfParser::new(PdfParserConfig::default()).unwrap();
    assert!(parser.can_parse("application/pdf"));
    assert!(!parser.can_parse("text/html"));
}
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion pdf_parser_new`
Expected: FAIL with "cannot find value `PdfParser`"

**Step 3: Write the PdfParser struct and Parser trait implementation**

```rust
// Add after response types

/// PDF parser that delegates to Python service via HTTP.
///
/// This parser sends PDF content to an HTTP service that uses PyMuPDF
/// for extraction, with fallback to Unstructured for complex layouts.
pub struct PdfParser {
    config: PdfParserConfig,
    client: Client,
}

impl PdfParser {
    /// Create a new PDF parser with the given configuration.
    ///
    /// # Errors
    ///
    /// Returns an error if the HTTP client cannot be created.
    pub fn new(config: PdfParserConfig) -> Result<Self> {
        let client = Client::builder()
            .timeout(Duration::from_secs(config.timeout_secs))
            .build()
            .map_err(|e| Error::Config(format!("Failed to create HTTP client: {e}")))?;

        Ok(Self { config, client })
    }

    /// Convert PDF service response to ParsedDocument.
    fn convert_response(
        &self,
        response: PdfParseResponse,
        metadata: Option<HashMap<String, serde_json::Value>>,
    ) -> ParsedDocument {
        let mut doc_metadata = metadata.unwrap_or_default();
        doc_metadata.extend(response.metadata);

        // Convert content blocks
        let blocks: Vec<ContentBlock> = response
            .blocks
            .into_iter()
            .enumerate()
            .map(|(i, block)| {
                let content_type = match block.content_type.as_str() {
                    "table" => ContentType::Table,
                    "code" => ContentType::Code,
                    "image" => ContentType::Image,
                    _ => ContentType::Text,
                };

                ContentBlock {
                    content_type,
                    content: block.content,
                    page_number: block.page_number,
                    position: block.position.or(Some(i as u32)),
                    metadata: HashMap::new(),
                }
            })
            .collect();

        // Convert tables
        let tables: Vec<TableContent> = response
            .tables
            .into_iter()
            .map(|t| TableContent {
                headers: t.headers,
                rows: t.rows,
                caption: t.caption,
            })
            .collect();

        ParsedDocument {
            text: response.text,
            blocks,
            tables,
            title: response.title,
            author: response.author,
            created_date: response.created_date,
            modified_date: response.modified_date,
            page_count: response.page_count,
            language: None,
            metadata: doc_metadata,
        }
    }
}

impl Parser for PdfParser {
    fn supported_mime_types(&self) -> &[&str] {
        &["application/pdf"]
    }

    fn parse(
        &self,
        content: &[u8],
        metadata: Option<HashMap<String, serde_json::Value>>,
    ) -> Result<ParsedDocument> {
        // Use blocking HTTP call since Parser trait is sync
        // In production, consider making this async
        let runtime = tokio::runtime::Handle::try_current()
            .map_err(|_| Error::Parse("No tokio runtime available".to_string()))?;

        runtime.block_on(async {
            let request_body = PdfParseRequest {
                extract_tables: self.config.extract_tables,
                ocr_enabled: self.config.ocr_enabled,
                ocr_language: self.config.ocr_language.clone(),
                max_pages: self.config.max_pages,
            };

            let response = self
                .client
                .post(&self.config.service_url)
                .header("Content-Type", "application/pdf")
                .query(&[
                    ("extract_tables", self.config.extract_tables.to_string()),
                    ("ocr_enabled", self.config.ocr_enabled.to_string()),
                    ("ocr_language", self.config.ocr_language.clone()),
                ])
                .body(content.to_vec())
                .send()
                .await
                .map_err(|e| Error::Parse(format!("HTTP request failed: {e}")))?;

            if !response.status().is_success() {
                let status = response.status();
                let body = response.text().await.unwrap_or_default();
                return Err(Error::Parse(format!(
                    "PDF service returned error {status}: {body}"
                )));
            }

            let pdf_response: PdfParseResponse = response
                .json()
                .await
                .map_err(|e| Error::Parse(format!("Failed to parse response: {e}")))?;

            Ok(self.convert_response(pdf_response, metadata))
        })
    }
}
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion pdf_parser_new && cargo test -p rag-ingestion pdf_parser_supported`
Expected: PASS

**Step 5: Commit**

```bash
git add crates/rag-ingestion/src/parsers/pdf.rs
git commit -m "feat(rag-ingestion): implement PDF parser HTTP client"
```

---

## Task 5: Register PDF Parser in Module

**Files:**
- Modify: `crates/rag-ingestion/src/parsers/mod.rs`

**Step 1: Add pdf module to parsers/mod.rs**

```rust
//! Document parsers for various file formats.
//!
//! This module provides parsers for:
//! - HTML documents ([`HtmlParser`])
//! - Markdown documents ([`MarkdownParser`])
//! - PDF documents ([`PdfParser`]) - delegates to Python service

mod base;
mod html;
mod markdown;
mod pdf;

pub use base::{ContentBlock, ContentType, ParsedDocument, Parser, TableContent};
pub use html::{HtmlParser, HtmlParserConfig};
pub use markdown::MarkdownParser;
pub use pdf::{PdfParser, PdfParserConfig};
```

**Step 2: Verify compilation**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo check -p rag-ingestion`
Expected: Compilation succeeds

**Step 3: Commit**

```bash
git add crates/rag-ingestion/src/parsers/mod.rs
git commit -m "feat(rag-ingestion): export PDF parser from parsers module"
```

---

## Task 6: DOCX Parser - OOXML Types

**Files:**
- Create: `crates/rag-ingestion/src/parsers/docx.rs`

**Step 1: Write the failing test for DOCX config**

```rust
// In crates/rag-ingestion/src/parsers/docx.rs
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_docx_parser_default() {
        let parser = DocxParser::default();
        assert!(parser.config.extract_tables);
        assert!(parser.config.preserve_styles);
    }
}
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion docx_parser_default`
Expected: FAIL with "cannot find value `DocxParser`"

**Step 3: Write the config and parser struct**

```rust
//! DOCX parser using quick-xml for OOXML format.
//!
//! Word documents (.docx) are ZIP archives containing XML files.
//! The main content is in `word/document.xml`.

use quick_xml::events::Event;
use quick_xml::Reader;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::io::{Cursor, Read};
use zip::ZipArchive;

use super::base::{ContentBlock, ContentType, ParsedDocument, Parser, TableContent};
use crate::{Error, Result};

/// Configuration for DOCX parser.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocxParserConfig {
    /// Whether to extract tables.
    pub extract_tables: bool,
    /// Whether to preserve paragraph styles (headings, etc.).
    pub preserve_styles: bool,
}

impl Default for DocxParserConfig {
    fn default() -> Self {
        Self {
            extract_tables: true,
            preserve_styles: true,
        }
    }
}

/// Parser for Word documents (.docx).
///
/// Uses quick-xml to parse the OOXML format directly without
/// external dependencies like python-docx.
pub struct DocxParser {
    config: DocxParserConfig,
}

impl DocxParser {
    /// Create a new DOCX parser with custom configuration.
    #[must_use]
    pub fn new(config: DocxParserConfig) -> Self {
        Self { config }
    }
}

impl Default for DocxParser {
    fn default() -> Self {
        Self::new(DocxParserConfig::default())
    }
}
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion docx_parser_default`
Expected: PASS

**Step 5: Commit**

```bash
git add crates/rag-ingestion/src/parsers/docx.rs
git commit -m "feat(rag-ingestion): add DOCX parser config types"
```

---

## Task 7: DOCX Parser - ZIP Extraction

**Files:**
- Modify: `crates/rag-ingestion/src/parsers/docx.rs`

**Step 1: Write the failing test for ZIP extraction**

```rust
// Add to tests module
#[test]
fn test_docx_extract_document_xml() {
    // Minimal valid DOCX structure
    let docx_bytes = create_minimal_docx();
    let parser = DocxParser::default();
    let xml = parser.extract_document_xml(&docx_bytes);
    assert!(xml.is_ok());
    assert!(xml.unwrap().contains("<w:document"));
}

fn create_minimal_docx() -> Vec<u8> {
    use std::io::Write;
    use zip::write::SimpleFileOptions;
    use zip::ZipWriter;

    let mut buffer = Cursor::new(Vec::new());
    {
        let mut zip = ZipWriter::new(&mut buffer);
        let options = SimpleFileOptions::default();

        // [Content_Types].xml
        zip.start_file("[Content_Types].xml", options).unwrap();
        zip.write_all(br#"<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"#).unwrap();

        // word/document.xml
        zip.start_file("word/document.xml", options).unwrap();
        zip.write_all(br#"<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>
<w:p><w:r><w:t>Hello World</w:t></w:r></w:p>
</w:body>
</w:document>"#).unwrap();

        zip.finish().unwrap();
    }
    buffer.into_inner()
}
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion docx_extract_document_xml`
Expected: FAIL with "method not found"

**Step 3: Implement ZIP extraction**

```rust
// Add to DocxParser impl block

impl DocxParser {
    // ... existing methods ...

    /// Extract the main document.xml from the DOCX ZIP archive.
    fn extract_document_xml(&self, content: &[u8]) -> Result<String> {
        let cursor = Cursor::new(content);
        let mut archive = ZipArchive::new(cursor)
            .map_err(|e| Error::Parse(format!("Invalid DOCX file (not a valid ZIP): {e}")))?;

        let mut document_xml = archive.by_name("word/document.xml").map_err(|e| {
            Error::Parse(format!("DOCX missing word/document.xml: {e}"))
        })?;

        let mut xml_content = String::new();
        document_xml
            .read_to_string(&mut xml_content)
            .map_err(|e| Error::Parse(format!("Failed to read document.xml: {e}")))?;

        Ok(xml_content)
    }

    /// Extract core.xml for document properties (title, author, dates).
    fn extract_core_properties(&self, content: &[u8]) -> Option<CoreProperties> {
        let cursor = Cursor::new(content);
        let mut archive = ZipArchive::new(cursor).ok()?;
        let mut core_xml = archive.by_name("docProps/core.xml").ok()?;

        let mut xml_content = String::new();
        core_xml.read_to_string(&mut xml_content).ok()?;

        self.parse_core_properties(&xml_content)
    }

    fn parse_core_properties(&self, xml: &str) -> Option<CoreProperties> {
        let mut reader = Reader::from_str(xml);
        reader.config_mut().trim_text(true);

        let mut props = CoreProperties::default();
        let mut current_tag = String::new();
        let mut buf = Vec::new();

        loop {
            match reader.read_event_into(&mut buf) {
                Ok(Event::Start(e)) => {
                    current_tag = String::from_utf8_lossy(e.local_name().as_ref()).to_string();
                }
                Ok(Event::Text(e)) => {
                    let text = e.unescape().ok()?.to_string();
                    match current_tag.as_str() {
                        "title" => props.title = Some(text),
                        "creator" => props.author = Some(text),
                        "created" => props.created = Some(text),
                        "modified" => props.modified = Some(text),
                        _ => {}
                    }
                }
                Ok(Event::Eof) => break,
                Err(_) => break,
                _ => {}
            }
            buf.clear();
        }

        Some(props)
    }
}

/// Document core properties from docProps/core.xml.
#[derive(Debug, Default)]
struct CoreProperties {
    title: Option<String>,
    author: Option<String>,
    created: Option<String>,
    modified: Option<String>,
}
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion docx_extract_document_xml`
Expected: PASS

**Step 5: Commit**

```bash
git add crates/rag-ingestion/src/parsers/docx.rs
git commit -m "feat(rag-ingestion): add DOCX ZIP extraction"
```

---

## Task 8: DOCX Parser - XML Parsing

**Files:**
- Modify: `crates/rag-ingestion/src/parsers/docx.rs`

**Step 1: Write the failing test for text extraction**

```rust
// Add to tests module
#[test]
fn test_docx_parse_extracts_text() {
    let docx_bytes = create_minimal_docx();
    let parser = DocxParser::default();
    let result = parser.parse(&docx_bytes, None);

    assert!(result.is_ok());
    let doc = result.unwrap();
    assert!(doc.text.contains("Hello World"));
}

#[test]
fn test_docx_parse_multiple_paragraphs() {
    let docx_bytes = create_docx_with_paragraphs(&["First paragraph.", "Second paragraph."]);
    let parser = DocxParser::default();
    let doc = parser.parse(&docx_bytes, None).unwrap();

    assert!(doc.text.contains("First paragraph"));
    assert!(doc.text.contains("Second paragraph"));
    assert!(doc.blocks.len() >= 2);
}

fn create_docx_with_paragraphs(paragraphs: &[&str]) -> Vec<u8> {
    use std::io::Write;
    use zip::write::SimpleFileOptions;
    use zip::ZipWriter;

    let mut body = String::new();
    for p in paragraphs {
        body.push_str(&format!(r#"<w:p><w:r><w:t>{}</w:t></w:r></w:p>"#, p));
    }

    let document_xml = format!(
        r#"<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>{}</w:body>
</w:document>"#,
        body
    );

    let mut buffer = Cursor::new(Vec::new());
    {
        let mut zip = ZipWriter::new(&mut buffer);
        let options = SimpleFileOptions::default();

        zip.start_file("[Content_Types].xml", options).unwrap();
        zip.write_all(br#"<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>"#).unwrap();

        zip.start_file("word/document.xml", options).unwrap();
        zip.write_all(document_xml.as_bytes()).unwrap();

        zip.finish().unwrap();
    }
    buffer.into_inner()
}
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion docx_parse_extracts_text`
Expected: FAIL with "method `parse` not found"

**Step 3: Implement the Parser trait**

```rust
// Add to DocxParser impl block

impl DocxParser {
    // ... existing methods ...

    /// Parse the document.xml content and extract paragraphs.
    fn parse_document_content(&self, xml: &str) -> Result<(Vec<String>, Vec<ContentBlock>)> {
        let mut reader = Reader::from_str(xml);
        reader.config_mut().trim_text(true);

        let mut paragraphs = Vec::new();
        let mut blocks = Vec::new();
        let mut current_paragraph = String::new();
        let mut in_paragraph = false;
        let mut in_text = false;
        let mut position = 0u32;
        let mut buf = Vec::new();

        loop {
            match reader.read_event_into(&mut buf) {
                Ok(Event::Start(e)) => {
                    let local_name = e.local_name();
                    match local_name.as_ref() {
                        b"p" => {
                            in_paragraph = true;
                            current_paragraph.clear();
                        }
                        b"t" => {
                            in_text = true;
                        }
                        _ => {}
                    }
                }
                Ok(Event::Text(e)) => {
                    if in_text {
                        if let Ok(text) = e.unescape() {
                            current_paragraph.push_str(&text);
                        }
                    }
                }
                Ok(Event::End(e)) => {
                    let local_name = e.local_name();
                    match local_name.as_ref() {
                        b"p" => {
                            in_paragraph = false;
                            let trimmed = current_paragraph.trim().to_string();
                            if !trimmed.is_empty() {
                                paragraphs.push(trimmed.clone());
                                blocks.push(ContentBlock {
                                    content_type: ContentType::Text,
                                    content: trimmed,
                                    page_number: None,
                                    position: Some(position),
                                    metadata: HashMap::new(),
                                });
                                position += 1;
                            }
                        }
                        b"t" => {
                            in_text = false;
                        }
                        _ => {}
                    }
                }
                Ok(Event::Eof) => break,
                Err(e) => {
                    return Err(Error::Parse(format!("XML parsing error: {e}")));
                }
                _ => {}
            }
            buf.clear();
        }

        Ok((paragraphs, blocks))
    }
}

impl Parser for DocxParser {
    fn supported_mime_types(&self) -> &[&str] {
        &["application/vnd.openxmlformats-officedocument.wordprocessingml.document"]
    }

    fn parse(
        &self,
        content: &[u8],
        metadata: Option<HashMap<String, serde_json::Value>>,
    ) -> Result<ParsedDocument> {
        let xml = self.extract_document_xml(content)?;
        let (paragraphs, blocks) = self.parse_document_content(&xml)?;
        let core_props = self.extract_core_properties(content);

        let text = paragraphs.join("\n\n");
        let mut doc_metadata = metadata.unwrap_or_default();

        // Add any extra metadata here if needed

        Ok(ParsedDocument {
            text,
            blocks,
            tables: Vec::new(), // Table extraction in next task
            title: core_props.as_ref().and_then(|p| p.title.clone()),
            author: core_props.as_ref().and_then(|p| p.author.clone()),
            created_date: core_props.as_ref().and_then(|p| p.created.clone()),
            modified_date: core_props.as_ref().and_then(|p| p.modified.clone()),
            page_count: None,
            language: None,
            metadata: doc_metadata,
        })
    }
}
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion docx_parse`
Expected: PASS

**Step 5: Commit**

```bash
git add crates/rag-ingestion/src/parsers/docx.rs
git commit -m "feat(rag-ingestion): implement DOCX Parser trait with text extraction"
```

---

## Task 9: DOCX Parser - Table Extraction

**Files:**
- Modify: `crates/rag-ingestion/src/parsers/docx.rs`

**Step 1: Write the failing test for table extraction**

```rust
// Add to tests module
#[test]
fn test_docx_parse_extracts_tables() {
    let docx_bytes = create_docx_with_table();
    let parser = DocxParser::default();
    let doc = parser.parse(&docx_bytes, None).unwrap();

    assert_eq!(doc.tables.len(), 1);
    assert_eq!(doc.tables[0].headers, vec!["Name", "Age"]);
    assert_eq!(doc.tables[0].rows.len(), 2);
}

fn create_docx_with_table() -> Vec<u8> {
    use std::io::Write;
    use zip::write::SimpleFileOptions;
    use zip::ZipWriter;

    let document_xml = r#"<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>
<w:tbl>
  <w:tr>
    <w:tc><w:p><w:r><w:t>Name</w:t></w:r></w:p></w:tc>
    <w:tc><w:p><w:r><w:t>Age</w:t></w:r></w:p></w:tc>
  </w:tr>
  <w:tr>
    <w:tc><w:p><w:r><w:t>Alice</w:t></w:r></w:p></w:tc>
    <w:tc><w:p><w:r><w:t>30</w:t></w:r></w:p></w:tc>
  </w:tr>
  <w:tr>
    <w:tc><w:p><w:r><w:t>Bob</w:t></w:r></w:p></w:tc>
    <w:tc><w:p><w:r><w:t>25</w:t></w:r></w:p></w:tc>
  </w:tr>
</w:tbl>
</w:body>
</w:document>"#;

    let mut buffer = Cursor::new(Vec::new());
    {
        let mut zip = ZipWriter::new(&mut buffer);
        let options = SimpleFileOptions::default();

        zip.start_file("[Content_Types].xml", options).unwrap();
        zip.write_all(br#"<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"></Types>"#).unwrap();

        zip.start_file("word/document.xml", options).unwrap();
        zip.write_all(document_xml.as_bytes()).unwrap();

        zip.finish().unwrap();
    }
    buffer.into_inner()
}
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion docx_parse_extracts_tables`
Expected: FAIL (tables is empty)

**Step 3: Implement table extraction**

```rust
// Modify parse_document_content to also extract tables

impl DocxParser {
    /// Parse the document.xml content and extract paragraphs and tables.
    fn parse_document_content(
        &self,
        xml: &str,
    ) -> Result<(Vec<String>, Vec<ContentBlock>, Vec<TableContent>)> {
        let mut reader = Reader::from_str(xml);
        reader.config_mut().trim_text(true);

        let mut paragraphs = Vec::new();
        let mut blocks = Vec::new();
        let mut tables = Vec::new();
        let mut current_paragraph = String::new();
        let mut in_paragraph = false;
        let mut in_text = false;
        let mut position = 0u32;

        // Table parsing state
        let mut in_table = false;
        let mut in_row = false;
        let mut in_cell = false;
        let mut current_table_rows: Vec<Vec<String>> = Vec::new();
        let mut current_row: Vec<String> = Vec::new();
        let mut current_cell = String::new();

        let mut buf = Vec::new();

        loop {
            match reader.read_event_into(&mut buf) {
                Ok(Event::Start(e)) => {
                    let local_name = e.local_name();
                    match local_name.as_ref() {
                        b"tbl" => {
                            in_table = true;
                            current_table_rows.clear();
                        }
                        b"tr" => {
                            in_row = true;
                            current_row.clear();
                        }
                        b"tc" => {
                            in_cell = true;
                            current_cell.clear();
                        }
                        b"p" if !in_table => {
                            in_paragraph = true;
                            current_paragraph.clear();
                        }
                        b"t" => {
                            in_text = true;
                        }
                        _ => {}
                    }
                }
                Ok(Event::Text(e)) => {
                    if in_text {
                        if let Ok(text) = e.unescape() {
                            if in_cell {
                                current_cell.push_str(&text);
                            } else if in_paragraph {
                                current_paragraph.push_str(&text);
                            }
                        }
                    }
                }
                Ok(Event::End(e)) => {
                    let local_name = e.local_name();
                    match local_name.as_ref() {
                        b"tbl" => {
                            in_table = false;
                            if self.config.extract_tables && !current_table_rows.is_empty() {
                                let (headers, rows) = if current_table_rows.len() > 1 {
                                    let headers = current_table_rows[0].clone();
                                    let rows = current_table_rows[1..].to_vec();
                                    (headers, rows)
                                } else {
                                    (current_table_rows[0].clone(), Vec::new())
                                };

                                tables.push(TableContent {
                                    headers,
                                    rows,
                                    caption: None,
                                });

                                // Also add as content block
                                let table_text = tables.last().unwrap().to_text();
                                blocks.push(ContentBlock {
                                    content_type: ContentType::Table,
                                    content: table_text,
                                    page_number: None,
                                    position: Some(position),
                                    metadata: HashMap::new(),
                                });
                                position += 1;
                            }
                        }
                        b"tr" => {
                            in_row = false;
                            if !current_row.is_empty() {
                                current_table_rows.push(current_row.clone());
                            }
                        }
                        b"tc" => {
                            in_cell = false;
                            current_row.push(current_cell.trim().to_string());
                        }
                        b"p" if !in_table => {
                            in_paragraph = false;
                            let trimmed = current_paragraph.trim().to_string();
                            if !trimmed.is_empty() {
                                paragraphs.push(trimmed.clone());
                                blocks.push(ContentBlock {
                                    content_type: ContentType::Text,
                                    content: trimmed,
                                    page_number: None,
                                    position: Some(position),
                                    metadata: HashMap::new(),
                                });
                                position += 1;
                            }
                        }
                        b"t" => {
                            in_text = false;
                        }
                        _ => {}
                    }
                }
                Ok(Event::Eof) => break,
                Err(e) => {
                    return Err(Error::Parse(format!("XML parsing error: {e}")));
                }
                _ => {}
            }
            buf.clear();
        }

        Ok((paragraphs, blocks, tables))
    }
}

// Update the Parser::parse implementation to use the new signature
impl Parser for DocxParser {
    fn supported_mime_types(&self) -> &[&str] {
        &["application/vnd.openxmlformats-officedocument.wordprocessingml.document"]
    }

    fn parse(
        &self,
        content: &[u8],
        metadata: Option<HashMap<String, serde_json::Value>>,
    ) -> Result<ParsedDocument> {
        let xml = self.extract_document_xml(content)?;
        let (paragraphs, blocks, tables) = self.parse_document_content(&xml)?;
        let core_props = self.extract_core_properties(content);

        let text = paragraphs.join("\n\n");
        let doc_metadata = metadata.unwrap_or_default();

        Ok(ParsedDocument {
            text,
            blocks,
            tables,
            title: core_props.as_ref().and_then(|p| p.title.clone()),
            author: core_props.as_ref().and_then(|p| p.author.clone()),
            created_date: core_props.as_ref().and_then(|p| p.created.clone()),
            modified_date: core_props.as_ref().and_then(|p| p.modified.clone()),
            page_count: None,
            language: None,
            metadata: doc_metadata,
        })
    }
}
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion docx`
Expected: All DOCX tests PASS

**Step 5: Commit**

```bash
git add crates/rag-ingestion/src/parsers/docx.rs
git commit -m "feat(rag-ingestion): add DOCX table extraction"
```

---

## Task 10: Register DOCX Parser in Module

**Files:**
- Modify: `crates/rag-ingestion/src/parsers/mod.rs`

**Step 1: Add docx module export**

```rust
//! Document parsers for various file formats.
//!
//! This module provides parsers for:
//! - HTML documents ([`HtmlParser`])
//! - Markdown documents ([`MarkdownParser`])
//! - PDF documents ([`PdfParser`]) - delegates to Python service
//! - DOCX documents ([`DocxParser`]) - pure Rust OOXML parsing

mod base;
mod docx;
mod html;
mod markdown;
mod pdf;

pub use base::{ContentBlock, ContentType, ParsedDocument, Parser, TableContent};
pub use docx::{DocxParser, DocxParserConfig};
pub use html::{HtmlParser, HtmlParserConfig};
pub use markdown::MarkdownParser;
pub use pdf::{PdfParser, PdfParserConfig};
```

**Step 2: Verify compilation**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo check -p rag-ingestion`
Expected: Compilation succeeds

**Step 3: Commit**

```bash
git add crates/rag-ingestion/src/parsers/mod.rs
git commit -m "feat(rag-ingestion): export DOCX parser from parsers module"
```

---

## Task 11: Semantic Chunker - Sentence Segmentation

**Files:**
- Create: `crates/rag-ingestion/src/chunking/semantic.rs`

**Step 1: Write the failing test for sentence segmentation**

```rust
// In crates/rag-ingestion/src/chunking/semantic.rs
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_split_into_sentences() {
        let text = "First sentence. Second sentence! Third one? Yes.";
        let sentences = split_into_sentences(text);

        assert_eq!(sentences.len(), 4);
        assert_eq!(sentences[0], "First sentence.");
        assert_eq!(sentences[1], "Second sentence!");
        assert_eq!(sentences[2], "Third one?");
        assert_eq!(sentences[3], "Yes.");
    }

    #[test]
    fn test_split_handles_abbreviations() {
        let text = "Dr. Smith went to Washington D.C. for the meeting.";
        let sentences = split_into_sentences(text);

        // Should not split on abbreviations
        assert_eq!(sentences.len(), 1);
    }
}
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion split_into_sentences`
Expected: FAIL with "cannot find function `split_into_sentences`"

**Step 3: Implement sentence segmentation**

```rust
//! Semantic chunker that splits text at sentence boundaries.
//!
//! Uses Unicode segmentation for language-independent sentence detection,
//! with special handling for common abbreviations.

use lazy_static::lazy_static;
use regex::Regex;
use rag_types::{ChunkId, DocumentId};
use serde_json::Value;
use std::collections::HashMap;
use tiktoken_rs::CoreBPE;
use unicode_segmentation::UnicodeSegmentation;

use super::base::{Chunk, ChunkingConfig, ChunkingStrategy};
use crate::{Error, Result};

lazy_static! {
    /// Common abbreviations that shouldn't trigger sentence breaks.
    static ref ABBREVIATIONS: Regex = Regex::new(
        r"(?i)\b(Mr|Mrs|Ms|Dr|Prof|Sr|Jr|vs|etc|i\.e|e\.g|Inc|Ltd|Corp|Co|St|Ave|Blvd|Rd|Mt|ft|lb|oz|pt|qt|gal|ml|cm|km|kg|[A-Z])\.$"
    ).unwrap();
}

/// Split text into sentences using Unicode segmentation.
///
/// Handles:
/// - Standard sentence endings (. ! ?)
/// - Abbreviations (Dr., etc.)
/// - Quoted sentences
pub fn split_into_sentences(text: &str) -> Vec<String> {
    let mut sentences = Vec::new();
    let mut current = String::new();

    for sentence in text.unicode_sentences() {
        let trimmed = sentence.trim();
        if trimmed.is_empty() {
            continue;
        }

        // Check if this ends with an abbreviation
        if ABBREVIATIONS.is_match(&current) && !current.is_empty() {
            // Merge with previous - this is a continuation
            current.push(' ');
            current.push_str(trimmed);
        } else if !current.is_empty() {
            sentences.push(current.clone());
            current = trimmed.to_string();
        } else {
            current = trimmed.to_string();
        }
    }

    // Don't forget the last sentence
    if !current.is_empty() {
        sentences.push(current);
    }

    sentences
}
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion split_into_sentences`
Expected: PASS

**Step 5: Commit**

```bash
git add crates/rag-ingestion/src/chunking/semantic.rs
git commit -m "feat(rag-ingestion): add sentence segmentation for semantic chunker"
```

---

## Task 12: Semantic Chunker - Strategy Implementation

**Files:**
- Modify: `crates/rag-ingestion/src/chunking/semantic.rs`

**Step 1: Write the failing test for semantic chunker**

```rust
// Add to tests module
#[test]
fn test_semantic_chunker_name() {
    let chunker = SemanticChunker::default();
    assert_eq!(chunker.name(), "semantic_sentence");
}

#[test]
fn test_semantic_chunker_groups_sentences() {
    let text = "First sentence here. Second sentence follows. Third sentence ends. Fourth one now.";
    let config = ChunkingConfig {
        target_tokens: 15,
        max_tokens: 30,
        chunk_overlap: 5,
        min_chunk_size: 5,
        ..Default::default()
    };

    let chunker = SemanticChunker::new(config).unwrap();
    let doc_id = DocumentId::new();
    let chunks = chunker.chunk(text, doc_id, None).unwrap();

    // Should create multiple chunks
    assert!(chunks.len() >= 2);

    // Each chunk should respect max_tokens
    for chunk in &chunks {
        assert!(chunk.token_count <= 30, "Chunk has {} tokens", chunk.token_count);
    }
}

#[test]
fn test_semantic_chunker_handles_long_sentences() {
    let long_sentence = "This is a very long sentence ".repeat(50);
    let config = ChunkingConfig {
        target_tokens: 20,
        max_tokens: 50,
        chunk_overlap: 5,
        min_chunk_size: 10,
        ..Default::default()
    };

    let chunker = SemanticChunker::new(config).unwrap();
    let chunks = chunker.chunk(&long_sentence, DocumentId::new(), None).unwrap();

    // Should split the long sentence
    assert!(chunks.len() > 1);
}
```

**Step 2: Run tests to verify they fail**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion semantic_chunker_name`
Expected: FAIL with "cannot find value `SemanticChunker`"

**Step 3: Implement the SemanticChunker**

```rust
// Add to semantic.rs after split_into_sentences

/// Semantic chunker that splits text at sentence boundaries.
///
/// This strategy produces more coherent chunks than character-based splitting
/// by respecting natural language boundaries.
pub struct SemanticChunker {
    config: ChunkingConfig,
    tokenizer: CoreBPE,
}

impl SemanticChunker {
    /// Create a new semantic chunker with the given configuration.
    ///
    /// # Errors
    ///
    /// Returns an error if the tokenizer cannot be loaded.
    pub fn new(config: ChunkingConfig) -> Result<Self> {
        let tokenizer = tiktoken_rs::cl100k_base()
            .map_err(|e| Error::Config(format!("Failed to load tokenizer: {e}")))?;

        Ok(Self { config, tokenizer })
    }

    /// Count tokens in text.
    #[allow(clippy::cast_possible_truncation)]
    fn count_tokens(&self, text: &str) -> u32 {
        self.tokenizer.encode_ordinary(text).len() as u32
    }

    /// Split a long sentence that exceeds max_tokens.
    fn split_long_sentence(&self, sentence: &str, start_offset: usize) -> Vec<(String, usize, usize)> {
        let tokens = self.tokenizer.encode_ordinary(sentence);
        let max = self.config.max_tokens as usize;
        let mut parts = Vec::new();
        let mut char_offset = start_offset;
        let mut i = 0;

        while i < tokens.len() {
            let chunk_tokens: Vec<_> = tokens[i..(i + max).min(tokens.len())].to_vec();
            let chunk_text = self.tokenizer.decode(chunk_tokens.clone()).unwrap_or_default();
            let len = chunk_text.len();

            parts.push((chunk_text, char_offset, char_offset + len));
            char_offset += len;
            i += max;
        }

        parts
    }

    /// Get sentences for overlap from the end of a chunk.
    fn get_overlap_sentences(&self, sentences: &[String]) -> Vec<String> {
        let mut result = Vec::new();
        let mut total_tokens = 0;
        let overlap = self.config.chunk_overlap;

        for sent in sentences.iter().rev() {
            let tokens = self.count_tokens(sent);
            if total_tokens + tokens > overlap {
                break;
            }
            result.insert(0, sent.clone());
            total_tokens += tokens;
        }

        result
    }
}

impl Default for SemanticChunker {
    fn default() -> Self {
        Self::new(ChunkingConfig::default()).expect("Default tokenizer should load")
    }
}

impl ChunkingStrategy for SemanticChunker {
    fn name(&self) -> &str {
        "semantic_sentence"
    }

    fn config(&self) -> &ChunkingConfig {
        &self.config
    }

    fn chunk(
        &self,
        text: &str,
        document_id: DocumentId,
        metadata: Option<HashMap<String, Value>>,
    ) -> Result<Vec<Chunk>> {
        let metadata = metadata.unwrap_or_default();
        let sentences = split_into_sentences(text);

        let mut chunks = Vec::new();
        let mut current_sentences: Vec<String> = Vec::new();
        let mut current_tokens = 0u32;
        let mut current_start = 0usize;
        let mut char_offset = 0usize;
        let mut chunk_index = 0u32;

        for sentence in sentences {
            let sent_tokens = self.count_tokens(&sentence);
            let sent_len = sentence.len();

            // Handle sentences that exceed max_tokens
            if sent_tokens > self.config.max_tokens {
                // Flush current chunk first
                if !current_sentences.is_empty() {
                    let content = current_sentences.join(" ");
                    let end = char_offset;
                    chunks.push(Chunk {
                        chunk_id: ChunkId::new(),
                        document_id,
                        content: content.clone(),
                        chunk_index,
                        start_char: current_start,
                        end_char: end,
                        token_count: self.count_tokens(&content),
                        parent_chunk_id: None,
                        child_chunk_ids: Vec::new(),
                        metadata: metadata.clone(),
                        source_page: None,
                        source_section: None,
                    });
                    chunk_index += 1;
                    current_sentences.clear();
                    current_tokens = 0;
                }

                // Split long sentence into sub-chunks
                let sub_chunks = self.split_long_sentence(&sentence, char_offset);
                for (content, start, end) in sub_chunks {
                    chunks.push(Chunk {
                        chunk_id: ChunkId::new(),
                        document_id,
                        content: content.clone(),
                        chunk_index,
                        start_char: start,
                        end_char: end,
                        token_count: self.count_tokens(&content),
                        parent_chunk_id: None,
                        child_chunk_ids: Vec::new(),
                        metadata: metadata.clone(),
                        source_page: None,
                        source_section: None,
                    });
                    chunk_index += 1;
                }

                char_offset += sent_len + 1; // +1 for space
                current_start = char_offset;
                continue;
            }

            // Check if adding this sentence exceeds target
            if current_tokens + sent_tokens > self.config.target_tokens && !current_sentences.is_empty() {
                // Create chunk from current sentences
                let content = current_sentences.join(" ");
                let end = char_offset;
                chunks.push(Chunk {
                    chunk_id: ChunkId::new(),
                    document_id,
                    content: content.clone(),
                    chunk_index,
                    start_char: current_start,
                    end_char: end,
                    token_count: self.count_tokens(&content),
                    parent_chunk_id: None,
                    child_chunk_ids: Vec::new(),
                    metadata: metadata.clone(),
                    source_page: None,
                    source_section: None,
                });
                chunk_index += 1;

                // Get overlap sentences
                let overlap_sentences = self.get_overlap_sentences(&current_sentences);
                current_sentences = overlap_sentences;
                current_sentences.push(sentence);
                current_tokens = current_sentences.iter().map(|s| self.count_tokens(s)).sum();
                current_start = char_offset;
            } else {
                if current_sentences.is_empty() {
                    current_start = char_offset;
                }
                current_sentences.push(sentence);
                current_tokens += sent_tokens;
            }

            char_offset += sent_len + 1; // +1 for space between sentences
        }

        // Don't forget the last chunk
        if !current_sentences.is_empty() {
            let content = current_sentences.join(" ");
            chunks.push(Chunk {
                chunk_id: ChunkId::new(),
                document_id,
                content: content.clone(),
                chunk_index,
                start_char: current_start,
                end_char: text.len(),
                token_count: self.count_tokens(&content),
                parent_chunk_id: None,
                child_chunk_ids: Vec::new(),
                metadata: metadata.clone(),
                source_page: None,
                source_section: None,
            });
        }

        Ok(chunks)
    }
}
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion semantic_chunker`
Expected: PASS

**Step 5: Commit**

```bash
git add crates/rag-ingestion/src/chunking/semantic.rs
git commit -m "feat(rag-ingestion): implement semantic chunker strategy"
```

---

## Task 13: Register Semantic Chunker in Module

**Files:**
- Modify: `crates/rag-ingestion/src/chunking/mod.rs`

**Step 1: Add semantic module export**

```rust
//! Text chunking strategies for document processing.
//!
//! This module provides chunking strategies for splitting documents
//! into chunks suitable for embedding:
//! - [`RecursiveCharacterSplitter`]: Split by paragraphs, sentences, words
//! - [`SemanticChunker`]: Split at sentence boundaries

mod base;
mod recursive;
mod semantic;

pub use base::{Chunk, ChunkingConfig, ChunkingResult, ChunkingStrategy};
pub use recursive::RecursiveCharacterSplitter;
pub use semantic::SemanticChunker;
```

**Step 2: Update lib.rs to export SemanticChunker**

In `crates/rag-ingestion/src/lib.rs`, update the chunking re-exports:

```rust
// Chunking (commonly used)
pub use chunking::{Chunk, ChunkingConfig, ChunkingStrategy, RecursiveCharacterSplitter, SemanticChunker};
```

**Step 3: Verify compilation**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo check -p rag-ingestion`
Expected: Compilation succeeds

**Step 4: Commit**

```bash
git add crates/rag-ingestion/src/chunking/mod.rs crates/rag-ingestion/src/lib.rs
git commit -m "feat(rag-ingestion): export semantic chunker from chunking module"
```

---

## Task 14: PII Detection - Pattern Types

**Files:**
- Create: `crates/rag-ingestion/src/pii/mod.rs`
- Create: `crates/rag-ingestion/src/pii/types.rs`

**Step 1: Write the failing test for PII types**

```rust
// In crates/rag-ingestion/src/pii/types.rs
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_pii_type_display() {
        assert_eq!(PiiType::Email.as_str(), "EMAIL");
        assert_eq!(PiiType::Phone.as_str(), "PHONE");
        assert_eq!(PiiType::Ssn.as_str(), "SSN");
        assert_eq!(PiiType::CreditCard.as_str(), "CREDIT_CARD");
    }

    #[test]
    fn test_pii_entity_creation() {
        let entity = PiiEntity {
            entity_type: PiiType::Email,
            text: "test@example.com".to_string(),
            start: 0,
            end: 16,
            score: 0.95,
        };
        assert_eq!(entity.entity_type, PiiType::Email);
    }
}
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion pii_type_display`
Expected: FAIL with "cannot find value `PiiType`"

**Step 3: Implement PII types**

```rust
// crates/rag-ingestion/src/pii/types.rs

//! PII detection types and models.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

/// Types of PII that can be detected.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum PiiType {
    /// Email address
    Email,
    /// Phone number
    Phone,
    /// Social Security Number (US)
    Ssn,
    /// Credit card number
    CreditCard,
    /// IP address
    IpAddress,
    /// Person name (requires NLP, not implemented in regex-only mode)
    Person,
    /// Location (requires NLP, not implemented in regex-only mode)
    Location,
}

impl PiiType {
    /// Get the string representation of the PII type.
    #[must_use]
    pub const fn as_str(&self) -> &'static str {
        match self {
            Self::Email => "EMAIL",
            Self::Phone => "PHONE",
            Self::Ssn => "SSN",
            Self::CreditCard => "CREDIT_CARD",
            Self::IpAddress => "IP_ADDRESS",
            Self::Person => "PERSON",
            Self::Location => "LOCATION",
        }
    }
}

/// A detected PII entity.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PiiEntity {
    /// Type of PII detected.
    pub entity_type: PiiType,
    /// The actual text that was detected.
    pub text: String,
    /// Start character offset in the original text.
    pub start: usize,
    /// End character offset in the original text.
    pub end: usize,
    /// Confidence score (0.0 to 1.0).
    pub score: f64,
}

/// Result of PII detection on a text.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PiiResult {
    /// All detected PII entities.
    pub entities: Vec<PiiEntity>,
    /// Count of entities by type.
    pub entity_counts: HashMap<PiiType, usize>,
    /// Whether any PII was detected.
    pub has_pii: bool,
    /// Whether high-sensitivity PII was detected (SSN, credit card).
    pub high_sensitivity: bool,
}

impl Default for PiiResult {
    fn default() -> Self {
        Self {
            entities: Vec::new(),
            entity_counts: HashMap::new(),
            has_pii: false,
            high_sensitivity: false,
        }
    }
}
```

```rust
// crates/rag-ingestion/src/pii/mod.rs

//! PII (Personally Identifiable Information) detection.
//!
//! This module provides regex-based PII detection for common patterns:
//! - Email addresses
//! - Phone numbers (US format)
//! - Social Security Numbers
//! - Credit card numbers
//! - IP addresses
//!
//! Note: This covers ~80% of PII detection use cases. For NER-based
//! detection of names and locations, consider using the Python Presidio
//! service via HTTP.

mod types;

pub use types::{PiiEntity, PiiResult, PiiType};
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion pii_type`
Expected: PASS

**Step 5: Commit**

```bash
git add crates/rag-ingestion/src/pii/
git commit -m "feat(rag-ingestion): add PII detection types"
```

---

## Task 15: PII Detection - Regex Patterns

**Files:**
- Create: `crates/rag-ingestion/src/pii/patterns.rs`
- Modify: `crates/rag-ingestion/src/pii/mod.rs`

**Step 1: Write the failing test for pattern matching**

```rust
// In crates/rag-ingestion/src/pii/patterns.rs
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_email_pattern() {
        let re = &PATTERNS.email;
        assert!(re.is_match("test@example.com"));
        assert!(re.is_match("user.name+tag@domain.co.uk"));
        assert!(!re.is_match("not an email"));
    }

    #[test]
    fn test_phone_pattern() {
        let re = &PATTERNS.phone;
        assert!(re.is_match("(555) 123-4567"));
        assert!(re.is_match("555-123-4567"));
        assert!(re.is_match("555.123.4567"));
        assert!(re.is_match("+1 555 123 4567"));
    }

    #[test]
    fn test_ssn_pattern() {
        let re = &PATTERNS.ssn;
        assert!(re.is_match("123-45-6789"));
        assert!(re.is_match("123 45 6789"));
        assert!(!re.is_match("123456789")); // No separators - not matched for safety
    }

    #[test]
    fn test_credit_card_pattern() {
        let re = &PATTERNS.credit_card;
        assert!(re.is_match("4111-1111-1111-1111")); // Visa
        assert!(re.is_match("4111 1111 1111 1111"));
        assert!(re.is_match("5500000000000004")); // MasterCard
    }

    #[test]
    fn test_ip_address_pattern() {
        let re = &PATTERNS.ip_address;
        assert!(re.is_match("192.168.1.1"));
        assert!(re.is_match("10.0.0.1"));
        assert!(!re.is_match("999.999.999.999")); // Invalid octets
    }
}
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion email_pattern`
Expected: FAIL with "cannot find value `PATTERNS`"

**Step 3: Implement pattern definitions**

```rust
// crates/rag-ingestion/src/pii/patterns.rs

//! Regex patterns for PII detection.

use lazy_static::lazy_static;
use regex::Regex;

/// Collection of compiled regex patterns for PII detection.
pub struct PiiPatterns {
    pub email: Regex,
    pub phone: Regex,
    pub ssn: Regex,
    pub credit_card: Regex,
    pub ip_address: Regex,
}

lazy_static! {
    /// Pre-compiled PII detection patterns.
    pub static ref PATTERNS: PiiPatterns = PiiPatterns {
        // Email: RFC 5322 simplified
        email: Regex::new(
            r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
        ).unwrap(),

        // Phone: US formats with optional country code
        // Matches: (555) 123-4567, 555-123-4567, 555.123.4567, +1 555 123 4567
        phone: Regex::new(
            r"(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}"
        ).unwrap(),

        // SSN: Must have separators to avoid false positives
        // Matches: 123-45-6789, 123 45 6789
        ssn: Regex::new(
            r"\b[0-9]{3}[-\s][0-9]{2}[-\s][0-9]{4}\b"
        ).unwrap(),

        // Credit card: Major brands with optional separators
        // Visa: 4xxx, MC: 5[1-5]xx, Amex: 3[47]xx, Discover: 6xxx
        credit_card: Regex::new(
            r"\b(?:4[0-9]{3}|5[1-5][0-9]{2}|3[47][0-9]{2}|6(?:011|5[0-9]{2}))[- ]?[0-9]{4}[- ]?[0-9]{4}[- ]?[0-9]{4}\b"
        ).unwrap(),

        // IPv4 address with valid octet ranges
        ip_address: Regex::new(
            r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b"
        ).unwrap(),
    };
}
```

**Step 4: Update mod.rs to include patterns**

```rust
// crates/rag-ingestion/src/pii/mod.rs

//! PII (Personally Identifiable Information) detection.

mod patterns;
mod types;

pub use patterns::PATTERNS;
pub use types::{PiiEntity, PiiResult, PiiType};
```

**Step 5: Run tests to verify they pass**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion -- pii::patterns`
Expected: PASS

**Step 6: Commit**

```bash
git add crates/rag-ingestion/src/pii/
git commit -m "feat(rag-ingestion): add PII regex patterns"
```

---

## Task 16: PII Detection - Detector Implementation

**Files:**
- Create: `crates/rag-ingestion/src/pii/detector.rs`
- Modify: `crates/rag-ingestion/src/pii/mod.rs`

**Step 1: Write the failing test for detector**

```rust
// In crates/rag-ingestion/src/pii/detector.rs
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_detector_default_config() {
        let detector = PiiDetector::default();
        assert!(detector.config.detect_email);
        assert!(detector.config.detect_phone);
        assert_eq!(detector.config.score_threshold, 0.7);
    }

    #[test]
    fn test_detect_email() {
        let detector = PiiDetector::default();
        let text = "Contact me at john.doe@example.com for more info.";
        let result = detector.detect(text);

        assert!(result.has_pii);
        assert_eq!(result.entities.len(), 1);
        assert_eq!(result.entities[0].entity_type, PiiType::Email);
        assert_eq!(result.entities[0].text, "john.doe@example.com");
    }

    #[test]
    fn test_detect_multiple_types() {
        let detector = PiiDetector::default();
        let text = "Email: test@example.com, Phone: (555) 123-4567, SSN: 123-45-6789";
        let result = detector.detect(text);

        assert!(result.has_pii);
        assert!(result.high_sensitivity); // SSN detected
        assert_eq!(result.entities.len(), 3);
    }

    #[test]
    fn test_detect_no_pii() {
        let detector = PiiDetector::default();
        let text = "This is a normal text without any personal information.";
        let result = detector.detect(text);

        assert!(!result.has_pii);
        assert!(result.entities.is_empty());
    }

    #[test]
    fn test_redact() {
        let detector = PiiDetector::default();
        let text = "Contact john@example.com or call 555-123-4567";
        let redacted = detector.redact(text);

        assert!(redacted.contains("[EMAIL]"));
        assert!(redacted.contains("[PHONE]"));
        assert!(!redacted.contains("john@example.com"));
    }
}
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion detector_default_config`
Expected: FAIL with "cannot find value `PiiDetector`"

**Step 3: Implement the PiiDetector**

```rust
// crates/rag-ingestion/src/pii/detector.rs

//! PII detector implementation using regex patterns.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;

use super::patterns::PATTERNS;
use super::types::{PiiEntity, PiiResult, PiiType};

/// Configuration for PII detection.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PiiDetectorConfig {
    /// Minimum confidence score to report a match.
    pub score_threshold: f64,
    /// Whether to detect email addresses.
    pub detect_email: bool,
    /// Whether to detect phone numbers.
    pub detect_phone: bool,
    /// Whether to detect SSNs.
    pub detect_ssn: bool,
    /// Whether to detect credit card numbers.
    pub detect_credit_card: bool,
    /// Whether to detect IP addresses.
    pub detect_ip_address: bool,
    /// High-sensitivity types that trigger the high_sensitivity flag.
    pub high_sensitivity_types: Vec<PiiType>,
}

impl Default for PiiDetectorConfig {
    fn default() -> Self {
        Self {
            score_threshold: 0.7,
            detect_email: true,
            detect_phone: true,
            detect_ssn: true,
            detect_credit_card: true,
            detect_ip_address: true,
            high_sensitivity_types: vec![PiiType::Ssn, PiiType::CreditCard],
        }
    }
}

/// PII detector using regex patterns.
///
/// Detects common PII patterns without requiring NLP models.
/// Covers approximately 80% of common PII detection use cases.
pub struct PiiDetector {
    pub config: PiiDetectorConfig,
}

impl PiiDetector {
    /// Create a new PII detector with custom configuration.
    #[must_use]
    pub fn new(config: PiiDetectorConfig) -> Self {
        Self { config }
    }

    /// Detect PII in the given text.
    #[must_use]
    pub fn detect(&self, text: &str) -> PiiResult {
        let mut entities = Vec::new();
        let mut entity_counts: HashMap<PiiType, usize> = HashMap::new();
        let mut high_sensitivity = false;

        // Detect each PII type
        if self.config.detect_email {
            self.detect_pattern(text, &PATTERNS.email, PiiType::Email, &mut entities);
        }
        if self.config.detect_phone {
            self.detect_pattern(text, &PATTERNS.phone, PiiType::Phone, &mut entities);
        }
        if self.config.detect_ssn {
            self.detect_pattern(text, &PATTERNS.ssn, PiiType::Ssn, &mut entities);
        }
        if self.config.detect_credit_card {
            self.detect_pattern(text, &PATTERNS.credit_card, PiiType::CreditCard, &mut entities);
        }
        if self.config.detect_ip_address {
            self.detect_pattern(text, &PATTERNS.ip_address, PiiType::IpAddress, &mut entities);
        }

        // Sort by position
        entities.sort_by_key(|e| e.start);

        // Count entities and check sensitivity
        for entity in &entities {
            *entity_counts.entry(entity.entity_type).or_insert(0) += 1;
            if self.config.high_sensitivity_types.contains(&entity.entity_type) {
                high_sensitivity = true;
            }
        }

        let has_pii = !entities.is_empty();

        PiiResult {
            entities,
            entity_counts,
            has_pii,
            high_sensitivity,
        }
    }

    /// Redact PII from text, replacing with placeholders like [EMAIL].
    #[must_use]
    pub fn redact(&self, text: &str) -> String {
        let result = self.detect(text);
        if result.entities.is_empty() {
            return text.to_string();
        }

        // Sort entities by position descending to replace from end
        let mut sorted_entities = result.entities;
        sorted_entities.sort_by(|a, b| b.start.cmp(&a.start));

        let mut redacted = text.to_string();
        for entity in sorted_entities {
            let placeholder = format!("[{}]", entity.entity_type.as_str());
            redacted.replace_range(entity.start..entity.end, &placeholder);
        }

        redacted
    }

    /// Detect matches for a single pattern type.
    fn detect_pattern(
        &self,
        text: &str,
        pattern: &regex::Regex,
        pii_type: PiiType,
        entities: &mut Vec<PiiEntity>,
    ) {
        for mat in pattern.find_iter(text) {
            entities.push(PiiEntity {
                entity_type: pii_type,
                text: mat.as_str().to_string(),
                start: mat.start(),
                end: mat.end(),
                score: 1.0, // Regex matches are deterministic
            });
        }
    }
}

impl Default for PiiDetector {
    fn default() -> Self {
        Self::new(PiiDetectorConfig::default())
    }
}
```

**Step 4: Update mod.rs**

```rust
// crates/rag-ingestion/src/pii/mod.rs

//! PII (Personally Identifiable Information) detection.
//!
//! This module provides regex-based PII detection for common patterns:
//! - Email addresses
//! - Phone numbers (US format)
//! - Social Security Numbers
//! - Credit card numbers
//! - IP addresses
//!
//! Note: This covers ~80% of PII detection use cases. For NER-based
//! detection of names and locations, consider using the Python Presidio
//! service via HTTP.

mod detector;
mod patterns;
mod types;

pub use detector::{PiiDetector, PiiDetectorConfig};
pub use patterns::PATTERNS;
pub use types::{PiiEntity, PiiResult, PiiType};
```

**Step 5: Run tests to verify they pass**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion -- pii::detector`
Expected: PASS

**Step 6: Commit**

```bash
git add crates/rag-ingestion/src/pii/
git commit -m "feat(rag-ingestion): implement PII detector with redaction"
```

---

## Task 17: Register PII Module in lib.rs

**Files:**
- Modify: `crates/rag-ingestion/src/lib.rs`

**Step 1: Add pii module to lib.rs**

Add after the existing module declarations:

```rust
pub mod api;
pub mod chunking;
pub mod connectors;
pub mod embedding;
pub mod error;
pub mod indexing;
pub mod parsers;
pub mod pii;  // Add this line
```

Add PII re-exports:

```rust
// PII detection
pub use pii::{PiiDetector, PiiDetectorConfig, PiiEntity, PiiResult, PiiType};
```

**Step 2: Verify compilation**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo check -p rag-ingestion`
Expected: Compilation succeeds

**Step 3: Commit**

```bash
git add crates/rag-ingestion/src/lib.rs
git commit -m "feat(rag-ingestion): export PII detection module"
```

---

## Task 18: Async Worker System - Job Types

**Files:**
- Create: `crates/rag-ingestion/src/worker/mod.rs`
- Create: `crates/rag-ingestion/src/worker/types.rs`

**Step 1: Write the failing test for job types**

```rust
// In crates/rag-ingestion/src/worker/types.rs
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_job_status_transitions() {
        assert!(JobStatus::Pending.can_transition_to(JobStatus::Running));
        assert!(JobStatus::Running.can_transition_to(JobStatus::Completed));
        assert!(JobStatus::Running.can_transition_to(JobStatus::Failed));
        assert!(!JobStatus::Completed.can_transition_to(JobStatus::Running));
    }

    #[test]
    fn test_job_serialization() {
        let job = Job {
            id: JobId::new(),
            job_type: JobType::Ingest,
            status: JobStatus::Pending,
            payload: serde_json::json!({"document_id": "test"}),
            created_at: chrono::Utc::now(),
            updated_at: chrono::Utc::now(),
            attempts: 0,
            max_attempts: 3,
            error: None,
        };

        let json = serde_json::to_string(&job).unwrap();
        let parsed: Job = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.id, job.id);
        assert_eq!(parsed.job_type, JobType::Ingest);
    }
}
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion job_status_transitions`
Expected: FAIL with "cannot find value `JobStatus`"

**Step 3: Implement job types**

```rust
// crates/rag-ingestion/src/worker/types.rs

//! Job types for the async worker system.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// Unique identifier for a job.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct JobId(Uuid);

impl JobId {
    /// Create a new random job ID.
    #[must_use]
    pub fn new() -> Self {
        Self(Uuid::new_v4())
    }

    /// Get the inner UUID.
    #[must_use]
    pub fn as_uuid(&self) -> Uuid {
        self.0
    }
}

impl Default for JobId {
    fn default() -> Self {
        Self::new()
    }
}

impl std::fmt::Display for JobId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

/// Types of jobs that can be processed.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum JobType {
    /// Document ingestion job.
    Ingest,
    /// Embedding generation job.
    Embed,
    /// Re-embedding job for model migration.
    Reembed,
    /// Document deletion job.
    Delete,
}

/// Status of a job.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum JobStatus {
    /// Job is waiting to be processed.
    Pending,
    /// Job is currently being processed.
    Running,
    /// Job completed successfully.
    Completed,
    /// Job failed after all retry attempts.
    Failed,
    /// Job was cancelled.
    Cancelled,
}

impl JobStatus {
    /// Check if transition to another status is valid.
    #[must_use]
    pub fn can_transition_to(&self, target: Self) -> bool {
        matches!(
            (self, target),
            (Self::Pending, Self::Running)
                | (Self::Pending, Self::Cancelled)
                | (Self::Running, Self::Completed)
                | (Self::Running, Self::Failed)
                | (Self::Running, Self::Pending) // For retry
        )
    }
}

/// A job to be processed by the worker system.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Job {
    /// Unique job identifier.
    pub id: JobId,
    /// Type of job.
    pub job_type: JobType,
    /// Current status.
    pub status: JobStatus,
    /// Job payload (JSON).
    pub payload: serde_json::Value,
    /// When the job was created.
    pub created_at: DateTime<Utc>,
    /// When the job was last updated.
    pub updated_at: DateTime<Utc>,
    /// Number of processing attempts.
    pub attempts: u32,
    /// Maximum retry attempts.
    pub max_attempts: u32,
    /// Error message if failed.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

impl Job {
    /// Create a new job with the given type and payload.
    #[must_use]
    pub fn new(job_type: JobType, payload: serde_json::Value) -> Self {
        let now = Utc::now();
        Self {
            id: JobId::new(),
            job_type,
            status: JobStatus::Pending,
            payload,
            created_at: now,
            updated_at: now,
            attempts: 0,
            max_attempts: 3,
            error: None,
        }
    }

    /// Mark the job as running.
    pub fn start(&mut self) {
        self.status = JobStatus::Running;
        self.attempts += 1;
        self.updated_at = Utc::now();
    }

    /// Mark the job as completed.
    pub fn complete(&mut self) {
        self.status = JobStatus::Completed;
        self.updated_at = Utc::now();
    }

    /// Mark the job as failed.
    pub fn fail(&mut self, error: impl Into<String>) {
        self.error = Some(error.into());
        self.updated_at = Utc::now();

        if self.attempts >= self.max_attempts {
            self.status = JobStatus::Failed;
        } else {
            self.status = JobStatus::Pending; // Retry
        }
    }
}
```

```rust
// crates/rag-ingestion/src/worker/mod.rs

//! Async worker system for background job processing.
//!
//! This module provides a Redis-based job queue system for processing
//! ingestion tasks asynchronously:
//!
//! - Job queues using Redis lists (LPUSH/BRPOP)
//! - Configurable worker pools with tokio
//! - Job status tracking
//! - Dead letter queue for failed jobs
//! - Graceful shutdown support

mod types;

pub use types::{Job, JobId, JobStatus, JobType};
```

**Step 4: Run tests to verify they pass**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion -- worker::types`
Expected: PASS

**Step 5: Commit**

```bash
git add crates/rag-ingestion/src/worker/
git commit -m "feat(rag-ingestion): add worker job types"
```

---

## Task 19: Async Worker System - Queue Client

**Files:**
- Create: `crates/rag-ingestion/src/worker/queue.rs`
- Modify: `crates/rag-ingestion/src/worker/mod.rs`

**Step 1: Write the failing test for queue client**

```rust
// In crates/rag-ingestion/src/worker/queue.rs
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_queue_config_default() {
        let config = QueueConfig::default();
        assert_eq!(config.queue_prefix, "rag:jobs");
        assert_eq!(config.default_queue, "ingestion");
    }

    #[test]
    fn test_queue_names() {
        let config = QueueConfig::default();
        assert_eq!(config.queue_name("ingestion"), "rag:jobs:ingestion");
        assert_eq!(config.dlq_name("ingestion"), "rag:jobs:ingestion:dlq");
    }
}
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion queue_config_default`
Expected: FAIL with "cannot find value `QueueConfig`"

**Step 3: Implement queue configuration**

```rust
// crates/rag-ingestion/src/worker/queue.rs

//! Redis-based job queue implementation.

use redis::aio::ConnectionManager;
use redis::{AsyncCommands, Client};
use serde::{Deserialize, Serialize};
use std::time::Duration;
use tracing::{debug, instrument, warn};

use super::types::{Job, JobId};
use crate::{Error, Result};

/// Configuration for the job queue.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct QueueConfig {
    /// Redis URL.
    pub redis_url: String,
    /// Prefix for all queue keys.
    pub queue_prefix: String,
    /// Default queue name.
    pub default_queue: String,
    /// Timeout for blocking pop operations (seconds).
    pub pop_timeout_secs: u64,
    /// Visibility timeout - how long a job can be processing before considered stuck.
    pub visibility_timeout_secs: u64,
}

impl Default for QueueConfig {
    fn default() -> Self {
        Self {
            redis_url: "redis://localhost:6379".to_string(),
            queue_prefix: "rag:jobs".to_string(),
            default_queue: "ingestion".to_string(),
            pop_timeout_secs: 5,
            visibility_timeout_secs: 300, // 5 minutes
        }
    }
}

impl QueueConfig {
    /// Get the full queue name with prefix.
    #[must_use]
    pub fn queue_name(&self, queue: &str) -> String {
        format!("{}:{}", self.queue_prefix, queue)
    }

    /// Get the dead letter queue name.
    #[must_use]
    pub fn dlq_name(&self, queue: &str) -> String {
        format!("{}:{}:dlq", self.queue_prefix, queue)
    }

    /// Get the processing set name (for visibility timeout tracking).
    #[must_use]
    pub fn processing_name(&self, queue: &str) -> String {
        format!("{}:{}:processing", self.queue_prefix, queue)
    }
}

/// Redis-based job queue client.
#[derive(Clone)]
pub struct JobQueue {
    conn: ConnectionManager,
    config: QueueConfig,
}

impl JobQueue {
    /// Connect to Redis and create a new job queue.
    ///
    /// # Errors
    ///
    /// Returns an error if the connection fails.
    #[instrument(skip(config), fields(url = %config.redis_url))]
    pub async fn connect(config: QueueConfig) -> Result<Self> {
        debug!("Connecting to Redis for job queue");

        let client = Client::open(config.redis_url.as_str())
            .map_err(|e| Error::Config(format!("Failed to create Redis client: {e}")))?;

        let conn = ConnectionManager::new(client)
            .await
            .map_err(|e| Error::Config(format!("Failed to connect to Redis: {e}")))?;

        debug!("Successfully connected to Redis job queue");

        Ok(Self { conn, config })
    }

    /// Push a job to the queue.
    #[instrument(skip(self, job), fields(job_id = %job.id, job_type = ?job.job_type))]
    pub async fn push(&self, job: &Job, queue: Option<&str>) -> Result<()> {
        let queue_name = self.config.queue_name(queue.unwrap_or(&self.config.default_queue));
        let serialized = serde_json::to_string(job)?;

        let mut conn = self.conn.clone();
        conn.lpush::<_, _, ()>(&queue_name, &serialized)
            .await
            .map_err(|e| Error::Indexing(format!("Failed to push job: {e}")))?;

        debug!("Pushed job to queue {}", queue_name);
        Ok(())
    }

    /// Pop a job from the queue (blocking).
    ///
    /// Returns `None` if no job is available within the timeout.
    #[instrument(skip(self))]
    pub async fn pop(&self, queue: Option<&str>) -> Result<Option<Job>> {
        let queue_name = self.config.queue_name(queue.unwrap_or(&self.config.default_queue));

        let mut conn = self.conn.clone();
        let result: Option<(String, String)> = conn
            .brpop(&queue_name, self.config.pop_timeout_secs as f64)
            .await
            .map_err(|e| Error::Indexing(format!("Failed to pop job: {e}")))?;

        match result {
            Some((_, job_json)) => {
                let job: Job = serde_json::from_str(&job_json)?;
                debug!(job_id = %job.id, "Popped job from queue");
                Ok(Some(job))
            }
            None => Ok(None),
        }
    }

    /// Move a job to the dead letter queue.
    #[instrument(skip(self, job), fields(job_id = %job.id))]
    pub async fn move_to_dlq(&self, job: &Job, queue: Option<&str>) -> Result<()> {
        let dlq_name = self.config.dlq_name(queue.unwrap_or(&self.config.default_queue));
        let serialized = serde_json::to_string(job)?;

        let mut conn = self.conn.clone();
        conn.lpush::<_, _, ()>(&dlq_name, &serialized)
            .await
            .map_err(|e| Error::Indexing(format!("Failed to move job to DLQ: {e}")))?;

        warn!(job_id = %job.id, "Moved failed job to DLQ");
        Ok(())
    }

    /// Get the length of a queue.
    #[instrument(skip(self))]
    pub async fn queue_length(&self, queue: Option<&str>) -> Result<usize> {
        let queue_name = self.config.queue_name(queue.unwrap_or(&self.config.default_queue));

        let mut conn = self.conn.clone();
        let len: usize = conn
            .llen(&queue_name)
            .await
            .map_err(|e| Error::Indexing(format!("Failed to get queue length: {e}")))?;

        Ok(len)
    }

    /// Check if the queue connection is healthy.
    pub async fn health_check(&self) -> Result<()> {
        let mut conn = self.conn.clone();
        let _: String = redis::cmd("PING")
            .query_async(&mut conn)
            .await
            .map_err(|e| Error::Indexing(format!("Redis health check failed: {e}")))?;
        Ok(())
    }
}

impl std::fmt::Debug for JobQueue {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("JobQueue")
            .field("config", &self.config)
            .finish_non_exhaustive()
    }
}
```

**Step 4: Update mod.rs**

```rust
// crates/rag-ingestion/src/worker/mod.rs

//! Async worker system for background job processing.

mod queue;
mod types;

pub use queue::{JobQueue, QueueConfig};
pub use types::{Job, JobId, JobStatus, JobType};
```

**Step 5: Run tests to verify they pass**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion -- worker::queue`
Expected: PASS

**Step 6: Commit**

```bash
git add crates/rag-ingestion/src/worker/
git commit -m "feat(rag-ingestion): add Redis job queue client"
```

---

## Task 20: Async Worker System - Worker Pool

**Files:**
- Create: `crates/rag-ingestion/src/worker/pool.rs`
- Modify: `crates/rag-ingestion/src/worker/mod.rs`

**Step 1: Write the failing test for worker pool**

```rust
// In crates/rag-ingestion/src/worker/pool.rs
#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_worker_pool_config_default() {
        let config = WorkerPoolConfig::default();
        assert_eq!(config.concurrency, 4);
        assert!(config.graceful_shutdown_timeout_secs > 0);
    }
}
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion worker_pool_config_default`
Expected: FAIL with "cannot find value `WorkerPoolConfig`"

**Step 3: Implement worker pool**

```rust
// crates/rag-ingestion/src/worker/pool.rs

//! Worker pool for processing jobs concurrently.

use serde::{Deserialize, Serialize};
use std::future::Future;
use std::pin::Pin;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use tokio::sync::Semaphore;
use tokio::task::JoinSet;
use tracing::{debug, error, info, instrument, warn};

use super::queue::JobQueue;
use super::types::{Job, JobStatus};
use crate::Result;

/// Configuration for the worker pool.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WorkerPoolConfig {
    /// Number of concurrent workers.
    pub concurrency: usize,
    /// Queue to process jobs from.
    pub queue: String,
    /// Graceful shutdown timeout in seconds.
    pub graceful_shutdown_timeout_secs: u64,
}

impl Default for WorkerPoolConfig {
    fn default() -> Self {
        Self {
            concurrency: 4,
            queue: "ingestion".to_string(),
            graceful_shutdown_timeout_secs: 30,
        }
    }
}

/// Type alias for job handler functions.
pub type JobHandler = Box<
    dyn Fn(Job) -> Pin<Box<dyn Future<Output = Result<()>> + Send>> + Send + Sync,
>;

/// Worker pool for processing jobs from a queue.
pub struct WorkerPool {
    config: WorkerPoolConfig,
    queue: JobQueue,
    shutdown: Arc<AtomicBool>,
}

impl WorkerPool {
    /// Create a new worker pool.
    #[must_use]
    pub fn new(config: WorkerPoolConfig, queue: JobQueue) -> Self {
        Self {
            config,
            queue,
            shutdown: Arc::new(AtomicBool::new(false)),
        }
    }

    /// Run the worker pool with the given job handler.
    ///
    /// This method spawns `concurrency` worker tasks that continuously
    /// pop jobs from the queue and process them.
    #[instrument(skip(self, handler))]
    pub async fn run<F, Fut>(&self, handler: F) -> Result<()>
    where
        F: Fn(Job) -> Fut + Send + Sync + Clone + 'static,
        Fut: Future<Output = Result<()>> + Send + 'static,
    {
        info!(
            concurrency = self.config.concurrency,
            queue = %self.config.queue,
            "Starting worker pool"
        );

        let semaphore = Arc::new(Semaphore::new(self.config.concurrency));
        let mut tasks = JoinSet::new();

        while !self.shutdown.load(Ordering::Relaxed) {
            // Wait for available worker slot
            let permit = semaphore.clone().acquire_owned().await.unwrap();

            // Try to get a job
            match self.queue.pop(Some(&self.config.queue)).await {
                Ok(Some(mut job)) => {
                    let queue = self.queue.clone();
                    let queue_name = self.config.queue.clone();
                    let handler = handler.clone();

                    tasks.spawn(async move {
                        let _permit = permit; // Hold permit until done
                        let job_id = job.id;

                        debug!(job_id = %job_id, "Processing job");
                        job.start();

                        match handler(job.clone()).await {
                            Ok(()) => {
                                job.complete();
                                debug!(job_id = %job_id, "Job completed successfully");
                            }
                            Err(e) => {
                                error!(job_id = %job_id, error = %e, "Job failed");
                                job.fail(e.to_string());

                                if job.status == JobStatus::Failed {
                                    // Max retries exceeded, move to DLQ
                                    if let Err(e) = queue.move_to_dlq(&job, Some(&queue_name)).await {
                                        error!(job_id = %job_id, error = %e, "Failed to move to DLQ");
                                    }
                                } else {
                                    // Retry - push back to queue
                                    if let Err(e) = queue.push(&job, Some(&queue_name)).await {
                                        error!(job_id = %job_id, error = %e, "Failed to requeue job");
                                    }
                                }
                            }
                        }
                    });
                }
                Ok(None) => {
                    // No job available, release permit and continue
                    drop(permit);
                }
                Err(e) => {
                    warn!(error = %e, "Error popping job from queue");
                    drop(permit);
                    tokio::time::sleep(std::time::Duration::from_secs(1)).await;
                }
            }

            // Clean up completed tasks
            while let Some(result) = tasks.try_join_next() {
                if let Err(e) = result {
                    error!(error = %e, "Worker task panicked");
                }
            }
        }

        info!("Worker pool shutting down, waiting for tasks to complete");

        // Wait for remaining tasks with timeout
        let timeout = std::time::Duration::from_secs(self.config.graceful_shutdown_timeout_secs);
        let deadline = tokio::time::Instant::now() + timeout;

        while !tasks.is_empty() {
            tokio::select! {
                result = tasks.join_next() => {
                    if let Some(Err(e)) = result {
                        error!(error = %e, "Worker task panicked during shutdown");
                    }
                }
                _ = tokio::time::sleep_until(deadline) => {
                    warn!("Graceful shutdown timeout, aborting remaining tasks");
                    tasks.abort_all();
                    break;
                }
            }
        }

        info!("Worker pool stopped");
        Ok(())
    }

    /// Signal the worker pool to shut down.
    pub fn shutdown(&self) {
        info!("Shutdown signal received");
        self.shutdown.store(true, Ordering::Relaxed);
    }

    /// Check if shutdown has been requested.
    #[must_use]
    pub fn is_shutdown(&self) -> bool {
        self.shutdown.load(Ordering::Relaxed)
    }
}
```

**Step 4: Update mod.rs**

```rust
// crates/rag-ingestion/src/worker/mod.rs

//! Async worker system for background job processing.
//!
//! This module provides a Redis-based job queue system for processing
//! ingestion tasks asynchronously:
//!
//! - Job queues using Redis lists (LPUSH/BRPOP)
//! - Configurable worker pools with tokio
//! - Job status tracking
//! - Dead letter queue for failed jobs
//! - Graceful shutdown support
//!
//! # Example
//!
//! ```rust,ignore
//! use rag_ingestion::worker::{JobQueue, QueueConfig, WorkerPool, WorkerPoolConfig, Job};
//!
//! // Create queue
//! let queue = JobQueue::connect(QueueConfig::default()).await?;
//!
//! // Push a job
//! let job = Job::new(JobType::Ingest, serde_json::json!({"doc_id": "123"}));
//! queue.push(&job, None).await?;
//!
//! // Create worker pool
//! let pool = WorkerPool::new(WorkerPoolConfig::default(), queue.clone());
//!
//! // Run with handler
//! pool.run(|job| async move {
//!     println!("Processing job: {:?}", job);
//!     Ok(())
//! }).await?;
//! ```

mod pool;
mod queue;
mod types;

pub use pool::{WorkerPool, WorkerPoolConfig};
pub use queue::{JobQueue, QueueConfig};
pub use types::{Job, JobId, JobStatus, JobType};
```

**Step 5: Run tests to verify they pass**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion -- worker`
Expected: PASS

**Step 6: Commit**

```bash
git add crates/rag-ingestion/src/worker/
git commit -m "feat(rag-ingestion): add worker pool with graceful shutdown"
```

---

## Task 21: Register Worker Module in lib.rs

**Files:**
- Modify: `crates/rag-ingestion/src/lib.rs`

**Step 1: Add worker module to lib.rs**

```rust
pub mod api;
pub mod chunking;
pub mod connectors;
pub mod embedding;
pub mod error;
pub mod indexing;
pub mod parsers;
pub mod pii;
pub mod worker;  // Add this line
```

Add worker re-exports:

```rust
// Worker system
pub use worker::{Job, JobId, JobQueue, JobStatus, JobType, QueueConfig, WorkerPool, WorkerPoolConfig};
```

**Step 2: Verify compilation and run all tests**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion`
Expected: All tests PASS

**Step 3: Commit**

```bash
git add crates/rag-ingestion/src/lib.rs
git commit -m "feat(rag-ingestion): export worker system module"
```

---

## Task 22: Update Implementation Plan Document

**Files:**
- Modify: `workflow/epics/8-rust-migration/08.0-rust-implementation-plan.md`

**Step 1: Update the status of Phase 4 components**

Update the following sections in the implementation plan:

```markdown
### P4.1: PDF Parser ✅ COMPLETE

**Effort:** 2-3 weeks | **Risk:** Low (HTTP client approach) | **Value:** High

```
Tasks:
├── ✅ HTTP client to Python PDF service
├── ✅ Request/response types
├── ✅ ParsedDocument conversion
└── ✅ Unit tests
```

**Implementation:** `crates/rag-ingestion/src/parsers/pdf.rs`

**Note:** Uses HTTP delegation to Python PyMuPDF service as recommended fallback strategy.

---

### P4.2: DOCX Parser ✅ COMPLETE

**Effort:** 1-2 weeks | **Risk:** Medium | **Value:** Medium

```
Tasks:
├── ✅ ZIP extraction with zip crate
├── ✅ XML parsing with quick-xml
├── ✅ Text extraction from paragraphs
├── ✅ Table extraction
├── ✅ Core properties extraction
└── ✅ Unit tests
```

**Implementation:** `crates/rag-ingestion/src/parsers/docx.rs`

---

### P4.3: Semantic Chunker ✅ COMPLETE

**Effort:** 1 week | **Risk:** Low | **Value:** Medium

```
Tasks:
├── ✅ Sentence segmentation with unicode-segmentation
├── ✅ Abbreviation handling
├── ✅ Sentence grouping by token count
├── ✅ Long sentence handling
├── ✅ Overlap by sentences
└── ✅ Unit tests
```

**Implementation:** `crates/rag-ingestion/src/chunking/semantic.rs`

---

### P4.4: PII Detection ✅ COMPLETE

**Effort:** 1 week | **Risk:** Low | **Value:** Medium

```
Tasks:
├── ✅ Regex patterns for email, phone, SSN, credit card, IP
├── ✅ Configurable detection levels
├── ✅ Redaction support
├── ✅ High-sensitivity flagging
└── ✅ Unit tests
```

**Implementation:** `crates/rag-ingestion/src/pii/`

**Note:** Covers ~80% of PII detection. For NER-based detection, use Python Presidio via HTTP.

---

### P4.5: Async Worker System ✅ COMPLETE

**Effort:** 2-3 weeks | **Risk:** Medium | **Value:** Critical

```
Tasks:
├── ✅ Job types and status tracking
├── ✅ Redis queue client (LPUSH/BRPOP)
├── ✅ Worker pool with configurable concurrency
├── ✅ Dead letter queue
├── ✅ Graceful shutdown
└── ✅ Unit tests
```

**Implementation:** `crates/rag-ingestion/src/worker/`
```

**Step 2: Commit**

```bash
git add workflow/epics/8-rust-migration/08.0-rust-implementation-plan.md
git commit -m "docs: update implementation plan with Phase 4 completion status"
```

---

## Task 23: Final Verification

**Step 1: Run all ingestion crate tests**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo test -p rag-ingestion`
Expected: All tests pass

**Step 2: Run clippy for code quality**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo clippy -p rag-ingestion -- -D warnings`
Expected: No warnings or errors

**Step 3: Run rustfmt for formatting**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo fmt -p rag-ingestion -- --check`
Expected: All files properly formatted

**Step 4: Build documentation**

Run: `cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates && cargo doc -p rag-ingestion --no-deps`
Expected: Documentation builds successfully

**Step 5: Final commit with all Phase 4 components**

```bash
git add -A
git commit -m "feat(rag-ingestion): complete Phase 4 implementation

Phase 4 Rust Ingestion Complex Components:
- P4.1: PDF Parser (HTTP client to Python service)
- P4.2: DOCX Parser (pure Rust with quick-xml)
- P4.3: Semantic Chunker (sentence-boundary based)
- P4.4: PII Detection (regex patterns)
- P4.5: Async Worker System (Redis queues + tokio pool)

All components include comprehensive unit tests."
```

---

## Summary

This plan implements the 5 remaining Phase 4 components:

| Task | Component | Approach | Tests |
|------|-----------|----------|-------|
| 2-5 | PDF Parser | HTTP client to Python service | 3 tests |
| 6-10 | DOCX Parser | quick-xml + zip for OOXML | 5 tests |
| 11-13 | Semantic Chunker | unicode-segmentation | 5 tests |
| 14-17 | PII Detection | regex patterns | 8 tests |
| 18-21 | Worker System | Redis + tokio | 4 tests |

**Total: 23 tasks, ~25 tests, 5 new modules**

**Dependencies added:**
- `quick-xml` - OOXML parsing
- `zip` - DOCX archive extraction
- `unicode-segmentation` - Sentence boundaries
- `regex`, `lazy_static` - PII patterns

**Architectural decisions:**
1. PDF uses HTTP delegation (recommended in original plan)
2. DOCX is pure Rust (no python-docx dependency)
3. Semantic chunker avoids spaCy (uses unicode rules)
4. PII is regex-only (~80% coverage, NLP via HTTP fallback)
5. Worker uses existing Redis dependency

---

Plan complete and saved to `docs/plans/2025-01-29-phase4-rust-ingestion-complex.md`. Two execution options:

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

Which approach?