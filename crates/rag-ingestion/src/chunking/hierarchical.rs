//! Hierarchical document-structure-aware chunker.
//!
//! This chunker identifies section headings first, then chunks each section
//! independently using the recursive character splitter. The resulting chunks
//! carry section metadata for retrieval-time context.

use rag_types::DocumentId;
use serde_json::Value;
use std::collections::HashMap;

use super::base::{Chunk, ChunkingConfig, ChunkingStrategy};
use super::recursive::RecursiveCharacterSplitter;
use crate::Result;

#[derive(Debug, Clone)]
struct Section {
    heading: Option<String>,
    start_char: usize,
    content: String,
}

/// Hierarchical chunker that preserves document section boundaries.
pub struct HierarchicalChunker {
    config: ChunkingConfig,
    recursive_splitter: RecursiveCharacterSplitter,
}

impl HierarchicalChunker {
    /// Create a hierarchical chunker with default config.
    ///
    /// # Errors
    ///
    /// Returns an error if the tokenizer cannot be loaded.
    pub fn new() -> Result<Self> {
        Self::with_config(ChunkingConfig::default())
    }

    /// Create a hierarchical chunker with custom config.
    ///
    /// # Errors
    ///
    /// Returns an error if the recursive splitter cannot be created.
    pub fn with_config(config: ChunkingConfig) -> Result<Self> {
        let recursive_splitter = RecursiveCharacterSplitter::new(config.clone())?;
        Ok(Self {
            config,
            recursive_splitter,
        })
    }

    fn push_section(
        text: &str,
        start: usize,
        end: usize,
        heading: Option<String>,
        sections: &mut Vec<Section>,
    ) {
        let Some((trimmed_start, trimmed_end)) = Self::trimmed_bounds(text, start, end) else {
            return;
        };

        let content = text[trimmed_start..trimmed_end].to_string();
        sections.push(Section {
            heading,
            start_char: trimmed_start,
            content,
        });
    }

    fn trimmed_bounds(text: &str, start: usize, end: usize) -> Option<(usize, usize)> {
        if start >= end || end > text.len() {
            return None;
        }

        let slice = &text[start..end];
        let leading = slice
            .char_indices()
            .find(|(_, c)| !c.is_whitespace())
            .map(|(i, _)| i)?;
        let trailing = slice
            .char_indices()
            .rev()
            .find(|(_, c)| !c.is_whitespace())
            .map(|(i, c)| i + c.len_utf8())?;

        Some((start + leading, start + trailing))
    }

    fn split_sections(text: &str) -> Vec<Section> {
        if text.trim().is_empty() {
            return vec![];
        }

        let mut sections = Vec::new();
        let mut cursor = 0usize;
        let mut section_start = 0usize;
        let mut current_heading: Option<String> = None;
        let mut found_heading = false;

        for line in text.split_inclusive('\n') {
            let line_start = cursor;
            cursor += line.len();

            let content = line.trim_end_matches('\n').trim_end_matches('\r').trim();
            if let Some(heading) = Self::extract_heading(content) {
                found_heading = true;
                Self::push_section(
                    text,
                    section_start,
                    line_start,
                    current_heading.clone(),
                    &mut sections,
                );
                current_heading = Some(heading);
                section_start = cursor;
            }
        }

        Self::push_section(
            text,
            section_start,
            text.len(),
            current_heading,
            &mut sections,
        );

        if found_heading {
            sections
        } else {
            let mut fallback = Vec::new();
            Self::push_section(text, 0, text.len(), None, &mut fallback);
            fallback
        }
    }

    fn extract_heading(line: &str) -> Option<String> {
        if line.is_empty() {
            return None;
        }

        // Markdown heading: # Heading
        if line.starts_with('#') {
            let heading = line.trim_start_matches('#').trim();
            if !heading.is_empty() {
                return Some(heading.to_string());
            }
        }

        // Numbered headings: 1.2 Title, 3 Title
        if Self::looks_like_numbered_heading(line) {
            return Some(line.trim_end_matches(':').to_string());
        }

        // ALL CAPS headings: EXECUTIVE SUMMARY
        if Self::looks_like_uppercase_heading(line) {
            return Some(line.to_string());
        }

        // Title heading ending in colon: Overview:
        if Self::looks_like_colon_heading(line) {
            return Some(line.trim_end_matches(':').to_string());
        }

        None
    }

    fn looks_like_numbered_heading(line: &str) -> bool {
        let words: Vec<&str> = line.split_whitespace().collect();
        if words.len() < 2 || words.len() > 12 {
            return false;
        }

        let token = words[0].trim_end_matches('.');
        let parts: Vec<&str> = token.split('.').collect();
        if parts.is_empty() {
            return false;
        }
        if parts
            .iter()
            .any(|part| part.is_empty() || !part.chars().all(|c| c.is_ascii_digit()))
        {
            return false;
        }

        !line.ends_with('.') && !line.ends_with('?') && !line.ends_with('!')
    }

    fn looks_like_uppercase_heading(line: &str) -> bool {
        if line.len() > 100 || line.ends_with('.') {
            return false;
        }
        let word_count = line.split_whitespace().count();
        if !(2..=12).contains(&word_count) {
            return false;
        }

        let letters: Vec<char> = line.chars().filter(|c| c.is_alphabetic()).collect();
        if letters.len() < 4 {
            return false;
        }

        letters.iter().all(|c| c.is_uppercase())
    }

    fn looks_like_colon_heading(line: &str) -> bool {
        if !line.ends_with(':') || line.contains("://") {
            return false;
        }

        let word_count = line.split_whitespace().count();
        (1..=10).contains(&word_count)
    }
}

impl Default for HierarchicalChunker {
    fn default() -> Self {
        Self::new().expect("Default tokenizer should load")
    }
}

impl ChunkingStrategy for HierarchicalChunker {
    fn name(&self) -> &'static str {
        "hierarchical_document_structure"
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
        let base_metadata = metadata.unwrap_or_default();
        let sections = Self::split_sections(text);

        let mut all_chunks = Vec::new();
        let mut next_index = 0u32;

        for section in sections {
            let mut section_metadata = base_metadata.clone();
            if let Some(heading) = &section.heading {
                section_metadata
                    .insert("source_section".to_string(), Value::String(heading.clone()));
            }

            let section_chunks = self.recursive_splitter.chunk(
                &section.content,
                document_id,
                Some(section_metadata.clone()),
            )?;

            for mut chunk in section_chunks {
                chunk.chunk_index = next_index;
                next_index += 1;

                chunk.start_char += section.start_char;
                chunk.end_char += section.start_char;
                chunk.metadata.clone_from(&section_metadata);
                chunk.source_section.clone_from(&section.heading);

                all_chunks.push(chunk);
            }
        }

        Ok(all_chunks)
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
    fn test_hierarchical_chunker_name() {
        let chunker = HierarchicalChunker::default();
        assert_eq!(chunker.name(), "hierarchical_document_structure");
    }

    #[test]
    fn test_hierarchical_detects_markdown_sections() {
        let chunker = HierarchicalChunker::with_config(ChunkingConfig {
            target_tokens: 30,
            max_tokens: 60,
            chunk_overlap: 5,
            min_chunk_size: 5,
            tokenizer: "cl100k_base".to_string(),
        })
        .unwrap();

        let text = r#"
# Introduction
This is the introduction section.

## Details
This is the details section with more text.
"#;

        let chunks = chunker.chunk(text, make_doc_id(), None).unwrap();
        assert!(chunks.len() >= 2);
        assert!(chunks
            .iter()
            .any(|c| c.source_section.as_deref() == Some("Introduction")));
        assert!(chunks
            .iter()
            .any(|c| c.source_section.as_deref() == Some("Details")));
    }

    #[test]
    fn test_hierarchical_no_heading_falls_back_to_single_flow() {
        let chunker = HierarchicalChunker::default();
        let text = "Plain body text with no explicit headings.";

        let chunks = chunker.chunk(text, make_doc_id(), None).unwrap();
        assert!(!chunks.is_empty());
        assert!(chunks.iter().all(|c| c.source_section.is_none()));
    }

    #[test]
    fn test_hierarchical_sets_section_metadata() {
        let chunker = HierarchicalChunker::default();
        let text = "Overview:\nThis section has content.";

        let chunks = chunker.chunk(text, make_doc_id(), None).unwrap();
        assert!(!chunks.is_empty());
        assert_eq!(
            chunks[0].metadata.get("source_section"),
            Some(&Value::String("Overview".to_string()))
        );
    }

    #[test]
    fn test_hierarchical_respects_max_tokens() {
        let chunker = HierarchicalChunker::with_config(ChunkingConfig {
            target_tokens: 50,
            max_tokens: 100,
            chunk_overlap: 10,
            min_chunk_size: 10,
            tokenizer: "cl100k_base".to_string(),
        })
        .unwrap();

        let text = format!(
            "# Section\n{}",
            "This is a sentence with enough words to make several chunks. ".repeat(80)
        );
        let chunks = chunker.chunk(&text, make_doc_id(), None).unwrap();

        assert!(!chunks.is_empty());
        for chunk in &chunks {
            assert!(
                chunk.token_count <= 100,
                "Chunk exceeds max tokens: {} > 100",
                chunk.token_count
            );
        }
    }

    #[test]
    fn test_split_sections_detects_numbered_heading() {
        let sections = HierarchicalChunker::split_sections("1.2 Scope\nDefinition text.");

        assert_eq!(sections.len(), 1);
        assert_eq!(sections[0].heading.as_deref(), Some("1.2 Scope"));
    }
}
