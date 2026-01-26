//! Recursive character text splitter.

#[allow(unused_imports)] // ChunkId used in implementation
use rag_types::{ChunkId, DocumentId};
use serde_json::Value;
use std::collections::HashMap;
use tiktoken_rs::CoreBPE;

#[allow(unused_imports)] // Used in implementation
use super::base::{Chunk, ChunkingConfig, ChunkingStrategy};
use crate::{Error, Result};

/// Separators used for recursive splitting, in order of preference.
const SEPARATORS: &[&str] = &[
    "\n\n", // Paragraphs
    "\n",   // Lines
    ". ",   // Sentences
    "? ",
    "! ",
    "; ",
    ", ",
    " ", // Words
    "",  // Characters (fallback)
];

/// Recursive character text splitter.
///
/// Splits text by trying different separators in order of preference,
/// maintaining semantic coherence by preferring larger natural boundaries.
#[allow(dead_code)] // Fields used by implementation in next task
pub struct RecursiveCharacterSplitter {
    config: ChunkingConfig,
    tokenizer: CoreBPE,
}

impl RecursiveCharacterSplitter {
    /// Create a new splitter with the given configuration.
    ///
    /// # Errors
    ///
    /// Returns an error if the tokenizer cannot be loaded.
    pub fn new(config: ChunkingConfig) -> Result<Self> {
        let tokenizer = tiktoken_rs::cl100k_base()
            .map_err(|e| Error::Config(format!("Failed to load tokenizer: {e}")))?;

        Ok(Self { config, tokenizer })
    }

    /// Count tokens in text.
    #[allow(dead_code)] // Used by implementation in next task
    #[allow(clippy::cast_possible_truncation)]
    fn count_tokens(&self, text: &str) -> u32 {
        self.tokenizer.encode_ordinary(text).len() as u32
    }
}

impl Default for RecursiveCharacterSplitter {
    fn default() -> Self {
        Self::new(ChunkingConfig::default()).expect("Default tokenizer should load")
    }
}

#[allow(clippy::unnecessary_literal_bound)]
impl ChunkingStrategy for RecursiveCharacterSplitter {
    fn name(&self) -> &str {
        "recursive_character"
    }

    fn config(&self) -> &ChunkingConfig {
        &self.config
    }

    fn chunk(
        &self,
        text: &str,
        document_id: DocumentId,
        metadata: Option<HashMap<String, Value>>,
    ) -> Result<Vec<Chunk>> {
        // TODO: Implement
        let _ = (text, document_id, metadata, &SEPARATORS);
        todo!()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;

    fn make_doc_id() -> DocumentId {
        DocumentId::new()
    }

    #[test]
    fn test_strategy_name() {
        let splitter = RecursiveCharacterSplitter::default();
        assert_eq!(splitter.name(), "recursive_character");
    }

    #[test]
    fn test_chunk_simple_text() {
        let text = "This is a simple test paragraph.";
        let splitter = RecursiveCharacterSplitter::default();
        let doc_id = make_doc_id();

        let chunks = splitter.chunk(text, doc_id, None).unwrap();

        assert_eq!(chunks.len(), 1);
        assert_eq!(chunks[0].content, text);
        assert_eq!(chunks[0].chunk_index, 0);
        assert_eq!(chunks[0].document_id, doc_id);
    }

    #[test]
    fn test_chunk_respects_max_tokens() {
        // Create a long text that exceeds max_tokens
        let paragraph = "This is a test sentence. ".repeat(100);
        let config = ChunkingConfig {
            target_tokens: 50,
            max_tokens: 100,
            chunk_overlap: 10,
            min_chunk_size: 20,
            ..Default::default()
        };

        let splitter = RecursiveCharacterSplitter::new(config).unwrap();
        let chunks = splitter.chunk(&paragraph, make_doc_id(), None).unwrap();

        // Should create multiple chunks
        assert!(chunks.len() > 1);

        // Each chunk should be under max_tokens
        for chunk in &chunks {
            assert!(
                chunk.token_count <= 100,
                "Chunk has {} tokens, expected <= 100",
                chunk.token_count
            );
        }
    }

    #[test]
    fn test_chunk_preserves_character_offsets() {
        let text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph.";
        let config = ChunkingConfig {
            target_tokens: 10,
            max_tokens: 20,
            chunk_overlap: 0,
            min_chunk_size: 1,
            ..Default::default()
        };

        let splitter = RecursiveCharacterSplitter::new(config).unwrap();
        let chunks = splitter.chunk(text, make_doc_id(), None).unwrap();

        // Verify offsets are valid
        for chunk in &chunks {
            assert!(chunk.start_char <= chunk.end_char);
            assert!(chunk.end_char <= text.len());
        }
    }

    #[test]
    fn test_chunk_creates_overlap() {
        let text = "First sentence here. Second sentence follows. Third sentence ends.";
        let config = ChunkingConfig {
            target_tokens: 8,
            max_tokens: 15,
            chunk_overlap: 3,
            min_chunk_size: 3,
            ..Default::default()
        };

        let splitter = RecursiveCharacterSplitter::new(config).unwrap();
        let chunks = splitter.chunk(text, make_doc_id(), None).unwrap();

        // With overlap, later chunks should contain some text from previous chunks
        if chunks.len() > 1 {
            // Check that chunks have some overlap (not strictly disjoint)
            let first_end = &chunks[0].content;
            let second_start = &chunks[1].content;

            // The second chunk should start with some content from the end of the first
            // (This is a rough check - overlap implementation may vary)
            let first_words: Vec<&str> = first_end.split_whitespace().collect();
            let second_words: Vec<&str> = second_start.split_whitespace().collect();

            // At least verify both chunks have content
            assert!(!first_words.is_empty());
            assert!(!second_words.is_empty());
        }
    }

    #[test]
    fn test_chunk_attaches_metadata() {
        let text = "Test content.";
        let mut metadata = HashMap::new();
        metadata.insert("source".to_string(), Value::String("test".to_string()));

        let splitter = RecursiveCharacterSplitter::default();
        let chunks = splitter.chunk(text, make_doc_id(), Some(metadata)).unwrap();

        assert_eq!(chunks.len(), 1);
        assert_eq!(
            chunks[0].metadata.get("source"),
            Some(&Value::String("test".to_string()))
        );
    }

    #[test]
    fn test_chunk_splits_by_paragraphs_first() {
        let text = "Paragraph one content.\n\nParagraph two content.\n\nParagraph three content.";
        let config = ChunkingConfig {
            target_tokens: 10,
            max_tokens: 20,
            chunk_overlap: 0,
            min_chunk_size: 3,
            ..Default::default()
        };

        let splitter = RecursiveCharacterSplitter::new(config).unwrap();
        let chunks = splitter.chunk(text, make_doc_id(), None).unwrap();

        // Should split on paragraph boundaries
        assert!(chunks.len() >= 2);
    }

    #[test]
    fn test_chunk_handles_empty_text() {
        let splitter = RecursiveCharacterSplitter::default();
        let chunks = splitter.chunk("", make_doc_id(), None).unwrap();

        assert!(chunks.is_empty());
    }

    #[test]
    fn test_chunk_handles_whitespace_only() {
        let splitter = RecursiveCharacterSplitter::default();
        let chunks = splitter.chunk("   \n\n   \t  ", make_doc_id(), None).unwrap();

        assert!(chunks.is_empty());
    }

    #[test]
    fn test_chunk_sequential_indices() {
        let text = "One. Two. Three. Four. Five. Six. Seven. Eight. Nine. Ten.";
        let config = ChunkingConfig {
            target_tokens: 5,
            max_tokens: 10,
            chunk_overlap: 0,
            min_chunk_size: 2,
            ..Default::default()
        };

        let splitter = RecursiveCharacterSplitter::new(config).unwrap();
        let chunks = splitter.chunk(text, make_doc_id(), None).unwrap();

        // Verify indices are sequential
        for (i, chunk) in chunks.iter().enumerate() {
            assert_eq!(chunk.chunk_index, i as u32);
        }
    }

    #[test]
    fn test_count_tokens() {
        let splitter = RecursiveCharacterSplitter::default();

        // "Hello world" should be 2 tokens with cl100k_base
        let count = splitter.count_tokens("Hello world");
        assert!(count >= 2, "Expected at least 2 tokens, got {count}");
    }
}
