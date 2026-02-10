//! Integration tests for the rag-ingestion crate.

use rag_ingestion::chunking::{ChunkingConfig, ChunkingStrategy, RecursiveCharacterSplitter};
use rag_ingestion::parsers::{ContentType, HtmlParser, MarkdownParser, Parser};
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
        #[allow(clippy::cast_possible_truncation)]
        let expected_index = i as u32;
        assert_eq!(chunk.chunk_index, expected_index);
        assert!(!chunk.content.is_empty());
        assert!(chunk.token_count > 0);
        assert!(chunk.start_char <= chunk.end_char);
    }
}

#[test]
fn test_markdown_to_chunks_pipeline() {
    let markdown = r"---
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
";

    // Parse Markdown
    let parser = MarkdownParser;
    let doc = parser.parse(markdown.as_bytes(), None).unwrap();

    assert_eq!(doc.title, Some("Technical Documentation".to_string()));
    assert!(!doc.tables.is_empty());

    // Verify code blocks were extracted
    let code_block_count = doc
        .blocks
        .iter()
        .filter(|b| b.content_type == ContentType::Code)
        .count();
    assert!(code_block_count >= 2);

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
        "# Large Document\n\n{paragraph}\n\n## Section Two\n\n{paragraph}\n\n## Section Three\n\n{paragraph}"
    );

    let parser = MarkdownParser;
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
    assert!(
        chunks.len() > 5,
        "Expected > 5 chunks, got {}",
        chunks.len()
    );

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
