//! Document parsing and chunking for the RAG pipeline.
//!
//! This crate provides components for the ingestion phase of the RAG pipeline:
//!
//! - **Parsers** ([`parsers`]): Extract structured content from documents
//!   - [`parsers::HtmlParser`]: Parse HTML documents using `scraper`
//!   - [`parsers::MarkdownParser`]: Parse Markdown with YAML frontmatter
//!
//! - **Chunking** ([`chunking`]): Split text into chunks for embedding
//!   - [`chunking::RecursiveCharacterSplitter`]: Split by paragraphs, sentences, words
//!
//! # Example
//!
//! ```rust
//! use rag_ingestion::parsers::{HtmlParser, Parser};
//! use rag_ingestion::chunking::{RecursiveCharacterSplitter, ChunkingStrategy, ChunkingConfig};
//! use rag_types::DocumentId;
//!
//! // Parse an HTML document
//! let html = b"<html><head><title>Title</title></head><body><p>Content here.</p></body></html>";
//! let parser = HtmlParser::default();
//! let doc = parser.parse(html, None).unwrap();
//!
//! assert_eq!(doc.title, Some("Title".to_string()));
//!
//! // Chunk the extracted text
//! let config = ChunkingConfig {
//!     target_tokens: 100,
//!     max_tokens: 200,
//!     ..Default::default()
//! };
//! let chunker = RecursiveCharacterSplitter::new(config).unwrap();
//! let chunks = chunker.chunk(&doc.text, DocumentId::new(), None).unwrap();
//!
//! assert!(!chunks.is_empty());
//! ```
//!
//! # Feature Roadmap
//!
//! Future additions (Phase 4):
//! - PDF parser
//! - DOCX parser
//! - Semantic chunker (sentence-boundary based)

pub mod chunking;
pub mod connectors;
pub mod embedding;
pub mod error;
pub mod indexing;
pub mod parsers;

pub use error::{Error, Result};
