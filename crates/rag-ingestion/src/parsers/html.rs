//! HTML document parser.

use scraper::{Html, Selector};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;

#[allow(unused_imports)] // Used by implementation in next task
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
        // TODO: Implement
        let _ = (&self.config, content, metadata);
        let _ = Html::new_document();
        let _ = Selector::parse("body");
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
        assert!(links.iter().any(
            |l| { l.get("href").and_then(|h| h.as_str()) == Some("https://example.com") }
        ));
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
