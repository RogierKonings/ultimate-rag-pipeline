//! Query preprocessing with normalization and type classification.
//!
//! This module provides the [`QueryPreprocessor`] for normalizing queries
//! and classifying them into types that inform search strategy selection.
//!
//! # Example
//!
//! ```
//! use rag_retrieval::query::{QueryPreprocessor, QueryPreprocessorConfig};
//!
//! let config = QueryPreprocessorConfig::default();
//! let preprocessor = QueryPreprocessor::new(config);
//!
//! let result = preprocessor.preprocess("  What is Rust?  ").unwrap();
//! assert_eq!(result.normalized, "what is rust?");
//! assert!(result.was_modified);
//! ```

use serde::{Deserialize, Serialize};
use unicode_normalization::UnicodeNormalization;

use crate::error::{Result, RetrievalError};
use crate::types::QueryType;

/// Configuration for query preprocessing.
#[allow(clippy::struct_excessive_bools)]
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct QueryPreprocessorConfig {
    /// Minimum allowed query length (in characters).
    pub min_query_length: usize,
    /// Maximum allowed query length (in characters).
    pub max_query_length: usize,
    /// Whether to normalize whitespace (collapse multiple spaces).
    pub normalize_whitespace: bool,
    /// Whether to convert query to lowercase.
    pub lowercase: bool,
    /// Whether to remove punctuation from the query.
    pub remove_punctuation: bool,
    /// Whether to apply Unicode NFC normalization.
    pub unicode_normalize: bool,
}

impl Default for QueryPreprocessorConfig {
    fn default() -> Self {
        Self {
            min_query_length: 2,
            max_query_length: 1000,
            normalize_whitespace: true,
            lowercase: true,
            remove_punctuation: false,
            unicode_normalize: true,
        }
    }
}

impl QueryPreprocessorConfig {
    /// Create a new configuration with custom settings.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Set the minimum query length.
    #[must_use]
    pub const fn with_min_query_length(mut self, len: usize) -> Self {
        self.min_query_length = len;
        self
    }

    /// Set the maximum query length.
    #[must_use]
    pub const fn with_max_query_length(mut self, len: usize) -> Self {
        self.max_query_length = len;
        self
    }

    /// Set whether to normalize whitespace.
    #[must_use]
    pub const fn with_normalize_whitespace(mut self, normalize: bool) -> Self {
        self.normalize_whitespace = normalize;
        self
    }

    /// Set whether to lowercase the query.
    #[must_use]
    pub const fn with_lowercase(mut self, lowercase: bool) -> Self {
        self.lowercase = lowercase;
        self
    }

    /// Set whether to remove punctuation.
    #[must_use]
    pub const fn with_remove_punctuation(mut self, remove: bool) -> Self {
        self.remove_punctuation = remove;
        self
    }

    /// Set whether to apply Unicode normalization.
    #[must_use]
    pub const fn with_unicode_normalize(mut self, normalize: bool) -> Self {
        self.unicode_normalize = normalize;
        self
    }
}

/// A preprocessed query with normalization applied and type classified.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PreprocessedQuery {
    /// Original query string.
    pub original: String,
    /// Normalized query string.
    pub normalized: String,
    /// Classified query type.
    pub query_type: QueryType,
    /// Whether the query was modified during preprocessing.
    pub was_modified: bool,
    /// Query tokens (split on whitespace).
    pub tokens: Vec<String>,
    /// Detected language (optional, for future use).
    pub language: Option<String>,
}

impl PreprocessedQuery {
    /// Create a new preprocessed query.
    #[must_use]
    pub fn new(original: String, normalized: String, query_type: QueryType) -> Self {
        let was_modified = original != normalized;
        let tokens = normalized.split_whitespace().map(String::from).collect();
        Self {
            original,
            normalized,
            query_type,
            was_modified,
            tokens,
            language: None,
        }
    }

    /// Get the number of tokens in the query.
    #[must_use]
    pub fn token_count(&self) -> usize {
        self.tokens.len()
    }
}

/// Query preprocessor that normalizes queries and classifies their types.
#[derive(Debug, Clone)]
pub struct QueryPreprocessor {
    config: QueryPreprocessorConfig,
}

impl QueryPreprocessor {
    /// Create a new query preprocessor with the given configuration.
    #[must_use]
    pub const fn new(config: QueryPreprocessorConfig) -> Self {
        Self { config }
    }

    /// Create a preprocessor with default configuration.
    #[must_use]
    pub fn with_defaults() -> Self {
        Self::new(QueryPreprocessorConfig::default())
    }

    /// Get the preprocessor configuration.
    #[must_use]
    pub const fn config(&self) -> &QueryPreprocessorConfig {
        &self.config
    }

    /// Preprocess a query: validate, normalize, and classify.
    ///
    /// # Errors
    ///
    /// Returns [`RetrievalError::InvalidRequest`] if:
    /// - The query is too short (after trimming whitespace)
    /// - The query is too long
    pub fn preprocess(&self, query: &str) -> Result<PreprocessedQuery> {
        // Trim leading/trailing whitespace first
        let trimmed = query.trim();

        // Validate query length
        if trimmed.len() < self.config.min_query_length {
            return Err(RetrievalError::invalid_request(format!(
                "Query too short: {} characters (minimum {})",
                trimmed.len(),
                self.config.min_query_length
            )));
        }

        if trimmed.len() > self.config.max_query_length {
            return Err(RetrievalError::invalid_request(format!(
                "Query too long: {} characters (maximum {})",
                trimmed.len(),
                self.config.max_query_length
            )));
        }

        // Apply normalizations
        let mut normalized = trimmed.to_string();

        // Unicode NFC normalization
        if self.config.unicode_normalize {
            normalized = normalized.nfc().collect::<String>();
        }

        // Normalize whitespace (collapse multiple spaces to single space)
        if self.config.normalize_whitespace {
            normalized = Self::collapse_whitespace(&normalized);
        }

        // Remove punctuation if configured
        if self.config.remove_punctuation {
            normalized = Self::remove_punctuation(&normalized);
        }

        // Lowercase if configured
        if self.config.lowercase {
            normalized = normalized.to_lowercase();
        }

        // Classify query type
        let query_type = self.classify_query_type(&normalized);

        Ok(PreprocessedQuery::new(
            query.to_string(),
            normalized,
            query_type,
        ))
    }

    /// Classify the type of a query based on its characteristics.
    ///
    /// Classification rules:
    /// - **Simple**: 1-2 words, no question marks
    /// - **Question**: Contains question mark or question words (who, what, where, when, why, how)
    /// - **Semantic**: Contains quotes or specific phrase markers
    /// - **Hybrid**: Default fallback
    #[must_use]
    pub fn classify_query_type(&self, query: &str) -> QueryType {
        let lower = query.to_lowercase();
        let word_count = query.split_whitespace().count();

        // Check for question indicators
        let has_question_mark = query.contains('?');
        let question_words = [
            "who", "what", "where", "when", "why", "how", "which", "whose",
        ];
        let starts_with_question_word = question_words.iter().any(|word| {
            lower.starts_with(word)
                && (lower.len() == word.len()
                    || lower[word.len()..].starts_with(|c: char| c.is_whitespace()))
        });
        let contains_question_word = question_words.iter().any(|word| lower.contains(word));

        // Check for semantic indicators (quoted phrases)
        let has_quotes = query.contains('"') || query.contains('\'');

        // Classification logic
        if has_quotes {
            // Queries with quotes are typically seeking exact matches or specific phrases
            QueryType::Semantic
        } else if has_question_mark || starts_with_question_word {
            // Explicit questions
            QueryType::Question
        } else if word_count <= 2 && !contains_question_word {
            // Short queries without question words are simple lookups
            QueryType::Simple
        } else {
            // Default to hybrid for complex queries
            QueryType::Hybrid
        }
    }

    /// Collapse multiple whitespace characters into single spaces.
    fn collapse_whitespace(s: &str) -> String {
        let mut result = String::with_capacity(s.len());
        let mut prev_was_whitespace = false;

        for c in s.chars() {
            if c.is_whitespace() {
                if !prev_was_whitespace {
                    result.push(' ');
                }
                prev_was_whitespace = true;
            } else {
                result.push(c);
                prev_was_whitespace = false;
            }
        }

        result.trim().to_string()
    }

    /// Remove punctuation from a string.
    fn remove_punctuation(s: &str) -> String {
        s.chars().filter(|c| !c.is_ascii_punctuation()).collect()
    }
}

impl Default for QueryPreprocessor {
    fn default() -> Self {
        Self::with_defaults()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        let config = QueryPreprocessorConfig::default();
        assert_eq!(config.min_query_length, 2);
        assert_eq!(config.max_query_length, 1000);
        assert!(config.normalize_whitespace);
        assert!(config.lowercase);
        assert!(!config.remove_punctuation);
        assert!(config.unicode_normalize);
    }

    #[test]
    fn test_config_builder() {
        let config = QueryPreprocessorConfig::new()
            .with_min_query_length(5)
            .with_max_query_length(500)
            .with_normalize_whitespace(false)
            .with_lowercase(false)
            .with_remove_punctuation(true)
            .with_unicode_normalize(false);

        assert_eq!(config.min_query_length, 5);
        assert_eq!(config.max_query_length, 500);
        assert!(!config.normalize_whitespace);
        assert!(!config.lowercase);
        assert!(config.remove_punctuation);
        assert!(!config.unicode_normalize);
    }

    #[test]
    fn test_preprocess_basic() {
        let preprocessor = QueryPreprocessor::with_defaults();
        let result = preprocessor.preprocess("Hello World").unwrap();

        assert_eq!(result.original, "Hello World");
        assert_eq!(result.normalized, "hello world");
        assert!(result.was_modified);
        assert_eq!(result.tokens, vec!["hello", "world"]);
    }

    #[test]
    fn test_preprocess_whitespace_normalization() {
        let preprocessor = QueryPreprocessor::with_defaults();
        let result = preprocessor
            .preprocess("  multiple   spaces   here  ")
            .unwrap();

        assert_eq!(result.normalized, "multiple spaces here");
        assert!(result.was_modified);
    }

    #[test]
    fn test_preprocess_query_too_short() {
        let preprocessor = QueryPreprocessor::with_defaults();
        let result = preprocessor.preprocess("a");

        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(matches!(err, RetrievalError::InvalidRequest(_)));
        assert!(err.to_string().contains("too short"));
    }

    #[test]
    fn test_preprocess_query_too_long() {
        let config = QueryPreprocessorConfig::default().with_max_query_length(10);
        let preprocessor = QueryPreprocessor::new(config);
        let result = preprocessor.preprocess("this is a very long query");

        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(matches!(err, RetrievalError::InvalidRequest(_)));
        assert!(err.to_string().contains("too long"));
    }

    #[test]
    fn test_preprocess_preserves_original() {
        let preprocessor = QueryPreprocessor::with_defaults();
        let result = preprocessor.preprocess("  HELLO  ").unwrap();

        assert_eq!(result.original, "  HELLO  ");
        assert_eq!(result.normalized, "hello");
    }

    #[test]
    fn test_classify_simple_query() {
        let preprocessor = QueryPreprocessor::with_defaults();

        // Single word
        assert_eq!(preprocessor.classify_query_type("rust"), QueryType::Simple);

        // Two words without question context
        assert_eq!(
            preprocessor.classify_query_type("rust programming"),
            QueryType::Simple
        );
    }

    #[test]
    fn test_classify_question_query() {
        let preprocessor = QueryPreprocessor::with_defaults();

        // Question mark
        assert_eq!(
            preprocessor.classify_query_type("what is rust?"),
            QueryType::Question
        );

        // Starts with question word
        assert_eq!(
            preprocessor.classify_query_type("what is rust"),
            QueryType::Question
        );
        assert_eq!(
            preprocessor.classify_query_type("how does rust work"),
            QueryType::Question
        );
        assert_eq!(
            preprocessor.classify_query_type("where can i learn rust"),
            QueryType::Question
        );
        assert_eq!(
            preprocessor.classify_query_type("when was rust released"),
            QueryType::Question
        );
        assert_eq!(
            preprocessor.classify_query_type("why use rust"),
            QueryType::Question
        );
        assert_eq!(
            preprocessor.classify_query_type("who created rust"),
            QueryType::Question
        );
        assert_eq!(
            preprocessor.classify_query_type("which rust version"),
            QueryType::Question
        );
    }

    #[test]
    fn test_classify_semantic_query() {
        let preprocessor = QueryPreprocessor::with_defaults();

        // Double quotes
        assert_eq!(
            preprocessor.classify_query_type("\"exact phrase\" search"),
            QueryType::Semantic
        );

        // Single quotes
        assert_eq!(
            preprocessor.classify_query_type("find 'specific term'"),
            QueryType::Semantic
        );
    }

    #[test]
    fn test_classify_hybrid_query() {
        let preprocessor = QueryPreprocessor::with_defaults();

        // Longer queries without question words
        assert_eq!(
            preprocessor.classify_query_type("rust programming language features benefits"),
            QueryType::Hybrid
        );
    }

    #[test]
    fn test_collapse_whitespace() {
        assert_eq!(
            QueryPreprocessor::collapse_whitespace("  hello   world  "),
            "hello world"
        );
        assert_eq!(QueryPreprocessor::collapse_whitespace("a\t\nb"), "a b");
        assert_eq!(
            QueryPreprocessor::collapse_whitespace("no  extra  spaces"),
            "no extra spaces"
        );
    }

    #[test]
    fn test_remove_punctuation() {
        assert_eq!(
            QueryPreprocessor::remove_punctuation("hello, world!"),
            "hello world"
        );
        assert_eq!(
            QueryPreprocessor::remove_punctuation("what's up?"),
            "whats up"
        );
    }

    #[test]
    fn test_preprocess_with_punctuation_removal() {
        let config = QueryPreprocessorConfig::default().with_remove_punctuation(true);
        let preprocessor = QueryPreprocessor::new(config);

        let result = preprocessor.preprocess("Hello, World!").unwrap();
        assert_eq!(result.normalized, "hello world");
    }

    #[test]
    fn test_preprocess_without_lowercase() {
        let config = QueryPreprocessorConfig::default().with_lowercase(false);
        let preprocessor = QueryPreprocessor::new(config);

        let result = preprocessor.preprocess("Hello World").unwrap();
        assert_eq!(result.normalized, "Hello World");
        assert!(!result.was_modified);
    }

    #[test]
    fn test_unicode_normalization() {
        let preprocessor = QueryPreprocessor::with_defaults();

        // Test with composed vs decomposed Unicode
        // "e\u{0301}" (e + combining acute) should normalize to "\u{00e9}" (e with acute)
        let decomposed = "caf\u{0065}\u{0301}"; // cafe with combining acute
        let result = preprocessor.preprocess(decomposed).unwrap();

        // After NFC normalization, the string should be normalized
        assert!(result.normalized.chars().count() <= decomposed.chars().count());
    }

    #[test]
    fn test_token_count() {
        let preprocessor = QueryPreprocessor::with_defaults();

        let result = preprocessor.preprocess("one two three").unwrap();
        assert_eq!(result.token_count(), 3);

        let result = preprocessor.preprocess("single").unwrap();
        assert_eq!(result.token_count(), 1);
    }

    #[test]
    fn test_preprocessed_query_new() {
        let query = PreprocessedQuery::new(
            "Original".to_string(),
            "original".to_string(),
            QueryType::Simple,
        );

        assert_eq!(query.original, "Original");
        assert_eq!(query.normalized, "original");
        assert_eq!(query.query_type, QueryType::Simple);
        assert!(query.was_modified);
        assert_eq!(query.tokens, vec!["original"]);
        assert!(query.language.is_none());
    }

    #[test]
    fn test_minimum_length_edge_case() {
        let config = QueryPreprocessorConfig::default().with_min_query_length(2);
        let preprocessor = QueryPreprocessor::new(config);

        // Exactly minimum length should work
        let result = preprocessor.preprocess("ab");
        assert!(result.is_ok());

        // One below minimum should fail
        let result = preprocessor.preprocess("a");
        assert!(result.is_err());
    }

    #[test]
    fn test_question_word_boundary() {
        let preprocessor = QueryPreprocessor::with_defaults();

        // "what" at beginning should be a question
        assert_eq!(
            preprocessor.classify_query_type("what is this"),
            QueryType::Question
        );

        // "whatever" should not trigger question classification
        // (word doesn't start cleanly with question word followed by space)
        assert_eq!(
            preprocessor.classify_query_type("whatever this is"),
            QueryType::Hybrid
        );
    }

    #[test]
    fn test_serialization() {
        let config = QueryPreprocessorConfig::default();
        let json = serde_json::to_string(&config).unwrap();
        let deserialized: QueryPreprocessorConfig = serde_json::from_str(&json).unwrap();

        assert_eq!(config.min_query_length, deserialized.min_query_length);
        assert_eq!(config.max_query_length, deserialized.max_query_length);
        assert_eq!(config.lowercase, deserialized.lowercase);
    }

    #[test]
    fn test_preprocessed_query_serialization() {
        let query = PreprocessedQuery::new(
            "Test Query".to_string(),
            "test query".to_string(),
            QueryType::Question,
        );

        let json = serde_json::to_string(&query).unwrap();
        let deserialized: PreprocessedQuery = serde_json::from_str(&json).unwrap();

        assert_eq!(query.original, deserialized.original);
        assert_eq!(query.normalized, deserialized.normalized);
        assert_eq!(query.query_type, deserialized.query_type);
        assert_eq!(query.was_modified, deserialized.was_modified);
        assert_eq!(query.tokens, deserialized.tokens);
    }
}
