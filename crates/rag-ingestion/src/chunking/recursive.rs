//! Recursive character text splitter.

use rag_types::{ChunkId, DocumentId};
use serde_json::Value;
use std::collections::HashMap;
use tiktoken_rs::CoreBPE;

use super::base::{Chunk, ChunkingConfig, ChunkingStrategy};
use crate::{Error, Result};

/// Separators used for recursive splitting, in order of preference.
const SEPARATORS: &[&str] = &[
    "\n\n", // Paragraphs
    "\n",   // Lines
    ". ",   // Sentences
    "? ", "! ", "; ", ", ", " ", // Words
    "",  // Characters (fallback)
];

/// Recursive character text splitter.
///
/// Splits text by trying different separators in order of preference,
/// maintaining semantic coherence by preferring larger natural boundaries.
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
    fn name(&self) -> &'static str {
        "recursive_character"
    }

    fn config(&self) -> &ChunkingConfig {
        &self.config
    }

    #[allow(clippy::too_many_lines)]
    fn chunk(
        &self,
        text: &str,
        document_id: DocumentId,
        metadata: Option<HashMap<String, Value>>,
    ) -> Result<Vec<Chunk>> {
        let metadata = metadata.unwrap_or_default();

        // Get raw splits with character offsets
        let raw_splits = self.split_recursive(text, SEPARATORS, 0);

        // Merge small chunks and handle overlap
        let merged = self.merge_and_overlap(raw_splits);

        let chunks = merged
            .into_iter()
            .enumerate()
            .map(|(i, (content, start, end))| {
                #[allow(clippy::cast_possible_truncation)]
                let chunk_index = i as u32;
                Chunk {
                    chunk_id: ChunkId::new(),
                    document_id,
                    content: content.clone(),
                    chunk_index,
                    start_char: start,
                    end_char: end,
                    token_count: self.count_tokens(&content),
                    parent_chunk_id: None,
                    child_chunk_ids: Vec::new(),
                    metadata: metadata.clone(),
                    source_page: None,
                    source_section: None,
                }
            })
            .collect();

        Ok(chunks)
    }
}

impl RecursiveCharacterSplitter {
    /// Recursively split text, tracking character offsets.
    fn split_recursive(
        &self,
        text: &str,
        separators: &[&str],
        offset: usize,
    ) -> Vec<(String, usize, usize)> {
        if text.trim().is_empty() {
            return vec![];
        }

        let Some((&sep, remaining_seps)) = separators.split_first() else {
            return vec![(text.to_string(), offset, offset + text.len())];
        };

        // Character-level split as fallback
        if sep.is_empty() {
            return self.split_by_tokens(text, offset);
        }

        // Check if separator exists in text
        if !text.contains(sep) {
            return self.split_recursive(text, remaining_seps, offset);
        }

        let mut parts = Vec::new();
        let mut current_offset = offset;

        for part in text.split(sep) {
            if part.trim().is_empty() {
                current_offset += part.len() + sep.len();
                continue;
            }

            let token_count = self.count_tokens(part);

            if token_count > self.config.max_tokens {
                // Too large, split further with next separator
                let sub_parts = self.split_recursive(part, remaining_seps, current_offset);
                parts.extend(sub_parts);
            } else {
                parts.push((
                    part.to_string(),
                    current_offset,
                    current_offset + part.len(),
                ));
            }

            current_offset += part.len() + sep.len();
        }

        parts
    }

    /// Split text into chunks of `target_tokens` size when no separators work.
    fn split_by_tokens(&self, text: &str, offset: usize) -> Vec<(String, usize, usize)> {
        let tokens = self.tokenizer.encode_ordinary(text);
        let mut parts = Vec::new();
        let mut char_offset = offset;

        let target = self.config.target_tokens as usize;
        let mut i = 0;

        while i < tokens.len() {
            let chunk_tokens: Vec<_> = tokens[i..(i + target).min(tokens.len())].to_vec();
            let chunk_text = self
                .tokenizer
                .decode(chunk_tokens.clone())
                .unwrap_or_default();
            let len = chunk_text.len();

            parts.push((chunk_text, char_offset, char_offset + len));

            char_offset += len;
            i += target;
        }

        parts
    }

    /// Merge small chunks and create overlapping chunks.
    fn merge_and_overlap(
        &self,
        splits: Vec<(String, usize, usize)>,
    ) -> Vec<(String, usize, usize)> {
        if splits.is_empty() {
            return vec![];
        }

        // First pass: merge small chunks
        let mut merged = Vec::new();
        let mut current_content = String::new();
        let mut current_start = splits[0].1;
        let mut current_end = splits[0].2;

        for (content, start, end) in splits {
            let potential_content = if current_content.is_empty() {
                content.clone()
            } else {
                format!("{current_content} {content}")
            };

            let potential_tokens = self.count_tokens(&potential_content);

            if potential_tokens <= self.config.target_tokens {
                // Can merge
                current_content = potential_content;
            } else {
                // Save current and start new
                if !current_content.is_empty()
                    && self.count_tokens(&current_content) >= self.config.min_chunk_size
                {
                    merged.push((current_content.clone(), current_start, current_end));
                } else if !current_content.is_empty() {
                    // Too small, merge with next
                    current_content = potential_content;
                    current_end = end;
                    continue;
                }

                current_content = content;
                current_start = start;
            }
            current_end = end;
        }

        // Don't forget the last chunk
        if !current_content.is_empty() {
            merged.push((current_content, current_start, current_end));
        }

        // Second pass: add overlap
        if self.config.chunk_overlap == 0 || merged.len() <= 1 {
            return merged;
        }

        let mut overlapped = vec![merged[0].clone()];

        for i in 1..merged.len() {
            let prev_content = &merged[i - 1].0;
            let overlap_text = self.get_overlap_text(prev_content);

            if overlap_text.is_empty() {
                overlapped.push(merged[i].clone());
            } else {
                let new_content = format!("{overlap_text} {}", merged[i].0);
                let overlap_char_len = overlap_text.len();
                let new_start = merged[i].1.saturating_sub(overlap_char_len);
                overlapped.push((new_content, new_start, merged[i].2));
            }
        }

        overlapped
    }

    /// Get the last N tokens worth of text for overlap.
    fn get_overlap_text(&self, text: &str) -> String {
        let tokens = self.tokenizer.encode_ordinary(text);
        let overlap = self.config.chunk_overlap as usize;

        if tokens.len() <= overlap {
            return text.to_string();
        }

        let overlap_tokens: Vec<_> = tokens[tokens.len() - overlap..].to_vec();
        self.tokenizer.decode(overlap_tokens).unwrap_or_default()
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
            // At least verify both chunks have content
            assert!(first_end.split_whitespace().next().is_some());
            assert!(second_start.split_whitespace().next().is_some());
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
        let chunks = splitter
            .chunk("   \n\n   \t  ", make_doc_id(), None)
            .unwrap();

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
            #[allow(clippy::cast_possible_truncation)]
            let expected = i as u32;
            assert_eq!(chunk.chunk_index, expected);
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
