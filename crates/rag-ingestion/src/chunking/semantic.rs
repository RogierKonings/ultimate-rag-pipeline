//! Semantic chunker for sentence-aware text splitting.
//!
//! Unlike the recursive character splitter, this chunker respects
//! sentence boundaries for better semantic coherence.

use rag_types::{ChunkId, DocumentId};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use tiktoken_rs::CoreBPE;
use unicode_segmentation::UnicodeSegmentation;

use super::base::{Chunk, ChunkingConfig, ChunkingStrategy};
use crate::{Error, Result};

/// Configuration for semantic chunking.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SemanticChunkerConfig {
    /// Target token count per chunk.
    pub target_tokens: u32,
    /// Maximum token count per chunk.
    pub max_tokens: u32,
    /// Token overlap between chunks.
    pub chunk_overlap: u32,
    /// Minimum chunk size in tokens.
    pub min_chunk_size: u32,
}

impl Default for SemanticChunkerConfig {
    fn default() -> Self {
        Self {
            target_tokens: 300,
            max_tokens: 512,
            chunk_overlap: 50,
            min_chunk_size: 50,
        }
    }
}

impl From<SemanticChunkerConfig> for ChunkingConfig {
    fn from(config: SemanticChunkerConfig) -> Self {
        Self {
            target_tokens: config.target_tokens,
            max_tokens: config.max_tokens,
            chunk_overlap: config.chunk_overlap,
            min_chunk_size: config.min_chunk_size,
            tokenizer: "cl100k_base".to_string(),
        }
    }
}

impl From<ChunkingConfig> for SemanticChunkerConfig {
    fn from(config: ChunkingConfig) -> Self {
        Self {
            target_tokens: config.target_tokens,
            max_tokens: config.max_tokens,
            chunk_overlap: config.chunk_overlap,
            min_chunk_size: config.min_chunk_size,
        }
    }
}

/// Semantic chunker that splits on sentence boundaries.
pub struct SemanticChunker {
    config: SemanticChunkerConfig,
    tokenizer: CoreBPE,
}

impl SemanticChunker {
    /// Create a new semantic chunker with default configuration.
    ///
    /// # Errors
    ///
    /// Returns an error if the tokenizer cannot be loaded.
    pub fn new() -> Result<Self> {
        Self::with_config(SemanticChunkerConfig::default())
    }

    /// Create a new semantic chunker with custom configuration.
    ///
    /// # Errors
    ///
    /// Returns an error if the tokenizer cannot be loaded.
    pub fn with_config(config: SemanticChunkerConfig) -> Result<Self> {
        let tokenizer = tiktoken_rs::cl100k_base()
            .map_err(|e| Error::Config(format!("Failed to load tokenizer: {e}")))?;

        Ok(Self { config, tokenizer })
    }

    /// Count tokens in text.
    #[allow(clippy::cast_possible_truncation)]
    fn count_tokens(&self, text: &str) -> u32 {
        self.tokenizer.encode_ordinary(text).len() as u32
    }

    /// Split text into sentences using unicode segmentation.
    fn split_sentences<'a>(&self, text: &'a str) -> Vec<&'a str> {
        text.unicode_sentences().collect()
    }

    /// Split a long sentence that exceeds max_tokens into smaller pieces.
    fn split_long_sentence(
        &self,
        sentence: &str,
        start_char: usize,
        document_id: DocumentId,
        base_index: u32,
        metadata: &HashMap<String, Value>,
    ) -> Vec<Chunk> {
        let mut chunks = Vec::new();
        let tokens = self.tokenizer.encode_ordinary(sentence);
        let mut i = 0;
        let mut char_offset = start_char;
        let mut sub_index = 0u32;

        while i < tokens.len() {
            let chunk_tokens: Vec<_> = tokens
                .iter()
                .skip(i)
                .take(self.config.max_tokens as usize)
                .copied()
                .collect();

            let chunk_text = self.tokenizer.decode(chunk_tokens.clone()).unwrap_or_default();

            let chunk_len = chunk_text.len();

            chunks.push(Chunk {
                chunk_id: ChunkId::new(),
                document_id,
                content: chunk_text,
                chunk_index: base_index + sub_index,
                start_char: char_offset,
                end_char: char_offset + chunk_len,
                #[allow(clippy::cast_possible_truncation)]
                token_count: chunk_tokens.len() as u32,
                parent_chunk_id: None,
                child_chunk_ids: Vec::new(),
                metadata: metadata.clone(),
                source_page: None,
                source_section: None,
            });

            char_offset += chunk_len;
            i += self.config.max_tokens as usize;
            sub_index += 1;
        }

        chunks
    }

    /// Get overlap sentences from the end of a sentence list.
    fn get_overlap_sentences<'a>(
        &self,
        sentences: &[&'a str],
        overlap_tokens: u32,
    ) -> Vec<&'a str> {
        let mut result = Vec::new();
        let mut total = 0u32;

        for &sent in sentences.iter().rev() {
            let tokens = self.count_tokens(sent);
            if total + tokens > overlap_tokens {
                break;
            }
            result.insert(0, sent);
            total += tokens;
        }

        result
    }

    /// Create a chunk from a list of sentences.
    fn create_chunk(
        &self,
        sentences: &[&str],
        document_id: DocumentId,
        chunk_index: u32,
        start_char: usize,
        end_char: usize,
        metadata: &HashMap<String, Value>,
    ) -> Chunk {
        let content = sentences.join(" ");
        Chunk {
            chunk_id: ChunkId::new(),
            document_id,
            content: content.clone(),
            chunk_index,
            start_char,
            end_char,
            token_count: self.count_tokens(&content),
            parent_chunk_id: None,
            child_chunk_ids: Vec::new(),
            metadata: metadata.clone(),
            source_page: None,
            source_section: None,
        }
    }
}

impl Default for SemanticChunker {
    fn default() -> Self {
        Self::new().expect("Default tokenizer should load")
    }
}

impl ChunkingStrategy for SemanticChunker {
    fn name(&self) -> &str {
        "semantic_sentence"
    }

    fn config(&self) -> &ChunkingConfig {
        // Convert on the fly
        // This is a bit inefficient but keeps the interface consistent
        // A better approach would be to store a ChunkingConfig directly
        // For now, we create it on demand
        Box::leak(Box::new(ChunkingConfig::from(self.config.clone())))
    }

    fn chunk(
        &self,
        text: &str,
        document_id: DocumentId,
        metadata: Option<HashMap<String, Value>>,
    ) -> Result<Vec<Chunk>> {
        let metadata = metadata.unwrap_or_default();
        let sentences = self.split_sentences(text);

        let mut chunks = Vec::new();
        let mut current_sentences: Vec<&str> = Vec::new();
        let mut current_tokens = 0u32;
        let mut current_start = 0usize;
        let mut chunk_index = 0u32;

        // Track character positions
        let mut char_pos = 0usize;

        for sent in &sentences {
            let sent_trimmed = sent.trim();
            if sent_trimmed.is_empty() {
                char_pos += sent.len();
                continue;
            }

            let sent_tokens = self.count_tokens(sent_trimmed);

            // Handle sentences that exceed max tokens
            if sent_tokens > self.config.max_tokens {
                // Flush current chunk first
                if !current_sentences.is_empty() {
                    let chunk = self.create_chunk(
                        &current_sentences,
                        document_id,
                        chunk_index,
                        current_start,
                        char_pos,
                        &metadata,
                    );
                    chunks.push(chunk);
                    chunk_index += 1;
                    current_sentences.clear();
                    current_tokens = 0;
                }

                // Split the long sentence
                let sub_chunks = self.split_long_sentence(
                    sent_trimmed,
                    char_pos,
                    document_id,
                    chunk_index,
                    &metadata,
                );
                let sub_count = sub_chunks.len() as u32;
                chunks.extend(sub_chunks);
                chunk_index += sub_count;

                char_pos += sent.len();
                current_start = char_pos;
                continue;
            }

            // Check if adding this sentence exceeds target size
            if current_tokens + sent_tokens > self.config.target_tokens {
                // Create chunk from current sentences
                if !current_sentences.is_empty() {
                    let chunk = self.create_chunk(
                        &current_sentences,
                        document_id,
                        chunk_index,
                        current_start,
                        char_pos,
                        &metadata,
                    );
                    chunks.push(chunk);
                    chunk_index += 1;

                    // Get overlap sentences
                    let overlap =
                        self.get_overlap_sentences(&current_sentences, self.config.chunk_overlap);
                    current_sentences = overlap.into_iter().collect();
                    current_tokens = current_sentences.iter().map(|s| self.count_tokens(s)).sum();
                    current_start = char_pos;
                }
            }

            if current_sentences.is_empty() {
                current_start = char_pos;
            }
            current_sentences.push(sent_trimmed);
            current_tokens += sent_tokens;
            char_pos += sent.len();
        }

        // Don't forget the last chunk
        if !current_sentences.is_empty() {
            let chunk = self.create_chunk(
                &current_sentences,
                document_id,
                chunk_index,
                current_start,
                char_pos,
                &metadata,
            );
            chunks.push(chunk);
        }

        Ok(chunks)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_doc_id() -> DocumentId {
        DocumentId::new()
    }

    #[test]
    fn test_semantic_chunker_config_default() {
        let config = SemanticChunkerConfig::default();
        assert_eq!(config.target_tokens, 300);
        assert_eq!(config.max_tokens, 512);
        assert_eq!(config.chunk_overlap, 50);
        assert_eq!(config.min_chunk_size, 50);
    }

    #[test]
    fn test_semantic_chunker_name() {
        let chunker = SemanticChunker::default();
        assert_eq!(chunker.name(), "semantic_sentence");
    }

    #[test]
    fn test_split_sentences() {
        let chunker = SemanticChunker::default();
        let text = "Hello world. This is a test. Another sentence here.";
        let sentences = chunker.split_sentences(text);
        assert_eq!(sentences.len(), 3);
    }

    #[test]
    fn test_count_tokens() {
        let chunker = SemanticChunker::default();
        let count = chunker.count_tokens("Hello world");
        assert!(count > 0);
        assert!(count < 10);
    }

    #[test]
    fn test_chunk_simple_text() {
        let chunker = SemanticChunker::with_config(SemanticChunkerConfig {
            target_tokens: 10,
            max_tokens: 20,
            chunk_overlap: 2,
            min_chunk_size: 1,
        })
        .unwrap();

        let doc_id = make_doc_id();
        let text = "First sentence. Second sentence. Third sentence. Fourth sentence.";

        let chunks = chunker.chunk(text, doc_id, None).unwrap();
        assert!(!chunks.is_empty());

        // Verify all chunks have correct document_id
        for chunk in &chunks {
            assert_eq!(chunk.document_id, doc_id);
            assert!(!chunk.content.is_empty());
        }
    }

    #[test]
    fn test_chunk_respects_max_tokens() {
        let chunker = SemanticChunker::with_config(SemanticChunkerConfig {
            target_tokens: 50,
            max_tokens: 100,
            chunk_overlap: 10,
            min_chunk_size: 10,
        })
        .unwrap();

        let doc_id = make_doc_id();
        // Create text with many sentences
        let text = (0..20)
            .map(|i| format!("This is sentence number {}.", i))
            .collect::<Vec<_>>()
            .join(" ");

        let chunks = chunker.chunk(&text, doc_id, None).unwrap();

        for chunk in &chunks {
            assert!(
                chunk.token_count <= 100,
                "Chunk exceeds max tokens: {} > 100",
                chunk.token_count
            );
        }
    }

    #[test]
    fn test_chunk_with_metadata() {
        let chunker = SemanticChunker::default();
        let doc_id = make_doc_id();
        let text = "Hello world. This is a test.";

        let mut metadata = HashMap::new();
        metadata.insert("source".to_string(), serde_json::json!("test"));

        let chunks = chunker.chunk(text, doc_id, Some(metadata)).unwrap();
        assert!(!chunks.is_empty());
        assert!(chunks[0].metadata.contains_key("source"));
    }

    #[test]
    fn test_get_overlap_sentences() {
        let chunker = SemanticChunker::with_config(SemanticChunkerConfig {
            target_tokens: 100,
            max_tokens: 200,
            chunk_overlap: 10,
            min_chunk_size: 10,
        })
        .unwrap();

        let sentences = vec!["First.", "Second.", "Third."];
        let overlap = chunker.get_overlap_sentences(&sentences, 10);

        // Should get some sentences back (depends on token count)
        assert!(!overlap.is_empty() || sentences.iter().all(|s| chunker.count_tokens(s) > 10));
    }

    #[test]
    fn test_chunk_handles_empty_text() {
        let chunker = SemanticChunker::default();
        let chunks = chunker.chunk("", make_doc_id(), None).unwrap();
        assert!(chunks.is_empty());
    }

    #[test]
    fn test_chunk_handles_whitespace() {
        let chunker = SemanticChunker::default();
        let chunks = chunker.chunk("   \n\n   ", make_doc_id(), None).unwrap();
        assert!(chunks.is_empty());
    }

    #[test]
    fn test_config_conversion() {
        let semantic_config = SemanticChunkerConfig {
            target_tokens: 200,
            max_tokens: 400,
            chunk_overlap: 30,
            min_chunk_size: 25,
        };

        let chunking_config: ChunkingConfig = semantic_config.clone().into();
        assert_eq!(chunking_config.target_tokens, 200);
        assert_eq!(chunking_config.max_tokens, 400);
        assert_eq!(chunking_config.chunk_overlap, 30);
        assert_eq!(chunking_config.min_chunk_size, 25);

        let back: SemanticChunkerConfig = chunking_config.into();
        assert_eq!(back.target_tokens, semantic_config.target_tokens);
        assert_eq!(back.max_tokens, semantic_config.max_tokens);
    }
}
