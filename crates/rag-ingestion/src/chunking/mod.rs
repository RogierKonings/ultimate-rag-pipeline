//! Text chunking strategies for document processing.
//!
//! This module provides chunking strategies for splitting documents
//! into chunks suitable for embedding:
//!
//! - **Auto** (default): analyzes the document and picks the best strategy via [`selector`]
//! - [`RecursiveCharacterSplitter`]: Split by paragraphs, sentences, words
//! - [`SemanticChunker`]: Split by sentence boundaries for prose-heavy text
//! - [`HierarchicalChunker`]: Split by detected document sections/headings
//! - [`TabularChunker`]: Row-per-chunk splitting for CSV, Markdown tables, HTML tables
//! - [`QAChunker`]: Question-and-answer pair splitting for FAQ documents
//! - [`MixedContentChunker`]: Zone-based splitting for mixed prose/table/code documents
//!
//! The [`selector`] module evaluates heading density, sentence length,
//! prose fraction, file type, table density, Q&A density, and parser-produced
//! blocks to pick the best strategy automatically.

mod base;
mod hierarchical;
pub(crate) mod mixed;
pub(crate) mod qa;
mod recursive;
mod selector;
mod semantic;
mod tabular;

pub use base::{Chunk, ChunkingConfig, ChunkingResult, ChunkingStrategy};
pub use hierarchical::HierarchicalChunker;
pub use mixed::MixedContentChunker;
pub use qa::QAChunker;
pub use recursive::RecursiveCharacterSplitter;
pub use selector::{analyze_document, select_strategy};
pub use semantic::{SemanticChunker, SemanticChunkerConfig};
pub use tabular::TabularChunker;
