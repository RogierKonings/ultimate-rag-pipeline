//! Markdown document parser.

use pulldown_cmark::{CodeBlockKind, Event, Options, Parser as MdParser, Tag, TagEnd};
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

    #[allow(clippy::too_many_lines)]
    fn parse(
        &self,
        content: &[u8],
        metadata: Option<HashMap<String, Value>>,
    ) -> Result<ParsedDocument> {
        let text = String::from_utf8_lossy(content);
        let mut result_metadata = metadata.unwrap_or_default();

        // Extract YAML frontmatter
        let (frontmatter, body) = Self::extract_frontmatter(&text);

        // Merge frontmatter into metadata (frontmatter values take precedence)
        if let Some(fm) = frontmatter {
            for (k, v) in fm {
                result_metadata.insert(k, v);
            }
        }

        // Parse markdown with pulldown-cmark (enable tables)
        let options = Options::ENABLE_TABLES;
        let parser = MdParser::new_ext(body, options);

        let mut blocks = Vec::new();
        let mut tables = Vec::new();
        // Get title from frontmatter first (if present)
        let mut title: Option<String> = result_metadata
            .get("title")
            .and_then(|v| v.as_str())
            .map(String::from);
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

        for event in parser {
            match event {
                Event::Start(Tag::Heading { level, .. }) => {
                    Self::flush_text(&mut current_text, &mut blocks, &mut position);
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
                            block
                                .metadata
                                .insert("heading_level".to_string(), Value::Number(level.into()));
                        }
                        blocks.push(block);
                        position += 1;
                    }
                    heading_level = None;
                }
                Event::Start(Tag::CodeBlock(kind)) => {
                    Self::flush_text(&mut current_text, &mut blocks, &mut position);
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
                    Self::flush_text(&mut current_text, &mut blocks, &mut position);
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
                Event::Start(Tag::TableHead | Tag::TableRow) => {
                    current_row.clear();
                }
                Event::End(TagEnd::TableHead) => {
                    // Header cells are directly under TableHead, not inside TableRow
                    table_headers = std::mem::take(&mut current_row);
                }
                Event::End(TagEnd::TableRow) => {
                    // Only data rows go here - headers are handled in TableHead
                    table_rows.push(std::mem::take(&mut current_row));
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
                        Self::flush_text(&mut current_text, &mut blocks, &mut position);
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
        Self::flush_text(&mut current_text, &mut blocks, &mut position);

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
    /// Returns a tuple of (frontmatter map, remaining text).
    fn extract_frontmatter(text: &str) -> (Option<HashMap<String, Value>>, &str) {
        if !text.starts_with("---") {
            return (None, text);
        }

        // Find closing ---
        let rest = &text[3..];
        let Some(end_pos) = rest.find("\n---") else {
            return (None, text);
        };

        let yaml_content = &rest[..end_pos];
        let remaining = &rest[end_pos + 4..]; // Skip past "\n---"
        let remaining = remaining.trim_start_matches('\n');

        serde_yaml::from_str::<HashMap<String, Value>>(yaml_content)
            .map_or((None, text), |fm| (Some(fm), remaining))
    }

    /// Flush accumulated text as a content block.
    fn flush_text(current_text: &mut String, blocks: &mut Vec<ContentBlock>, position: &mut u32) {
        let text = std::mem::take(current_text);
        let text = text.trim();

        if !text.is_empty() {
            blocks.push(ContentBlock::text(text, *position));
            *position += 1;
        }
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
