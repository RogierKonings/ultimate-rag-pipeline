//! Document parsing and chunking for the RAG pipeline.
//!
//! This crate provides:
//! - Document parsers for HTML and Markdown
//! - Text chunking strategies for embedding preparation
//!
//! # Example
//!
//! ```rust,ignore
//! use rag_ingestion::parsers::{HtmlParser, Parser};
//! use rag_ingestion::chunking::{RecursiveCharacterSplitter, ChunkingStrategy};
//!
//! // Parse HTML document
//! let parser = HtmlParser::default();
//! let doc = parser.parse(html_bytes, None)?;
//!
//! // Chunk the text
//! let chunker = RecursiveCharacterSplitter::default();
//! let chunks = chunker.chunk(&doc.text, document_id, None)?;
//! ```

pub mod error;
pub mod parsers;

pub use error::{Error, Result};
