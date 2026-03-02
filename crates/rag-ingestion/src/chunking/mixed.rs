//! Mixed-content chunker — zone-based strategy for documents that combine
//! prose, tables, and code in a single file.
//!
//! ## Zone detection
//!
//! When a [`ParsedDocument`] is available its `blocks` field is used to
//! identify content zones:
//!
//! | Block type          | Zone strategy                                       |
//! |---------------------|-----------------------------------------------------|
//! | `ContentType::Table`| [`TabularChunker`] logic (header + row batches)     |
//! | `ContentType::Code` | [`RecursiveCharacterSplitter`], half `target_tokens`, no overlap |
//! | `ContentType::Text` | [`SemanticChunker`] if avg sentence ≥ 80 chars, else recursive |
//! | `ContentType::Image`| Skipped (no textual content)                        |
//!
//! When only raw text is available the chunker detects zones from the text
//! itself using fenced code blocks (` ``` ` … ` ``` `), Markdown tables
//! (`| … |`), and Q&A patterns.
//!
//! All zone-chunks are merged into one ordered list with a sequential
//! `chunk_index` and `zone_type` / `zone_index` metadata fields.

use std::collections::HashMap;

use rag_types::{ChunkId, DocumentId};
use serde_json::Value;

use super::base::{Chunk, ChunkingConfig, ChunkingStrategy};
use super::qa::QAChunker;
use super::recursive::RecursiveCharacterSplitter;
use super::semantic::{SemanticChunker, SemanticChunkerConfig};
use super::tabular::TabularChunker;
use crate::parsers::{ContentType, ParsedDocument, TableContent};
use crate::{Error, Result};

// ---------------------------------------------------------------------------
// Zone types
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum ZoneKind {
    Prose,
    Code,
    Table,
    QA,
}

impl ZoneKind {
    fn as_str(self) -> &'static str {
        match self {
            Self::Prose => "prose",
            Self::Code => "code",
            Self::Table => "table",
            Self::QA => "qa",
        }
    }
}

struct Zone {
    kind: ZoneKind,
    text: String,
    /// Pre-parsed table (populated when zone comes from ParsedDocument.tables).
    table: Option<TableContent>,
}

// ---------------------------------------------------------------------------
// MixedContentChunker
// ---------------------------------------------------------------------------

/// Chunks mixed-content documents by applying different sub-strategies to
/// each content zone.
pub struct MixedContentChunker {
    config: ChunkingConfig,
}

impl MixedContentChunker {
    /// Create a new `MixedContentChunker`.
    pub fn new(config: ChunkingConfig) -> Self {
        Self { config }
    }

    // ------------------------------------------------------------------
    // Public: document-aware path
    // ------------------------------------------------------------------

    /// Chunk a document using its structured block list for zone detection.
    ///
    /// This is the preferred path when the caller has a [`ParsedDocument`]
    /// with populated `blocks`.  Falls back to [`Self::chunk`] (text-only
    /// analysis) when `blocks` is empty.
    ///
    /// # Errors
    ///
    /// Returns an error if any sub-chunker fails to initialise.
    pub fn chunk_with_doc(
        &self,
        text: &str,
        document_id: DocumentId,
        parsed_doc: &ParsedDocument,
        metadata: Option<HashMap<String, Value>>,
    ) -> Result<Vec<Chunk>> {
        if parsed_doc.blocks.is_empty() {
            return self.chunk(text, document_id, metadata);
        }

        let base_metadata = metadata.unwrap_or_default();

        // Build zones from blocks.
        let zones = Self::zones_from_blocks(parsed_doc);

        self.chunks_from_zones(zones, document_id, &base_metadata)
    }

    // ------------------------------------------------------------------
    // Internal: block-based zone building
    // ------------------------------------------------------------------

    fn zones_from_blocks(doc: &ParsedDocument) -> Vec<Zone> {
        let mut zones: Vec<Zone> = Vec::new();

        let mut table_iter = doc.tables.iter();

        for block in &doc.blocks {
            let kind = match block.content_type {
                ContentType::Table => ZoneKind::Table,
                ContentType::Code => ZoneKind::Code,
                ContentType::Image => continue, // skip images
                ContentType::Text => {
                    // Check for Q&A patterns within text blocks.
                    let qa_count = QAChunker::detect_pairs(&block.content).len();
                    if qa_count >= 2 {
                        ZoneKind::QA
                    } else {
                        ZoneKind::Prose
                    }
                }
            };

            // For table zones pull pre-parsed TableContent if available.
            let table = if kind == ZoneKind::Table {
                table_iter.next().cloned()
            } else {
                None
            };

            // Merge consecutive same-kind zones to reduce overhead.
            if let Some(last) = zones.last_mut() {
                if last.kind == kind && kind != ZoneKind::Table {
                    last.text.push('\n');
                    last.text.push_str(&block.content);
                    continue;
                }
            }

            zones.push(Zone {
                kind,
                text: block.content.clone(),
                table,
            });
        }

        zones
    }

    // ------------------------------------------------------------------
    // Internal: text-based zone building (fallback)
    // ------------------------------------------------------------------

    fn zones_from_text(text: &str) -> Vec<Zone> {
        let mut zones: Vec<Zone> = Vec::new();

        let mut current_kind: Option<ZoneKind> = None;
        let mut current_lines: Vec<&str> = Vec::new();
        let mut in_code_fence = false;

        let flush = |kind: ZoneKind, lines: &[&str]| -> Zone {
            Zone {
                kind,
                text: lines.join("\n"),
                table: None,
            }
        };

        for line in text.lines() {
            let trimmed = line.trim();

            // Code fence toggle.
            if trimmed.starts_with("```") {
                if in_code_fence {
                    // End of code block.
                    current_lines.push(line);
                    if current_kind.is_some() {
                        let z = flush(current_kind.unwrap(), &current_lines);
                        zones.push(z);
                        current_lines.clear();
                        current_kind = None;
                    }
                    in_code_fence = false;
                    continue;
                }
                // Start of code block — flush prose first.
                if !current_lines.is_empty() {
                    if let Some(k) = current_kind {
                        let z = flush(k, &current_lines);
                        zones.push(z);
                        current_lines.clear();
                    }
                }
                in_code_fence = true;
                current_kind = Some(ZoneKind::Code);
                current_lines.push(line);
                continue;
            }

            if in_code_fence {
                current_lines.push(line);
                continue;
            }

            // Markdown table row.
            let is_table_row =
                trimmed.starts_with('|') && trimmed.ends_with('|') && trimmed.len() > 3;

            let new_kind = if is_table_row {
                ZoneKind::Table
            } else {
                ZoneKind::Prose
            };

            // Zone transition.
            if Some(new_kind) != current_kind {
                if !current_lines.is_empty() {
                    if let Some(k) = current_kind {
                        let z = flush(k, &current_lines);
                        zones.push(z);
                        current_lines.clear();
                    }
                }
                current_kind = Some(new_kind);
            }

            current_lines.push(line);
        }

        // Flush remainder.
        if !current_lines.is_empty() {
            if let Some(k) = current_kind {
                let z = flush(k, &current_lines);
                zones.push(z);
            }
        }

        // Post-process: upgrade Prose zones that look like Q&A.
        zones
            .into_iter()
            .map(|mut z| {
                if z.kind == ZoneKind::Prose && QAChunker::detect_pairs(&z.text).len() >= 2 {
                    z.kind = ZoneKind::QA;
                }
                z
            })
            .collect()
    }

    // ------------------------------------------------------------------
    // Internal: chunking each zone
    // ------------------------------------------------------------------

    fn chunks_from_zones(
        &self,
        zones: Vec<Zone>,
        document_id: DocumentId,
        base_metadata: &HashMap<String, Value>,
    ) -> Result<Vec<Chunk>> {
        let mut all_chunks: Vec<Chunk> = Vec::new();

        for (zone_idx, zone) in zones.into_iter().enumerate() {
            let zone_chunks = self.chunk_zone(&zone, zone_idx, document_id, base_metadata)?;
            all_chunks.extend(zone_chunks);
        }

        // Re-number chunk_index sequentially across all zones.
        for (i, chunk) in all_chunks.iter_mut().enumerate() {
            #[allow(clippy::cast_possible_truncation)]
            {
                chunk.chunk_index = i as u32;
            }
        }

        Ok(all_chunks)
    }

    fn chunk_zone(
        &self,
        zone: &Zone,
        zone_idx: usize,
        document_id: DocumentId,
        base_metadata: &HashMap<String, Value>,
    ) -> Result<Vec<Chunk>> {
        let mut zone_meta = base_metadata.clone();
        zone_meta.insert("zone_type".into(), serde_json::json!(zone.kind.as_str()));
        zone_meta.insert("zone_index".into(), serde_json::json!(zone_idx));

        let mut chunks = match zone.kind {
            ZoneKind::Table => self.chunk_table_zone(zone, document_id, zone_meta)?,
            ZoneKind::Code => self.chunk_code_zone(&zone.text, document_id, zone_meta)?,
            ZoneKind::QA => self.chunk_qa_zone(&zone.text, document_id, zone_meta)?,
            ZoneKind::Prose => self.chunk_prose_zone(&zone.text, document_id, zone_meta)?,
        };

        // zone_index is already in metadata; chunk_index will be re-assigned later.
        for chunk in &mut chunks {
            chunk.chunk_id = ChunkId::new(); // ensure unique IDs
        }

        Ok(chunks)
    }

    fn chunk_table_zone(
        &self,
        zone: &Zone,
        document_id: DocumentId,
        meta: HashMap<String, Value>,
    ) -> Result<Vec<Chunk>> {
        let chunker = TabularChunker::new(self.config.clone())?;
        if let Some(ref table) = zone.table {
            chunker.chunk_tables(std::slice::from_ref(table), document_id, &meta)
        } else {
            // Fall back to text-based detection.
            chunker.chunk(&zone.text, document_id, Some(meta))
        }
    }

    fn chunk_code_zone(
        &self,
        text: &str,
        document_id: DocumentId,
        meta: HashMap<String, Value>,
    ) -> Result<Vec<Chunk>> {
        // Smaller targets for code; no overlap (code shouldn't bleed across
        // function/class boundaries).
        let code_config = ChunkingConfig {
            target_tokens: self.config.target_tokens / 2,
            max_tokens: self.config.max_tokens,
            chunk_overlap: 0,
            min_chunk_size: self.config.min_chunk_size,
            tokenizer: self.config.tokenizer.clone(),
        };
        let splitter = RecursiveCharacterSplitter::new(code_config)
            .map_err(|e| Error::Config(format!("Code zone splitter failed: {e}")))?;
        splitter.chunk(text, document_id, Some(meta))
    }

    fn chunk_qa_zone(
        &self,
        text: &str,
        document_id: DocumentId,
        meta: HashMap<String, Value>,
    ) -> Result<Vec<Chunk>> {
        let chunker = QAChunker::new(self.config.clone());
        chunker.chunk(text, document_id, Some(meta))
    }

    fn chunk_prose_zone(
        &self,
        text: &str,
        document_id: DocumentId,
        meta: HashMap<String, Value>,
    ) -> Result<Vec<Chunk>> {
        // Use semantic if sentences are long, otherwise recursive.
        let avg_sentence_len = estimate_avg_sentence_len(text);

        if avg_sentence_len >= 80.0 {
            let semantic_config = SemanticChunkerConfig::from(self.config.clone());
            let chunker = SemanticChunker::with_config(semantic_config)
                .map_err(|e| Error::Config(format!("Prose zone (semantic) failed: {e}")))?;
            chunker.chunk(text, document_id, Some(meta))
        } else {
            let splitter = RecursiveCharacterSplitter::new(self.config.clone())
                .map_err(|e| Error::Config(format!("Prose zone (recursive) failed: {e}")))?;
            splitter.chunk(text, document_id, Some(meta))
        }
    }
}

// ---------------------------------------------------------------------------
// ChunkingStrategy trait impl
// ---------------------------------------------------------------------------

impl ChunkingStrategy for MixedContentChunker {
    fn name(&self) -> &'static str {
        "mixed_content"
    }

    fn config(&self) -> &ChunkingConfig {
        &self.config
    }

    /// Chunk mixed-content text using text-based zone detection.
    ///
    /// For better results when a [`ParsedDocument`] is available use
    /// [`MixedContentChunker::chunk_with_doc`] instead.
    fn chunk(
        &self,
        text: &str,
        document_id: DocumentId,
        metadata: Option<HashMap<String, Value>>,
    ) -> Result<Vec<Chunk>> {
        let base_metadata = metadata.unwrap_or_default();
        let zones = Self::zones_from_text(text);
        self.chunks_from_zones(zones, document_id, &base_metadata)
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

fn estimate_avg_sentence_len(text: &str) -> f64 {
    let mut count = 0_usize;
    let mut total = 0_usize;
    for sentence in text.split_inclusive(&['.', '?', '!']) {
        let t = sentence.trim();
        if t.len() > 3 {
            count += 1;
            total += t.len();
        }
    }
    if count == 0 {
        return 0.0;
    }
    total as f64 / count as f64
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn default_config() -> ChunkingConfig {
        ChunkingConfig {
            target_tokens: 100,
            max_tokens: 200,
            chunk_overlap: 10,
            min_chunk_size: 10,
            tokenizer: "cl100k_base".to_string(),
        }
    }

    fn make_doc_id() -> DocumentId {
        DocumentId::new()
    }

    #[test]
    fn test_zones_from_text_identifies_code_zone() {
        let _chunker = MixedContentChunker::new(default_config());
        let text = "Some prose paragraph here.\n\
                    ```rust\nfn main() { println!(\"hello\"); }\n```\n\
                    More prose after the code.";

        let zones = MixedContentChunker::zones_from_text(text);
        let kinds: Vec<ZoneKind> = zones.iter().map(|z| z.kind).collect();
        assert!(kinds.contains(&ZoneKind::Code));
        assert!(kinds.contains(&ZoneKind::Prose));
    }

    #[test]
    fn test_zones_from_text_identifies_table_zone() {
        let _chunker = MixedContentChunker::new(default_config());
        let text = "Intro text.\n\
                    | Name | Value |\n\
                    | --- | --- |\n\
                    | A | 1 |\n\
                    Trailing text.";

        let zones = MixedContentChunker::zones_from_text(text);
        let kinds: Vec<ZoneKind> = zones.iter().map(|z| z.kind).collect();
        assert!(kinds.contains(&ZoneKind::Table));
        assert!(kinds.contains(&ZoneKind::Prose));
    }

    #[test]
    fn test_chunk_mixed_content_produces_zone_metadata() {
        let chunker = MixedContentChunker::new(default_config());
        let text = "Intro paragraph about the topic.\n\
                    ```python\nprint('hello')\n```\n\
                    Summary of results.";

        let chunks = chunker.chunk(text, make_doc_id(), None).unwrap();
        assert!(!chunks.is_empty());

        let has_zone_type = chunks.iter().all(|c| c.metadata.contains_key("zone_type"));
        assert!(has_zone_type, "all chunks should have zone_type metadata");

        let has_code_zone = chunks
            .iter()
            .any(|c| c.metadata["zone_type"] == serde_json::json!("code"));
        assert!(has_code_zone, "should have at least one code zone chunk");
    }

    #[test]
    fn test_chunk_indices_are_sequential() {
        let chunker = MixedContentChunker::new(default_config());
        let text = "First prose section.\n\
                    ```\nsome code\n```\n\
                    Second prose section.";

        let chunks = chunker.chunk(text, make_doc_id(), None).unwrap();
        for (expected, chunk) in chunks.iter().enumerate() {
            let expected_index = expected as u32;
            assert_eq!(chunk.chunk_index, expected_index);
        }
    }

    #[test]
    fn test_chunk_with_doc_uses_blocks() {
        use crate::parsers::ContentBlock;

        let chunker = MixedContentChunker::new(default_config());
        let doc = ParsedDocument {
            text: "Prose content.\n```code\nfn foo() {}\n```".into(),
            blocks: vec![
                ContentBlock {
                    content_type: ContentType::Text,
                    content: "Prose content.".into(),
                    page_number: None,
                    position: Some(0),
                    metadata: HashMap::new(),
                },
                ContentBlock {
                    content_type: ContentType::Code,
                    content: "fn foo() {}".into(),
                    page_number: None,
                    position: Some(1),
                    metadata: HashMap::new(),
                },
            ],
            ..Default::default()
        };

        let chunks = chunker
            .chunk_with_doc(&doc.text, make_doc_id(), &doc, None)
            .unwrap();

        assert!(!chunks.is_empty());
        let has_code = chunks
            .iter()
            .any(|c| c.metadata.get("zone_type") == Some(&serde_json::json!("code")));
        assert!(has_code);
    }

    #[test]
    fn test_chunk_with_doc_falls_back_to_text_when_blocks_empty() {
        let chunker = MixedContentChunker::new(default_config());
        let doc = ParsedDocument {
            text: "Just some plain text without blocks.".into(),
            ..Default::default()
        };

        // Should not error.
        let chunks = chunker
            .chunk_with_doc(&doc.text, make_doc_id(), &doc, None)
            .unwrap();
        assert!(!chunks.is_empty());
    }

    #[test]
    fn test_estimate_avg_sentence_len() {
        let short = "Hi. Ok. Yes.";
        assert!(estimate_avg_sentence_len(short) < 80.0);

        let long =
            "This is a considerably longer sentence that provides a lot of detailed context and background information.";
        assert!(estimate_avg_sentence_len(long) >= 80.0);
    }
}
