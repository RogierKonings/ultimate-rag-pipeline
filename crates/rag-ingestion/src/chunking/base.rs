//! Base types and traits for text chunking.

use rag_types::{ChunkId, DocumentId};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;

use crate::Result;

/// Configuration for chunking strategies.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChunkingConfig {
    /// Target number of tokens per chunk.
    pub target_tokens: u32,
    /// Maximum tokens allowed per chunk.
    pub max_tokens: u32,
    /// Number of tokens to overlap between chunks.
    pub chunk_overlap: u32,
    /// Minimum chunk size in tokens.
    pub min_chunk_size: u32,
    /// Tokenizer model name (e.g., `cl100k_base`).
    pub tokenizer: String,
}

impl Default for ChunkingConfig {
    fn default() -> Self {
        Self {
            target_tokens: 300,
            max_tokens: 512,
            chunk_overlap: 50,
            min_chunk_size: 50,
            tokenizer: "cl100k_base".to_string(),
        }
    }
}

/// A chunk of text from a document.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Chunk {
    /// Unique identifier for this chunk.
    pub chunk_id: ChunkId,
    /// ID of the source document.
    pub document_id: DocumentId,
    /// The chunk text content.
    pub content: String,
    /// Position of this chunk in the document (0-indexed).
    pub chunk_index: u32,
    /// Character offset where this chunk starts in the original text.
    pub start_char: usize,
    /// Character offset where this chunk ends in the original text.
    pub end_char: usize,
    /// Number of tokens in this chunk.
    pub token_count: u32,

    /// Parent chunk ID for hierarchical retrieval.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub parent_chunk_id: Option<ChunkId>,
    /// Child chunk IDs for hierarchical retrieval.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub child_chunk_ids: Vec<ChunkId>,

    /// Additional metadata.
    #[serde(default, skip_serializing_if = "HashMap::is_empty")]
    pub metadata: HashMap<String, Value>,

    /// Source page number (for PDFs).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_page: Option<u32>,
    /// Source section heading.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub source_section: Option<String>,
}

/// Result of chunking a document.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChunkingResult {
    /// ID of the source document.
    pub document_id: DocumentId,
    /// The generated chunks.
    pub chunks: Vec<Chunk>,
    /// Total number of chunks.
    pub total_chunks: usize,
    /// Name of the strategy used.
    pub strategy_used: String,
    /// Configuration that was used.
    pub config: ChunkingConfig,
}

/// Trait for text chunking strategies.
///
/// Strategies split document text into chunks suitable for embedding.
pub trait ChunkingStrategy: Send + Sync {
    /// Returns the strategy name identifier.
    fn name(&self) -> &'static str;

    /// Split text into chunks.
    ///
    /// # Arguments
    ///
    /// * `text` - The document text to chunk.
    /// * `document_id` - ID of the source document.
    /// * `metadata` - Optional metadata to attach to each chunk.
    ///
    /// # Errors
    ///
    /// Returns an error if chunking fails.
    fn chunk(
        &self,
        text: &str,
        document_id: DocumentId,
        metadata: Option<HashMap<String, Value>>,
    ) -> Result<Vec<Chunk>>;

    /// Get the configuration for this strategy.
    fn config(&self) -> &ChunkingConfig;
}
