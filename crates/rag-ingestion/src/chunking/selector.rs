//! Intelligent chunking strategy selection based on document characteristics.
//!
//! Analyzes document text, parser-produced structural metadata, and file type
//! to automatically choose the most appropriate chunking strategy. Explicit
//! caller overrides are still honored.

use rag_types::ChunkingStrategy as ChunkingStrategyType;

use super::hierarchical::HierarchicalChunker;
use super::qa::QAChunker;
use crate::parsers::{ContentType, ParsedDocument};

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/// Lightweight profile of a document's structural characteristics.
///
/// Built by [`analyze_document`] from the parsed text and optional structured
/// blocks, then fed to [`select_strategy`].
#[derive(Debug, Clone)]
#[allow(dead_code)] // fields retained for logging and future heuristic expansion
pub struct DocumentProfile {
    /// Total character count of the text.
    pub char_count: usize,
    /// Total number of lines.
    pub line_count: usize,
    /// Number of heading-like lines detected in text.
    pub heading_count: usize,
    /// Heading density: headings per 1000 characters.
    pub heading_density: f64,
    /// Average sentence length in characters.
    pub avg_sentence_len: f64,
    /// Fraction of non-empty lines that end with sentence punctuation.
    pub prose_fraction: f64,
    /// Number of structured content blocks from parser (if available).
    pub block_count: usize,
    /// Number of heading blocks from parser metadata.
    pub structured_heading_count: usize,
    /// Number of code blocks from parser.
    pub code_block_count: usize,
    /// Number of table blocks from parser.
    pub table_block_count: usize,
    /// Number of Q&A pairs detected in the document text.
    pub qa_pair_count: usize,
    /// Diversity of content block types: `distinct ContentType count / 4`.
    ///
    /// A value ≥ 0.3 with ≥ 10 blocks and at least one table typically
    /// indicates a mixed-content layout.
    pub block_type_variance: f64,
    /// Lowercase file extension (without dot).
    pub file_extension: String,
    /// Source type from the job payload.
    pub source_type: String,
}

/// Result of automatic strategy selection.
#[derive(Debug, Clone)]
pub struct StrategySelection {
    /// The chosen strategy.
    pub strategy: ChunkingStrategyType,
    /// Human-readable reason for the choice (for logging / debugging).
    pub reason: String,
    /// Confidence level: `"high"`, `"medium"`, or `"low"`.
    pub confidence: &'static str,
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/// Analyze a document to build a [`DocumentProfile`] for strategy selection.
///
/// This is deliberately lightweight — no tokenizer, just character/line
/// scanning plus optional block analysis.
pub fn analyze_document(
    text: &str,
    parsed_doc: Option<&ParsedDocument>,
    file_extension: &str,
    source_type: &str,
) -> DocumentProfile {
    let char_count = text.len();
    let lines: Vec<&str> = text.lines().collect();
    let line_count = lines.len();

    let heading_count = lines
        .iter()
        .filter(|line| HierarchicalChunker::extract_heading(line.trim()).is_some())
        .count();

    let heading_density = if char_count > 0 {
        heading_count as f64 / (char_count as f64 / 1000.0)
    } else {
        0.0
    };

    let avg_sentence_len = estimate_avg_sentence_len(text);
    let prose_fraction = estimate_prose_fraction(text);

    let (
        block_count,
        structured_heading_count,
        code_block_count,
        table_block_count,
        block_type_variance,
    ) = if let Some(doc) = parsed_doc {
        analyze_blocks(&doc.blocks)
    } else {
        (0, 0, 0, 0, 0.0)
    };

    let qa_pair_count = QAChunker::detect_pairs(text).len();

    DocumentProfile {
        char_count,
        line_count,
        heading_count,
        heading_density,
        avg_sentence_len,
        prose_fraction,
        block_count,
        structured_heading_count,
        code_block_count,
        table_block_count,
        qa_pair_count,
        block_type_variance,
        file_extension: file_extension.to_lowercase(),
        source_type: source_type.to_string(),
    }
}

/// Select the best chunking strategy based on the document profile.
///
/// Decision tree (evaluated top-to-bottom, first match wins):
///
/// 1.  CSV file extension                                    → Tabular
/// 2.  Table-heavy blocks (> 20% of blocks)                 → Tabular
/// 3.  Q&A pair count >= 3                                   → QA
/// 4.  Mixed block types (variance ≥ 0.3, ≥ 10 blocks, has tables) → `MixedContent`
/// 5.  Markdown with >= 2 headings                           → Hierarchical
/// 6.  Parser blocks with >= 3 structured headings (>= 5%)  → Hierarchical
/// 7.  Code-heavy blocks (> 30%)                             → Recursive
/// 8.  Short documents (< 1500 chars)                        → Recursive
/// 9.  High heading density (>= 3 / 1000 chars)              → Hierarchical
/// 10. Moderate heading density (>= 3 headings, >= 1/1000)   → Hierarchical
/// 11. Long sentences (avg >= 120 chars) + prose-heavy (>= 60%) → Semantic
/// 12. Long unstructured prose (> 5000 chars, >= 70%, <= 1 heading) → Semantic
/// 13. HTML with >= 2 headings                               → Hierarchical
/// 14. Default fallback                                       → Recursive
#[allow(clippy::too_many_lines)]
pub fn select_strategy(profile: &DocumentProfile) -> StrategySelection {
    // 1. CSV files are always tabular.
    if profile.file_extension == "csv" {
        return StrategySelection {
            strategy: ChunkingStrategyType::Tabular,
            reason: "CSV file extension".into(),
            confidence: "high",
        };
    }

    // 2. Table-heavy documents.
    if profile.block_count > 0 {
        let table_ratio = profile.table_block_count as f64 / profile.block_count as f64;
        if table_ratio > 0.20 {
            return StrategySelection {
                strategy: ChunkingStrategyType::Tabular,
                reason: "Table-heavy document (>20% of blocks are tables)".into(),
                confidence: "high",
            };
        }
    }

    // 3. Q&A / FAQ documents.
    if profile.qa_pair_count >= 3 {
        return StrategySelection {
            strategy: ChunkingStrategyType::QA,
            reason: format!("Q&A document ({} pairs detected)", profile.qa_pair_count),
            confidence: "high",
        };
    }

    // 4. Mixed-content documents (multiple block types + tables).
    if profile.block_type_variance >= 0.3
        && profile.block_count >= 10
        && profile.table_block_count > 0
    {
        return StrategySelection {
            strategy: ChunkingStrategyType::MixedContent,
            reason: "Mixed-content document (tables + prose/code)".into(),
            confidence: "medium",
        };
    }

    // 5. Markdown extension hint.
    if profile.file_extension == "md" || profile.file_extension == "markdown" {
        if profile.heading_count >= 2 || profile.structured_heading_count >= 2 {
            return StrategySelection {
                strategy: ChunkingStrategyType::Hierarchical,
                reason: "Markdown with multiple headings".into(),
                confidence: "high",
            };
        }
        return StrategySelection {
            strategy: ChunkingStrategyType::Recursive,
            reason: "Markdown without heading structure".into(),
            confidence: "medium",
        };
    }

    // 6. Parser-produced structured headings.
    if profile.block_count > 0 && profile.structured_heading_count >= 3 {
        let heading_ratio =
            profile.structured_heading_count as f64 / profile.block_count as f64;
        if heading_ratio >= 0.05 {
            return StrategySelection {
                strategy: ChunkingStrategyType::Hierarchical,
                reason: "Parser detected multiple structured headings".into(),
                confidence: "high",
            };
        }
    }

    // 7. Code-heavy documents.
    if profile.block_count > 0 {
        let code_ratio = profile.code_block_count as f64 / profile.block_count as f64;
        if code_ratio > 0.3 {
            return StrategySelection {
                strategy: ChunkingStrategyType::Recursive,
                reason: "Code-heavy document".into(),
                confidence: "medium",
            };
        }
    }

    // 8. Short documents.
    if profile.char_count < 1500 {
        return StrategySelection {
            strategy: ChunkingStrategyType::Recursive,
            reason: "Short document".into(),
            confidence: "high",
        };
    }

    // 9. High heading density.
    if profile.heading_density >= 3.0 {
        return StrategySelection {
            strategy: ChunkingStrategyType::Hierarchical,
            reason: "High heading density in text".into(),
            confidence: "high",
        };
    }

    // 10. Moderate heading density.
    if profile.heading_count >= 3 && profile.heading_density >= 1.0 {
        return StrategySelection {
            strategy: ChunkingStrategyType::Hierarchical,
            reason: "Moderate heading density".into(),
            confidence: "medium",
        };
    }

    // 11. Long sentences in prose-heavy text.
    if profile.avg_sentence_len >= 120.0 && profile.prose_fraction >= 0.6 {
        return StrategySelection {
            strategy: ChunkingStrategyType::Semantic,
            reason: "Long sentences in prose-heavy text".into(),
            confidence: "high",
        };
    }

    // 12. Long unstructured prose.
    if profile.char_count > 5000 && profile.prose_fraction >= 0.7 && profile.heading_count <= 1 {
        return StrategySelection {
            strategy: ChunkingStrategyType::Semantic,
            reason: "Long unstructured prose".into(),
            confidence: "medium",
        };
    }

    // 13. HTML with headings.
    if (profile.file_extension == "html" || profile.file_extension == "htm")
        && profile.heading_count >= 2
    {
        return StrategySelection {
            strategy: ChunkingStrategyType::Hierarchical,
            reason: "HTML with detected headings".into(),
            confidence: "medium",
        };
    }

    // 14. Default fallback.
    StrategySelection {
        strategy: ChunkingStrategyType::Recursive,
        reason: "No strong signal detected".into(),
        confidence: "medium",
    }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/// Estimate average sentence length by splitting on sentence-ending punctuation.
fn estimate_avg_sentence_len(text: &str) -> f64 {
    let mut count = 0_usize;
    let mut total_chars = 0_usize;

    for sentence in text.split_inclusive(&['.', '?', '!']) {
        let trimmed = sentence.trim();
        if trimmed.len() > 3 {
            count += 1;
            total_chars += trimmed.len();
        }
    }

    if count == 0 {
        return 0.0;
    }
    total_chars as f64 / count as f64
}

/// Estimate fraction of non-empty lines that look like prose sentences.
fn estimate_prose_fraction(text: &str) -> f64 {
    let lines: Vec<&str> = text
        .lines()
        .map(str::trim)
        .filter(|l| !l.is_empty())
        .collect();

    if lines.is_empty() {
        return 0.0;
    }

    let prose_lines = lines
        .iter()
        .filter(|l| {
            l.ends_with('.')
                || l.ends_with('?')
                || l.ends_with('!')
                || l.ends_with('"')
                || l.ends_with(')')
        })
        .count();

    prose_lines as f64 / lines.len() as f64
}

/// Analyze structured content blocks from the parser.
///
/// Returns `(block_count, structured_heading_count, code_block_count,
/// table_block_count, block_type_variance)`.
fn analyze_blocks(
    blocks: &[crate::parsers::ContentBlock],
) -> (usize, usize, usize, usize, f64) {
    let block_count = blocks.len();

    let structured_heading_count = blocks
        .iter()
        .filter(|b| {
            // Markdown parser sets heading_level
            b.metadata.contains_key("heading_level")
            // HTML parser sets tag: h1, h2, ..., h6
            || b.metadata
                .get("tag")
                .and_then(|v| v.as_str())
                .is_some_and(|tag| {
                    tag.len() == 2
                        && tag.starts_with('h')
                        && tag.as_bytes().get(1).is_some_and(u8::is_ascii_digit)
                })
        })
        .count();

    let code_block_count = blocks
        .iter()
        .filter(|b| b.content_type == ContentType::Code)
        .count();

    let table_block_count = blocks
        .iter()
        .filter(|b| b.content_type == ContentType::Table)
        .count();

    // Block-type diversity: distinct content types / 4 (normalised to 0..1).
    let block_type_variance = if block_count == 0 {
        0.0
    } else {
        let has_text = blocks.iter().any(|b| b.content_type == ContentType::Text);
        let has_table = blocks.iter().any(|b| b.content_type == ContentType::Table);
        let has_code = blocks.iter().any(|b| b.content_type == ContentType::Code);
        let has_image = blocks.iter().any(|b| b.content_type == ContentType::Image);
        let distinct = [has_text, has_table, has_code, has_image]
            .iter()
            .filter(|&&v| v)
            .count();
        distinct as f64 / 4.0
    };

    (
        block_count,
        structured_heading_count,
        code_block_count,
        table_block_count,
        block_type_variance,
    )
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn make_profile(overrides: impl FnOnce(&mut DocumentProfile)) -> DocumentProfile {
        let mut p = DocumentProfile {
            char_count: 3000,
            line_count: 50,
            heading_count: 0,
            heading_density: 0.0,
            avg_sentence_len: 50.0,
            prose_fraction: 0.3,
            block_count: 0,
            structured_heading_count: 0,
            code_block_count: 0,
            table_block_count: 0,
            qa_pair_count: 0,
            block_type_variance: 0.0,
            file_extension: "txt".into(),
            source_type: "file".into(),
        };
        overrides(&mut p);
        p
    }

    // --- analyze_document tests ---

    #[test]
    fn test_analyze_empty_document() {
        let profile = analyze_document("", None, "txt", "file");
        assert_eq!(profile.char_count, 0);
        assert_eq!(profile.heading_count, 0);
        assert_eq!(profile.heading_density, 0.0);
        assert_eq!(profile.avg_sentence_len, 0.0);
    }

    #[test]
    fn test_analyze_markdown_with_headings() {
        let text = "# Title\n\nSome text here.\n\n## Section 1\n\nMore text.\n\n## Section 2\n\nEven more.";
        let profile = analyze_document(text, None, "md", "file");
        assert_eq!(profile.heading_count, 3);
        assert!(profile.heading_density > 2.0);
    }

    #[test]
    fn test_analyze_prose_document() {
        let sentence = "This is a fairly long sentence that describes something in considerable detail and provides a lot of context. ";
        let text = sentence.repeat(20);
        let profile = analyze_document(&text, None, "txt", "file");
        assert!(profile.avg_sentence_len > 50.0);
        assert!(profile.prose_fraction > 0.0);
        assert_eq!(profile.heading_count, 0);
    }

    #[test]
    fn test_analyze_with_parser_blocks() {
        use crate::parsers::ContentBlock;
        use std::collections::HashMap;

        let text = "# Title\nContent here.";
        let mut heading_meta = HashMap::new();
        heading_meta.insert("heading_level".into(), serde_json::json!(1));

        let blocks = vec![
            ContentBlock {
                content_type: ContentType::Text,
                content: "Title".into(),
                page_number: None,
                position: Some(0),
                metadata: heading_meta,
            },
            ContentBlock {
                content_type: ContentType::Text,
                content: "Content here.".into(),
                page_number: None,
                position: Some(1),
                metadata: HashMap::new(),
            },
        ];

        let doc = ParsedDocument {
            text: text.into(),
            blocks,
            ..Default::default()
        };

        let profile = analyze_document(&doc.text, Some(&doc), "md", "file");
        assert_eq!(profile.structured_heading_count, 1);
        assert_eq!(profile.block_count, 2);
    }

    // --- select_strategy tests: existing rules ---

    #[test]
    fn test_short_document_returns_recursive() {
        let sel = select_strategy(&make_profile(|p| {
            p.char_count = 500;
        }));
        assert_eq!(sel.strategy, ChunkingStrategyType::Recursive);
    }

    #[test]
    fn test_markdown_with_headings_returns_hierarchical() {
        let sel = select_strategy(&make_profile(|p| {
            p.file_extension = "md".into();
            p.heading_count = 5;
            p.heading_density = 1.0;
        }));
        assert_eq!(sel.strategy, ChunkingStrategyType::Hierarchical);
    }

    #[test]
    fn test_markdown_without_headings_returns_recursive() {
        let sel = select_strategy(&make_profile(|p| {
            p.file_extension = "md".into();
            p.heading_count = 0;
            p.structured_heading_count = 0;
        }));
        assert_eq!(sel.strategy, ChunkingStrategyType::Recursive);
    }

    #[test]
    fn test_long_prose_returns_semantic() {
        let sel = select_strategy(&make_profile(|p| {
            p.char_count = 10_000;
            p.avg_sentence_len = 150.0;
            p.prose_fraction = 0.8;
        }));
        assert_eq!(sel.strategy, ChunkingStrategyType::Semantic);
    }

    #[test]
    fn test_long_unstructured_prose_returns_semantic() {
        let sel = select_strategy(&make_profile(|p| {
            p.char_count = 8000;
            p.prose_fraction = 0.75;
            p.heading_count = 0;
            p.avg_sentence_len = 80.0;
        }));
        assert_eq!(sel.strategy, ChunkingStrategyType::Semantic);
    }

    #[test]
    fn test_high_heading_density_returns_hierarchical() {
        let sel = select_strategy(&make_profile(|p| {
            p.heading_count = 12;
            p.heading_density = 4.0;
        }));
        assert_eq!(sel.strategy, ChunkingStrategyType::Hierarchical);
    }

    #[test]
    fn test_structured_blocks_with_headings_returns_hierarchical() {
        let sel = select_strategy(&make_profile(|p| {
            p.block_count = 40;
            p.structured_heading_count = 8;
        }));
        assert_eq!(sel.strategy, ChunkingStrategyType::Hierarchical);
    }

    #[test]
    fn test_code_heavy_returns_recursive() {
        let sel = select_strategy(&make_profile(|p| {
            p.file_extension = "html".into();
            p.block_count = 10;
            p.code_block_count = 5;
        }));
        assert_eq!(sel.strategy, ChunkingStrategyType::Recursive);
    }

    #[test]
    fn test_html_with_headings_returns_hierarchical() {
        let sel = select_strategy(&make_profile(|p| {
            p.file_extension = "html".into();
            p.heading_count = 4;
            p.heading_density = 0.5;
        }));
        assert_eq!(sel.strategy, ChunkingStrategyType::Hierarchical);
    }

    #[test]
    fn test_default_fallback_is_recursive() {
        let sel = select_strategy(&make_profile(|_| {}));
        assert_eq!(sel.strategy, ChunkingStrategyType::Recursive);
    }

    // --- select_strategy tests: new rules ---

    #[test]
    fn test_csv_extension_returns_tabular() {
        let sel = select_strategy(&make_profile(|p| {
            p.file_extension = "csv".into();
        }));
        assert_eq!(sel.strategy, ChunkingStrategyType::Tabular);
        assert_eq!(sel.confidence, "high");
    }

    #[test]
    fn test_table_heavy_blocks_returns_tabular() {
        let sel = select_strategy(&make_profile(|p| {
            p.block_count = 10;
            p.table_block_count = 3; // 30% > 20% threshold
        }));
        assert_eq!(sel.strategy, ChunkingStrategyType::Tabular);
    }

    #[test]
    fn test_qa_document_returns_qa() {
        let sel = select_strategy(&make_profile(|p| {
            p.qa_pair_count = 5;
        }));
        assert_eq!(sel.strategy, ChunkingStrategyType::QA);
        assert_eq!(sel.confidence, "high");
    }

    #[test]
    fn test_mixed_content_returns_mixed_content() {
        let sel = select_strategy(&make_profile(|p| {
            p.block_count = 15;
            p.block_type_variance = 0.5; // text + table + code = 3/4 = 0.75
            p.table_block_count = 2;
        }));
        assert_eq!(sel.strategy, ChunkingStrategyType::MixedContent);
    }

    #[test]
    fn test_qa_takes_priority_over_short_document() {
        // Q&A rule (3) fires before short-doc rule (8).
        let sel = select_strategy(&make_profile(|p| {
            p.char_count = 800; // short
            p.qa_pair_count = 4; // but has Q&A
        }));
        assert_eq!(sel.strategy, ChunkingStrategyType::QA);
    }
}
