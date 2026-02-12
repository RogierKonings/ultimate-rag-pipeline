//! PDF document parser.
//!
//! Uses the `pdf-extract` crate for PDF text extraction with a fallback to
//! the `pdftotext` CLI (from poppler-utils) for PDFs that `pdf-extract` cannot handle.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use std::io::Write;
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
    /// Whether to attempt OCR for scanned/image-based PDFs.
    pub ocr_enabled: bool,
    /// Tesseract language code(s) for OCR (e.g., "eng", "eng+nld").
    pub ocr_language: String,
}

impl Default for PdfParserConfig {
    fn default() -> Self {
        Self {
            max_pages: None,
            extract_tables: true,
            fallback_service_url: None,
            ocr_enabled: true,
            ocr_language: "eng".to_string(),
        }
    }
}

/// PDF parsing errors.
#[derive(Debug, Error)]
pub enum PdfError {
    #[error("Failed to parse PDF: {0}")]
    ParseError(String),
    #[error("No text content found in PDF")]
    NoContent,
    #[error("OCR failed: {0}")]
    OcrError(String),
    #[error("OCR is required but tesseract is not available. Install tesseract-ocr to process scanned PDFs.")]
    OcrNotAvailable,
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
        let text = pdf_extract::extract_text_from_mem(content)
            .map_err(|e| PdfError::ParseError(e.to_string()))?;

        self.text_to_document(&text)
    }

    /// Fallback: parse PDF by shelling out to `pdftotext` (poppler-utils).
    fn parse_with_pdftotext(&self, content: &[u8]) -> Result<ParsedDocument, PdfError> {
        // Write bytes to a temp file since pdftotext reads from a file path.
        let mut tmp = tempfile::NamedTempFile::new()
            .map_err(|e| PdfError::ParseError(format!("Failed to create temp file: {e}")))?;
        tmp.write_all(content)
            .map_err(|e| PdfError::ParseError(format!("Failed to write temp file: {e}")))?;
        tmp.flush()
            .map_err(|e| PdfError::ParseError(format!("Failed to flush temp file: {e}")))?;

        let output = std::process::Command::new("pdftotext")
            .arg("-layout")
            .arg(tmp.path())
            .arg("-") // write to stdout
            .output()
            .map_err(|e| PdfError::ParseError(format!("pdftotext not available: {e}")))?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(PdfError::ParseError(format!("pdftotext failed: {stderr}")));
        }

        let text = String::from_utf8_lossy(&output.stdout).into_owned();
        self.text_to_document(&text)
    }

    /// Convert extracted text into a `ParsedDocument`.
    fn text_to_document(&self, text: &str) -> Result<ParsedDocument, PdfError> {
        if text.trim().is_empty() {
            return Err(PdfError::NoContent);
        }

        // Split text by form feed characters (page breaks) if present
        let pages: Vec<&str> = text.split('\x0c').collect();
        let page_count = pages.len();

        let mut blocks = Vec::new();
        let mut full_text_parts = Vec::new();
        let max_pages = self.config.max_pages.unwrap_or(page_count);

        #[allow(clippy::cast_possible_truncation)] // page indices fit in u32
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

        #[allow(clippy::cast_possible_truncation)] // page count fits in u32
        let page_count_u32 = page_count as u32;
        Ok(ParsedDocument {
            text: full_text_parts.join("\n\n"),
            blocks,
            tables: Vec::new(),
            title: None,
            author: None,
            created_date: None,
            modified_date: None,
            page_count: Some(page_count_u32),
            language: None,
            metadata: HashMap::new(),
        })
    }

    /// Check if tesseract is available on the system.
    fn is_tesseract_available() -> bool {
        std::process::Command::new("tesseract")
            .arg("--version")
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false)
    }

    /// Fallback: parse scanned PDF via OCR using pdftoppm + tesseract.
    #[allow(clippy::too_many_lines)]
    fn parse_with_ocr(&self, content: &[u8]) -> Result<ParsedDocument, PdfError> {
        if !Self::is_tesseract_available() {
            return Err(PdfError::OcrNotAvailable);
        }

        let tmp_dir = tempfile::TempDir::new()
            .map_err(|e| PdfError::OcrError(format!("Failed to create temp dir: {e}")))?;

        let pdf_path = tmp_dir.path().join("input.pdf");
        std::fs::write(&pdf_path, content)
            .map_err(|e| PdfError::OcrError(format!("Failed to write temp PDF: {e}")))?;

        // Convert PDF to PPM images using pdftoppm (from poppler-utils)
        let ppm_prefix = tmp_dir.path().join("page");

        let mut pdftoppm_cmd = std::process::Command::new("pdftoppm");
        pdftoppm_cmd
            .arg("-r")
            .arg("300") // 300 DPI for good OCR quality
            .arg(&pdf_path)
            .arg(&ppm_prefix);

        if let Some(max_pages) = self.config.max_pages {
            pdftoppm_cmd.arg("-l").arg(max_pages.to_string());
        }

        let pdftoppm_output = pdftoppm_cmd
            .output()
            .map_err(|e| PdfError::OcrError(format!("pdftoppm not available: {e}")))?;

        if !pdftoppm_output.status.success() {
            let stderr = String::from_utf8_lossy(&pdftoppm_output.stderr);
            return Err(PdfError::OcrError(format!("pdftoppm failed: {stderr}")));
        }

        // Collect generated image files sorted by name (page order)
        let mut image_files: Vec<std::path::PathBuf> = std::fs::read_dir(tmp_dir.path())
            .map_err(|e| PdfError::OcrError(format!("Failed to read temp dir: {e}")))?
            .filter_map(std::result::Result::ok)
            .map(|entry| entry.path())
            .filter(|path| {
                path.extension()
                    .and_then(|ext| ext.to_str())
                    .is_some_and(|ext| ext == "ppm" || ext == "pgm" || ext == "pbm")
            })
            .collect();

        image_files.sort();

        if image_files.is_empty() {
            return Err(PdfError::OcrError(
                "pdftoppm produced no image files".to_string(),
            ));
        }

        // Run tesseract on each page image
        let max_pages = self.config.max_pages.unwrap_or(image_files.len());
        let mut blocks = Vec::new();
        let mut full_text_parts = Vec::new();

        #[allow(clippy::cast_possible_truncation)]
        for (idx, image_path) in image_files.iter().take(max_pages).enumerate() {
            let output = std::process::Command::new("tesseract")
                .arg(image_path)
                .arg("stdout")
                .arg("-l")
                .arg(&self.config.ocr_language)
                .output()
                .map_err(|e| {
                    PdfError::OcrError(format!("tesseract failed on page {}: {e}", idx + 1))
                })?;

            if !output.status.success() {
                let stderr = String::from_utf8_lossy(&output.stderr);
                tracing::warn!(page = idx + 1, stderr = %stderr, "tesseract warning on page");
                continue;
            }

            let page_text = String::from_utf8_lossy(&output.stdout).into_owned();
            let trimmed = page_text.trim();

            if !trimmed.is_empty() {
                full_text_parts.push(trimmed.to_string());

                let mut block_meta = HashMap::new();
                block_meta.insert("page".to_string(), Value::Number((idx + 1).into()));
                block_meta.insert(
                    "extraction_method".to_string(),
                    Value::String("ocr".to_string()),
                );

                blocks.push(ContentBlock {
                    content_type: ContentType::Text,
                    content: trimmed.to_string(),
                    page_number: Some((idx + 1) as u32),
                    position: Some(idx as u32),
                    metadata: block_meta,
                });
            }
        }

        if blocks.is_empty() {
            return Err(PdfError::OcrError(
                "OCR completed but extracted no text from any page".to_string(),
            ));
        }

        #[allow(clippy::cast_possible_truncation)]
        let page_count = image_files.len() as u32;

        let mut doc_metadata = HashMap::new();
        doc_metadata.insert(
            "extraction_method".to_string(),
            Value::String("ocr".to_string()),
        );

        Ok(ParsedDocument {
            text: full_text_parts.join("\n\n"),
            blocks,
            tables: Vec::new(),
            title: None,
            author: None,
            created_date: None,
            modified_date: None,
            page_count: Some(page_count),
            language: None,
            metadata: doc_metadata,
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
        // Step 1: Try pdf-extract (fast, native Rust)
        let result = self.parse_with_pdf_extract(content);

        // Step 2: On failure, try pdftotext (poppler CLI)
        let result = result.or_else(|e| {
            tracing::warn!("pdf-extract failed ({e}), trying pdftotext fallback");
            self.parse_with_pdftotext(content)
        });

        // Step 3: If text extraction found no content, try OCR
        let result = result.or_else(|e| {
            if self.config.ocr_enabled {
                tracing::info!(
                    "Text extraction failed ({e}), attempting OCR fallback for scanned PDF"
                );
                self.parse_with_ocr(content)
            } else {
                tracing::warn!("Text extraction failed and OCR is disabled");
                Err(e)
            }
        });

        match result {
            Ok(mut doc) => {
                if doc
                    .metadata
                    .get("extraction_method")
                    .and_then(|v| v.as_str())
                    == Some("ocr")
                {
                    tracing::info!("PDF parsed successfully using OCR fallback");
                }
                if let Some(meta) = metadata {
                    doc.metadata.extend(meta);
                }
                Ok(doc)
            }
            Err(PdfError::OcrNotAvailable) => {
                tracing::error!(
                    "PDF appears to be scanned/image-based but tesseract-ocr is not installed"
                );
                Err(crate::Error::Parse(
                    "PDF appears to be scanned/image-based and requires OCR, \
                     but tesseract-ocr is not installed. \
                     Install tesseract-ocr to process scanned PDFs."
                        .to_string(),
                ))
            }
            Err(PdfError::OcrError(msg)) => {
                tracing::error!(error = %msg, "OCR fallback also failed for scanned PDF");
                Err(crate::Error::Parse(format!(
                    "PDF appears to be scanned/image-based. \
                     Text extraction and OCR both failed. OCR error: {msg}"
                )))
            }
            Err(PdfError::NoContent) => {
                tracing::warn!("PDF parsing produced no text content from any method");
                Err(crate::Error::Parse(
                    "No text content found in PDF. \
                     The document may be empty or contain only images."
                        .to_string(),
                ))
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
        assert!(config.ocr_enabled);
        assert_eq!(config.ocr_language, "eng");
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
            ocr_enabled: true,
            ocr_language: "eng+nld".to_string(),
        };
        let parser = PdfParser::with_config(config);
        assert_eq!(parser.config.max_pages, Some(10));
        assert_eq!(parser.config.ocr_language, "eng+nld");
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

    #[test]
    fn test_text_to_document_empty() {
        let parser = PdfParser::new();
        let result = parser.text_to_document("");
        assert!(matches!(result, Err(PdfError::NoContent)));
    }

    #[test]
    fn test_text_to_document_with_pages() {
        let parser = PdfParser::new();
        let text = "Page 1 content\x0cPage 2 content";
        let doc = parser.text_to_document(text).unwrap();
        assert_eq!(doc.blocks.len(), 2);
        assert_eq!(doc.page_count, Some(2));
    }

    #[test]
    fn test_is_tesseract_available_does_not_panic() {
        let _available = PdfParser::is_tesseract_available();
    }

    #[test]
    fn test_ocr_disabled_does_not_attempt_ocr() {
        let config = PdfParserConfig {
            ocr_enabled: false,
            ..PdfParserConfig::default()
        };
        let parser = PdfParser::with_config(config);
        let result = parser.parse(b"not a pdf", None);
        assert!(result.is_err());
        let err_msg = result.unwrap_err().to_string();
        assert!(
            !err_msg.contains("OCR"),
            "Error should not mention OCR when disabled: {err_msg}"
        );
    }
}
