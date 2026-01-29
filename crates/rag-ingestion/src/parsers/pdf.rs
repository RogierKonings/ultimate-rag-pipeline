//! PDF document parser.
//!
//! Uses the `pdf-extract` crate for PDF text extraction.
//! For complex layouts with OCR, consider using a fallback HTTP service.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use thiserror::Error;

use crate::parsers::base::{ContentBlock, ContentType, ParsedDocument, Parser};

/// PDF parser configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PdfParserConfig {
    /// Maximum pages to process (None = all).
    pub max_pages: Option<usize>,
    /// Whether to extract tables.
    pub extract_tables: bool,
    /// URL for fallback HTTP service (e.g., Python PDF service).
    pub fallback_service_url: Option<String>,
}

impl Default for PdfParserConfig {
    fn default() -> Self {
        Self {
            max_pages: None,
            extract_tables: true,
            fallback_service_url: None,
        }
    }
}

/// PDF parsing errors.
#[derive(Debug, Error)]
pub enum PdfError {
    #[error("Failed to parse PDF: {0}")]
    ParseError(String),
    #[error("PDF file is encrypted")]
    Encrypted,
    #[error("No text content found in PDF")]
    NoContent,
    #[error("Fallback service error: {0}")]
    FallbackError(String),
}

/// PDF document parser.
pub struct PdfParser {
    config: PdfParserConfig,
}

impl PdfParser {
    /// Create a new PDF parser with default configuration.
    #[must_use]
    pub fn new() -> Self {
        Self::with_config(PdfParserConfig::default())
    }

    /// Create a new PDF parser with custom configuration.
    #[must_use]
    pub fn with_config(config: PdfParserConfig) -> Self {
        Self { config }
    }

    /// Parse PDF using the pdf-extract crate.
    fn parse_with_pdf_extract(&self, content: &[u8]) -> Result<ParsedDocument, PdfError> {
        // Extract text from PDF bytes
        let text = pdf_extract::extract_text_from_mem(content)
            .map_err(|e| PdfError::ParseError(e.to_string()))?;

        if text.trim().is_empty() {
            return Err(PdfError::NoContent);
        }

        // Split text by form feed characters (page breaks) if present
        let pages: Vec<&str> = text.split('\x0c').collect();
        let page_count = pages.len();

        let mut blocks = Vec::new();
        let mut full_text_parts = Vec::new();
        let max_pages = self.config.max_pages.unwrap_or(page_count);

        for (idx, page_text) in pages.iter().take(max_pages).enumerate() {
            let trimmed = page_text.trim();
            if !trimmed.is_empty() {
                full_text_parts.push(trimmed.to_string());

                let mut block_meta = HashMap::new();
                block_meta.insert("page".to_string(), Value::Number((idx + 1).into()));

                blocks.push(ContentBlock {
                    content_type: ContentType::Text,
                    content: trimmed.to_string(),
                    page_number: Some((idx + 1) as u32),
                    position: Some(idx as u32),
                    metadata: block_meta,
                });
            }
        }

        // If no page breaks, treat the whole text as one block
        if blocks.is_empty() && !text.trim().is_empty() {
            blocks.push(ContentBlock {
                content_type: ContentType::Text,
                content: text.trim().to_string(),
                page_number: Some(1),
                position: Some(0),
                metadata: HashMap::new(),
            });
            full_text_parts.push(text.trim().to_string());
        }

        Ok(ParsedDocument {
            text: full_text_parts.join("\n\n"),
            blocks,
            tables: Vec::new(),
            title: None,
            author: None,
            created_date: None,
            modified_date: None,
            page_count: Some(page_count as u32),
            language: None,
            metadata: HashMap::new(),
        })
    }
}

impl Default for PdfParser {
    fn default() -> Self {
        Self::new()
    }
}

impl Parser for PdfParser {
    fn supported_mime_types(&self) -> &[&str] {
        &["application/pdf"]
    }

    fn parse(
        &self,
        content: &[u8],
        metadata: Option<HashMap<String, Value>>,
    ) -> crate::Result<ParsedDocument> {
        match self.parse_with_pdf_extract(content) {
            Ok(mut doc) => {
                if let Some(meta) = metadata {
                    doc.metadata.extend(meta);
                }
                Ok(doc)
            }
            Err(e) => {
                tracing::warn!("PDF parsing failed: {}", e);
                Err(crate::Error::Parse(e.to_string()))
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_pdf_parser_config_default() {
        let config = PdfParserConfig::default();
        assert!(config.max_pages.is_none());
        assert!(config.extract_tables);
        assert!(config.fallback_service_url.is_none());
    }

    #[test]
    fn test_pdf_parser_supported_mime_types() {
        let parser = PdfParser::new();
        assert_eq!(parser.supported_mime_types(), &["application/pdf"]);
    }

    #[test]
    fn test_pdf_parser_with_config() {
        let config = PdfParserConfig {
            max_pages: Some(10),
            extract_tables: false,
            fallback_service_url: Some("http://localhost:8005".into()),
        };
        let parser = PdfParser::with_config(config);
        assert_eq!(parser.config.max_pages, Some(10));
    }

    #[test]
    fn test_parse_invalid_pdf() {
        let parser = PdfParser::new();
        let result = parser.parse(b"not a pdf", None);
        assert!(result.is_err());
    }

    #[test]
    fn test_can_parse() {
        let parser = PdfParser::new();
        assert!(parser.can_parse("application/pdf"));
        assert!(!parser.can_parse("text/html"));
    }
}
