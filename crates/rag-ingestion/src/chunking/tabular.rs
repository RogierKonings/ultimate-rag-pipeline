//! Tabular chunker for structured data documents.
//!
//! Handles three table formats:
//!
//! 1. **Structured tables** from `ParsedDocument.tables` (HTML parser output,
//!    Markdown parser output).  Use [`TabularChunker::chunk_tables`].
//! 2. **Markdown tables** detected inline in raw text (`| col | col |` lines).
//!    Handled automatically by the [`ChunkingStrategy::chunk`] trait method.
//! 3. **CSV text** where every line has a consistent comma-separated column
//!    count.  Handled automatically by the [`ChunkingStrategy::chunk`] trait
//!    method.
//!
//! Every chunk repeats the header row so it is independently searchable
//! without neighbouring chunks for context.

use std::collections::HashMap;

use rag_types::{ChunkId, DocumentId};
use serde_json::Value;
use tiktoken_rs::CoreBPE;

use super::base::{Chunk, ChunkingConfig, ChunkingStrategy};
use super::recursive::RecursiveCharacterSplitter;
use crate::parsers::TableContent;
use crate::{Error, Result};

// ---------------------------------------------------------------------------
// TabularChunker
// ---------------------------------------------------------------------------

/// Chunks tabular documents so that every chunk contains the column headers
/// followed by a batch of data rows.
pub struct TabularChunker {
    config: ChunkingConfig,
    tokenizer: CoreBPE,
}

impl TabularChunker {
    /// Create a new `TabularChunker` from a shared [`ChunkingConfig`].
    ///
    /// # Errors
    ///
    /// Returns an error if the tokenizer cannot be loaded.
    pub fn new(config: ChunkingConfig) -> Result<Self> {
        let tokenizer = tiktoken_rs::cl100k_base()
            .map_err(|e| Error::Config(format!("Failed to load tokenizer: {e}")))?;
        Ok(Self { config, tokenizer })
    }

    // ------------------------------------------------------------------
    // Public: structured table path
    // ------------------------------------------------------------------

    /// Chunk pre-parsed tables from `ParsedDocument.tables`.
    ///
    /// This is the primary path when the document parser has already produced
    /// structured [`TableContent`] objects (e.g. from HTML or Markdown).
    ///
    /// Each output chunk contains the Markdown-formatted header row, a
    /// separator row, and a batch of data rows sized to `target_tokens`.
    ///
    /// # Errors
    ///
    /// Returns an error if tokenization fails.
    pub fn chunk_tables(
        &self,
        tables: &[TableContent],
        document_id: DocumentId,
        base_metadata: &HashMap<String, Value>,
    ) -> Result<Vec<Chunk>> {
        let mut chunks = Vec::new();
        let mut global_index = 0u32;

        for (table_idx, table) in tables.iter().enumerate() {
            self.chunk_single_table(
                table,
                table_idx,
                document_id,
                base_metadata,
                &mut chunks,
                &mut global_index,
            );
        }

        Ok(chunks)
    }

    // ------------------------------------------------------------------
    // Internal helpers
    // ------------------------------------------------------------------

    fn count_tokens(&self, text: &str) -> u32 {
        #[allow(clippy::cast_possible_truncation)]
        {
            self.tokenizer.encode_ordinary(text).len() as u32
        }
    }

    /// Format a slice of cell values as a Markdown table row (`| a | b |`).
    fn format_md_row(cells: &[String]) -> String {
        format!("| {} |", cells.join(" | "))
    }

    /// Build a Markdown separator row (`| --- | --- |`).
    fn format_md_separator(ncols: usize) -> String {
        let dashes = vec!["---".to_string(); ncols];
        format!("| {} |", dashes.join(" | "))
    }

    /// Chunk a single [`TableContent`] into one or more [`Chunk`]s.
    fn chunk_single_table(
        &self,
        table: &TableContent,
        table_idx: usize,
        document_id: DocumentId,
        base_metadata: &HashMap<String, Value>,
        chunks: &mut Vec<Chunk>,
        global_index: &mut u32,
    ) {
        let header_line = Self::format_md_row(&table.headers);
        let separator = Self::format_md_separator(table.headers.len());
        let header_block = format!("{header_line}\n{separator}");
        let header_tokens = self.count_tokens(&header_block);

        let mut batch_rows: Vec<String> = Vec::new();
        let mut batch_tokens = header_tokens;
        let mut batch_start_row = 0usize;

        for (row_idx, row) in table.rows.iter().enumerate() {
            let row_line = Self::format_md_row(row);
            let row_tokens = self.count_tokens(&row_line);

            if batch_tokens + row_tokens > self.config.target_tokens && !batch_rows.is_empty() {
                // Flush current batch before it overflows.
                Self::push_table_chunk(
                    &self.config,
                    &header_block,
                    &batch_rows,
                    table_idx,
                    batch_start_row,
                    row_idx.saturating_sub(1),
                    &table.headers,
                    table.caption.as_deref(),
                    document_id,
                    base_metadata,
                    chunks,
                    global_index,
                );
                batch_rows.clear();
                batch_tokens = header_tokens;
                batch_start_row = row_idx;
            }

            batch_rows.push(row_line);
            batch_tokens += row_tokens;
        }

        // Flush any remaining rows.
        if !batch_rows.is_empty() {
            let end_row = table.rows.len().saturating_sub(1);
            Self::push_table_chunk(
                &self.config,
                &header_block,
                &batch_rows,
                table_idx,
                batch_start_row,
                end_row,
                &table.headers,
                table.caption.as_deref(),
                document_id,
                base_metadata,
                chunks,
                global_index,
            );
        }
    }

    /// Construct a [`Chunk`] from a batch of table rows and append it.
    #[allow(clippy::too_many_arguments)]
    fn push_table_chunk(
        config: &ChunkingConfig,
        header_block: &str,
        rows: &[String],
        table_idx: usize,
        row_start: usize,
        row_end: usize,
        headers: &[String],
        caption: Option<&str>,
        document_id: DocumentId,
        base_metadata: &HashMap<String, Value>,
        chunks: &mut Vec<Chunk>,
        global_index: &mut u32,
    ) {
        let content = std::iter::once(header_block)
            .chain(rows.iter().map(String::as_str))
            .collect::<Vec<_>>()
            .join("\n");

        let mut metadata = base_metadata.clone();
        metadata.insert("table_index".into(), serde_json::json!(table_idx));
        metadata.insert("row_start".into(), serde_json::json!(row_start));
        metadata.insert("row_end".into(), serde_json::json!(row_end));
        metadata.insert(
            "column_names".into(),
            serde_json::to_value(headers).unwrap_or_default(),
        );
        if let Some(cap) = caption {
            metadata.insert("table_caption".into(), serde_json::json!(cap));
        }

        // Count tokens inline (config carries tokenizer name but TabularChunker
        // uses its own CoreBPE; approximate via byte length as fallback).
        let token_count = {
            // Simple heuristic: ~4 bytes per token for mixed content.
            #[allow(clippy::cast_possible_truncation)]
            let approx = (content.len() / 4).max(1) as u32;
            // Respect the configured maximum.
            approx.min(config.max_tokens)
        };

        chunks.push(Chunk {
            chunk_id: ChunkId::new(),
            document_id,
            content: content.clone(),
            chunk_index: *global_index,
            // Tabular chunks don't carry char offsets into the original text.
            start_char: 0,
            end_char: content.len(),
            token_count,
            parent_chunk_id: None,
            child_chunk_ids: Vec::new(),
            metadata,
            source_page: None,
            source_section: None,
        });

        *global_index += 1;
    }

    // ------------------------------------------------------------------
    // Text-based table detection
    // ------------------------------------------------------------------

    /// Attempt to parse a Markdown table from raw text.
    ///
    /// Looks for a sequence of `| ... |` lines where the second line is a
    /// separator (`| --- |`).  Returns `None` if no table is found.
    fn detect_markdown_table(text: &str) -> Option<TableContent> {
        let mut table_lines: Vec<&str> = Vec::new();
        let mut found_table = false;

        for line in text.lines() {
            let trimmed = line.trim();
            if trimmed.starts_with('|') && trimmed.ends_with('|') && trimmed.len() > 3 {
                table_lines.push(trimmed);
                found_table = true;
            } else if found_table {
                // Stop at the first non-table line after the table started.
                break;
            }
        }

        // Need at least: header row + separator row + one data row.
        if table_lines.len() < 3 {
            return None;
        }

        // Validate the separator row (contains only `|`, `-`, `:`, ` `).
        let sep = table_lines[1];
        if !sep.chars().all(|c| matches!(c, '|' | '-' | ':' | ' ')) {
            return None;
        }

        let headers = Self::parse_md_row(table_lines[0]);
        if headers.is_empty() {
            return None;
        }

        let rows: Vec<Vec<String>> = table_lines[2..]
            .iter()
            .map(|l| Self::parse_md_row(l))
            .filter(|row| row.len() == headers.len())
            .collect();

        if rows.is_empty() {
            return None;
        }

        Some(TableContent {
            headers,
            rows,
            caption: None,
        })
    }

    /// Parse cells from a `| cell | cell |` Markdown row.
    fn parse_md_row(line: &str) -> Vec<String> {
        let inner = line.trim().trim_start_matches('|').trim_end_matches('|');
        inner
            .split('|')
            .map(|cell| cell.trim().to_string())
            .filter(|c| !c.is_empty())
            .collect()
    }

    /// Attempt to parse CSV-formatted text into a [`TableContent`].
    ///
    /// A "CSV" here means: every non-empty line has the same number of
    /// comma-separated fields and there are at least two columns and two rows.
    fn detect_csv(text: &str) -> Option<TableContent> {
        let lines: Vec<&str> = text
            .lines()
            .map(str::trim)
            .filter(|l| !l.is_empty())
            .collect();

        if lines.len() < 2 {
            return None;
        }

        let parse_csv_row = |line: &str| -> Vec<String> {
            // Minimal CSV parsing: handle double-quoted fields.
            let mut cells = Vec::new();
            let mut current = String::new();
            let mut in_quotes = false;

            for ch in line.chars() {
                match ch {
                    '"' => in_quotes = !in_quotes,
                    ',' if !in_quotes => {
                        cells.push(current.trim().to_string());
                        current.clear();
                    }
                    other => current.push(other),
                }
            }
            cells.push(current.trim().to_string());
            cells
        };

        let first_row = parse_csv_row(lines[0]);
        let ncols = first_row.len();

        // Require at least 2 columns to be a table.
        if ncols < 2 {
            return None;
        }

        let mut rows: Vec<Vec<String>> = Vec::new();
        for line in &lines[1..] {
            let row = parse_csv_row(line);
            if row.len() != ncols {
                // Inconsistent column count → not a valid CSV table.
                return None;
            }
            rows.push(row);
        }

        Some(TableContent {
            headers: first_row,
            rows,
            caption: None,
        })
    }
}

// ---------------------------------------------------------------------------
// ChunkingStrategy trait impl
// ---------------------------------------------------------------------------

impl ChunkingStrategy for TabularChunker {
    fn name(&self) -> &'static str {
        "tabular"
    }

    fn config(&self) -> &ChunkingConfig {
        &self.config
    }

    /// Chunk raw text that is (or contains) a table.
    ///
    /// Detection order:
    /// 1. Markdown table (`| col |` lines with separator row)
    /// 2. CSV (consistent comma-separated columns)
    /// 3. Fallback to [`RecursiveCharacterSplitter`]
    fn chunk(
        &self,
        text: &str,
        document_id: DocumentId,
        metadata: Option<HashMap<String, Value>>,
    ) -> Result<Vec<Chunk>> {
        let base_metadata = metadata.unwrap_or_default();

        // Try Markdown table first.
        if let Some(table) = Self::detect_markdown_table(text) {
            return self.chunk_tables(&[table], document_id, &base_metadata);
        }

        // Try CSV.
        if let Some(table) = Self::detect_csv(text) {
            return self.chunk_tables(&[table], document_id, &base_metadata);
        }

        // Fallback: treat as unstructured text.
        let splitter = RecursiveCharacterSplitter::new(self.config.clone())?;
        splitter.chunk(text, document_id, Some(base_metadata))
    }
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
    fn test_chunk_tables_with_single_table() {
        let chunker = TabularChunker::new(default_config()).unwrap();
        let table = TableContent {
            headers: vec!["Name".into(), "Price".into(), "SKU".into()],
            rows: vec![
                vec!["Widget A".into(), "9.99".into(), "WA01".into()],
                vec!["Widget B".into(), "14.99".into(), "WB01".into()],
                vec!["Widget C".into(), "4.99".into(), "WC01".into()],
            ],
            caption: None,
        };

        let chunks = chunker
            .chunk_tables(&[table], make_doc_id(), &HashMap::new())
            .unwrap();

        // All rows fit in one chunk given our generous token budget.
        assert!(!chunks.is_empty());
        // Every chunk must contain the header.
        for chunk in &chunks {
            assert!(chunk.content.contains("Name"), "chunk missing header");
            assert_eq!(chunk.metadata["table_index"], serde_json::json!(0));
        }
    }

    #[test]
    fn test_chunk_tables_splits_large_table() {
        // Tiny token budget forces row-by-row splitting.
        let config = ChunkingConfig {
            target_tokens: 10,
            max_tokens: 20,
            chunk_overlap: 0,
            min_chunk_size: 1,
            tokenizer: "cl100k_base".to_string(),
        };
        let chunker = TabularChunker::new(config).unwrap();

        let rows: Vec<Vec<String>> = (0..20)
            .map(|i| vec![format!("item-{i}"), format!("{}", i * 10)])
            .collect();
        let table = TableContent {
            headers: vec!["Item".into(), "Value".into()],
            rows,
            caption: None,
        };

        let chunks = chunker
            .chunk_tables(&[table], make_doc_id(), &HashMap::new())
            .unwrap();

        // Must produce multiple chunks.
        assert!(
            chunks.len() > 1,
            "expected multiple chunks, got {}",
            chunks.len()
        );
        // Every chunk must carry the header.
        for chunk in &chunks {
            assert!(
                chunk.content.contains("Item | Value"),
                "chunk missing header"
            );
        }
    }

    #[test]
    fn test_chunk_tables_with_caption() {
        let chunker = TabularChunker::new(default_config()).unwrap();
        let table = TableContent {
            headers: vec!["A".into(), "B".into()],
            rows: vec![vec!["1".into(), "2".into()]],
            caption: Some("Test table".to_string()),
        };

        let chunks = chunker
            .chunk_tables(&[table], make_doc_id(), &HashMap::new())
            .unwrap();

        assert!(!chunks.is_empty());
        assert_eq!(
            chunks[0].metadata["table_caption"],
            serde_json::json!("Test table")
        );
    }

    #[test]
    fn test_detect_markdown_table() {
        let text = "Some intro text.\n\
                    | Name | Price |\n\
                    | --- | --- |\n\
                    | Item A | 10.00 |\n\
                    | Item B | 20.00 |\n\
                    Some trailing text.";

        let table = TabularChunker::detect_markdown_table(text).unwrap();
        assert_eq!(table.headers, vec!["Name".to_string(), "Price".to_string()]);
        assert_eq!(table.rows.len(), 2);
    }

    #[test]
    fn test_detect_markdown_table_returns_none_for_prose() {
        let text = "Just some regular prose without any table structure.";
        assert!(TabularChunker::detect_markdown_table(text).is_none());
    }

    #[test]
    fn test_detect_csv_simple() {
        let csv = "Name,Price,SKU\nWidget A,9.99,WA01\nWidget B,14.99,WB01";
        let table = TabularChunker::detect_csv(csv).unwrap();
        assert_eq!(table.headers, vec!["Name", "Price", "SKU"]);
        assert_eq!(table.rows.len(), 2);
    }

    #[test]
    fn test_detect_csv_with_quoted_fields() {
        let csv = "Name,Description\n\"Widget A\",\"Great, value\"\nWidget B,Simple";
        let table = TabularChunker::detect_csv(csv).unwrap();
        assert_eq!(table.headers.len(), 2);
        assert_eq!(table.rows.len(), 2);
    }

    #[test]
    fn test_detect_csv_single_column_returns_none() {
        let text = "one\ntwo\nthree";
        assert!(TabularChunker::detect_csv(text).is_none());
    }

    #[test]
    fn test_detect_csv_inconsistent_columns_returns_none() {
        let text = "a,b,c\n1,2\n3,4,5";
        assert!(TabularChunker::detect_csv(text).is_none());
    }

    #[test]
    fn test_chunk_markdown_table_via_trait() {
        let chunker = TabularChunker::new(default_config()).unwrap();
        let text = "| Col1 | Col2 |\n| --- | --- |\n| A | B |\n| C | D |";
        let chunks = chunker.chunk(text, make_doc_id(), None).unwrap();
        assert!(!chunks.is_empty());
        assert!(chunks[0].content.contains("Col1"));
    }

    #[test]
    fn test_chunk_csv_via_trait() {
        let chunker = TabularChunker::new(default_config()).unwrap();
        let text = "Product,Qty,Price\nApple,10,1.20\nBanana,5,0.50";
        let chunks = chunker.chunk(text, make_doc_id(), None).unwrap();
        assert!(!chunks.is_empty());
        assert!(chunks[0].content.contains("Product"));
    }

    #[test]
    fn test_chunk_falls_back_to_recursive_for_prose() {
        let chunker = TabularChunker::new(default_config()).unwrap();
        let text = "Just some regular prose. No tables here at all.";
        // Should not error; falls back to recursive.
        let chunks = chunker.chunk(text, make_doc_id(), None).unwrap();
        assert!(!chunks.is_empty());
    }

    #[test]
    fn test_multiple_tables_get_distinct_table_index() {
        let chunker = TabularChunker::new(default_config()).unwrap();
        let t1 = TableContent {
            headers: vec!["A".into(), "B".into()],
            rows: vec![vec!["1".into(), "2".into()]],
            caption: None,
        };
        let t2 = TableContent {
            headers: vec!["X".into(), "Y".into()],
            rows: vec![vec!["3".into(), "4".into()]],
            caption: None,
        };

        let chunks = chunker
            .chunk_tables(&[t1, t2], make_doc_id(), &HashMap::new())
            .unwrap();

        assert_eq!(chunks.len(), 2);
        assert_eq!(chunks[0].metadata["table_index"], serde_json::json!(0));
        assert_eq!(chunks[1].metadata["table_index"], serde_json::json!(1));
        assert_eq!(chunks[0].chunk_index, 0);
        assert_eq!(chunks[1].chunk_index, 1);
    }
}
