//! DOCX (Office Open XML) document parser.
//!
//! Parses Word documents by extracting text from the XML structure.

use quick_xml::events::Event;
use quick_xml::Reader;
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use std::io::Read;
use thiserror::Error;
use zip::ZipArchive;

use crate::parsers::base::{ContentBlock, ContentType, ParsedDocument, Parser, TableContent};

/// DOCX parser configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocxParserConfig {
    /// Whether to extract tables.
    pub extract_tables: bool,
    /// Whether to preserve style information.
    pub preserve_styles: bool,
}

impl Default for DocxParserConfig {
    fn default() -> Self {
        Self {
            extract_tables: true,
            preserve_styles: false,
        }
    }
}

/// DOCX parsing errors.
#[derive(Debug, Error)]
pub enum DocxError {
    #[error("Failed to read ZIP archive: {0}")]
    ZipError(String),
    #[error("Invalid DOCX structure: missing {0}")]
    InvalidStructure(String),
    #[error("XML parsing error: {0}")]
    XmlError(String),
    #[error("IO error: {0}")]
    IoError(#[from] std::io::Error),
}

/// DOCX document parser.
pub struct DocxParser {
    config: DocxParserConfig,
}

impl DocxParser {
    /// Create a new DOCX parser with default configuration.
    #[must_use]
    pub fn new() -> Self {
        Self::with_config(DocxParserConfig::default())
    }

    /// Create a new DOCX parser with custom configuration.
    #[must_use]
    pub fn with_config(config: DocxParserConfig) -> Self {
        Self { config }
    }

    /// Extract text content from DOCX document.
    #[allow(clippy::type_complexity)] // return type is clear in context
    fn extract_content(
        &self,
        content: &[u8],
    ) -> Result<(Vec<String>, Vec<ContentBlock>, Vec<TableContent>), DocxError> {
        let cursor = std::io::Cursor::new(content);
        let mut archive =
            ZipArchive::new(cursor).map_err(|e| DocxError::ZipError(e.to_string()))?;

        // Read document.xml (main content)
        let mut doc_xml = String::new();
        {
            let mut doc_file = archive
                .by_name("word/document.xml")
                .map_err(|_| DocxError::InvalidStructure("word/document.xml".into()))?;
            doc_file.read_to_string(&mut doc_xml)?;
        }

        // Parse XML content
        let (paragraphs, blocks, tables) = self.parse_document_xml(&doc_xml)?;

        Ok((paragraphs, blocks, tables))
    }

    /// Parse the document.xml content.
    #[allow(clippy::type_complexity, clippy::too_many_lines)]
    fn parse_document_xml(
        &self,
        xml: &str,
    ) -> Result<(Vec<String>, Vec<ContentBlock>, Vec<TableContent>), DocxError> {
        let mut reader = Reader::from_str(xml);
        reader.config_mut().trim_text(true);

        let mut paragraphs = Vec::new();
        let mut blocks = Vec::new();
        let mut tables = Vec::new();

        let mut current_paragraph = String::new();
        let mut current_style: Option<String> = None;
        let mut in_paragraph = false;
        let mut in_table = false;
        let mut current_table_rows: Vec<Vec<String>> = Vec::new();
        let mut current_row: Vec<String> = Vec::new();
        let mut current_cell = String::new();
        let mut position = 0u32;

        let mut buf = Vec::new();

        loop {
            match reader.read_event_into(&mut buf) {
                Ok(Event::Start(ref e)) => match e.name().as_ref() {
                    b"w:p" => {
                        in_paragraph = true;
                        current_paragraph.clear();
                        current_style = None;
                    }
                    b"w:tbl" => {
                        in_table = true;
                        current_table_rows.clear();
                    }
                    b"w:tr" => {
                        current_row.clear();
                    }
                    b"w:tc" => {
                        current_cell.clear();
                    }
                    b"w:pStyle" => {
                        // Extract style name
                        for attr in e.attributes().flatten() {
                            if attr.key.as_ref() == b"w:val" {
                                current_style =
                                    Some(String::from_utf8_lossy(&attr.value).to_string());
                            }
                        }
                    }
                    _ => {}
                },
                Ok(Event::Text(ref e)) => {
                    let text = e.decode().unwrap_or_default();
                    if in_table {
                        current_cell.push_str(&text);
                    } else if in_paragraph {
                        current_paragraph.push_str(&text);
                    }
                }
                Ok(Event::End(ref e)) => match e.name().as_ref() {
                    b"w:p" => {
                        if !current_paragraph.trim().is_empty() {
                            let text = current_paragraph.trim().to_string();
                            if !in_table {
                                paragraphs.push(text.clone());

                                let mut metadata = HashMap::new();
                                if self.config.preserve_styles {
                                    if let Some(ref style) = current_style {
                                        metadata.insert(
                                            "style".to_string(),
                                            Value::String(style.clone()),
                                        );
                                    }
                                }

                                blocks.push(ContentBlock {
                                    content_type: ContentType::Text,
                                    content: text,
                                    page_number: None,
                                    position: Some(position),
                                    metadata,
                                });
                                position += 1;
                            }
                        }
                        in_paragraph = false;
                    }
                    b"w:tc" => {
                        current_row.push(current_cell.trim().to_string());
                    }
                    b"w:tr" => {
                        if !current_row.is_empty() {
                            current_table_rows.push(current_row.clone());
                        }
                    }
                    b"w:tbl" => {
                        if self.config.extract_tables && !current_table_rows.is_empty() {
                            if let Some(table) = self.rows_to_table(&current_table_rows) {
                                // Add table text to blocks
                                blocks.push(ContentBlock {
                                    content_type: ContentType::Table,
                                    content: self.table_to_text(&table),
                                    page_number: None,
                                    position: Some(position),
                                    metadata: HashMap::new(),
                                });
                                position += 1;
                                tables.push(table);
                            }
                        }
                        in_table = false;
                    }
                    _ => {}
                },
                Ok(Event::Eof) => break,
                Err(e) => return Err(DocxError::XmlError(e.to_string())),
                _ => {}
            }
            buf.clear();
        }

        Ok((paragraphs, blocks, tables))
    }

    /// Convert rows to `TableContent` (first row as headers).
    #[allow(clippy::unused_self)] // kept as method for API consistency
    fn rows_to_table(&self, rows: &[Vec<String>]) -> Option<TableContent> {
        if rows.is_empty() {
            return None;
        }

        let headers = rows[0].clone();
        let data_rows = if rows.len() > 1 {
            rows[1..].to_vec()
        } else {
            Vec::new()
        };

        Some(TableContent {
            headers,
            rows: data_rows,
            caption: None,
        })
    }

    /// Convert table to plain text.
    #[allow(clippy::unused_self)] // kept as method for API consistency
    fn table_to_text(&self, table: &TableContent) -> String {
        let mut lines = Vec::new();

        // Headers
        lines.push(table.headers.join(" | "));
        lines.push("-".repeat(lines[0].len()));

        // Rows
        for row in &table.rows {
            lines.push(row.join(" | "));
        }

        lines.join("\n")
    }

    /// Extract core properties (metadata) from DOCX.
    #[allow(clippy::unused_self)] // kept as method for API consistency
    fn extract_core_properties(
        &self,
        content: &[u8],
    ) -> Result<HashMap<String, String>, DocxError> {
        let cursor = std::io::Cursor::new(content);
        let mut archive =
            ZipArchive::new(cursor).map_err(|e| DocxError::ZipError(e.to_string()))?;

        let mut props = HashMap::new();

        // Try to read core.xml
        if let Ok(mut core_file) = archive.by_name("docProps/core.xml") {
            let mut core_xml = String::new();
            core_file.read_to_string(&mut core_xml)?;

            let mut reader = Reader::from_str(&core_xml);
            reader.config_mut().trim_text(true);

            let mut buf = Vec::new();
            let mut current_tag: Option<String> = None;

            loop {
                match reader.read_event_into(&mut buf) {
                    Ok(Event::Start(ref e)) => {
                        let name = String::from_utf8_lossy(e.name().as_ref()).to_string();
                        current_tag = Some(name);
                    }
                    Ok(Event::Text(ref e)) => {
                        if let Some(ref tag) = current_tag {
                            let text = e.decode().unwrap_or_default().to_string();
                            if !text.is_empty() {
                                props.insert(tag.clone(), text);
                            }
                        }
                    }
                    Ok(Event::End(_)) => {
                        current_tag = None;
                    }
                    Ok(Event::Eof) | Err(_) => break,
                    _ => {}
                }
                buf.clear();
            }
        }

        Ok(props)
    }
}

impl Default for DocxParser {
    fn default() -> Self {
        Self::new()
    }
}

impl Parser for DocxParser {
    fn supported_mime_types(&self) -> &[&str] {
        &["application/vnd.openxmlformats-officedocument.wordprocessingml.document"]
    }

    fn parse(
        &self,
        content: &[u8],
        metadata: Option<HashMap<String, Value>>,
    ) -> crate::Result<ParsedDocument> {
        let (paragraphs, blocks, tables) = self
            .extract_content(content)
            .map_err(|e| crate::Error::Parse(e.to_string()))?;

        let core_props = self.extract_core_properties(content).unwrap_or_default();

        let mut doc_metadata: HashMap<String, Value> = HashMap::new();
        if let Some(meta) = metadata {
            doc_metadata.extend(meta);
        }

        Ok(ParsedDocument {
            text: paragraphs.join("\n\n"),
            blocks,
            tables,
            title: core_props.get("dc:title").cloned(),
            author: core_props.get("dc:creator").cloned(),
            created_date: core_props.get("dcterms:created").cloned(),
            modified_date: core_props.get("dcterms:modified").cloned(),
            page_count: None,
            language: None,
            metadata: doc_metadata,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_docx_parser_config_default() {
        let config = DocxParserConfig::default();
        assert!(config.extract_tables);
        assert!(!config.preserve_styles);
    }

    #[test]
    fn test_docx_parser_supported_mime_types() {
        let parser = DocxParser::new();
        let types = parser.supported_mime_types();
        assert_eq!(types.len(), 1);
        assert!(types[0].contains("wordprocessingml"));
    }

    #[test]
    fn test_parse_invalid_docx() {
        let parser = DocxParser::new();
        let result = parser.parse(b"not a docx", None);
        assert!(result.is_err());
    }

    #[test]
    fn test_table_to_text() {
        let parser = DocxParser::new();
        let table = TableContent {
            headers: vec!["Col1".into(), "Col2".into()],
            rows: vec![vec!["A".into(), "B".into()]],
            caption: None,
        };
        let text = parser.table_to_text(&table);
        assert!(text.contains("Col1 | Col2"));
        assert!(text.contains("A | B"));
    }

    #[test]
    fn test_rows_to_table() {
        let parser = DocxParser::new();
        let rows = vec![
            vec!["Header1".into(), "Header2".into()],
            vec!["Value1".into(), "Value2".into()],
        ];
        let table = parser.rows_to_table(&rows);
        assert!(table.is_some());
        let t = table.unwrap();
        assert_eq!(t.headers, vec!["Header1", "Header2"]);
        assert_eq!(t.rows.len(), 1);
    }

    #[test]
    fn test_can_parse() {
        let parser = DocxParser::new();
        assert!(parser
            .can_parse("application/vnd.openxmlformats-officedocument.wordprocessingml.document"));
        assert!(!parser.can_parse("text/html"));
    }
}
