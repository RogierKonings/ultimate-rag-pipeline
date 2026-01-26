# Rust Ingestion: Parsers and Chunking Design

> **Date:** 2025-01-26
> **Phase:** 3.1-3.3 of Rust Migration
> **Scope:** HTML Parser, Markdown Parser, Recursive Character Chunker

## Overview

This document describes the design for the first components of the Rust ingestion service: document parsers and text chunking. These are pure computation components with no external service dependencies, making them ideal starting points.

## Crate Structure

```
crates/rag-ingestion/
├── Cargo.toml
└── src/
    ├── lib.rs
    ├── error.rs
    ├── parsers/
    │   ├── mod.rs
    │   ├── base.rs        # Parser trait + ParsedDocument types
    │   ├── html.rs        # HTML parser (scraper crate)
    │   └── markdown.rs    # Markdown parser (pulldown-cmark + serde_yaml)
    └── chunking/
        ├── mod.rs
        ├── base.rs        # ChunkingStrategy trait + Chunk type
        └── recursive.rs   # RecursiveCharacterSplitter
```

## Dependencies

| Crate | Version | Purpose |
|-------|---------|---------|
| `rag-types` | internal | `DocumentId`, `ChunkId` |
| `scraper` | 0.20 | HTML parsing (html5ever-based) |
| `pulldown-cmark` | 0.11 | Markdown parsing |
| `serde_yaml` | 0.9 | YAML frontmatter extraction |
| `tiktoken-rs` | 0.5 | Token counting (cl100k_base) |
| `serde` | 1.0 | Serialization |
| `serde_json` | 1.0 | JSON metadata |
| `thiserror` | 1.0 | Error types |
| `uuid` | 1.0 | UUID generation |

## Parser Types

### ContentType

```rust
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum ContentType {
    Text,
    Table,
    Image,
    Code,
}
```

### ContentBlock

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ContentBlock {
    pub content_type: ContentType,
    pub content: String,
    pub page_number: Option<u32>,
    pub position: Option<u32>,
    #[serde(default)]
    pub metadata: HashMap<String, Value>,
}
```

### TableContent

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TableContent {
    pub headers: Vec<String>,
    pub rows: Vec<Vec<String>>,
    pub caption: Option<String>,
}
```

### ParsedDocument

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ParsedDocument {
    pub text: String,
    pub blocks: Vec<ContentBlock>,
    pub tables: Vec<TableContent>,
    pub title: Option<String>,
    pub author: Option<String>,
    pub created_date: Option<String>,
    pub modified_date: Option<String>,
    pub page_count: Option<u32>,
    pub language: Option<String>,
    #[serde(default)]
    pub metadata: HashMap<String, Value>,
}
```

### Parser Trait

```rust
pub trait Parser: Send + Sync {
    fn supported_mime_types(&self) -> &[&str];

    fn parse(
        &self,
        content: &[u8],
        metadata: Option<HashMap<String, Value>>
    ) -> Result<ParsedDocument>;

    fn can_parse(&self, mime_type: &str) -> bool {
        self.supported_mime_types().contains(&mime_type)
    }
}
```

## HTML Parser

- Uses `scraper` crate (html5ever-based)
- Pre-compiled selectors for performance
- Configurable: `remove_scripts`, `remove_styles`, `remove_comments`, `extract_links`
- Extracts: title, semantic blocks (p, h1-h6, li, blockquote), code blocks, tables, links

**MIME types:** `text/html`, `application/xhtml+xml`

## Markdown Parser

- Uses `pulldown-cmark` for event-based parsing
- Uses `serde_yaml` for frontmatter extraction
- Extracts: title (from H1 or frontmatter), code blocks with language, tables, text blocks

**MIME types:** `text/markdown`, `text/x-markdown`

## Chunking Types

### ChunkingConfig

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChunkingConfig {
    pub target_tokens: u32,      // Default: 300
    pub max_tokens: u32,         // Default: 512
    pub chunk_overlap: u32,      // Default: 50
    pub min_chunk_size: u32,     // Default: 50
    pub tokenizer: String,       // Default: "cl100k_base"
}
```

### Chunk

```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Chunk {
    pub chunk_id: ChunkId,
    pub document_id: DocumentId,
    pub content: String,
    pub chunk_index: u32,
    pub start_char: usize,
    pub end_char: usize,
    pub token_count: u32,
    pub parent_chunk_id: Option<ChunkId>,
    #[serde(default)]
    pub child_chunk_ids: Vec<ChunkId>,
    #[serde(default)]
    pub metadata: HashMap<String, Value>,
    pub source_page: Option<u32>,
    pub source_section: Option<String>,
}
```

### ChunkingStrategy Trait

```rust
pub trait ChunkingStrategy: Send + Sync {
    fn name(&self) -> &str;

    fn chunk(
        &self,
        text: &str,
        document_id: DocumentId,
        metadata: Option<HashMap<String, Value>>,
    ) -> Result<Vec<Chunk>>;
}
```

## Recursive Character Splitter

Algorithm (matches Python implementation):

1. **Split recursively** using separators in order: `\n\n`, `\n`, `. `, `? `, `! `, `; `, `, `, ` `, ``
2. **Track character offsets** for citation support
3. **Merge small chunks** below `min_chunk_size`
4. **Add overlap** from previous chunk's last N tokens

Uses `tiktoken-rs` with `cl100k_base` tokenizer for exact parity with Python.

## Not Included

- PDF/DOCX parsers (Phase 4)
- SemanticChunker with spaCy (Phase 4)
- API layer (after P3.4-P3.6)
- HierarchicalChunker (can be added later)

## Testing Strategy

1. Unit tests for each parser with fixture files
2. Unit tests for chunker with known inputs
3. Parity tests comparing output to Python implementation
4. Property-based tests for chunker invariants (no content loss, valid offsets)

## Success Criteria

- All parsers pass unit tests
- Chunker produces identical token counts to Python
- Character offsets are accurate
- Performance: parsing + chunking faster than Python equivalent
