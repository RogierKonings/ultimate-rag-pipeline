//! Markdown document parser.

use pulldown_cmark::{Event, Parser as MdParser, Tag, TagEnd};
use serde_json::Value;
use std::collections::HashMap;

#[allow(unused_imports)] // Used by implementation in next task
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
        let _ = (content, metadata);
        let _ = MdParser::new("");
        let _ = (Event::Start(Tag::Paragraph), TagEnd::Paragraph);
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
