//! Text chunking strategies for document processing.
//!
//! This module provides chunking strategies for splitting documents
//! into chunks suitable for embedding:
//! - [`RecursiveCharacterSplitter`]: Split by paragraphs, sentences, words

mod base;
mod recursive;

pub use base::{Chunk, ChunkingConfig, ChunkingResult, ChunkingStrategy};
pub use recursive::RecursiveCharacterSplitter;
