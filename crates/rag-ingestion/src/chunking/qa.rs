//! Q&A / FAQ chunker — keeps each question+answer pair as one retrieval unit.
//!
//! ## Detection
//!
//! Q&A pairs are detected by three patterns (tried in priority order):
//!
//! 1. **Explicit prefix** — lines starting with `Q:`, `Q.`, `Q)`,
//!    `Question:`, or `Question.` followed by lines starting with `A:`,
//!    `A.`, `A)`, `Answer:`, or `Answer.`.
//! 2. **Heading-ending-in-question-mark** — any heading (as detected by
//!    [`HierarchicalChunker::extract_heading`]) whose text ends with `?`,
//!    with the section content as the answer.
//! 3. **Implicit** — a short paragraph (≤ 2 sentences) ending in `?`
//!    followed by a non-question paragraph as the answer.
//!
//! ## Fallback
//!
//! If fewer than [`MIN_QA_PAIRS`] pairs are found the chunker falls back to
//! [`SemanticChunker`], which is the most appropriate strategy for FAQ-style
//! prose when explicit Q&A structure is absent.

use std::collections::HashMap;

use rag_types::{ChunkId, DocumentId};
use serde_json::Value;

use super::base::{Chunk, ChunkingConfig, ChunkingStrategy};
use super::hierarchical::HierarchicalChunker;
use super::recursive::RecursiveCharacterSplitter;
use super::semantic::{SemanticChunker, SemanticChunkerConfig};
use crate::{Error, Result};

/// Minimum number of Q&A pairs required before the dedicated strategy is used.
/// Documents with fewer pairs fall back to [`SemanticChunker`].
const MIN_QA_PAIRS: usize = 3;

/// Maximum token count for a single Q&A chunk before the answer is split.
const QA_ANSWER_SOFT_LIMIT: usize = 400;

// ---------------------------------------------------------------------------
// Public types
// ---------------------------------------------------------------------------

/// A detected question–answer pair.
#[derive(Debug)]
pub struct QAPair {
    pub question: String,
    pub answer: String,
}

// ---------------------------------------------------------------------------
// QAChunker
// ---------------------------------------------------------------------------

/// Chunks FAQ / Q&A documents so that each question+answer pair is one chunk.
pub struct QAChunker {
    config: ChunkingConfig,
}

impl QAChunker {
    /// Create a new `QAChunker`.
    pub fn new(config: ChunkingConfig) -> Self {
        Self { config }
    }

    // ------------------------------------------------------------------
    // Public: Q&A pair detection (also called by the auto-selector)
    // ------------------------------------------------------------------

    /// Detect Q&A pairs from raw text.
    ///
    /// Returns a `Vec` of `(question, answer)` tuples.  The caller can use
    /// the length to decide whether to use this chunker or a fallback.
    pub fn detect_pairs(text: &str) -> Vec<QAPair> {
        // Try the highest-confidence pattern first.
        let explicit = detect_explicit_qa(text);
        if !explicit.is_empty() {
            return explicit;
        }

        let heading = detect_heading_questions(text);
        if !heading.is_empty() {
            return heading;
        }

        detect_implicit_qa(text)
    }

    // ------------------------------------------------------------------
    // Internal helpers
    // ------------------------------------------------------------------

    /// Build a chunk from a single [`QAPair`].
    ///
    /// If the pair exceeds the configured token budget the answer is split
    /// across multiple chunks, each of which begins with the question.
    fn pairs_to_chunks(
        &self,
        pairs: Vec<QAPair>,
        document_id: DocumentId,
        base_metadata: &HashMap<String, Value>,
    ) -> Result<Vec<Chunk>> {
        let mut chunks = Vec::new();
        let mut chunk_index = 0u32;

        // Use recursive splitter to handle oversized answers.
        let splitter = RecursiveCharacterSplitter::new(self.config.clone())?;

        for (pair_idx, pair) in pairs.into_iter().enumerate() {
            let question_preview: String = pair.question.chars().take(120).collect();
            let full_text = format!("{}\n{}", pair.question, pair.answer);

            // Estimate size; split the answer if the pair is very long.
            let is_large = full_text.len() > QA_ANSWER_SOFT_LIMIT * 4; // ~4 chars/token

            if is_large {
                // Split the answer; prepend the question to each piece.
                let answer_chunks =
                    splitter.chunk(&pair.answer, document_id, Some(base_metadata.clone()))?;

                for (i, answer_chunk) in answer_chunks.into_iter().enumerate() {
                    let content = if i == 0 {
                        format!("{}\n{}", pair.question, answer_chunk.content)
                    } else {
                        format!(
                            "{} (continued)\n{}",
                            pair.question, answer_chunk.content
                        )
                    };
                    let mut meta = base_metadata.clone();
                    meta.extend(answer_chunk.metadata);
                    meta.insert("qa_index".into(), serde_json::json!(pair_idx));
                    meta.insert("question".into(), serde_json::json!(&question_preview));

                    chunks.push(Chunk {
                        chunk_id: ChunkId::new(),
                        document_id,
                        content: content.clone(),
                        chunk_index,
                        start_char: answer_chunk.start_char,
                        end_char: answer_chunk.end_char,
                        token_count: answer_chunk.token_count,
                        parent_chunk_id: None,
                        child_chunk_ids: Vec::new(),
                        metadata: meta,
                        source_page: None,
                        source_section: None,
                    });
                    chunk_index += 1;
                }
            } else {
                let mut meta = base_metadata.clone();
                meta.insert("qa_index".into(), serde_json::json!(pair_idx));
                meta.insert("question".into(), serde_json::json!(&question_preview));

                #[allow(clippy::cast_possible_truncation)]
                let token_count = (full_text.len() / 4).max(1) as u32;

                chunks.push(Chunk {
                    chunk_id: ChunkId::new(),
                    document_id,
                    content: full_text.clone(),
                    chunk_index,
                    start_char: 0,
                    end_char: full_text.len(),
                    token_count,
                    parent_chunk_id: None,
                    child_chunk_ids: Vec::new(),
                    metadata: meta,
                    source_page: None,
                    source_section: None,
                });
                chunk_index += 1;
            }
        }

        Ok(chunks)
    }
}

// ---------------------------------------------------------------------------
// ChunkingStrategy trait impl
// ---------------------------------------------------------------------------

impl ChunkingStrategy for QAChunker {
    fn name(&self) -> &'static str {
        "qa"
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
        let pairs = Self::detect_pairs(text);

        if pairs.len() >= MIN_QA_PAIRS {
            return self.pairs_to_chunks(pairs, document_id, &base_metadata);
        }

        // Fallback: too few Q&A pairs — treat as prose.
        let semantic_config = SemanticChunkerConfig::from(self.config.clone());
        let chunker = SemanticChunker::with_config(semantic_config)
            .map_err(|e| Error::Config(format!("QA fallback (semantic) failed: {e}")))?;
        chunker.chunk(text, document_id, Some(base_metadata))
    }
}

// ---------------------------------------------------------------------------
// Detection helpers
// ---------------------------------------------------------------------------

/// Detect explicitly prefixed Q&A pairs (`Q:` / `A:` style).
fn detect_explicit_qa(text: &str) -> Vec<QAPair> {
    let q_prefixes = ["q:", "q.", "q)", "question:", "question."];
    let a_prefixes = ["a:", "a.", "a)", "answer:", "answer."];

    let is_question_line = |line: &str| -> bool {
        let lower = line.trim().to_lowercase();
        q_prefixes.iter().any(|p| lower.starts_with(p))
    };

    let strip_prefix = |line: &str, prefixes: &[&str]| -> String {
        let lower = line.trim().to_lowercase();
        for prefix in prefixes {
            if lower.starts_with(prefix) {
                return line.trim()[prefix.len()..].trim().to_string();
            }
        }
        line.trim().to_string()
    };

    let mut pairs = Vec::new();
    let mut current_question: Option<String> = None;
    let mut answer_lines: Vec<String> = Vec::new();

    for line in text.lines() {
        let trimmed = line.trim();

        if is_question_line(trimmed) {
            // Save previous pair.
            if let Some(q) = current_question.take() {
                let answer = answer_lines.join(" ").trim().to_string();
                if !answer.is_empty() {
                    pairs.push(QAPair { question: q, answer });
                }
                answer_lines.clear();
            }
            current_question = Some(strip_prefix(trimmed, &q_prefixes));
        } else if current_question.is_some() {
            let lower = trimmed.to_lowercase();
            let is_answer_start = a_prefixes.iter().any(|p| lower.starts_with(p));

            if is_answer_start {
                let answer_text = strip_prefix(trimmed, &a_prefixes);
                if !answer_text.is_empty() {
                    answer_lines.push(answer_text);
                }
            } else if !trimmed.is_empty() {
                answer_lines.push(trimmed.to_string());
            }
        }
    }

    // Flush last pair.
    if let Some(q) = current_question {
        let answer = answer_lines.join(" ").trim().to_string();
        if !answer.is_empty() {
            pairs.push(QAPair { question: q, answer });
        }
    }

    pairs
}

/// Detect Q&A pairs where a heading ends in `?`.
fn detect_heading_questions(text: &str) -> Vec<QAPair> {
    let mut pairs = Vec::new();
    let mut current_question: Option<String> = None;
    let mut answer_lines: Vec<String> = Vec::new();

    for line in text.lines() {
        let trimmed = line.trim();

        if let Some(heading) = HierarchicalChunker::extract_heading(trimmed) {
            if heading.trim_end().ends_with('?') {
                // Save previous pair.
                if let Some(q) = current_question.take() {
                    let answer = answer_lines.join(" ").trim().to_string();
                    if !answer.is_empty() {
                        pairs.push(QAPair { question: q, answer });
                    }
                    answer_lines.clear();
                }
                current_question = Some(heading);
            } else if current_question.is_some() {
                // Non-question heading ends the current answer.
                if let Some(q) = current_question.take() {
                    let answer = answer_lines.join(" ").trim().to_string();
                    if !answer.is_empty() {
                        pairs.push(QAPair { question: q, answer });
                    }
                    answer_lines.clear();
                }
            }
        } else if current_question.is_some() && !trimmed.is_empty() {
            answer_lines.push(trimmed.to_string());
        }
    }

    // Flush last pair.
    if let Some(q) = current_question {
        let answer = answer_lines.join(" ").trim().to_string();
        if !answer.is_empty() {
            pairs.push(QAPair { question: q, answer });
        }
    }

    pairs
}

/// Detect implicit Q&A: a short paragraph ending in `?` followed by prose.
fn detect_implicit_qa(text: &str) -> Vec<QAPair> {
    // Split into paragraphs (blank-line separated).
    let paragraphs: Vec<&str> = text
        .split("\n\n")
        .map(str::trim)
        .filter(|p| !p.is_empty())
        .collect();

    if paragraphs.len() < 2 {
        return Vec::new();
    }

    let is_question_para = |para: &&str| -> bool {
        let trimmed = para.trim();
        // Short (≤ 2 sentences) paragraph ending in `?`.
        let sentence_count = trimmed
            .split(['.', '?', '!'])
            .filter(|s| !s.trim().is_empty())
            .count();
        sentence_count <= 2 && trimmed.ends_with('?')
    };

    let mut pairs = Vec::new();
    let mut i = 0;

    while i + 1 < paragraphs.len() {
        if is_question_para(&paragraphs[i]) && !is_question_para(&paragraphs[i + 1]) {
            pairs.push(QAPair {
                question: paragraphs[i].to_string(),
                answer: paragraphs[i + 1].to_string(),
            });
            i += 2; // Consume both.
        } else {
            i += 1;
        }
    }

    pairs
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;

    fn default_config() -> ChunkingConfig {
        ChunkingConfig {
            target_tokens: 300,
            max_tokens: 512,
            chunk_overlap: 50,
            min_chunk_size: 50,
            tokenizer: "cl100k_base".to_string(),
        }
    }

    fn make_doc_id() -> DocumentId {
        DocumentId::new()
    }

    // --- detect_explicit_qa ---

    #[test]
    fn test_detect_explicit_qa_colon_style() {
        let text = "Q: What is the return policy?\nA: You can return within 30 days.\n\
                    Q: How do I track my order?\nA: Use the tracking link in your email.\n\
                    Q: Can I cancel?\nA: Yes, before it ships.";

        let pairs = detect_explicit_qa(text);
        assert_eq!(pairs.len(), 3);
        assert!(pairs[0].question.contains("return policy"));
        assert!(pairs[0].answer.contains("30 days"));
    }

    #[test]
    fn test_detect_explicit_qa_full_word_style() {
        let text = "Question: What is the capital of France?\nAnswer: Paris is the capital.\n\
                    Question: What is 2+2?\nAnswer: It equals four.\n\
                    Question: Is Rust fast?\nAnswer: Yes, very fast.";

        let pairs = detect_explicit_qa(text);
        assert_eq!(pairs.len(), 3);
    }

    #[test]
    fn test_detect_explicit_qa_multiline_answer() {
        let text = "Q: What are the payment methods?\n\
                    A: We accept the following:\n\
                    Credit cards, PayPal, and bank transfer.\n\
                    Q: What is the delivery time?\n\
                    A: Usually 3-5 business days.";

        let pairs = detect_explicit_qa(text);
        assert_eq!(pairs.len(), 2);
        assert!(pairs[0].answer.contains("Credit cards"));
    }

    // --- detect_heading_questions ---

    #[test]
    fn test_detect_heading_questions_markdown() {
        let text = "## What is your refund policy?\n\
                    We offer full refunds within 30 days of purchase.\n\n\
                    ## How do I contact support?\n\
                    Email us at support@example.com.\n\n\
                    ## Can I upgrade my plan?\n\
                    Yes, you can upgrade at any time.";

        let pairs = detect_heading_questions(text);
        assert_eq!(pairs.len(), 3);
        assert!(pairs[0].question.contains("refund policy"));
        assert!(pairs[0].answer.contains("30 days"));
    }

    // --- detect_implicit_qa ---

    #[test]
    fn test_detect_implicit_qa() {
        let text = "What is your return policy?\n\n\
                    We accept returns within 30 days of purchase, provided the item is in \
                    its original condition.\n\n\
                    How do I track my shipment?\n\n\
                    After your order ships, you will receive an email with a tracking number \
                    you can use on our tracking page.\n\n\
                    Can I change my order after placing it?\n\n\
                    Yes, orders can be changed within 1 hour of placement.";

        let pairs = detect_implicit_qa(text);
        assert_eq!(pairs.len(), 3);
    }

    // --- QAChunker.chunk ---

    #[test]
    fn test_chunk_explicit_qa_document() {
        let chunker = QAChunker::new(default_config());
        let text = "Q: What is Rust?\nA: A systems programming language.\n\
                    Q: Is Rust safe?\nA: Yes, it has a strong ownership model.\n\
                    Q: Is Rust fast?\nA: Extremely fast, often competitive with C.";

        let chunks = chunker.chunk(text, make_doc_id(), None).unwrap();
        assert_eq!(chunks.len(), 3);

        for chunk in &chunks {
            assert!(chunk.metadata.contains_key("qa_index"));
            assert!(chunk.metadata.contains_key("question"));
        }
    }

    #[test]
    fn test_chunk_falls_back_to_semantic_when_too_few_pairs() {
        let chunker = QAChunker::new(default_config());
        // Only 2 Q&A pairs — below MIN_QA_PAIRS.
        let text = "Q: One question?\nA: One answer.\nQ: Two question?\nA: Two answer.\n\
                    Some extra prose that makes the document longer for semantic chunking to work on.";

        // Should not error; falls back to semantic chunker.
        let chunks = chunker.chunk(text, make_doc_id(), None).unwrap();
        assert!(!chunks.is_empty());
    }

    #[test]
    fn test_detect_pairs_uses_heading_fallback() {
        let text = "## Is Rust fast?\nYes, it is.\n## Is Rust safe?\nYes.\n## Is Rust popular?\nGrowing.";
        let pairs = QAChunker::detect_pairs(text);
        assert_eq!(pairs.len(), 3);
    }
}
