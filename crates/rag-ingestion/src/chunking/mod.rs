//! Text chunking strategies for document processing.
//!
//! This module provides chunking strategies for splitting documents
//! into chunks suitable for embedding:
//! - [`RecursiveCharacterSplitter`]: Split by paragraphs, sentences, words (default)
//! - [`SemanticChunker`]: Split by sentence boundaries for prose-heavy text
//! - [`HierarchicalChunker`]: Split by detected document sections/headings
//!
//! When no strategy is explicitly requested, the [`selector`] module
//! auto-selects the best strategy by analyzing document characteristics
//! (heading density, sentence length, file type, parser-produced blocks).

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
