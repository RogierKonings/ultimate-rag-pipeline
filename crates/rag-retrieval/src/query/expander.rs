//! Query expansion with synonym support and optional LLM-based expansion.
//!
//! This module provides the [`QueryExpander`] for expanding user queries
//! to improve retrieval recall by generating related query variations.
//!
//! # Features
//!
//! - **Synonym expansion**: Uses an in-memory synonym database to generate
//!   query variations by replacing words with their synonyms
//! - **LLM expansion** (optional): Can call an LLM gateway for more sophisticated
//!   query expansions (stub implementation for future integration)
//! - **Configurable limits**: Control the maximum number of expansions
//!
//! # Example
//!
//! ```
//! use rag_retrieval::query::{QueryExpander, QueryExpanderConfig};
//!
//! let config = QueryExpanderConfig::default();
//! let expander = QueryExpander::new(config).expect("Failed to create expander");
//!
//! // Expand a query using synonyms
//! let expansions = expander.expand_with_synonyms("find the best documents");
//! assert!(expansions.len() > 1);
//! ```

use std::collections::HashMap;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tracing::{debug, warn};

use crate::error::{RetrievalError, Result};

/// Configuration for query expansion.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct QueryExpanderConfig {
    /// Whether query expansion is enabled.
    pub enabled: bool,
    /// Maximum number of query expansions to generate.
    pub max_expansions: usize,
    /// Whether to include the original query in the results.
    pub include_original: bool,
    /// Whether to use synonym-based expansion.
    pub use_synonyms: bool,
    /// Whether to use LLM-based expansion.
    pub use_llm: bool,
    /// URL of the LLM gateway for LLM-based expansion.
    pub llm_gateway_url: Option<String>,
    /// Timeout for LLM requests in milliseconds.
    pub llm_timeout_ms: u64,
}

impl Default for QueryExpanderConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            max_expansions: 5,
            include_original: true,
            use_synonyms: true,
            use_llm: false,
            llm_gateway_url: None,
            llm_timeout_ms: 3000,
        }
    }
}

impl QueryExpanderConfig {
    /// Create a new configuration with default settings.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Set whether expansion is enabled.
    #[must_use]
    pub const fn with_enabled(mut self, enabled: bool) -> Self {
        self.enabled = enabled;
        self
    }

    /// Set the maximum number of expansions.
    #[must_use]
    pub const fn with_max_expansions(mut self, max: usize) -> Self {
        self.max_expansions = max;
        self
    }

    /// Set whether to include the original query.
    #[must_use]
    pub const fn with_include_original(mut self, include: bool) -> Self {
        self.include_original = include;
        self
    }

    /// Set whether to use synonym expansion.
    #[must_use]
    pub const fn with_use_synonyms(mut self, use_synonyms: bool) -> Self {
        self.use_synonyms = use_synonyms;
        self
    }

    /// Set whether to use LLM expansion.
    #[must_use]
    pub const fn with_use_llm(mut self, use_llm: bool) -> Self {
        self.use_llm = use_llm;
        self
    }

    /// Set the LLM gateway URL.
    #[must_use]
    pub fn with_llm_gateway_url(mut self, url: impl Into<String>) -> Self {
        self.llm_gateway_url = Some(url.into());
        self
    }

    /// Set the LLM timeout in milliseconds.
    #[must_use]
    pub const fn with_llm_timeout_ms(mut self, timeout_ms: u64) -> Self {
        self.llm_timeout_ms = timeout_ms;
        self
    }
}

/// Query expander that generates query variations for improved retrieval.
#[derive(Debug, Clone)]
pub struct QueryExpander {
    /// Configuration for the expander.
    config: QueryExpanderConfig,
    /// In-memory synonym database.
    synonyms: HashMap<String, Vec<String>>,
    /// HTTP client for LLM calls.
    http_client: Option<reqwest::Client>,
}

impl QueryExpander {
    /// Create a new query expander with the given configuration.
    ///
    /// This initializes the expander with a built-in synonym database
    /// and optionally creates an HTTP client for LLM calls.
    ///
    /// # Errors
    ///
    /// Returns an error if LLM is enabled and the HTTP client cannot be created.
    pub fn new(config: QueryExpanderConfig) -> Result<Self> {
        let http_client = if config.use_llm {
            Some(
                reqwest::Client::builder()
                    .timeout(Duration::from_millis(config.llm_timeout_ms))
                    .build()
                    .map_err(|e| RetrievalError::config(format!("Failed to create HTTP client: {e}")))?,
            )
        } else {
            None
        };

        Ok(Self {
            config,
            synonyms: Self::default_synonyms(),
            http_client,
        })
    }

    /// Create a query expander with default configuration.
    ///
    /// # Errors
    ///
    /// Returns an error if the HTTP client cannot be created.
    pub fn with_defaults() -> Result<Self> {
        Self::new(QueryExpanderConfig::default())
    }

    /// Add custom synonyms to the expander.
    ///
    /// This merges the provided synonyms with the existing database.
    /// If a word already exists, the new synonyms are appended.
    #[must_use]
    pub fn with_synonyms(mut self, synonyms: HashMap<String, Vec<String>>) -> Self {
        for (word, syns) in synonyms {
            self.synonyms
                .entry(word.to_lowercase())
                .or_default()
                .extend(syns.into_iter().map(|s| s.to_lowercase()));
        }
        self
    }

    /// Get the expander configuration.
    #[must_use]
    pub const fn config(&self) -> &QueryExpanderConfig {
        &self.config
    }

    /// Get the synonym database.
    #[must_use]
    pub fn synonyms(&self) -> &HashMap<String, Vec<String>> {
        &self.synonyms
    }

    /// Expand a query into multiple variations.
    ///
    /// This method combines synonym-based and LLM-based expansion based on
    /// the configuration. Results are deduplicated and limited to `max_expansions`.
    ///
    /// # Arguments
    ///
    /// * `query` - The original query string to expand
    ///
    /// # Returns
    ///
    /// A vector of query variations, starting with the original query
    /// if `include_original` is true.
    ///
    /// # Errors
    ///
    /// Returns `RetrievalError::Llm` if LLM expansion is enabled and fails.
    pub async fn expand(&self, query: &str) -> Result<Vec<String>> {
        if !self.config.enabled {
            return Ok(vec![query.to_string()]);
        }

        let mut expansions = Vec::new();

        // Include original query first if configured
        if self.config.include_original {
            expansions.push(query.to_string());
        }

        // Add synonym-based expansions
        if self.config.use_synonyms {
            let synonym_expansions = self.expand_with_synonyms(query);
            for expansion in synonym_expansions {
                if expansion != query && !expansions.contains(&expansion) {
                    expansions.push(expansion);
                }
            }
        }

        // Add LLM-based expansions
        if self.config.use_llm {
            match self.expand_with_llm(query).await {
                Ok(llm_expansions) => {
                    for expansion in llm_expansions {
                        if !expansions.contains(&expansion) {
                            expansions.push(expansion);
                        }
                    }
                }
                Err(e) => {
                    warn!("LLM expansion failed, continuing with synonym expansion only: {e}");
                }
            }
        }

        // Deduplicate and limit results
        expansions.truncate(self.config.max_expansions);

        debug!(
            "Expanded query '{}' into {} variations",
            query,
            expansions.len()
        );

        Ok(expansions)
    }

    /// Expand a query using only synonym replacement.
    ///
    /// This method generates query variations by replacing words with their
    /// synonyms from the synonym database.
    ///
    /// # Arguments
    ///
    /// * `query` - The query string to expand
    ///
    /// # Returns
    ///
    /// A vector of query variations. Always includes at least the original query.
    #[must_use]
    pub fn expand_with_synonyms(&self, query: &str) -> Vec<String> {
        let mut expansions = vec![query.to_string()];

        let words: Vec<&str> = query.split_whitespace().collect();

        // For each word in the query, try to find synonyms
        for (i, word) in words.iter().enumerate() {
            let word_lower = word.to_lowercase();

            if let Some(syns) = self.synonyms.get(&word_lower) {
                // Generate expansions by replacing this word with each synonym
                for syn in syns {
                    let mut new_words = words.clone();
                    new_words[i] = syn.as_str();
                    let expansion = new_words.join(" ");

                    if !expansions.contains(&expansion) {
                        expansions.push(expansion);
                    }
                }
            }
        }

        expansions
    }

    /// Expand a query using LLM-based generation.
    ///
    /// This method calls an LLM gateway to generate semantically related
    /// query variations.
    ///
    /// # Arguments
    ///
    /// * `query` - The query string to expand
    ///
    /// # Returns
    ///
    /// A vector of LLM-generated query variations.
    ///
    /// # Errors
    ///
    /// Returns `RetrievalError::Llm` if the LLM request fails.
    /// Returns `RetrievalError::Config` if LLM is not configured.
    ///
    /// # Note
    ///
    /// This is currently a stub implementation. Full LLM integration
    /// should be implemented based on the LLM gateway API specification.
    #[allow(clippy::unused_async)] // Will use await when LLM call is implemented
    pub async fn expand_with_llm(&self, query: &str) -> Result<Vec<String>> {
        let Some(ref _gateway_url) = self.config.llm_gateway_url else {
            return Err(RetrievalError::config(
                "LLM gateway URL not configured for query expansion",
            ));
        };

        let Some(ref _client) = self.http_client else {
            return Err(RetrievalError::config(
                "HTTP client not initialized for LLM expansion",
            ));
        };

        // TODO: Implement actual LLM call to generate query expansions
        // This should:
        // 1. Send a request to the LLM gateway with a prompt like:
        //    "Generate 3 alternative search queries for: {query}"
        // 2. Parse the response to extract the generated queries
        // 3. Return the list of expansions
        //
        // For now, return a stub response indicating LLM expansion is not yet implemented
        warn!(
            "LLM-based query expansion is not yet implemented. Query: '{}'",
            query
        );

        Ok(vec![])
    }

    /// Create the default synonym database.
    fn default_synonyms() -> HashMap<String, Vec<String>> {
        HashMap::from([
            // Search/retrieval verbs
            (
                "find".to_string(),
                vec![
                    "search".to_string(),
                    "locate".to_string(),
                    "discover".to_string(),
                ],
            ),
            (
                "search".to_string(),
                vec![
                    "find".to_string(),
                    "look for".to_string(),
                    "query".to_string(),
                ],
            ),
            (
                "get".to_string(),
                vec![
                    "retrieve".to_string(),
                    "fetch".to_string(),
                    "obtain".to_string(),
                ],
            ),
            // Question words
            (
                "how".to_string(),
                vec!["what way".to_string(), "in what manner".to_string()],
            ),
            (
                "what".to_string(),
                vec!["which".to_string()],
            ),
            // Quality adjectives
            (
                "best".to_string(),
                vec![
                    "top".to_string(),
                    "optimal".to_string(),
                    "ideal".to_string(),
                ],
            ),
            (
                "good".to_string(),
                vec![
                    "great".to_string(),
                    "excellent".to_string(),
                    "quality".to_string(),
                ],
            ),
            // CRUD operations
            (
                "create".to_string(),
                vec![
                    "make".to_string(),
                    "build".to_string(),
                    "generate".to_string(),
                ],
            ),
            (
                "delete".to_string(),
                vec![
                    "remove".to_string(),
                    "erase".to_string(),
                    "drop".to_string(),
                ],
            ),
            (
                "update".to_string(),
                vec![
                    "modify".to_string(),
                    "change".to_string(),
                    "edit".to_string(),
                ],
            ),
            (
                "add".to_string(),
                vec![
                    "insert".to_string(),
                    "include".to_string(),
                    "append".to_string(),
                ],
            ),
            // Technical terms
            (
                "error".to_string(),
                vec![
                    "issue".to_string(),
                    "problem".to_string(),
                    "bug".to_string(),
                ],
            ),
            (
                "fix".to_string(),
                vec![
                    "solve".to_string(),
                    "resolve".to_string(),
                    "repair".to_string(),
                ],
            ),
            (
                "configure".to_string(),
                vec![
                    "setup".to_string(),
                    "set up".to_string(),
                    "initialize".to_string(),
                ],
            ),
            (
                "install".to_string(),
                vec![
                    "setup".to_string(),
                    "deploy".to_string(),
                ],
            ),
            // Common nouns
            (
                "document".to_string(),
                vec![
                    "file".to_string(),
                    "doc".to_string(),
                    "record".to_string(),
                ],
            ),
            (
                "list".to_string(),
                vec![
                    "array".to_string(),
                    "collection".to_string(),
                ],
            ),
            (
                "function".to_string(),
                vec![
                    "method".to_string(),
                    "procedure".to_string(),
                ],
            ),
        ])
    }
}


#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        let config = QueryExpanderConfig::default();
        assert!(config.enabled);
        assert_eq!(config.max_expansions, 5);
        assert!(config.include_original);
        assert!(config.use_synonyms);
        assert!(!config.use_llm);
        assert!(config.llm_gateway_url.is_none());
        assert_eq!(config.llm_timeout_ms, 3000);
    }

    #[test]
    fn test_config_builder() {
        let config = QueryExpanderConfig::new()
            .with_enabled(false)
            .with_max_expansions(10)
            .with_include_original(false)
            .with_use_synonyms(false)
            .with_use_llm(true)
            .with_llm_gateway_url("http://localhost:8004")
            .with_llm_timeout_ms(5000);

        assert!(!config.enabled);
        assert_eq!(config.max_expansions, 10);
        assert!(!config.include_original);
        assert!(!config.use_synonyms);
        assert!(config.use_llm);
        assert_eq!(
            config.llm_gateway_url,
            Some("http://localhost:8004".to_string())
        );
        assert_eq!(config.llm_timeout_ms, 5000);
    }

    #[test]
    fn test_expand_with_synonyms_basic() {
        let expander = QueryExpander::with_defaults().unwrap();
        let expansions = expander.expand_with_synonyms("find the best documents");

        // Should include original
        assert!(expansions.contains(&"find the best documents".to_string()));

        // Should include synonym expansions
        assert!(
            expansions.iter().any(|e| e.contains("search"))
                || expansions.iter().any(|e| e.contains("locate"))
        );
        assert!(
            expansions.iter().any(|e| e.contains("top"))
                || expansions.iter().any(|e| e.contains("optimal"))
        );
    }

    #[test]
    fn test_expand_with_synonyms_no_matches() {
        let expander = QueryExpander::with_defaults().unwrap();
        let expansions = expander.expand_with_synonyms("xyz abc");

        // Should only contain the original
        assert_eq!(expansions.len(), 1);
        assert_eq!(expansions[0], "xyz abc");
    }

    #[test]
    fn test_expand_with_synonyms_multiple_words() {
        let expander = QueryExpander::with_defaults().unwrap();
        let expansions = expander.expand_with_synonyms("create document");

        // Should include original
        assert!(expansions.contains(&"create document".to_string()));

        // Should include expansions for "create" -> make, build, generate
        assert!(expansions.iter().any(|e| e.contains("make")));
        assert!(expansions.iter().any(|e| e.contains("build")));
        assert!(expansions.iter().any(|e| e.contains("generate")));

        // Should include expansions for "document" -> file, doc, record
        assert!(expansions.iter().any(|e| e.contains("file")));
        assert!(expansions.contains(&"create doc".to_string()));
        assert!(expansions.iter().any(|e| e.contains("record")));
    }

    #[test]
    fn test_expand_with_synonyms_case_insensitive() {
        let expander = QueryExpander::with_defaults().unwrap();
        let expansions = expander.expand_with_synonyms("FIND something");

        // Should match "find" synonyms even though input is uppercase
        assert!(expansions.len() > 1);
    }

    #[test]
    fn test_custom_synonyms() {
        let mut custom_synonyms = HashMap::new();
        custom_synonyms.insert(
            "custom".to_string(),
            vec!["specialized".to_string(), "unique".to_string()],
        );

        let expander = QueryExpander::with_defaults().unwrap().with_synonyms(custom_synonyms);

        let expansions = expander.expand_with_synonyms("custom word");

        assert!(expansions.contains(&"custom word".to_string()));
        assert!(expansions.contains(&"specialized word".to_string()));
        assert!(expansions.contains(&"unique word".to_string()));
    }

    #[test]
    fn test_custom_synonyms_merge() {
        let mut custom_synonyms = HashMap::new();
        // Add to existing synonyms for "find"
        custom_synonyms.insert("find".to_string(), vec!["seek".to_string()]);

        let expander = QueryExpander::with_defaults().unwrap().with_synonyms(custom_synonyms);

        // Check that "seek" was added to the synonyms for "find"
        let find_synonyms = expander.synonyms().get("find").unwrap();
        assert!(find_synonyms.contains(&"seek".to_string()));

        // Original synonyms should still be there
        assert!(find_synonyms.contains(&"search".to_string()));
    }

    #[tokio::test]
    async fn test_expand_disabled() {
        let config = QueryExpanderConfig::default().with_enabled(false);
        let expander = QueryExpander::new(config).unwrap();

        let expansions = expander.expand("find the best").await.unwrap();

        // Should only return the original query
        assert_eq!(expansions.len(), 1);
        assert_eq!(expansions[0], "find the best");
    }

    #[tokio::test]
    async fn test_expand_without_original() {
        let config = QueryExpanderConfig::default().with_include_original(false);
        let expander = QueryExpander::new(config).unwrap();

        let expansions = expander.expand("find something").await.unwrap();

        // Should not include the exact original query as the first element
        // (though it might appear if no synonyms were found)
        if expansions.len() > 1 {
            // If we have expansions, check that they are different from original
            assert!(expansions.iter().any(|e| e != "find something"));
        }
    }

    #[tokio::test]
    async fn test_expand_max_expansions() {
        let config = QueryExpanderConfig::default().with_max_expansions(2);
        let expander = QueryExpander::new(config).unwrap();

        let expansions = expander.expand("find the best documents").await.unwrap();

        // Should be limited to max_expansions
        assert!(expansions.len() <= 2);
    }

    #[tokio::test]
    async fn test_expand_deduplication() {
        let expander = QueryExpander::with_defaults().unwrap();
        let expansions = expander.expand("find documents").await.unwrap();

        // Check no duplicates
        let unique: std::collections::HashSet<_> = expansions.iter().collect();
        assert_eq!(unique.len(), expansions.len());
    }

    #[tokio::test]
    async fn test_expand_with_llm_not_configured() {
        let config = QueryExpanderConfig::default().with_use_llm(true);
        // Note: llm_gateway_url is not set
        let expander = QueryExpander::new(config).unwrap();

        // LLM expansion should fail gracefully (warning logged, but overall expansion succeeds)
        let expansions = expander.expand("test query").await.unwrap();

        // Should still get at least the original query
        assert!(expansions.contains(&"test query".to_string()));
    }

    #[test]
    fn test_expander_accessors() {
        let config = QueryExpanderConfig::default().with_max_expansions(3);
        let expander = QueryExpander::new(config).unwrap();

        assert_eq!(expander.config().max_expansions, 3);
        assert!(!expander.synonyms().is_empty());
    }

    #[test]
    fn test_serialization_config() {
        let config = QueryExpanderConfig::default()
            .with_max_expansions(10)
            .with_llm_gateway_url("http://test.com");

        let json = serde_json::to_string(&config).unwrap();
        let deserialized: QueryExpanderConfig = serde_json::from_str(&json).unwrap();

        assert_eq!(config.max_expansions, deserialized.max_expansions);
        assert_eq!(config.llm_gateway_url, deserialized.llm_gateway_url);
    }

    #[test]
    fn test_default_synonyms_coverage() {
        let synonyms = QueryExpander::default_synonyms();

        // Verify key entries exist
        assert!(synonyms.contains_key("find"));
        assert!(synonyms.contains_key("search"));
        assert!(synonyms.contains_key("create"));
        assert!(synonyms.contains_key("delete"));
        assert!(synonyms.contains_key("update"));
        assert!(synonyms.contains_key("best"));
        assert!(synonyms.contains_key("error"));
        assert!(synonyms.contains_key("fix"));
    }

    #[test]
    fn test_expander_with_defaults() {
        let expander = QueryExpander::with_defaults().unwrap();
        assert!(expander.config().enabled);
        assert!(!expander.synonyms().is_empty());
    }
}
