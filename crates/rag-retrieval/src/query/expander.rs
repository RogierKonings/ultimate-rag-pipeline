//! Query expansion with synonym support and LLM-based expansion.
//!
//! This module provides the [`QueryExpander`] for expanding user queries
//! to improve retrieval recall by generating related query variations.
//!
//! # Features
//!
//! - **Synonym expansion**: Uses an in-memory synonym database to generate
//!   query variations by replacing words with their synonyms
//! - **LLM expansion** (optional): Calls an LLM gateway (OpenAI-compatible API)
//!   for more sophisticated query expansions
//! - **Configurable limits**: Control the maximum number of expansions
//! - **Graceful fallback**: LLM failures degrade to synonym-only expansion
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
use tracing::{debug, instrument, warn};

use crate::error::{Result, RetrievalError};

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

    /// Load configuration from environment variables.
    ///
    /// Environment variables:
    /// - `EXPANSION_ENABLED`: Whether expansion is enabled (default: true)
    /// - `EXPANSION_MAX`: Maximum number of expansions (default: 5)
    /// - `EXPANSION_USE_SYNONYMS`: Use synonym expansion (default: true)
    /// - `EXPANSION_USE_LLM`: Use LLM expansion (default: false)
    /// - `LLM_GATEWAY_URL`: LLM gateway URL (default: none)
    /// - `RETRIEVAL_EXPANSION_TIMEOUT_MS`: Timeout in milliseconds (default: 5000)
    #[must_use]
    pub fn from_env() -> Self {
        let mut config = Self::default();

        if let Ok(val) = std::env::var("EXPANSION_ENABLED") {
            config.enabled = val.to_lowercase() == "true" || val == "1";
        }

        if let Ok(val) = std::env::var("EXPANSION_MAX") {
            if let Ok(v) = val.parse() {
                config.max_expansions = v;
            }
        }

        if let Ok(val) = std::env::var("EXPANSION_USE_SYNONYMS") {
            config.use_synonyms = val.to_lowercase() == "true" || val == "1";
        }

        if let Ok(val) = std::env::var("EXPANSION_USE_LLM") {
            config.use_llm = val.to_lowercase() == "true" || val == "1";
        }

        if let Ok(url) = std::env::var("LLM_GATEWAY_URL") {
            config.llm_gateway_url = Some(url);
        }

        if let Ok(val) = std::env::var("RETRIEVAL_EXPANSION_TIMEOUT_MS") {
            if let Ok(v) = val.parse() {
                config.llm_timeout_ms = v;
            }
        }

        config
    }

    /// Get the chat completions API endpoint URL.
    #[must_use]
    pub fn completions_endpoint(&self) -> Option<String> {
        self.llm_gateway_url
            .as_ref()
            .map(|url| format!("{}/v1/chat/completions", url.trim_end_matches('/')))
    }
}

/// Default prompt for LLM-based query expansion.
const EXPANSION_PROMPT_TEMPLATE: &str = "Generate {count} alternative search queries for the following query. Each alternative should capture the same intent but use different wording. Return ONLY the queries, one per line, without numbering or bullet points.\n\nQuery: {query}\n\nAlternative queries:";

/// Request body for the OpenAI-compatible chat completions API.
#[derive(Debug, Serialize)]
struct LlmExpansionRequest {
    /// Model identifier.
    model: String,
    /// Chat messages.
    messages: Vec<LlmMessage>,
    /// Maximum tokens to generate.
    max_tokens: usize,
    /// Temperature for generation (low for consistent expansions).
    temperature: f32,
}

/// A chat message for the LLM request.
#[derive(Debug, Serialize)]
struct LlmMessage {
    /// Role of the message sender.
    role: String,
    /// Content of the message.
    content: String,
}

/// Response from the OpenAI-compatible chat completions API.
#[derive(Debug, Deserialize)]
struct LlmExpansionResponse {
    /// List of completion choices.
    choices: Vec<LlmChoice>,
}

/// A single choice from the LLM response.
#[derive(Debug, Deserialize)]
struct LlmChoice {
    /// The generated message.
    message: LlmResponseMessage,
}

/// The generated message content.
#[derive(Debug, Deserialize)]
struct LlmResponseMessage {
    /// The content of the generated message.
    content: String,
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
                    .map_err(|e| {
                        RetrievalError::config(format!("Failed to create HTTP client: {e}"))
                    })?,
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
    /// This method calls an LLM gateway (OpenAI-compatible chat completions API)
    /// to generate semantically related query variations. The LLM is prompted to
    /// produce alternative phrasings that capture the same search intent.
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
    /// Returns `RetrievalError::Config` if LLM is not configured.
    /// Returns `RetrievalError::Llm` if the LLM request fails.
    /// Returns `RetrievalError::Timeout` if the request times out.
    #[instrument(skip(self), fields(query_len = query.len()))]
    pub async fn expand_with_llm(&self, query: &str) -> Result<Vec<String>> {
        let Some(ref gateway_url) = self.config.llm_gateway_url else {
            return Err(RetrievalError::config(
                "LLM gateway URL not configured for query expansion",
            ));
        };

        let Some(ref client) = self.http_client else {
            return Err(RetrievalError::config(
                "HTTP client not initialized for LLM expansion",
            ));
        };

        let endpoint = format!("{}/v1/chat/completions", gateway_url.trim_end_matches('/'));

        // Request max_expansions - 1 alternatives (original query is counted separately)
        let num_alternatives = self.config.max_expansions.saturating_sub(1).max(1);

        let prompt = EXPANSION_PROMPT_TEMPLATE
            .replace("{count}", &num_alternatives.to_string())
            .replace("{query}", query);

        let request = LlmExpansionRequest {
            model: "llama3.2".to_string(),
            messages: vec![LlmMessage {
                role: "user".to_string(),
                content: prompt,
            }],
            max_tokens: 256,
            temperature: 0.3, // Low temperature for consistent expansions
        };

        debug!(
            endpoint = %endpoint,
            num_alternatives,
            "Sending LLM expansion request"
        );

        let response = client
            .post(&endpoint)
            .json(&request)
            .send()
            .await
            .map_err(|e| {
                if e.is_timeout() {
                    RetrievalError::timeout(format!(
                        "LLM expansion request timed out after {}ms",
                        self.config.llm_timeout_ms
                    ))
                } else if e.is_connect() {
                    RetrievalError::llm(format!(
                        "Failed to connect to LLM gateway at {gateway_url}: {e}"
                    ))
                } else {
                    RetrievalError::llm(format!("LLM expansion request failed: {e}"))
                }
            })?;

        let status = response.status();
        if !status.is_success() {
            let error_text = response
                .text()
                .await
                .unwrap_or_else(|_| "Unknown error".to_string());
            return Err(RetrievalError::llm(format!(
                "LLM gateway returned {status}: {error_text}"
            )));
        }

        let llm_response: LlmExpansionResponse = response.json().await.map_err(|e| {
            RetrievalError::llm(format!("Failed to parse LLM expansion response: {e}"))
        })?;

        let raw_content = llm_response
            .choices
            .into_iter()
            .next()
            .map(|c| c.message.content)
            .unwrap_or_default();

        let expansions = parse_expansion_response(&raw_content, query);

        debug!(num_expansions = expansions.len(), "LLM expansion completed");

        Ok(expansions)
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
            ("what".to_string(), vec!["which".to_string()]),
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
                vec!["setup".to_string(), "deploy".to_string()],
            ),
            // Common nouns
            (
                "document".to_string(),
                vec!["file".to_string(), "doc".to_string(), "record".to_string()],
            ),
            (
                "list".to_string(),
                vec!["array".to_string(), "collection".to_string()],
            ),
            (
                "function".to_string(),
                vec!["method".to_string(), "procedure".to_string()],
            ),
        ])
    }
}

/// Parse the LLM response text into individual query expansions.
///
/// This function applies deterministic validation to the LLM output:
/// - Splits on newlines
/// - Strips numbering prefixes (e.g., "1.", "- ", "* ")
/// - Filters out empty lines and lines that are too short (< 3 chars)
/// - Filters out lines that are too long (> 500 chars)
/// - Deduplicates against the original query
fn parse_expansion_response(response_text: &str, original_query: &str) -> Vec<String> {
    let original_lower = original_query.trim().to_lowercase();

    response_text
        .lines()
        .map(|line| {
            // Strip common numbering/bullet prefixes
            let trimmed = line.trim();
            let stripped = trimmed
                .strip_prefix(|c: char| c.is_ascii_digit())
                .and_then(|s| s.strip_prefix('.'))
                .or_else(|| trimmed.strip_prefix('-'))
                .or_else(|| trimmed.strip_prefix('*'))
                .or_else(|| trimmed.strip_prefix(')'))
                .unwrap_or(trimmed)
                .trim()
                .to_string();
            stripped
        })
        .filter(|s| {
            // Must be at least 3 characters and at most 500 characters
            let len = s.len();
            len >= 3 && len <= 500
        })
        .filter(|s| {
            // Must not be identical to the original query (case-insensitive)
            s.trim().to_lowercase() != original_lower
        })
        .collect()
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

        let expander = QueryExpander::with_defaults()
            .unwrap()
            .with_synonyms(custom_synonyms);

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

        let expander = QueryExpander::with_defaults()
            .unwrap()
            .with_synonyms(custom_synonyms);

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

    // --- parse_expansion_response tests ---

    #[test]
    fn test_parse_expansion_response_basic() {
        let response = "How to configure a database\nSetting up database connection\nDatabase configuration guide";
        let expansions = parse_expansion_response(response, "database setup");

        assert_eq!(expansions.len(), 3);
        assert!(expansions.contains(&"How to configure a database".to_string()));
        assert!(expansions.contains(&"Setting up database connection".to_string()));
        assert!(expansions.contains(&"Database configuration guide".to_string()));
    }

    #[test]
    fn test_parse_expansion_response_with_numbering() {
        let response = "1. How to configure a database\n2. Setting up database connection\n3. Database configuration guide";
        let expansions = parse_expansion_response(response, "database setup");

        assert_eq!(expansions.len(), 3);
        assert!(expansions.contains(&"How to configure a database".to_string()));
    }

    #[test]
    fn test_parse_expansion_response_with_bullets() {
        let response = "- How to configure a database\n- Setting up database connection\n* Database configuration guide";
        let expansions = parse_expansion_response(response, "database setup");

        assert_eq!(expansions.len(), 3);
    }

    #[test]
    fn test_parse_expansion_response_filters_empty_lines() {
        let response = "How to configure\n\n\nSetting up connection\n  \nDatabase guide";
        let expansions = parse_expansion_response(response, "original query");

        // Empty lines are filtered (len < 3)
        assert_eq!(expansions.len(), 3);
    }

    #[test]
    fn test_parse_expansion_response_filters_too_short() {
        let response = "ab\nHow to configure a database\nxy";
        let expansions = parse_expansion_response(response, "original query");

        assert_eq!(expansions.len(), 1);
        assert_eq!(expansions[0], "How to configure a database");
    }

    #[test]
    fn test_parse_expansion_response_filters_duplicate_of_original() {
        let response = "database setup\nHow to set up a database\nDatabase Setup";
        let expansions = parse_expansion_response(response, "database setup");

        // "database setup" and "Database Setup" (case-insensitive) should be filtered
        assert_eq!(expansions.len(), 1);
        assert_eq!(expansions[0], "How to set up a database");
    }

    #[test]
    fn test_parse_expansion_response_empty_input() {
        let expansions = parse_expansion_response("", "test query");
        assert!(expansions.is_empty());
    }

    #[test]
    fn test_config_from_env() {
        std::env::set_var("EXPANSION_ENABLED", "true");
        std::env::set_var("EXPANSION_MAX", "8");
        std::env::set_var("EXPANSION_USE_LLM", "true");
        std::env::set_var("LLM_GATEWAY_URL", "http://llm:8004");
        std::env::set_var("RETRIEVAL_EXPANSION_TIMEOUT_MS", "7000");

        let config = QueryExpanderConfig::from_env();

        assert!(config.enabled);
        assert_eq!(config.max_expansions, 8);
        assert!(config.use_llm);
        assert_eq!(config.llm_gateway_url, Some("http://llm:8004".to_string()));
        assert_eq!(config.llm_timeout_ms, 7000);

        // Clean up
        std::env::remove_var("EXPANSION_ENABLED");
        std::env::remove_var("EXPANSION_MAX");
        std::env::remove_var("EXPANSION_USE_LLM");
        std::env::remove_var("LLM_GATEWAY_URL");
        std::env::remove_var("RETRIEVAL_EXPANSION_TIMEOUT_MS");
    }

    #[test]
    fn test_completions_endpoint() {
        let config = QueryExpanderConfig::default().with_llm_gateway_url("http://localhost:8004");
        assert_eq!(
            config.completions_endpoint(),
            Some("http://localhost:8004/v1/chat/completions".to_string())
        );

        // Test with trailing slash
        let config = QueryExpanderConfig::default().with_llm_gateway_url("http://localhost:8004/");
        assert_eq!(
            config.completions_endpoint(),
            Some("http://localhost:8004/v1/chat/completions".to_string())
        );

        // Test without URL configured
        let config = QueryExpanderConfig::default();
        assert_eq!(config.completions_endpoint(), None);
    }
}

#[cfg(test)]
mod llm_integration_tests {
    use super::*;
    use wiremock::matchers::{method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    fn mock_llm_response(content: &str) -> serde_json::Value {
        serde_json::json!({
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": content
                },
                "finish_reason": "stop"
            }]
        })
    }

    #[tokio::test]
    async fn test_expand_with_llm_success() {
        let mock_server = MockServer::start().await;

        let response_body = mock_llm_response(
            "How to configure database connections\nDatabase setup tutorial\nSetting up a database from scratch",
        );

        Mock::given(method("POST"))
            .and(path("/v1/chat/completions"))
            .respond_with(ResponseTemplate::new(200).set_body_json(&response_body))
            .mount(&mock_server)
            .await;

        let config = QueryExpanderConfig::default()
            .with_use_llm(true)
            .with_llm_gateway_url(mock_server.uri())
            .with_llm_timeout_ms(5000);

        let expander = QueryExpander::new(config).unwrap();
        let expansions = expander.expand_with_llm("database setup").await.unwrap();

        assert_eq!(expansions.len(), 3);
        assert!(expansions.iter().any(|e| e.contains("configure")));
        assert!(expansions.iter().any(|e| e.contains("tutorial")));
    }

    #[tokio::test]
    async fn test_expand_with_llm_full_pipeline() {
        let mock_server = MockServer::start().await;

        let response_body =
            mock_llm_response("Locating optimal documents\nRetrieving the best files");

        Mock::given(method("POST"))
            .and(path("/v1/chat/completions"))
            .respond_with(ResponseTemplate::new(200).set_body_json(&response_body))
            .mount(&mock_server)
            .await;

        let config = QueryExpanderConfig::default()
            .with_use_llm(true)
            .with_use_synonyms(true)
            .with_include_original(true)
            .with_max_expansions(10)
            .with_llm_gateway_url(mock_server.uri())
            .with_llm_timeout_ms(5000);

        let expander = QueryExpander::new(config).unwrap();
        let expansions = expander.expand("find the best documents").await.unwrap();

        // Should include original query + synonym expansions + LLM expansions
        assert!(expansions.len() > 1);
        assert_eq!(expansions[0], "find the best documents"); // Original first
                                                              // LLM expansions should be included
        assert!(expansions
            .iter()
            .any(|e| e.contains("Locating") || e.contains("Retrieving")));
    }

    #[tokio::test]
    async fn test_expand_with_llm_server_error_fallback() {
        let mock_server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/v1/chat/completions"))
            .respond_with(ResponseTemplate::new(500).set_body_string("Internal Server Error"))
            .mount(&mock_server)
            .await;

        let config = QueryExpanderConfig::default()
            .with_use_llm(true)
            .with_use_synonyms(true)
            .with_include_original(true)
            .with_llm_gateway_url(mock_server.uri())
            .with_llm_timeout_ms(5000);

        let expander = QueryExpander::new(config).unwrap();

        // The full expand() method should gracefully fall back
        let expansions = expander.expand("find documents").await.unwrap();

        // Should still get original + synonym expansions despite LLM failure
        assert!(!expansions.is_empty());
        assert!(expansions.contains(&"find documents".to_string()));
    }

    #[tokio::test]
    async fn test_expand_with_llm_timeout() {
        let mock_server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/v1/chat/completions"))
            .respond_with(
                ResponseTemplate::new(200)
                    .set_body_json(&mock_llm_response("test expansion"))
                    .set_delay(std::time::Duration::from_secs(10)),
            )
            .mount(&mock_server)
            .await;

        let config = QueryExpanderConfig::default()
            .with_use_llm(true)
            .with_llm_gateway_url(mock_server.uri())
            .with_llm_timeout_ms(100); // Very short timeout

        let expander = QueryExpander::new(config).unwrap();
        let result = expander.expand_with_llm("test query").await;

        // Should fail with timeout
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(
            matches!(err, RetrievalError::Timeout(_)),
            "Expected timeout error, got: {err}"
        );
    }

    #[tokio::test]
    async fn test_expand_with_llm_connection_refused() {
        // Use a port that nothing is listening on
        let config = QueryExpanderConfig::default()
            .with_use_llm(true)
            .with_llm_gateway_url("http://127.0.0.1:1")
            .with_llm_timeout_ms(2000);

        let expander = QueryExpander::new(config).unwrap();
        let result = expander.expand_with_llm("test query").await;

        // Should fail with connection error
        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(
            matches!(err, RetrievalError::Llm(_)),
            "Expected LLM error, got: {err}"
        );
    }

    #[tokio::test]
    async fn test_expand_with_llm_invalid_json_response() {
        let mock_server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/v1/chat/completions"))
            .respond_with(ResponseTemplate::new(200).set_body_string("not valid json"))
            .mount(&mock_server)
            .await;

        let config = QueryExpanderConfig::default()
            .with_use_llm(true)
            .with_llm_gateway_url(mock_server.uri())
            .with_llm_timeout_ms(5000);

        let expander = QueryExpander::new(config).unwrap();
        let result = expander.expand_with_llm("test query").await;

        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(
            matches!(err, RetrievalError::Llm(_)),
            "Expected LLM error for invalid JSON, got: {err}"
        );
    }

    #[tokio::test]
    async fn test_expand_with_llm_empty_choices() {
        let mock_server = MockServer::start().await;

        let response_body = serde_json::json!({
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "choices": []
        });

        Mock::given(method("POST"))
            .and(path("/v1/chat/completions"))
            .respond_with(ResponseTemplate::new(200).set_body_json(&response_body))
            .mount(&mock_server)
            .await;

        let config = QueryExpanderConfig::default()
            .with_use_llm(true)
            .with_llm_gateway_url(mock_server.uri())
            .with_llm_timeout_ms(5000);

        let expander = QueryExpander::new(config).unwrap();
        let result = expander.expand_with_llm("test query").await.unwrap();

        // Empty choices should yield empty expansions (empty string from unwrap_or_default)
        assert!(result.is_empty());
    }

    #[tokio::test]
    async fn test_expand_with_llm_not_configured() {
        let config = QueryExpanderConfig::default().with_use_llm(true);
        // Note: llm_gateway_url is not set
        let expander = QueryExpander::new(config).unwrap();

        let result = expander.expand_with_llm("test query").await;
        assert!(result.is_err());
        assert!(
            matches!(result.unwrap_err(), RetrievalError::Config(_)),
            "Expected Config error when URL not set"
        );
    }
}
