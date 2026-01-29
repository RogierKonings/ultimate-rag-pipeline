//! Text chunking strategies for document processing.
//!
//! This module provides chunking strategies for splitting documents
//! into chunks suitable for embedding:
//! - [`RecursiveCharacterSplitter`]: Split by paragraphs, sentences, words
//! - [`SemanticChunker`]: Split by sentence boundaries for better coherence

mod base;
mod recursive;
mod semantic;

pub use base::{Chunk, ChunkingConfig, ChunkingResult, ChunkingStrategy};
pub use recursive::RecursiveCharacterSplitter;
pub use semantic::{SemanticChunker, SemanticChunkerConfig};
