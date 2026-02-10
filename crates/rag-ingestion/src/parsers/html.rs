//! HTML document parser.

use scraper::{Html, Selector};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;

use super::base::{ContentBlock, ContentType, ParsedDocument, Parser, TableContent};
use crate::Result;

/// Configuration for the HTML parser.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[allow(clippy::struct_excessive_bools)]
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
    pub const fn new(config: HtmlParserConfig) -> Self {
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
                if let Some(table) = Self::extract_table(&table_el) {
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
            .map_or_else(|| document.root_element().id(), |el| el.id());

        self.collect_text_recursive(document, root, &mut texts);

        texts.join("\n")
    }

    /// Recursively collect text, skipping excluded tags.
    fn collect_text_recursive(
        &self,
        document: &Html,
        node_id: ego_tree::NodeId,
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
    fn extract_table(table_el: &scraper::ElementRef) -> Option<TableContent> {
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
                    .is_some_and(|el| el.name() == "thead");

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
        let html = r"
            <!DOCTYPE html>
            <html>
            <head><title>Test Document</title></head>
            <body>
                <h1>Hello World</h1>
                <p>This is a test paragraph.</p>
            </body>
            </html>
        ";

        let parser = HtmlParser::default();
        let result = parser.parse(html.as_bytes(), None).unwrap();

        assert_eq!(result.title, Some("Test Document".to_string()));
        assert!(result.text.contains("Hello World"));
        assert!(result.text.contains("This is a test paragraph"));
    }

    #[test]
    fn test_parse_extracts_blocks() {
        let html = r"
            <html>
            <body>
                <h1>Title</h1>
                <p>Paragraph one.</p>
                <p>Paragraph two.</p>
            </body>
            </html>
        ";

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
        assert!(text_blocks
            .iter()
            .any(|b| b.content.contains("Paragraph one")));
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
        let html = r"
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
        ";

        let parser = HtmlParser::default();
        let result = parser.parse(html.as_bytes(), None).unwrap();

        assert_eq!(result.tables.len(), 1);
        assert_eq!(result.tables[0].headers, vec!["Name", "Age"]);
        assert_eq!(result.tables[0].rows.len(), 2);
        assert_eq!(result.tables[0].rows[0], vec!["Alice", "30"]);
    }

    #[test]
    fn test_parse_extracts_links() {
        let html = r##"
            <html>
            <body>
                <a href="https://example.com">Example</a>
                <a href="#anchor">Internal</a>
            </body>
            </html>
        "##;

        let parser = HtmlParser::default();
        let result = parser.parse(html.as_bytes(), None).unwrap();

        let links = result.metadata.get("links");
        assert!(links.is_some());

        let links = links.unwrap().as_array().unwrap();
        // Should only include external link, not anchor
        assert!(links
            .iter()
            .any(|l| { l.get("href").and_then(|h| h.as_str()) == Some("https://example.com") }));
    }

    #[test]
    fn test_parse_removes_scripts() {
        let html = r"
            <html>
            <body>
                <p>Real content</p>
                <script>alert('malicious');</script>
            </body>
            </html>
        ";

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
