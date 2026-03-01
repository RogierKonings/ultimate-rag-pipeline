//! Text chunking strategies for document processing.
//!
//! This module provides chunking strategies for splitting documents
//! into chunks suitable for embedding:
//! - **Auto** (default): analyzes the document and picks the best strategy via [`selector`]
//! - [`RecursiveCharacterSplitter`]: Split by paragraphs, sentences, words
//! - [`SemanticChunker`]: Split by sentence boundaries for prose-heavy text
//! - [`HierarchicalChunker`]: Split by detected document sections/headings
//!
//! The [`selector`] module evaluates heading density, sentence length,
//! prose fraction, file type, and parser-produced blocks to pick the best strategy.

mod base;
mod hierarchical;
mod recursive;
mod selector;
mod semantic;

pub use base::{Chunk, ChunkingConfig, ChunkingResult, ChunkingStrategy};
pub use hierarchical::HierarchicalChunker;
pub use recursive::RecursiveCharacterSplitter;
pub use selector::{analyze_document, select_strategy};
pub use semantic::{SemanticChunker, SemanticChunkerConfig};
