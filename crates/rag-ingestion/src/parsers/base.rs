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
    pub const fn new(headers: Vec<String>, rows: Vec<Vec<String>>) -> Self {
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
