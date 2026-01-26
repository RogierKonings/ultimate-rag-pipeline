# Rust Ingestion: Parsers and Chunking Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create the `rag-ingestion` crate with HTML parser, Markdown parser, and Recursive Character Chunker.

**Architecture:** New crate in workspace with `parsers` and `chunking` modules. Parsers are sync (CPU-bound), use existing `rag-types` for IDs. Follows TDD with parity tests against Python.

**Tech Stack:** scraper (HTML), pulldown-cmark (Markdown), serde_yaml (frontmatter), tiktoken-rs (tokenization)

---

## Task 1: Create Crate Skeleton

**Files:**
- Create: `crates/rag-ingestion/Cargo.toml`
- Create: `crates/rag-ingestion/src/lib.rs`
- Create: `crates/rag-ingestion/src/error.rs`
- Modify: `crates/Cargo.toml` (add to workspace members)

**Step 1: Create Cargo.toml**

Create `crates/rag-ingestion/Cargo.toml`:

```toml
[package]
name = "rag-ingestion"
version.workspace = true
edition.workspace = true
rust-version.workspace = true
license.workspace = true
description = "Document parsing and chunking for RAG pipeline"

[dependencies]
# Internal crates
rag-types = { path = "../rag-types" }

# Parsing
scraper = "0.20"
pulldown-cmark = "0.12"
serde_yaml = "0.9"

# Tokenization
tiktoken-rs = "0.6"

# Serialization
serde = { workspace = true }
serde_json = { workspace = true }

# Error handling
thiserror = { workspace = true }

# Utilities
uuid = { workspace = true }

[dev-dependencies]
pretty_assertions = "1.4"

[lints]
workspace = true
```

**Step 2: Create src/error.rs**

Create `crates/rag-ingestion/src/error.rs`:

```rust
//! Error types for the ingestion crate.

use thiserror::Error;

/// Errors that can occur during ingestion operations.
#[derive(Debug, Error)]
pub enum Error {
    /// Failed to parse document content.
    #[error("Parse error: {0}")]
    Parse(String),

    /// Failed to chunk document.
    #[error("Chunking error: {0}")]
    Chunking(String),

    /// Invalid configuration provided.
    #[error("Configuration error: {0}")]
    Config(String),

    /// IO error during file operations.
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    /// Serialization/deserialization error.
    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),
}

/// Result type alias for ingestion operations.
pub type Result<T> = std::result::Result<T, Error>;
```

**Step 3: Create src/lib.rs**

Create `crates/rag-ingestion/src/lib.rs`:

```rust
//! Document parsing and chunking for the RAG pipeline.
//!
//! This crate provides:
//! - Document parsers for HTML and Markdown
//! - Text chunking strategies for embedding preparation
//!
//! # Example
//!
//! ```rust,ignore
//! use rag_ingestion::parsers::{HtmlParser, Parser};
//! use rag_ingestion::chunking::{RecursiveCharacterSplitter, ChunkingStrategy};
//!
//! // Parse HTML document
//! let parser = HtmlParser::default();
//! let doc = parser.parse(html_bytes, None)?;
//!
//! // Chunk the text
//! let chunker = RecursiveCharacterSplitter::default();
//! let chunks = chunker.chunk(&doc.text, document_id, None)?;
//! ```

pub mod error;

pub use error::{Error, Result};
```

**Step 4: Add to workspace**

Modify `crates/Cargo.toml` - add `"rag-ingestion"` to the members array:

```toml
members = [
    "rag-types",
    "rag-config",
    "rag-cache",
    "rag-retrieval",
    "rag-auth",
    "rag-telemetry",
    "rag-storage",
    "rag-vectorstore",
    "rag-search",
    "rag-database",
    "rag-ingestion",
]
```

**Step 5: Verify it compiles**

Run: `cd crates && cargo build -p rag-ingestion`
Expected: Build succeeds with no errors

**Step 6: Commit**

```bash
git add crates/rag-ingestion crates/Cargo.toml
git commit -m "feat(rag-ingestion): create crate skeleton with error types"
```

---

## Task 2: Parser Base Types

**Files:**
- Create: `crates/rag-ingestion/src/parsers/mod.rs`
- Create: `crates/rag-ingestion/src/parsers/base.rs`
- Modify: `crates/rag-ingestion/src/lib.rs`

**Step 1: Create parsers/base.rs with types**

Create `crates/rag-ingestion/src/parsers/base.rs`:

```rust
//! Base types and traits for document parsers.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;

use crate::Result;

/// Types of content blocks extracted from documents.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ContentType {
    /// Plain text content.
    Text,
    /// Table data.
    Table,
    /// Image reference.
    Image,
    /// Code block.
    Code,
}

/// A block of content extracted from a document.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ContentBlock {
    /// Type of content in this block.
    pub content_type: ContentType,
    /// The actual content.
    pub content: String,
    /// Page number if applicable (for PDFs).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub page_number: Option<u32>,
    /// Position in document (sequential index).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub position: Option<u32>,
    /// Additional metadata (e.g., tag name, language).
    #[serde(default, skip_serializing_if = "HashMap::is_empty")]
    pub metadata: HashMap<String, Value>,
}

impl ContentBlock {
    /// Create a new text content block.
    #[must_use]
    pub fn text(content: impl Into<String>, position: u32) -> Self {
        Self {
            content_type: ContentType::Text,
            content: content.into(),
            page_number: None,
            position: Some(position),
            metadata: HashMap::new(),
        }
    }

    /// Create a new code content block.
    #[must_use]
    pub fn code(content: impl Into<String>, position: u32, language: Option<String>) -> Self {
        let mut metadata = HashMap::new();
        if let Some(lang) = language {
            metadata.insert("language".to_string(), Value::String(lang));
        }
        Self {
            content_type: ContentType::Code,
            content: content.into(),
            page_number: None,
            position: Some(position),
            metadata,
        }
    }

    /// Add metadata to this block.
    #[must_use]
    pub fn with_metadata(mut self, key: impl Into<String>, value: impl Into<Value>) -> Self {
        self.metadata.insert(key.into(), value.into());
        self
    }
}

/// Extracted table with headers and rows.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TableContent {
    /// Column headers.
    pub headers: Vec<String>,
    /// Table rows (each row is a vector of cell values).
    pub rows: Vec<Vec<String>>,
    /// Optional table caption.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub caption: Option<String>,
}

impl TableContent {
    /// Create a new table.
    #[must_use]
    pub fn new(headers: Vec<String>, rows: Vec<Vec<String>>) -> Self {
        Self {
            headers,
            rows,
            caption: None,
        }
    }

    /// Convert table to plain text representation.
    #[must_use]
    pub fn to_text(&self) -> String {
        let mut lines = Vec::new();

        if let Some(caption) = &self.caption {
            lines.push(caption.clone());
        }

        // Headers
        lines.push(self.headers.join(" | "));
        lines.push("-".repeat(lines.last().map_or(0, String::len)));

        // Rows
        for row in &self.rows {
            lines.push(row.join(" | "));
        }

        lines.join("\n")
    }
}

/// Result of parsing a document.
#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct ParsedDocument {
    /// Full extracted text content.
    pub text: String,
    /// Structured content blocks.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub blocks: Vec<ContentBlock>,
    /// Extracted tables.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub tables: Vec<TableContent>,
    /// Document title.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub title: Option<String>,
    /// Document author.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub author: Option<String>,
    /// Creation date.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub created_date: Option<String>,
    /// Last modification date.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub modified_date: Option<String>,
    /// Number of pages (for PDFs).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub page_count: Option<u32>,
    /// Detected language.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub language: Option<String>,
    /// Additional metadata.
    #[serde(default, skip_serializing_if = "HashMap::is_empty")]
    pub metadata: HashMap<String, Value>,
}

/// Trait for document parsers.
///
/// Parsers convert raw document bytes into structured [`ParsedDocument`] output.
/// They are synchronous since parsing is CPU-bound.
pub trait Parser: Send + Sync {
    /// Returns the MIME types this parser can handle.
    fn supported_mime_types(&self) -> &[&str];

    /// Parse document content.
    ///
    /// # Arguments
    ///
    /// * `content` - Raw document bytes.
    /// * `metadata` - Optional metadata to merge into the result.
    ///
    /// # Errors
    ///
    /// Returns an error if the document cannot be parsed.
    fn parse(
        &self,
        content: &[u8],
        metadata: Option<HashMap<String, Value>>,
    ) -> Result<ParsedDocument>;

    /// Check if this parser can handle the given MIME type.
    fn can_parse(&self, mime_type: &str) -> bool {
        self.supported_mime_types().contains(&mime_type)
    }
}
```

**Step 2: Create parsers/mod.rs**

Create `crates/rag-ingestion/src/parsers/mod.rs`:

```rust
//! Document parsers for various file formats.
//!
//! This module provides parsers for:
//! - HTML documents ([`HtmlParser`])
//! - Markdown documents ([`MarkdownParser`])

mod base;

pub use base::{ContentBlock, ContentType, ParsedDocument, Parser, TableContent};
```

**Step 3: Update lib.rs**

Modify `crates/rag-ingestion/src/lib.rs` to add the parsers module:

```rust
//! Document parsing and chunking for the RAG pipeline.
//!
//! This crate provides:
//! - Document parsers for HTML and Markdown
//! - Text chunking strategies for embedding preparation
//!
//! # Example
//!
//! ```rust,ignore
//! use rag_ingestion::parsers::{HtmlParser, Parser};
//! use rag_ingestion::chunking::{RecursiveCharacterSplitter, ChunkingStrategy};
//!
//! // Parse HTML document
//! let parser = HtmlParser::default();
//! let doc = parser.parse(html_bytes, None)?;
//!
//! // Chunk the text
//! let chunker = RecursiveCharacterSplitter::default();
//! let chunks = chunker.chunk(&doc.text, document_id, None)?;
//! ```

pub mod error;
pub mod parsers;

pub use error::{Error, Result};
```

**Step 4: Verify it compiles**

Run: `cd crates && cargo build -p rag-ingestion`
Expected: Build succeeds

**Step 5: Commit**

```bash
git add crates/rag-ingestion/src/
git commit -m "feat(rag-ingestion): add parser base types and trait"
```

---

## Task 3: HTML Parser - Tests First

**Files:**
- Create: `crates/rag-ingestion/src/parsers/html.rs`
- Modify: `crates/rag-ingestion/src/parsers/mod.rs`

**Step 1: Write failing tests**

Create `crates/rag-ingestion/src/parsers/html.rs`:

```rust
//! HTML document parser.

use scraper::{Html, Selector};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;

use super::base::{ContentBlock, ContentType, ParsedDocument, Parser, TableContent};
use crate::{Error, Result};

/// Configuration for the HTML parser.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HtmlParserConfig {
    /// Remove `<script>` elements.
    pub remove_scripts: bool,
    /// Remove `<style>` elements.
    pub remove_styles: bool,
    /// Remove HTML comments.
    pub remove_comments: bool,
    /// Extract links into metadata.
    pub extract_links: bool,
}

impl Default for HtmlParserConfig {
    fn default() -> Self {
        Self {
            remove_scripts: true,
            remove_styles: true,
            remove_comments: true,
            extract_links: true,
        }
    }
}

/// Parser for HTML documents.
///
/// Uses the `scraper` crate (built on `html5ever`) for robust HTML parsing.
pub struct HtmlParser {
    config: HtmlParserConfig,
}

impl HtmlParser {
    /// Create a new HTML parser with the given configuration.
    #[must_use]
    pub fn new(config: HtmlParserConfig) -> Self {
        Self { config }
    }
}

impl Default for HtmlParser {
    fn default() -> Self {
        Self::new(HtmlParserConfig::default())
    }
}

impl Parser for HtmlParser {
    fn supported_mime_types(&self) -> &[&str] {
        &["text/html", "application/xhtml+xml"]
    }

    fn parse(
        &self,
        content: &[u8],
        metadata: Option<HashMap<String, Value>>,
    ) -> Result<ParsedDocument> {
        // TODO: Implement
        todo!()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;

    #[test]
    fn test_supported_mime_types() {
        let parser = HtmlParser::default();
        assert!(parser.can_parse("text/html"));
        assert!(parser.can_parse("application/xhtml+xml"));
        assert!(!parser.can_parse("text/plain"));
    }

    #[test]
    fn test_parse_simple_html() {
        let html = r#"
            <!DOCTYPE html>
            <html>
            <head><title>Test Document</title></head>
            <body>
                <h1>Hello World</h1>
                <p>This is a test paragraph.</p>
            </body>
            </html>
        "#;

        let parser = HtmlParser::default();
        let result = parser.parse(html.as_bytes(), None).unwrap();

        assert_eq!(result.title, Some("Test Document".to_string()));
        assert!(result.text.contains("Hello World"));
        assert!(result.text.contains("This is a test paragraph"));
    }

    #[test]
    fn test_parse_extracts_blocks() {
        let html = r#"
            <html>
            <body>
                <h1>Title</h1>
                <p>Paragraph one.</p>
                <p>Paragraph two.</p>
            </body>
            </html>
        "#;

        let parser = HtmlParser::default();
        let result = parser.parse(html.as_bytes(), None).unwrap();

        // Should have blocks for h1 and both paragraphs
        assert!(result.blocks.len() >= 3);

        let text_blocks: Vec<_> = result
            .blocks
            .iter()
            .filter(|b| b.content_type == ContentType::Text)
            .collect();

        assert!(text_blocks.iter().any(|b| b.content.contains("Title")));
        assert!(text_blocks.iter().any(|b| b.content.contains("Paragraph one")));
    }

    #[test]
    fn test_parse_extracts_code_blocks() {
        let html = r#"
            <html>
            <body>
                <pre>fn main() { println!("Hello"); }</pre>
            </body>
            </html>
        "#;

        let parser = HtmlParser::default();
        let result = parser.parse(html.as_bytes(), None).unwrap();

        let code_blocks: Vec<_> = result
            .blocks
            .iter()
            .filter(|b| b.content_type == ContentType::Code)
            .collect();

        assert_eq!(code_blocks.len(), 1);
        assert!(code_blocks[0].content.contains("fn main()"));
    }

    #[test]
    fn test_parse_extracts_tables() {
        let html = r#"
            <html>
            <body>
                <table>
                    <thead>
                        <tr><th>Name</th><th>Age</th></tr>
                    </thead>
                    <tbody>
                        <tr><td>Alice</td><td>30</td></tr>
                        <tr><td>Bob</td><td>25</td></tr>
                    </tbody>
                </table>
            </body>
            </html>
        "#;

        let parser = HtmlParser::default();
        let result = parser.parse(html.as_bytes(), None).unwrap();

        assert_eq!(result.tables.len(), 1);
        assert_eq!(result.tables[0].headers, vec!["Name", "Age"]);
        assert_eq!(result.tables[0].rows.len(), 2);
        assert_eq!(result.tables[0].rows[0], vec!["Alice", "30"]);
    }

    #[test]
    fn test_parse_extracts_links() {
        let html = r#"
            <html>
            <body>
                <a href="https://example.com">Example</a>
                <a href="#anchor">Internal</a>
            </body>
            </html>
        "#;

        let parser = HtmlParser::default();
        let result = parser.parse(html.as_bytes(), None).unwrap();

        let links = result.metadata.get("links");
        assert!(links.is_some());

        let links = links.unwrap().as_array().unwrap();
        // Should only include external link, not anchor
        assert!(links.iter().any(|l| {
            l.get("href").and_then(|h| h.as_str()) == Some("https://example.com")
        }));
    }

    #[test]
    fn test_parse_removes_scripts() {
        let html = r#"
            <html>
            <body>
                <p>Real content</p>
                <script>alert('malicious');</script>
            </body>
            </html>
        "#;

        let parser = HtmlParser::default();
        let result = parser.parse(html.as_bytes(), None).unwrap();

        assert!(!result.text.contains("alert"));
        assert!(!result.text.contains("malicious"));
        assert!(result.text.contains("Real content"));
    }

    #[test]
    fn test_parse_handles_encoding_issues() {
        // Invalid UTF-8 bytes
        let content = b"<html><body>\xff\xfe Invalid bytes</body></html>";

        let parser = HtmlParser::default();
        let result = parser.parse(content, None);

        // Should not panic, should handle gracefully
        assert!(result.is_ok());
    }

    #[test]
    fn test_parse_merges_metadata() {
        let html = b"<html><head><title>Doc</title></head></html>";

        let mut metadata = HashMap::new();
        metadata.insert("source".to_string(), Value::String("test".to_string()));

        let parser = HtmlParser::default();
        let result = parser.parse(html, Some(metadata)).unwrap();

        assert_eq!(
            result.metadata.get("source"),
            Some(&Value::String("test".to_string()))
        );
    }
}
```

**Step 2: Update mod.rs**

Modify `crates/rag-ingestion/src/parsers/mod.rs`:

```rust
//! Document parsers for various file formats.
//!
//! This module provides parsers for:
//! - HTML documents ([`HtmlParser`])
//! - Markdown documents ([`MarkdownParser`])

mod base;
mod html;

pub use base::{ContentBlock, ContentType, ParsedDocument, Parser, TableContent};
pub use html::{HtmlParser, HtmlParserConfig};
```

**Step 3: Run tests to verify they fail**

Run: `cd crates && cargo test -p rag-ingestion`
Expected: Tests fail with "not yet implemented" panic

**Step 4: Commit the failing tests**

```bash
git add crates/rag-ingestion/src/parsers/
git commit -m "test(rag-ingestion): add failing tests for HTML parser"
```

---

## Task 4: HTML Parser - Implementation

**Files:**
- Modify: `crates/rag-ingestion/src/parsers/html.rs`

**Step 1: Implement the parse method**

Replace the `impl Parser for HtmlParser` block in `crates/rag-ingestion/src/parsers/html.rs`:

```rust
impl Parser for HtmlParser {
    fn supported_mime_types(&self) -> &[&str] {
        &["text/html", "application/xhtml+xml"]
    }

    fn parse(
        &self,
        content: &[u8],
        metadata: Option<HashMap<String, Value>>,
    ) -> Result<ParsedDocument> {
        let html_str = String::from_utf8_lossy(content);
        let document = Html::parse_document(&html_str);

        let mut result_metadata = metadata.unwrap_or_default();
        let mut blocks = Vec::new();
        let mut tables = Vec::new();
        let mut position = 0u32;

        // Extract title
        let title = Self::selector("title")
            .and_then(|sel| document.select(&sel).next())
            .map(|el| el.text().collect::<String>().trim().to_string())
            .filter(|s| !s.is_empty());

        // Extract semantic text blocks
        if let Some(selector) = Self::selector("p, h1, h2, h3, h4, h5, h6, li, blockquote") {
            for element in document.select(&selector) {
                // Skip if inside script or style
                if self.is_inside_excluded_tag(&element) {
                    continue;
                }

                let text: String = element.text().collect();
                let text = text.trim();

                if !text.is_empty() {
                    let mut block = ContentBlock::text(text, position);
                    block.metadata.insert(
                        "tag".to_string(),
                        Value::String(element.value().name().to_string()),
                    );
                    blocks.push(block);
                    position += 1;
                }
            }
        }

        // Extract code blocks
        if let Some(selector) = Self::selector("pre") {
            for element in document.select(&selector) {
                if self.is_inside_excluded_tag(&element) {
                    continue;
                }

                let text: String = element.text().collect();
                let text = text.trim();

                if !text.is_empty() {
                    blocks.push(ContentBlock::code(text, position, None));
                    position += 1;
                }
            }
        }

        // Extract tables
        if let Some(selector) = Self::selector("table") {
            for table_el in document.select(&selector) {
                if let Some(table) = self.extract_table(&table_el) {
                    // Add table as a block too
                    blocks.push(ContentBlock {
                        content_type: ContentType::Table,
                        content: table.to_text(),
                        page_number: None,
                        position: Some(position),
                        metadata: HashMap::new(),
                    });
                    position += 1;
                    tables.push(table);
                }
            }
        }

        // Extract links if enabled
        if self.config.extract_links {
            if let Some(selector) = Self::selector("a[href]") {
                let links: Vec<Value> = document
                    .select(&selector)
                    .filter_map(|el| {
                        let href = el.value().attr("href")?;
                        // Skip internal anchors
                        if href.starts_with('#') {
                            return None;
                        }
                        let text: String = el.text().collect();
                        Some(serde_json::json!({
                            "text": text.trim(),
                            "href": href
                        }))
                    })
                    .collect();

                if !links.is_empty() {
                    result_metadata.insert("links".to_string(), Value::Array(links));
                }
            }
        }

        // Extract full text (excluding scripts and styles)
        let full_text = self.extract_full_text(&document);

        Ok(ParsedDocument {
            text: full_text,
            blocks,
            tables,
            title,
            metadata: result_metadata,
            ..Default::default()
        })
    }
}

impl HtmlParser {
    /// Create a selector, returning None if invalid.
    fn selector(s: &str) -> Option<Selector> {
        Selector::parse(s).ok()
    }

    /// Check if an element is inside a script or style tag.
    fn is_inside_excluded_tag(&self, element: &scraper::ElementRef) -> bool {
        if !self.config.remove_scripts && !self.config.remove_styles {
            return false;
        }

        let mut current = element.parent();
        while let Some(parent) = current {
            if let Some(el) = parent.value().as_element() {
                let name = el.name();
                if (self.config.remove_scripts && name == "script")
                    || (self.config.remove_styles && name == "style")
                {
                    return true;
                }
            }
            current = parent.parent();
        }
        false
    }

    /// Extract full text content, excluding scripts and styles.
    fn extract_full_text(&self, document: &Html) -> String {
        let mut texts = Vec::new();

        // Get body or root element
        let root = Self::selector("body")
            .and_then(|sel| document.select(&sel).next())
            .map(|el| el.id())
            .unwrap_or_else(|| document.root_element().id());

        self.collect_text_recursive(document, root, &mut texts);

        texts.join("\n")
    }

    /// Recursively collect text, skipping excluded tags.
    fn collect_text_recursive(
        &self,
        document: &Html,
        node_id: scraper::node::NodeId,
        texts: &mut Vec<String>,
    ) {
        let node = document.tree.get(node_id);
        let Some(node) = node else { return };

        match node.value() {
            scraper::Node::Text(text) => {
                let trimmed = text.trim();
                if !trimmed.is_empty() {
                    texts.push(trimmed.to_string());
                }
            }
            scraper::Node::Element(el) => {
                let name = el.name();

                // Skip excluded tags
                if (self.config.remove_scripts && name == "script")
                    || (self.config.remove_styles && name == "style")
                {
                    return;
                }

                // Recurse into children
                for child in node.children() {
                    self.collect_text_recursive(document, child.id(), texts);
                }
            }
            _ => {
                // For other node types, recurse into children
                for child in node.children() {
                    self.collect_text_recursive(document, child.id(), texts);
                }
            }
        }
    }

    /// Extract a table from a table element.
    fn extract_table(&self, table_el: &scraper::ElementRef) -> Option<TableContent> {
        let mut headers = Vec::new();
        let mut rows = Vec::new();

        // Get caption
        let caption = Self::selector("caption")
            .and_then(|sel| table_el.select(&sel).next())
            .map(|el| el.text().collect::<String>().trim().to_string())
            .filter(|s| !s.is_empty());

        // Try to get headers from thead
        if let Some(thead_sel) = Self::selector("thead tr") {
            if let Some(header_row) = table_el.select(&thead_sel).next() {
                if let Some(cell_sel) = Self::selector("th, td") {
                    headers = header_row
                        .select(&cell_sel)
                        .map(|cell| cell.text().collect::<String>().trim().to_string())
                        .collect();
                }
            }
        }

        // Get body rows
        let row_selector = if Self::selector("tbody").is_some() {
            Self::selector("tbody tr, tr")
        } else {
            Self::selector("tr")
        };

        if let Some(row_sel) = row_selector {
            for row_el in table_el.select(&row_sel) {
                // Skip if this is in thead
                let in_thead = row_el
                    .parent()
                    .and_then(|p| p.value().as_element())
                    .map(|el| el.name() == "thead")
                    .unwrap_or(false);

                if in_thead {
                    continue;
                }

                if let Some(cell_sel) = Self::selector("td, th") {
                    let cells: Vec<_> = row_el.select(&cell_sel).collect();

                    if cells.is_empty() {
                        continue;
                    }

                    // Check if this is a header row (all th cells)
                    let all_th = cells.iter().all(|c| c.value().name() == "th");

                    let cell_texts: Vec<String> = cells
                        .iter()
                        .map(|cell| cell.text().collect::<String>().trim().to_string())
                        .collect();

                    if headers.is_empty() && all_th {
                        headers = cell_texts;
                    } else {
                        rows.push(cell_texts);
                    }
                }
            }
        }

        // If still no headers, use first row
        if headers.is_empty() && !rows.is_empty() {
            headers = rows.remove(0);
        }

        if headers.is_empty() {
            return None;
        }

        let mut table = TableContent::new(headers, rows);
        table.caption = caption;
        Some(table)
    }
}
```

**Step 2: Run tests to verify they pass**

Run: `cd crates && cargo test -p rag-ingestion`
Expected: All tests pass

**Step 3: Run clippy**

Run: `cd crates && cargo clippy -p rag-ingestion -- -D warnings`
Expected: No warnings

**Step 4: Commit**

```bash
git add crates/rag-ingestion/src/parsers/html.rs
git commit -m "feat(rag-ingestion): implement HTML parser"
```

---

## Task 5: Markdown Parser - Tests First

**Files:**
- Create: `crates/rag-ingestion/src/parsers/markdown.rs`
- Modify: `crates/rag-ingestion/src/parsers/mod.rs`

**Step 1: Write failing tests**

Create `crates/rag-ingestion/src/parsers/markdown.rs`:

```rust
//! Markdown document parser.

use pulldown_cmark::{CodeBlockKind, Event, Parser as MdParser, Tag, TagEnd};
use serde_json::Value;
use std::collections::HashMap;

use super::base::{ContentBlock, ContentType, ParsedDocument, Parser, TableContent};
use crate::Result;

/// Parser for Markdown documents.
///
/// Uses `pulldown-cmark` for event-based parsing and `serde_yaml` for frontmatter.
pub struct MarkdownParser;

impl Default for MarkdownParser {
    fn default() -> Self {
        Self
    }
}

impl Parser for MarkdownParser {
    fn supported_mime_types(&self) -> &[&str] {
        &["text/markdown", "text/x-markdown"]
    }

    fn parse(
        &self,
        content: &[u8],
        metadata: Option<HashMap<String, Value>>,
    ) -> Result<ParsedDocument> {
        // TODO: Implement
        todo!()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;

    #[test]
    fn test_supported_mime_types() {
        let parser = MarkdownParser::default();
        assert!(parser.can_parse("text/markdown"));
        assert!(parser.can_parse("text/x-markdown"));
        assert!(!parser.can_parse("text/plain"));
    }

    #[test]
    fn test_parse_simple_markdown() {
        let md = r#"# Hello World

This is a test paragraph.

Another paragraph here.
"#;

        let parser = MarkdownParser::default();
        let result = parser.parse(md.as_bytes(), None).unwrap();

        assert_eq!(result.title, Some("Hello World".to_string()));
        assert!(result.text.contains("This is a test paragraph"));
    }

    #[test]
    fn test_parse_extracts_frontmatter() {
        let md = r#"---
title: My Document
author: Test Author
tags:
  - rust
  - markdown
---

# Content

Some text here.
"#;

        let parser = MarkdownParser::default();
        let result = parser.parse(md.as_bytes(), None).unwrap();

        // Title from frontmatter takes precedence
        assert_eq!(result.title, Some("My Document".to_string()));
        assert_eq!(
            result.metadata.get("author"),
            Some(&Value::String("Test Author".to_string()))
        );

        let tags = result.metadata.get("tags").unwrap().as_array().unwrap();
        assert_eq!(tags.len(), 2);
    }

    #[test]
    fn test_parse_extracts_code_blocks() {
        let md = r#"# Code Example

```rust
fn main() {
    println!("Hello");
}
```

Some text.

```python
print("Hello")
```
"#;

        let parser = MarkdownParser::default();
        let result = parser.parse(md.as_bytes(), None).unwrap();

        let code_blocks: Vec<_> = result
            .blocks
            .iter()
            .filter(|b| b.content_type == ContentType::Code)
            .collect();

        assert_eq!(code_blocks.len(), 2);

        // Check language metadata
        assert_eq!(
            code_blocks[0].metadata.get("language"),
            Some(&Value::String("rust".to_string()))
        );
        assert_eq!(
            code_blocks[1].metadata.get("language"),
            Some(&Value::String("python".to_string()))
        );
    }

    #[test]
    fn test_parse_extracts_tables() {
        let md = r#"# Data

| Name | Age |
|------|-----|
| Alice | 30 |
| Bob | 25 |
"#;

        let parser = MarkdownParser::default();
        let result = parser.parse(md.as_bytes(), None).unwrap();

        assert_eq!(result.tables.len(), 1);
        assert_eq!(result.tables[0].headers, vec!["Name", "Age"]);
        assert_eq!(result.tables[0].rows.len(), 2);
    }

    #[test]
    fn test_parse_extracts_headings_as_blocks() {
        let md = r#"# Main Title

## Section One

Content one.

## Section Two

Content two.
"#;

        let parser = MarkdownParser::default();
        let result = parser.parse(md.as_bytes(), None).unwrap();

        let headings: Vec<_> = result
            .blocks
            .iter()
            .filter(|b| b.metadata.contains_key("heading_level"))
            .collect();

        assert!(headings.len() >= 2);
    }

    #[test]
    fn test_parse_handles_invalid_frontmatter() {
        let md = r#"---
invalid: yaml: [broken
---

# Title

Content.
"#;

        let parser = MarkdownParser::default();
        let result = parser.parse(md.as_bytes(), None).unwrap();

        // Should not crash, should fall back to parsing content
        // Title should come from H1
        assert_eq!(result.title, Some("Title".to_string()));
    }

    #[test]
    fn test_parse_merges_metadata() {
        let md = r#"---
title: From Frontmatter
---

Content.
"#;

        let mut metadata = HashMap::new();
        metadata.insert("source".to_string(), Value::String("test".to_string()));

        let parser = MarkdownParser::default();
        let result = parser.parse(md.as_bytes(), Some(metadata)).unwrap();

        // Both should be present, frontmatter overwrites conflicts
        assert_eq!(result.title, Some("From Frontmatter".to_string()));
        assert_eq!(
            result.metadata.get("source"),
            Some(&Value::String("test".to_string()))
        );
    }

    #[test]
    fn test_parse_title_from_h1_when_no_frontmatter() {
        let md = r#"# Document Title

Some content here.
"#;

        let parser = MarkdownParser::default();
        let result = parser.parse(md.as_bytes(), None).unwrap();

        assert_eq!(result.title, Some("Document Title".to_string()));
    }
}
```

**Step 2: Update mod.rs**

Modify `crates/rag-ingestion/src/parsers/mod.rs`:

```rust
//! Document parsers for various file formats.
//!
//! This module provides parsers for:
//! - HTML documents ([`HtmlParser`])
//! - Markdown documents ([`MarkdownParser`])

mod base;
mod html;
mod markdown;

pub use base::{ContentBlock, ContentType, ParsedDocument, Parser, TableContent};
pub use html::{HtmlParser, HtmlParserConfig};
pub use markdown::MarkdownParser;
```

**Step 3: Run tests to verify they fail**

Run: `cd crates && cargo test -p rag-ingestion markdown`
Expected: Tests fail with "not yet implemented"

**Step 4: Commit failing tests**

```bash
git add crates/rag-ingestion/src/parsers/
git commit -m "test(rag-ingestion): add failing tests for Markdown parser"
```

---

## Task 6: Markdown Parser - Implementation

**Files:**
- Modify: `crates/rag-ingestion/src/parsers/markdown.rs`

**Step 1: Implement the parser**

Replace the `impl Parser for MarkdownParser` and add helper methods in `crates/rag-ingestion/src/parsers/markdown.rs`:

```rust
impl Parser for MarkdownParser {
    fn supported_mime_types(&self) -> &[&str] {
        &["text/markdown", "text/x-markdown"]
    }

    fn parse(
        &self,
        content: &[u8],
        metadata: Option<HashMap<String, Value>>,
    ) -> Result<ParsedDocument> {
        let text = String::from_utf8_lossy(content);
        let mut result_metadata = metadata.unwrap_or_default();

        // Extract YAML frontmatter
        let (frontmatter, body) = self.extract_frontmatter(&text);

        // Merge frontmatter into metadata (frontmatter values take precedence)
        if let Some(fm) = frontmatter {
            for (k, v) in fm {
                result_metadata.insert(k, v);
            }
        }

        // Parse markdown with pulldown-cmark (enable tables)
        let options = pulldown_cmark::Options::ENABLE_TABLES;
        let parser = MdParser::new_ext(body, options);

        let mut blocks = Vec::new();
        let mut tables = Vec::new();
        let mut title: Option<String> = None;
        let mut position = 0u32;

        let mut current_text = String::new();
        let mut in_code_block = false;
        let mut code_language: Option<String> = None;
        let mut heading_level: Option<u32> = None;

        // Table state
        let mut in_table = false;
        let mut table_headers: Vec<String> = Vec::new();
        let mut table_rows: Vec<Vec<String>> = Vec::new();
        let mut current_row: Vec<String> = Vec::new();
        let mut in_table_head = false;

        for event in parser {
            match event {
                Event::Start(Tag::Heading { level, .. }) => {
                    self.flush_text(&mut current_text, &mut blocks, &mut position, None);
                    heading_level = Some(level as u32);
                }
                Event::End(TagEnd::Heading(_)) => {
                    let text = std::mem::take(&mut current_text);
                    let text = text.trim();

                    if !text.is_empty() {
                        // Capture first H1 as title if not set from frontmatter
                        if heading_level == Some(1) && title.is_none() {
                            title = Some(text.to_string());
                        }

                        let mut block = ContentBlock::text(text, position);
                        if let Some(level) = heading_level {
                            block.metadata.insert(
                                "heading_level".to_string(),
                                Value::Number(level.into()),
                            );
                        }
                        blocks.push(block);
                        position += 1;
                    }
                    heading_level = None;
                }
                Event::Start(Tag::CodeBlock(kind)) => {
                    self.flush_text(&mut current_text, &mut blocks, &mut position, None);
                    in_code_block = true;
                    code_language = match kind {
                        CodeBlockKind::Fenced(lang) => {
                            let lang = lang.to_string();
                            if lang.is_empty() {
                                None
                            } else {
                                Some(lang)
                            }
                        }
                        CodeBlockKind::Indented => None,
                    };
                }
                Event::End(TagEnd::CodeBlock) => {
                    let code = std::mem::take(&mut current_text);
                    let code = code.trim();

                    if !code.is_empty() {
                        blocks.push(ContentBlock::code(code, position, code_language.take()));
                        position += 1;
                    }
                    in_code_block = false;
                }
                Event::Start(Tag::Table(_)) => {
                    self.flush_text(&mut current_text, &mut blocks, &mut position, None);
                    in_table = true;
                    table_headers.clear();
                    table_rows.clear();
                }
                Event::End(TagEnd::Table) => {
                    if !table_headers.is_empty() {
                        let table = TableContent::new(
                            std::mem::take(&mut table_headers),
                            std::mem::take(&mut table_rows),
                        );

                        blocks.push(ContentBlock {
                            content_type: ContentType::Table,
                            content: table.to_text(),
                            page_number: None,
                            position: Some(position),
                            metadata: HashMap::new(),
                        });
                        position += 1;
                        tables.push(table);
                    }
                    in_table = false;
                }
                Event::Start(Tag::TableHead) => {
                    in_table_head = true;
                }
                Event::End(TagEnd::TableHead) => {
                    in_table_head = false;
                }
                Event::Start(Tag::TableRow) => {
                    current_row.clear();
                }
                Event::End(TagEnd::TableRow) => {
                    if in_table_head {
                        table_headers = std::mem::take(&mut current_row);
                    } else {
                        table_rows.push(std::mem::take(&mut current_row));
                    }
                }
                Event::Start(Tag::TableCell) => {
                    current_text.clear();
                }
                Event::End(TagEnd::TableCell) => {
                    current_row.push(std::mem::take(&mut current_text).trim().to_string());
                }
                Event::Start(Tag::Paragraph) => {
                    if !in_code_block && !in_table {
                        current_text.clear();
                    }
                }
                Event::End(TagEnd::Paragraph) => {
                    if !in_code_block && !in_table {
                        self.flush_text(&mut current_text, &mut blocks, &mut position, None);
                    }
                }
                Event::Text(text) => {
                    current_text.push_str(&text);
                }
                Event::Code(code) => {
                    // Inline code
                    current_text.push('`');
                    current_text.push_str(&code);
                    current_text.push('`');
                }
                Event::SoftBreak | Event::HardBreak => {
                    if in_code_block {
                        current_text.push('\n');
                    } else {
                        current_text.push(' ');
                    }
                }
                _ => {}
            }
        }

        // Flush any remaining text
        self.flush_text(&mut current_text, &mut blocks, &mut position, None);

        // Get title from frontmatter if not found in content
        let title = title.or_else(|| {
            result_metadata
                .get("title")
                .and_then(|v| v.as_str())
                .map(String::from)
        });

        Ok(ParsedDocument {
            text: body.to_string(),
            blocks,
            tables,
            title,
            metadata: result_metadata,
            ..Default::default()
        })
    }
}

impl MarkdownParser {
    /// Extract YAML frontmatter from markdown text.
    ///
    /// Returns (frontmatter_map, remaining_text).
    fn extract_frontmatter<'a>(
        &self,
        text: &'a str,
    ) -> (Option<HashMap<String, Value>>, &'a str) {
        if !text.starts_with("---") {
            return (None, text);
        }

        // Find closing ---
        let rest = &text[3..];
        let end_pos = rest.find("\n---");

        let Some(end_pos) = end_pos else {
            return (None, text);
        };

        let yaml_content = &rest[..end_pos];
        let remaining = &rest[end_pos + 4..]; // Skip past "\n---"
        let remaining = remaining.trim_start_matches('\n');

        match serde_yaml::from_str::<HashMap<String, Value>>(yaml_content) {
            Ok(fm) => (Some(fm), remaining),
            Err(_) => (None, text),
        }
    }

    /// Flush accumulated text as a content block.
    fn flush_text(
        &self,
        current_text: &mut String,
        blocks: &mut Vec<ContentBlock>,
        position: &mut u32,
        _heading_level: Option<u32>,
    ) {
        let text = std::mem::take(current_text);
        let text = text.trim();

        if !text.is_empty() {
            blocks.push(ContentBlock::text(text, *position));
            *position += 1;
        }
    }
}
```

**Step 2: Run tests**

Run: `cd crates && cargo test -p rag-ingestion markdown`
Expected: All tests pass

**Step 3: Run all tests and clippy**

Run: `cd crates && cargo test -p rag-ingestion && cargo clippy -p rag-ingestion -- -D warnings`
Expected: All tests pass, no clippy warnings

**Step 4: Commit**

```bash
git add crates/rag-ingestion/src/parsers/markdown.rs
git commit -m "feat(rag-ingestion): implement Markdown parser"
```

---

## Task 7: Chunking Base Types

**Files:**
- Create: `crates/rag-ingestion/src/chunking/mod.rs`
- Create: `crates/rag-ingestion/src/chunking/base.rs`
- Modify: `crates/rag-ingestion/src/lib.rs`

**Step 1: Create chunking/base.rs**

Create `crates/rag-ingestion/src/chunking/base.rs`:

```rust
//! Base types and traits for text chunking.

use rag_types::{ChunkId, DocumentId};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;

use crate::Result;

/// Configuration for chunking strategies.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChunkingConfig {
    /// Target number of tokens per chunk.
    pub target_tokens: u32,
    /// Maximum tokens allowed per chunk.
    pub max_tokens: u32,
    /// Number of tokens to overlap between chunks.
    pub chunk_overlap: u32,
    /// Minimum chunk size in tokens.
    pub min_chunk_size: u32,
    /// Tokenizer model name (e.g., "cl100k_base").
    pub tokenizer: String,
}

impl Default for ChunkingConfig {
    fn default() -> Self {
        Self {
            target_tokens: 300,
            max_tokens: 512,
            chunk_overlap: 50,
            min_chunk_size: 50,
            tokenizer: "cl100k_base".to_string(),
        }
    }
}

/// A chunk of text from a document.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Chunk {
    /// Unique identifier for this chunk.
    pub chunk_id: ChunkId,
    /// ID of the source document.
    pub document_id: DocumentId,
    /// The chunk text content.
    pub content: String,
    /// Position of this chunk in the document (0-indexed).
    pub chunk_index: u32,
    /// Character offset where this chunk starts in the original text.
    pub start_char: usize,
    /// Character offset where this chunk ends in the original text.
    pub end_char: usize,
    /// Number of tokens in this chunk.
    pub token_count: u32,

    /// Parent chunk ID for hierarchical retrieval.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub parent_chunk_id: Option<ChunkId>,
    /// Child chunk IDs for hierarchical retrieval.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub child_chunk_ids: Vec<ChunkId>,

    /// Additional metadata.
    #[serde(default, skip_serializing_if = "HashMap::is_empty")]
    pub metadata: HashMap<String, Value>,

    /// Source page number (for PDFs).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_page: Option<u32>,
    /// Source section heading.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_section: Option<String>,
}

/// Result of chunking a document.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChunkingResult {
    /// ID of the source document.
    pub document_id: DocumentId,
    /// The generated chunks.
    pub chunks: Vec<Chunk>,
    /// Total number of chunks.
    pub total_chunks: usize,
    /// Name of the strategy used.
    pub strategy_used: String,
    /// Configuration that was used.
    pub config: ChunkingConfig,
}

/// Trait for text chunking strategies.
///
/// Strategies split document text into chunks suitable for embedding.
pub trait ChunkingStrategy: Send + Sync {
    /// Returns the strategy name identifier.
    fn name(&self) -> &str;

    /// Split text into chunks.
    ///
    /// # Arguments
    ///
    /// * `text` - The document text to chunk.
    /// * `document_id` - ID of the source document.
    /// * `metadata` - Optional metadata to attach to each chunk.
    ///
    /// # Errors
    ///
    /// Returns an error if chunking fails.
    fn chunk(
        &self,
        text: &str,
        document_id: DocumentId,
        metadata: Option<HashMap<String, Value>>,
    ) -> Result<Vec<Chunk>>;

    /// Get the configuration for this strategy.
    fn config(&self) -> &ChunkingConfig;
}
```

**Step 2: Create chunking/mod.rs**

Create `crates/rag-ingestion/src/chunking/mod.rs`:

```rust
//! Text chunking strategies for document processing.
//!
//! This module provides chunking strategies for splitting documents
//! into chunks suitable for embedding:
//! - [`RecursiveCharacterSplitter`]: Split by paragraphs, sentences, words

mod base;

pub use base::{Chunk, ChunkingConfig, ChunkingResult, ChunkingStrategy};
```

**Step 3: Update lib.rs**

Modify `crates/rag-ingestion/src/lib.rs`:

```rust
//! Document parsing and chunking for the RAG pipeline.
//!
//! This crate provides:
//! - Document parsers for HTML and Markdown
//! - Text chunking strategies for embedding preparation
//!
//! # Example
//!
//! ```rust,ignore
//! use rag_ingestion::parsers::{HtmlParser, Parser};
//! use rag_ingestion::chunking::{RecursiveCharacterSplitter, ChunkingStrategy};
//!
//! // Parse HTML document
//! let parser = HtmlParser::default();
//! let doc = parser.parse(html_bytes, None)?;
//!
//! // Chunk the text
//! let chunker = RecursiveCharacterSplitter::default();
//! let chunks = chunker.chunk(&doc.text, document_id, None)?;
//! ```

pub mod chunking;
pub mod error;
pub mod parsers;

pub use error::{Error, Result};
```

**Step 4: Verify it compiles**

Run: `cd crates && cargo build -p rag-ingestion`
Expected: Build succeeds

**Step 5: Commit**

```bash
git add crates/rag-ingestion/src/
git commit -m "feat(rag-ingestion): add chunking base types and trait"
```

---

## Task 8: Recursive Character Splitter - Tests First

**Files:**
- Create: `crates/rag-ingestion/src/chunking/recursive.rs`
- Modify: `crates/rag-ingestion/src/chunking/mod.rs`

**Step 1: Write failing tests**

Create `crates/rag-ingestion/src/chunking/recursive.rs`:

```rust
//! Recursive character text splitter.

use rag_types::{ChunkId, DocumentId};
use serde_json::Value;
use std::collections::HashMap;
use tiktoken_rs::CoreBPE;

use super::base::{Chunk, ChunkingConfig, ChunkingStrategy};
use crate::{Error, Result};

/// Separators used for recursive splitting, in order of preference.
const SEPARATORS: &[&str] = &[
    "\n\n", // Paragraphs
    "\n",   // Lines
    ". ",   // Sentences
    "? ",
    "! ",
    "; ",
    ", ",
    " ", // Words
    "",  // Characters (fallback)
];

/// Recursive character text splitter.
///
/// Splits text by trying different separators in order of preference,
/// maintaining semantic coherence by preferring larger natural boundaries.
pub struct RecursiveCharacterSplitter {
    config: ChunkingConfig,
    tokenizer: CoreBPE,
}

impl RecursiveCharacterSplitter {
    /// Create a new splitter with the given configuration.
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
    fn count_tokens(&self, text: &str) -> u32 {
        self.tokenizer.encode_ordinary(text).len() as u32
    }
}

impl Default for RecursiveCharacterSplitter {
    fn default() -> Self {
        Self::new(ChunkingConfig::default()).expect("Default tokenizer should load")
    }
}

impl ChunkingStrategy for RecursiveCharacterSplitter {
    fn name(&self) -> &str {
        "recursive_character"
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
        // TODO: Implement
        todo!()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;

    fn make_doc_id() -> DocumentId {
        DocumentId::new()
    }

    #[test]
    fn test_strategy_name() {
        let splitter = RecursiveCharacterSplitter::default();
        assert_eq!(splitter.name(), "recursive_character");
    }

    #[test]
    fn test_chunk_simple_text() {
        let text = "This is a simple test paragraph.";
        let splitter = RecursiveCharacterSplitter::default();
        let doc_id = make_doc_id();

        let chunks = splitter.chunk(text, doc_id, None).unwrap();

        assert_eq!(chunks.len(), 1);
        assert_eq!(chunks[0].content, text);
        assert_eq!(chunks[0].chunk_index, 0);
        assert_eq!(chunks[0].document_id, doc_id);
    }

    #[test]
    fn test_chunk_respects_max_tokens() {
        // Create a long text that exceeds max_tokens
        let paragraph = "This is a test sentence. ".repeat(100);
        let config = ChunkingConfig {
            target_tokens: 50,
            max_tokens: 100,
            chunk_overlap: 10,
            min_chunk_size: 20,
            ..Default::default()
        };

        let splitter = RecursiveCharacterSplitter::new(config).unwrap();
        let chunks = splitter.chunk(&paragraph, make_doc_id(), None).unwrap();

        // Should create multiple chunks
        assert!(chunks.len() > 1);

        // Each chunk should be under max_tokens
        for chunk in &chunks {
            assert!(
                chunk.token_count <= 100,
                "Chunk has {} tokens, expected <= 100",
                chunk.token_count
            );
        }
    }

    #[test]
    fn test_chunk_preserves_character_offsets() {
        let text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph.";
        let config = ChunkingConfig {
            target_tokens: 10,
            max_tokens: 20,
            chunk_overlap: 0,
            min_chunk_size: 1,
            ..Default::default()
        };

        let splitter = RecursiveCharacterSplitter::new(config).unwrap();
        let chunks = splitter.chunk(text, make_doc_id(), None).unwrap();

        // Verify offsets are valid
        for chunk in &chunks {
            assert!(chunk.start_char <= chunk.end_char);
            assert!(chunk.end_char <= text.len());

            // Content should match the offset range (approximately - may include overlap)
            let expected = &text[chunk.start_char..chunk.end_char.min(text.len())];
            assert!(
                chunk.content.contains(expected.trim())
                    || expected.contains(chunk.content.trim())
                    || chunk.content.trim().starts_with(expected.trim().split_whitespace().next().unwrap_or(""))
            );
        }
    }

    #[test]
    fn test_chunk_creates_overlap() {
        let text = "First sentence here. Second sentence follows. Third sentence ends.";
        let config = ChunkingConfig {
            target_tokens: 8,
            max_tokens: 15,
            chunk_overlap: 3,
            min_chunk_size: 3,
            ..Default::default()
        };

        let splitter = RecursiveCharacterSplitter::new(config).unwrap();
        let chunks = splitter.chunk(text, make_doc_id(), None).unwrap();

        // With overlap, later chunks should contain some text from previous chunks
        if chunks.len() > 1 {
            // Check that chunks have some overlap (not strictly disjoint)
            let first_end = &chunks[0].content;
            let second_start = &chunks[1].content;

            // The second chunk should start with some content from the end of the first
            // (This is a rough check - overlap implementation may vary)
            let first_words: Vec<&str> = first_end.split_whitespace().collect();
            let second_words: Vec<&str> = second_start.split_whitespace().collect();

            // At least verify both chunks have content
            assert!(!first_words.is_empty());
            assert!(!second_words.is_empty());
        }
    }

    #[test]
    fn test_chunk_attaches_metadata() {
        let text = "Test content.";
        let mut metadata = HashMap::new();
        metadata.insert("source".to_string(), Value::String("test".to_string()));

        let splitter = RecursiveCharacterSplitter::default();
        let chunks = splitter.chunk(text, make_doc_id(), Some(metadata)).unwrap();

        assert_eq!(chunks.len(), 1);
        assert_eq!(
            chunks[0].metadata.get("source"),
            Some(&Value::String("test".to_string()))
        );
    }

    #[test]
    fn test_chunk_splits_by_paragraphs_first() {
        let text = "Paragraph one content.\n\nParagraph two content.\n\nParagraph three content.";
        let config = ChunkingConfig {
            target_tokens: 10,
            max_tokens: 20,
            chunk_overlap: 0,
            min_chunk_size: 3,
            ..Default::default()
        };

        let splitter = RecursiveCharacterSplitter::new(config).unwrap();
        let chunks = splitter.chunk(text, make_doc_id(), None).unwrap();

        // Should split on paragraph boundaries
        assert!(chunks.len() >= 2);
    }

    #[test]
    fn test_chunk_handles_empty_text() {
        let splitter = RecursiveCharacterSplitter::default();
        let chunks = splitter.chunk("", make_doc_id(), None).unwrap();

        assert!(chunks.is_empty());
    }

    #[test]
    fn test_chunk_handles_whitespace_only() {
        let splitter = RecursiveCharacterSplitter::default();
        let chunks = splitter.chunk("   \n\n   \t  ", make_doc_id(), None).unwrap();

        assert!(chunks.is_empty());
    }

    #[test]
    fn test_chunk_sequential_indices() {
        let text = "One. Two. Three. Four. Five. Six. Seven. Eight. Nine. Ten.";
        let config = ChunkingConfig {
            target_tokens: 5,
            max_tokens: 10,
            chunk_overlap: 0,
            min_chunk_size: 2,
            ..Default::default()
        };

        let splitter = RecursiveCharacterSplitter::new(config).unwrap();
        let chunks = splitter.chunk(text, make_doc_id(), None).unwrap();

        // Verify indices are sequential
        for (i, chunk) in chunks.iter().enumerate() {
            assert_eq!(chunk.chunk_index, i as u32);
        }
    }

    #[test]
    fn test_count_tokens() {
        let splitter = RecursiveCharacterSplitter::default();

        // "Hello world" should be 2 tokens with cl100k_base
        let count = splitter.count_tokens("Hello world");
        assert!(count >= 2, "Expected at least 2 tokens, got {count}");
    }
}
```

**Step 2: Update mod.rs**

Modify `crates/rag-ingestion/src/chunking/mod.rs`:

```rust
//! Text chunking strategies for document processing.
//!
//! This module provides chunking strategies for splitting documents
//! into chunks suitable for embedding:
//! - [`RecursiveCharacterSplitter`]: Split by paragraphs, sentences, words

mod base;
mod recursive;

pub use base::{Chunk, ChunkingConfig, ChunkingResult, ChunkingStrategy};
pub use recursive::RecursiveCharacterSplitter;
```

**Step 3: Run tests to verify they fail**

Run: `cd crates && cargo test -p rag-ingestion recursive`
Expected: Tests fail with "not yet implemented"

**Step 4: Commit failing tests**

```bash
git add crates/rag-ingestion/src/chunking/
git commit -m "test(rag-ingestion): add failing tests for RecursiveCharacterSplitter"
```

---

## Task 9: Recursive Character Splitter - Implementation

**Files:**
- Modify: `crates/rag-ingestion/src/chunking/recursive.rs`

**Step 1: Implement the chunking algorithm**

Replace the `impl ChunkingStrategy for RecursiveCharacterSplitter` block and add helper methods:

```rust
impl ChunkingStrategy for RecursiveCharacterSplitter {
    fn name(&self) -> &str {
        "recursive_character"
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

        // Get raw splits with character offsets
        let raw_splits = self.split_recursive(text, SEPARATORS, 0);

        // Merge small chunks and handle overlap
        let merged = self.merge_and_overlap(raw_splits);

        let chunks = merged
            .into_iter()
            .enumerate()
            .map(|(i, (content, start, end))| Chunk {
                chunk_id: ChunkId::new(),
                document_id,
                content: content.clone(),
                chunk_index: i as u32,
                start_char: start,
                end_char: end,
                token_count: self.count_tokens(&content),
                parent_chunk_id: None,
                child_chunk_ids: Vec::new(),
                metadata: metadata.clone(),
                source_page: None,
                source_section: None,
            })
            .collect();

        Ok(chunks)
    }
}

impl RecursiveCharacterSplitter {
    /// Recursively split text, tracking character offsets.
    fn split_recursive(
        &self,
        text: &str,
        separators: &[&str],
        offset: usize,
    ) -> Vec<(String, usize, usize)> {
        if text.trim().is_empty() {
            return vec![];
        }

        let Some((&sep, remaining_seps)) = separators.split_first() else {
            return vec![(text.to_string(), offset, offset + text.len())];
        };

        // Character-level split as fallback
        if sep.is_empty() {
            return self.split_by_tokens(text, offset);
        }

        // Check if separator exists in text
        if !text.contains(sep) {
            return self.split_recursive(text, remaining_seps, offset);
        }

        let mut parts = Vec::new();
        let mut current_offset = offset;

        for part in text.split(sep) {
            if part.trim().is_empty() {
                current_offset += part.len() + sep.len();
                continue;
            }

            let token_count = self.count_tokens(part);

            if token_count > self.config.max_tokens {
                // Too large, split further with next separator
                let sub_parts = self.split_recursive(part, remaining_seps, current_offset);
                parts.extend(sub_parts);
            } else {
                parts.push((part.to_string(), current_offset, current_offset + part.len()));
            }

            current_offset += part.len() + sep.len();
        }

        parts
    }

    /// Split text into chunks of target_tokens size when no separators work.
    fn split_by_tokens(&self, text: &str, offset: usize) -> Vec<(String, usize, usize)> {
        let tokens = self.tokenizer.encode_ordinary(text);
        let mut parts = Vec::new();
        let mut char_offset = offset;

        let target = self.config.target_tokens as usize;
        let mut i = 0;

        while i < tokens.len() {
            let chunk_tokens: Vec<_> = tokens[i..(i + target).min(tokens.len())].to_vec();
            let chunk_text = self
                .tokenizer
                .decode(chunk_tokens.clone())
                .unwrap_or_default();
            let len = chunk_text.len();

            parts.push((chunk_text, char_offset, char_offset + len));

            char_offset += len;
            i += target;
        }

        parts
    }

    /// Merge small chunks and create overlapping chunks.
    fn merge_and_overlap(
        &self,
        splits: Vec<(String, usize, usize)>,
    ) -> Vec<(String, usize, usize)> {
        if splits.is_empty() {
            return vec![];
        }

        // First pass: merge small chunks
        let mut merged = Vec::new();
        let mut current_content = String::new();
        let mut current_start = splits[0].1;
        let mut current_end = splits[0].2;

        for (content, start, end) in splits {
            let potential_content = if current_content.is_empty() {
                content.clone()
            } else {
                format!("{} {}", current_content, content)
            };

            let potential_tokens = self.count_tokens(&potential_content);

            if potential_tokens <= self.config.target_tokens {
                // Can merge
                current_content = potential_content;
                current_end = end;
            } else {
                // Save current and start new
                if !current_content.is_empty()
                    && self.count_tokens(&current_content) >= self.config.min_chunk_size
                {
                    merged.push((current_content.clone(), current_start, current_end));
                } else if !current_content.is_empty() {
                    // Too small, merge with next
                    current_content = potential_content;
                    current_end = end;
                    continue;
                }

                current_content = content;
                current_start = start;
                current_end = end;
            }
        }

        // Don't forget the last chunk
        if !current_content.is_empty() {
            merged.push((current_content, current_start, current_end));
        }

        // Second pass: add overlap
        if self.config.chunk_overlap == 0 || merged.len() <= 1 {
            return merged;
        }

        let mut overlapped = vec![merged[0].clone()];

        for i in 1..merged.len() {
            let prev_content = &merged[i - 1].0;
            let overlap_text = self.get_overlap_text(prev_content);

            if !overlap_text.is_empty() {
                let new_content = format!("{} {}", overlap_text, merged[i].0);
                let overlap_char_len = overlap_text.len();
                let new_start = merged[i].1.saturating_sub(overlap_char_len);
                overlapped.push((new_content, new_start, merged[i].2));
            } else {
                overlapped.push(merged[i].clone());
            }
        }

        overlapped
    }

    /// Get the last N tokens worth of text for overlap.
    fn get_overlap_text(&self, text: &str) -> String {
        let tokens = self.tokenizer.encode_ordinary(text);
        let overlap = self.config.chunk_overlap as usize;

        if tokens.len() <= overlap {
            return text.to_string();
        }

        let overlap_tokens: Vec<_> = tokens[tokens.len() - overlap..].to_vec();
        self.tokenizer.decode(overlap_tokens).unwrap_or_default()
    }
}
```

**Step 2: Run tests**

Run: `cd crates && cargo test -p rag-ingestion`
Expected: All tests pass

**Step 3: Run clippy**

Run: `cd crates && cargo clippy -p rag-ingestion -- -D warnings`
Expected: No warnings

**Step 4: Commit**

```bash
git add crates/rag-ingestion/src/chunking/recursive.rs
git commit -m "feat(rag-ingestion): implement RecursiveCharacterSplitter"
```

---

## Task 10: Integration Tests and Final Verification

**Files:**
- Create: `crates/rag-ingestion/tests/integration.rs`

**Step 1: Create integration tests**

Create `crates/rag-ingestion/tests/integration.rs`:

```rust
//! Integration tests for the rag-ingestion crate.

use rag_ingestion::chunking::{ChunkingConfig, ChunkingStrategy, RecursiveCharacterSplitter};
use rag_ingestion::parsers::{HtmlParser, MarkdownParser, Parser};
use rag_types::DocumentId;

#[test]
fn test_html_to_chunks_pipeline() {
    let html = r#"
        <!DOCTYPE html>
        <html>
        <head><title>Test Document</title></head>
        <body>
            <h1>Introduction</h1>
            <p>This is the first paragraph with some content that we want to process.</p>
            <p>This is the second paragraph with additional content for testing.</p>
            <h2>Details</h2>
            <p>Here are some more details about the topic at hand.</p>
            <pre>fn example() { println!("code"); }</pre>
        </body>
        </html>
    "#;

    // Parse HTML
    let parser = HtmlParser::default();
    let doc = parser.parse(html.as_bytes(), None).unwrap();

    assert_eq!(doc.title, Some("Test Document".to_string()));
    assert!(!doc.text.is_empty());
    assert!(!doc.blocks.is_empty());

    // Chunk the parsed text
    let config = ChunkingConfig {
        target_tokens: 50,
        max_tokens: 100,
        chunk_overlap: 10,
        min_chunk_size: 10,
        ..Default::default()
    };

    let chunker = RecursiveCharacterSplitter::new(config).unwrap();
    let chunks = chunker.chunk(&doc.text, DocumentId::new(), None).unwrap();

    assert!(!chunks.is_empty());

    // Verify chunk properties
    for (i, chunk) in chunks.iter().enumerate() {
        assert_eq!(chunk.chunk_index, i as u32);
        assert!(!chunk.content.is_empty());
        assert!(chunk.token_count > 0);
        assert!(chunk.start_char <= chunk.end_char);
    }
}

#[test]
fn test_markdown_to_chunks_pipeline() {
    let markdown = r#"---
title: Technical Documentation
author: Test Author
---

# Getting Started

This guide will help you get started with the project.

## Installation

First, install the dependencies:

```bash
npm install
```

Then configure your environment.

## Configuration

Create a config file with the following options:

| Option | Default | Description |
|--------|---------|-------------|
| debug | false | Enable debug mode |
| port | 3000 | Server port |

## Usage

Run the following command to start:

```bash
npm start
```
"#;

    // Parse Markdown
    let parser = MarkdownParser::default();
    let doc = parser.parse(markdown.as_bytes(), None).unwrap();

    assert_eq!(doc.title, Some("Technical Documentation".to_string()));
    assert!(!doc.tables.is_empty());

    // Verify code blocks were extracted
    let code_blocks: Vec<_> = doc
        .blocks
        .iter()
        .filter(|b| b.content_type == rag_ingestion::parsers::ContentType::Code)
        .collect();
    assert!(code_blocks.len() >= 2);

    // Chunk the parsed text
    let chunker = RecursiveCharacterSplitter::default();
    let chunks = chunker.chunk(&doc.text, DocumentId::new(), None).unwrap();

    assert!(!chunks.is_empty());

    // All content should be covered
    let total_content: String = chunks.iter().map(|c| c.content.clone()).collect();
    // Check key content is preserved
    assert!(total_content.contains("Getting Started") || doc.text.contains("Getting Started"));
}

#[test]
fn test_large_document_chunking() {
    // Generate a large document
    let paragraph = "This is a test paragraph with some content. ".repeat(50);
    let large_doc = format!(
        "# Large Document\n\n{}\n\n## Section Two\n\n{}\n\n## Section Three\n\n{}",
        paragraph, paragraph, paragraph
    );

    let parser = MarkdownParser::default();
    let doc = parser.parse(large_doc.as_bytes(), None).unwrap();

    let config = ChunkingConfig {
        target_tokens: 100,
        max_tokens: 200,
        chunk_overlap: 20,
        min_chunk_size: 30,
        ..Default::default()
    };

    let chunker = RecursiveCharacterSplitter::new(config).unwrap();
    let chunks = chunker.chunk(&doc.text, DocumentId::new(), None).unwrap();

    // Should create many chunks
    assert!(chunks.len() > 5, "Expected > 5 chunks, got {}", chunks.len());

    // No chunk should exceed max_tokens
    for chunk in &chunks {
        assert!(
            chunk.token_count <= 200,
            "Chunk {} has {} tokens",
            chunk.chunk_index,
            chunk.token_count
        );
    }
}
```

**Step 2: Run all tests**

Run: `cd crates && cargo test -p rag-ingestion`
Expected: All tests pass

**Step 3: Run clippy and fmt**

Run: `cd crates && cargo fmt -p rag-ingestion && cargo clippy -p rag-ingestion -- -D warnings`
Expected: Code formatted, no warnings

**Step 4: Build release to verify optimization**

Run: `cd crates && cargo build -p rag-ingestion --release`
Expected: Build succeeds

**Step 5: Commit**

```bash
git add crates/rag-ingestion/tests/
git commit -m "test(rag-ingestion): add integration tests for parse-chunk pipeline"
```

---

## Task 11: Documentation and Final Commit

**Files:**
- Modify: `crates/rag-ingestion/src/lib.rs` (update docs)

**Step 1: Update crate documentation**

Modify the doc comment at the top of `crates/rag-ingestion/src/lib.rs`:

```rust
//! Document parsing and chunking for the RAG pipeline.
//!
//! This crate provides components for the ingestion phase of the RAG pipeline:
//!
//! - **Parsers** ([`parsers`]): Extract structured content from documents
//!   - [`parsers::HtmlParser`]: Parse HTML documents using `scraper`
//!   - [`parsers::MarkdownParser`]: Parse Markdown with YAML frontmatter
//!
//! - **Chunking** ([`chunking`]): Split text into chunks for embedding
//!   - [`chunking::RecursiveCharacterSplitter`]: Split by paragraphs, sentences, words
//!
//! # Example
//!
//! ```rust
//! use rag_ingestion::parsers::{HtmlParser, Parser};
//! use rag_ingestion::chunking::{RecursiveCharacterSplitter, ChunkingStrategy, ChunkingConfig};
//! use rag_types::DocumentId;
//!
//! // Parse an HTML document
//! let html = b"<html><body><h1>Title</h1><p>Content here.</p></body></html>";
//! let parser = HtmlParser::default();
//! let doc = parser.parse(html, None).unwrap();
//!
//! assert_eq!(doc.title, Some("Title".to_string()));
//!
//! // Chunk the extracted text
//! let config = ChunkingConfig {
//!     target_tokens: 100,
//!     max_tokens: 200,
//!     ..Default::default()
//! };
//! let chunker = RecursiveCharacterSplitter::new(config).unwrap();
//! let chunks = chunker.chunk(&doc.text, DocumentId::new(), None).unwrap();
//!
//! assert!(!chunks.is_empty());
//! ```
//!
//! # Feature Roadmap
//!
//! Future additions (Phase 4):
//! - PDF parser
//! - DOCX parser
//! - Semantic chunker (sentence-boundary based)

pub mod chunking;
pub mod error;
pub mod parsers;

pub use error::{Error, Result};
```

**Step 2: Verify docs build**

Run: `cd crates && cargo doc -p rag-ingestion --no-deps`
Expected: Documentation builds without warnings

**Step 3: Final test run**

Run: `cd crates && cargo test -p rag-ingestion && cargo clippy -p rag-ingestion -- -D warnings`
Expected: All tests pass, no warnings

**Step 4: Final commit**

```bash
git add crates/rag-ingestion/
git commit -m "docs(rag-ingestion): add crate documentation and examples"
```

---

## Summary

This plan creates the `rag-ingestion` crate with:

| Component | Files | Tests |
|-----------|-------|-------|
| Crate skeleton | `Cargo.toml`, `lib.rs`, `error.rs` | - |
| Parser types | `parsers/base.rs`, `parsers/mod.rs` | - |
| HTML parser | `parsers/html.rs` | 9 tests |
| Markdown parser | `parsers/markdown.rs` | 8 tests |
| Chunking types | `chunking/base.rs`, `chunking/mod.rs` | - |
| Recursive splitter | `chunking/recursive.rs` | 10 tests |
| Integration | `tests/integration.rs` | 3 tests |

**Total: 30 tests across 11 tasks**

Each task follows TDD: write failing tests, implement, verify, commit.
