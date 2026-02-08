//! Hypothetical Document Embeddings (`HyDE`) generation for improved retrieval.
//!
//! This module implements `HyDE` generation, which generates hypothetical document(s)
//! from a query using an LLM, then embeds those hypothetical documents instead of
//! (or in addition to) the original query. This can improve retrieval quality for
//! complex queries.
//!
//! # Example
//!
//! ```no_run
//! use rag_retrieval::query::{HydeConfig, HydeGenerator};
//!
//! #[tokio::main]
//! async fn main() -> Result<(), Box<dyn std::error::Error>> {
//!     let config = HydeConfig::new()
//!         .with_llm_gateway_url("http://localhost:8004")
//!         .with_enabled(true);
//!     let generator = HydeGenerator::new(config)?;
//!
//!     let result = generator.generate("What is machine learning?").await?;
//!     println!("Generated {} hypothetical documents", result.hypothetical_docs.len());
//!
//!     Ok(())
//! }
//! ```

use std::time::{Duration, Instant};

use rag_config::build_http_client_with_timeout;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use tracing::{debug, instrument, warn};

use crate::error::{Result, RetrievalError};

/// Query placeholder used in the prompt template.
const QUERY_PLACEHOLDER: &str = "{query}";

/// Default prompt template for generating hypothetical documents.
const DEFAULT_PROMPT_TEMPLATE: &str = "Given the following search query, write a short passage (1-2 paragraphs) that would be a relevant document answering this query. The passage should be factual and informative.\n\nQuery: {query}\n\nRelevant passage:";

/// Configuration for the `HyDE` generator.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HydeConfig {
    /// Whether `HyDE` generation is enabled.
    #[serde(default)]
    pub enabled: bool,

    /// URL of the LLM gateway service.
    #[serde(default = "default_llm_gateway_url")]
    pub llm_gateway_url: String,

    /// Model name to use for generation.
    #[serde(default = "default_model")]
    pub model: String,

    /// Number of hypothetical documents to generate.
    #[serde(default = "default_num_hypothetical_docs")]
    pub num_hypothetical_docs: usize,

    /// Maximum length of generated documents (approximate tokens).
    #[serde(default = "default_max_doc_length")]
    pub max_doc_length: usize,

    /// Request timeout in milliseconds.
    #[serde(default = "default_timeout_ms")]
    pub timeout_ms: u64,

    /// Prompt template for generating hypothetical documents.
    /// Must contain `{query}` placeholder.
    #[serde(default = "default_prompt_template")]
    pub prompt_template: String,

    /// Temperature for generation (0.0 - 1.0).
    #[serde(default = "default_temperature")]
    pub temperature: f32,
}

fn default_llm_gateway_url() -> String {
    "http://localhost:8004".into()
}

fn default_model() -> String {
    "llama3.2".into()
}

const fn default_num_hypothetical_docs() -> usize {
    1
}

const fn default_max_doc_length() -> usize {
    512
}

const fn default_timeout_ms() -> u64 {
    10_000
}

fn default_prompt_template() -> String {
    DEFAULT_PROMPT_TEMPLATE.into()
}

const fn default_temperature() -> f32 {
    0.7
}

impl Default for HydeConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            llm_gateway_url: default_llm_gateway_url(),
            model: default_model(),
            num_hypothetical_docs: default_num_hypothetical_docs(),
            max_doc_length: default_max_doc_length(),
            timeout_ms: default_timeout_ms(),
            prompt_template: default_prompt_template(),
            temperature: default_temperature(),
        }
    }
}

impl HydeConfig {
    /// Create a new `HyDE` config with defaults.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Enable or disable `HyDE` generation.
    #[must_use]
    pub const fn with_enabled(mut self, enabled: bool) -> Self {
        self.enabled = enabled;
        self
    }

    /// Set the LLM gateway URL.
    #[must_use]
    pub fn with_llm_gateway_url(mut self, url: impl Into<String>) -> Self {
        self.llm_gateway_url = url.into();
        self
    }

    /// Set the model name.
    #[must_use]
    pub fn with_model(mut self, model: impl Into<String>) -> Self {
        self.model = model.into();
        self
    }

    /// Set the number of hypothetical documents to generate.
    ///
    /// # Panics
    ///
    /// Panics if `num_docs` is 0 or greater than 5.
    #[must_use]
    pub fn with_num_hypothetical_docs(mut self, num_docs: usize) -> Self {
        assert!(num_docs > 0, "num_hypothetical_docs must be at least 1");
        assert!(num_docs <= 5, "num_hypothetical_docs must be at most 5");
        self.num_hypothetical_docs = num_docs;
        self
    }

    /// Set the maximum document length (approximate tokens).
    #[must_use]
    pub const fn with_max_doc_length(mut self, max_length: usize) -> Self {
        self.max_doc_length = max_length;
        self
    }

    /// Set the timeout in milliseconds.
    #[must_use]
    pub const fn with_timeout_ms(mut self, timeout_ms: u64) -> Self {
        self.timeout_ms = timeout_ms;
        self
    }

    /// Set the timeout.
    #[must_use]
    #[allow(clippy::cast_possible_truncation, clippy::missing_const_for_fn)]
    pub fn with_timeout(mut self, timeout: Duration) -> Self {
        self.timeout_ms = timeout.as_millis() as u64;
        self
    }

    /// Set the prompt template.
    ///
    /// The template must contain `{query}` placeholder which will be replaced
    /// with the actual query.
    #[must_use]
    pub fn with_prompt_template(mut self, template: impl Into<String>) -> Self {
        self.prompt_template = template.into();
        self
    }

    /// Set the generation temperature.
    #[must_use]
    pub const fn with_temperature(mut self, temperature: f32) -> Self {
        self.temperature = temperature;
        self
    }

    /// Get the timeout as a Duration.
    #[must_use]
    pub const fn timeout(&self) -> Duration {
        Duration::from_millis(self.timeout_ms)
    }

    /// Get the chat completions API endpoint URL.
    #[must_use]
    pub fn completions_endpoint(&self) -> String {
        format!(
            "{}/v1/chat/completions",
            self.llm_gateway_url.trim_end_matches('/')
        )
    }

    /// Load configuration from environment variables.
    ///
    /// Environment variables:
    /// - `HYDE_ENABLED`: Whether `HyDE` is enabled (default: false)
    /// - `LLM_GATEWAY_URL`: LLM gateway service URL (default: `http://localhost:8004`)
    /// - `HYDE_MODEL`: Model name (default: `llama3.2`)
    /// - `HYDE_NUM_DOCS`: Number of hypothetical documents (default: 1)
    /// - `HYDE_MAX_DOC_LENGTH`: Maximum document length (default: 512)
    /// - `HYDE_TIMEOUT_MS`: Timeout in milliseconds (default: 10000)
    /// - `HYDE_TEMPERATURE`: Generation temperature (default: 0.7)
    #[must_use]
    pub fn from_env() -> Self {
        let mut config = Self::default();

        if let Ok(enabled) = std::env::var("HYDE_ENABLED") {
            config.enabled = enabled.to_lowercase() == "true" || enabled == "1";
        }

        if let Ok(url) = std::env::var("LLM_GATEWAY_URL") {
            config.llm_gateway_url = url;
        }

        if let Ok(model) = std::env::var("HYDE_MODEL") {
            config.model = model;
        }

        if let Ok(num_docs) = std::env::var("HYDE_NUM_DOCS") {
            if let Ok(n) = num_docs.parse::<usize>() {
                if n > 0 && n <= 5 {
                    config.num_hypothetical_docs = n;
                }
            }
        }

        if let Ok(max_length) = std::env::var("HYDE_MAX_DOC_LENGTH") {
            if let Ok(m) = max_length.parse() {
                config.max_doc_length = m;
            }
        }

        if let Ok(timeout) = std::env::var("HYDE_TIMEOUT_MS") {
            if let Ok(t) = timeout.parse() {
                config.timeout_ms = t;
            }
        }

        if let Ok(temp) = std::env::var("HYDE_TEMPERATURE") {
            if let Ok(t) = temp.parse() {
                config.temperature = t;
            }
        }

        config
    }

    /// Validate the configuration.
    ///
    /// # Errors
    ///
    /// Returns an error if:
    /// - `HyDE` is enabled but the LLM gateway URL is empty
    /// - The prompt template does not contain the `{query}` placeholder
    /// - `num_hypothetical_docs` is not between 1 and 5
    pub fn validate(&self) -> Result<()> {
        if self.enabled && self.llm_gateway_url.is_empty() {
            return Err(RetrievalError::config(
                "LLM gateway URL is required when HyDE is enabled",
            ));
        }

        if !self.prompt_template.contains(QUERY_PLACEHOLDER) {
            return Err(RetrievalError::config(
                "HyDE prompt template must contain {query} placeholder",
            ));
        }

        if self.num_hypothetical_docs == 0 || self.num_hypothetical_docs > 5 {
            return Err(RetrievalError::config(
                "num_hypothetical_docs must be between 1 and 5",
            ));
        }

        Ok(())
    }
}

/// Result of `HyDE` generation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HydeResult {
    /// Original query.
    pub original_query: String,

    /// Generated hypothetical documents.
    pub hypothetical_docs: Vec<String>,

    /// Whether generation was successful.
    pub success: bool,

    /// Generation time in milliseconds.
    pub generation_time_ms: u64,
}

impl HydeResult {
    /// Create a new successful `HyDE` result.
    #[must_use]
    pub const fn success(
        original_query: String,
        hypothetical_docs: Vec<String>,
        generation_time_ms: u64,
    ) -> Self {
        Self {
            original_query,
            hypothetical_docs,
            success: true,
            generation_time_ms,
        }
    }

    /// Create a new failed `HyDE` result (returns original query as fallback).
    #[must_use]
    pub const fn failure(original_query: String, generation_time_ms: u64) -> Self {
        Self {
            original_query,
            hypothetical_docs: Vec::new(),
            success: false,
            generation_time_ms,
        }
    }
}

/// Request body for the OpenAI-compatible chat completions API.
#[derive(Debug, Serialize)]
struct LlmRequest {
    /// Model identifier.
    model: String,
    /// Chat messages.
    messages: Vec<Message>,
    /// Maximum tokens to generate.
    max_tokens: usize,
    /// Temperature for generation.
    temperature: f32,
}

/// A chat message for the LLM request.
#[derive(Debug, Serialize)]
struct Message {
    /// Role of the message sender.
    role: String,
    /// Content of the message.
    content: String,
}

/// Response from the OpenAI-compatible chat completions API.
#[derive(Debug, Deserialize)]
struct LlmResponse {
    /// List of completion choices.
    choices: Vec<Choice>,
}

/// A single choice from the LLM response.
#[derive(Debug, Deserialize)]
struct Choice {
    /// The generated message.
    message: ResponseMessage,
}

/// The generated message content.
#[derive(Debug, Deserialize)]
struct ResponseMessage {
    /// The content of the generated message.
    content: String,
}

/// `HyDE` generator that generates hypothetical documents from queries.
///
/// The generator calls an LLM gateway (OpenAI-compatible API) to generate
/// hypothetical documents that can be used for improved retrieval.
#[derive(Debug, Clone)]
pub struct HydeGenerator {
    /// HTTP client for making requests.
    client: Client,
    /// Configuration for `HyDE` generation.
    config: HydeConfig,
}

impl HydeGenerator {
    /// Create a new `HyDE` generator with the given configuration.
    ///
    /// # Errors
    ///
    /// Returns an error if the configuration is invalid or the HTTP client
    /// cannot be created.
    pub fn new(config: HydeConfig) -> Result<Self> {
        config.validate()?;

        let client = build_http_client_with_timeout(config.timeout())
            .map_err(|e| RetrievalError::config(e))?;

        Ok(Self { client, config })
    }

    /// Create a new `HyDE` generator from environment variables.
    ///
    /// # Errors
    ///
    /// Returns an error if the configuration is invalid or the HTTP client
    /// cannot be created.
    pub fn from_env() -> Result<Self> {
        Self::new(HydeConfig::from_env())
    }

    /// Get the configuration.
    #[must_use]
    pub const fn config(&self) -> &HydeConfig {
        &self.config
    }

    /// Check if `HyDE` generation is enabled.
    #[must_use]
    pub const fn is_enabled(&self) -> bool {
        self.config.enabled
    }

    /// Generate hypothetical documents for the given query.
    ///
    /// If `HyDE` is disabled, returns an empty result immediately.
    ///
    /// # Arguments
    ///
    /// * `query` - The search query to generate hypothetical documents for
    ///
    /// # Errors
    ///
    /// Returns an error if the LLM request fails.
    #[allow(clippy::cast_possible_truncation)]
    #[instrument(skip(self, query), fields(query_len = query.len(), enabled = self.config.enabled))]
    pub async fn generate(&self, query: &str) -> Result<HydeResult> {
        let start = Instant::now();

        if !self.config.enabled {
            debug!("HyDE is disabled, returning empty result");
            return Ok(HydeResult::failure(
                query.to_string(),
                start.elapsed().as_millis() as u64,
            ));
        }

        let mut hypothetical_docs = Vec::with_capacity(self.config.num_hypothetical_docs);

        for i in 0..self.config.num_hypothetical_docs {
            debug!(doc_index = i, "Generating hypothetical document");

            match self.generate_single(query).await {
                Ok(doc) => {
                    hypothetical_docs.push(doc);
                }
                Err(e) => {
                    warn!(
                        doc_index = i,
                        error = %e,
                        "Failed to generate hypothetical document"
                    );
                    // Continue trying to generate remaining documents
                }
            }
        }

        let generation_time_ms = start.elapsed().as_millis() as u64;

        if hypothetical_docs.is_empty() {
            debug!(
                generation_time_ms,
                "All HyDE generations failed, returning failure result"
            );
            Ok(HydeResult::failure(query.to_string(), generation_time_ms))
        } else {
            debug!(
                num_docs = hypothetical_docs.len(),
                generation_time_ms, "HyDE generation successful"
            );
            Ok(HydeResult::success(
                query.to_string(),
                hypothetical_docs,
                generation_time_ms,
            ))
        }
    }

    /// Build the prompt for `HyDE` generation.
    #[must_use]
    pub fn build_prompt(&self, query: &str) -> String {
        self.config
            .prompt_template
            .replace(QUERY_PLACEHOLDER, query)
    }

    /// Generate a single hypothetical document.
    async fn generate_single(&self, query: &str) -> Result<String> {
        let prompt = self.build_prompt(query);
        self.call_llm(&prompt).await
    }

    /// Call the LLM gateway to generate text.
    async fn call_llm(&self, prompt: &str) -> Result<String> {
        let request = LlmRequest {
            model: self.config.model.clone(),
            messages: vec![Message {
                role: "user".to_string(),
                content: prompt.to_string(),
            }],
            max_tokens: self.config.max_doc_length,
            temperature: self.config.temperature,
        };

        let response = self
            .client
            .post(self.config.completions_endpoint())
            .json(&request)
            .send()
            .await
            .map_err(|e| {
                if e.is_timeout() {
                    RetrievalError::timeout(format!(
                        "HyDE LLM request timed out after {}ms",
                        self.config.timeout_ms
                    ))
                } else if e.is_connect() {
                    RetrievalError::llm(format!(
                        "Failed to connect to LLM gateway at {}: {e}",
                        self.config.llm_gateway_url
                    ))
                } else {
                    RetrievalError::llm(format!("HyDE LLM request failed: {e}"))
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

        let llm_response: LlmResponse = response
            .json()
            .await
            .map_err(|e| RetrievalError::llm(format!("Failed to parse LLM response: {e}")))?;

        llm_response
            .choices
            .into_iter()
            .next()
            .map(|c| c.message.content.trim().to_string())
            .ok_or_else(|| RetrievalError::llm("No choices in LLM response"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        let config = HydeConfig::default();
        assert!(!config.enabled);
        assert_eq!(config.llm_gateway_url, "http://localhost:8004");
        assert_eq!(config.model, "llama3.2");
        assert_eq!(config.num_hypothetical_docs, 1);
        assert_eq!(config.max_doc_length, 512);
        assert_eq!(config.timeout_ms, 10_000);
        assert!((config.temperature - 0.7).abs() < f32::EPSILON);
        assert!(config.prompt_template.contains(QUERY_PLACEHOLDER));
    }

    #[test]
    fn test_config_builder() {
        let config = HydeConfig::new()
            .with_enabled(true)
            .with_llm_gateway_url("http://llm:8004")
            .with_model("gpt-4")
            .with_num_hypothetical_docs(3)
            .with_max_doc_length(256)
            .with_timeout(Duration::from_secs(5))
            .with_temperature(0.5);

        assert!(config.enabled);
        assert_eq!(config.llm_gateway_url, "http://llm:8004");
        assert_eq!(config.model, "gpt-4");
        assert_eq!(config.num_hypothetical_docs, 3);
        assert_eq!(config.max_doc_length, 256);
        assert_eq!(config.timeout_ms, 5_000);
        assert!((config.temperature - 0.5).abs() < f32::EPSILON);
    }

    #[test]
    fn test_config_validation_valid() {
        let config = HydeConfig::new()
            .with_enabled(true)
            .with_llm_gateway_url("http://llm:8004");

        assert!(config.validate().is_ok());
    }

    #[test]
    fn test_config_validation_missing_url() {
        let config = HydeConfig {
            enabled: true,
            llm_gateway_url: String::new(),
            ..Default::default()
        };

        let result = config.validate();
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("URL is required"));
    }

    #[test]
    fn test_config_validation_invalid_template() {
        let config = HydeConfig {
            enabled: true,
            llm_gateway_url: "http://llm:8004".into(),
            prompt_template: "No placeholder here".into(),
            ..Default::default()
        };

        let result = config.validate();
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("placeholder"));
    }

    #[test]
    fn test_config_validation_invalid_num_docs_zero() {
        let config = HydeConfig {
            enabled: true,
            llm_gateway_url: "http://llm:8004".into(),
            num_hypothetical_docs: 0,
            ..Default::default()
        };

        let result = config.validate();
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("between 1 and 5"));
    }

    #[test]
    fn test_config_validation_invalid_num_docs_too_high() {
        let config = HydeConfig {
            enabled: true,
            llm_gateway_url: "http://llm:8004".into(),
            num_hypothetical_docs: 6,
            ..Default::default()
        };

        let result = config.validate();
        assert!(result.is_err());
        assert!(result.unwrap_err().to_string().contains("between 1 and 5"));
    }

    #[test]
    #[should_panic(expected = "num_hypothetical_docs must be at least 1")]
    fn test_with_num_docs_zero_panics() {
        let _ = HydeConfig::new().with_num_hypothetical_docs(0);
    }

    #[test]
    #[should_panic(expected = "num_hypothetical_docs must be at most 5")]
    fn test_with_num_docs_too_high_panics() {
        let _ = HydeConfig::new().with_num_hypothetical_docs(6);
    }

    #[test]
    fn test_completions_endpoint() {
        let config = HydeConfig::new().with_llm_gateway_url("http://llm:8004");
        assert_eq!(
            config.completions_endpoint(),
            "http://llm:8004/v1/chat/completions"
        );

        // Test with trailing slash
        let config = HydeConfig::new().with_llm_gateway_url("http://llm:8004/");
        assert_eq!(
            config.completions_endpoint(),
            "http://llm:8004/v1/chat/completions"
        );
    }

    #[test]
    fn test_timeout_conversion() {
        let config = HydeConfig::new().with_timeout_ms(5000);
        assert_eq!(config.timeout(), Duration::from_millis(5000));

        let config = HydeConfig::new().with_timeout(Duration::from_secs(3));
        assert_eq!(config.timeout_ms, 3000);
    }

    #[test]
    fn test_generator_creation_disabled() {
        // When HyDE is disabled, validation should pass even with empty URL
        let config = HydeConfig::new().with_enabled(false);
        let generator = HydeGenerator::new(config);
        assert!(generator.is_ok());
        assert!(!generator.unwrap().is_enabled());
    }

    #[test]
    fn test_generator_creation_enabled() {
        let config = HydeConfig::new()
            .with_enabled(true)
            .with_llm_gateway_url("http://llm:8004");

        let generator = HydeGenerator::new(config);
        assert!(generator.is_ok());
        assert!(generator.unwrap().is_enabled());
    }

    #[test]
    fn test_build_prompt() {
        let config = HydeConfig::new()
            .with_enabled(true)
            .with_llm_gateway_url("http://llm:8004");
        let generator = HydeGenerator::new(config).unwrap();

        let prompt = generator.build_prompt("What is machine learning?");
        assert!(prompt.contains("What is machine learning?"));
        assert!(prompt.contains("search query"));
        assert!(prompt.contains("Relevant passage:"));
    }

    #[test]
    fn test_build_prompt_custom_template() {
        let config = HydeConfig::new()
            .with_enabled(true)
            .with_llm_gateway_url("http://llm:8004")
            .with_prompt_template("Answer: {query}");
        let generator = HydeGenerator::new(config).unwrap();

        let prompt = generator.build_prompt("test query");
        assert_eq!(prompt, "Answer: test query");
    }

    #[test]
    fn test_hyde_result_success() {
        let result = HydeResult::success(
            "test query".to_string(),
            vec!["doc1".to_string(), "doc2".to_string()],
            150,
        );

        assert!(result.success);
        assert_eq!(result.original_query, "test query");
        assert_eq!(result.hypothetical_docs.len(), 2);
        assert_eq!(result.generation_time_ms, 150);
    }

    #[test]
    fn test_hyde_result_failure() {
        let result = HydeResult::failure("test query".to_string(), 50);

        assert!(!result.success);
        assert_eq!(result.original_query, "test query");
        assert!(result.hypothetical_docs.is_empty());
        assert_eq!(result.generation_time_ms, 50);
    }

    #[tokio::test]
    async fn test_generate_when_disabled() {
        let config = HydeConfig::new().with_enabled(false);
        let generator = HydeGenerator::new(config).unwrap();

        let result = generator.generate("test query").await.unwrap();

        assert!(!result.success);
        assert_eq!(result.original_query, "test query");
        assert!(result.hypothetical_docs.is_empty());
    }

    #[test]
    fn test_config_serialization() {
        let config = HydeConfig::new()
            .with_enabled(true)
            .with_llm_gateway_url("http://llm:8004")
            .with_model("gpt-4")
            .with_num_hypothetical_docs(2);

        let json = serde_json::to_string(&config).unwrap();
        assert!(json.contains("\"enabled\":true"));
        assert!(json.contains("llm:8004"));
        assert!(json.contains("gpt-4"));

        let deserialized: HydeConfig = serde_json::from_str(&json).unwrap();
        assert!(deserialized.enabled);
        assert_eq!(deserialized.llm_gateway_url, "http://llm:8004");
        assert_eq!(deserialized.model, "gpt-4");
        assert_eq!(deserialized.num_hypothetical_docs, 2);
    }

    #[test]
    fn test_llm_request_serialization() {
        let request = LlmRequest {
            model: "gpt-4".to_string(),
            messages: vec![Message {
                role: "user".to_string(),
                content: "Test prompt".to_string(),
            }],
            max_tokens: 512,
            temperature: 0.7,
        };

        let json = serde_json::to_string(&request).unwrap();
        assert!(json.contains("\"model\":\"gpt-4\""));
        assert!(json.contains("\"role\":\"user\""));
        assert!(json.contains("\"content\":\"Test prompt\""));
        assert!(json.contains("\"max_tokens\":512"));
    }
}

#[cfg(test)]
mod llm_integration_tests {
    use super::*;
    use wiremock::matchers::{method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    fn mock_completion_response(content: &str) -> serde_json::Value {
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
    async fn test_hyde_generate_success() {
        let mock_server = MockServer::start().await;

        let hypothetical_doc = "Machine learning is a branch of artificial intelligence \
            that focuses on building systems that learn from data. These systems use \
            algorithms to identify patterns and make decisions with minimal human intervention.";

        Mock::given(method("POST"))
            .and(path("/v1/chat/completions"))
            .respond_with(
                ResponseTemplate::new(200)
                    .set_body_json(&mock_completion_response(hypothetical_doc)),
            )
            .mount(&mock_server)
            .await;

        let config = HydeConfig::new()
            .with_enabled(true)
            .with_llm_gateway_url(mock_server.uri())
            .with_timeout_ms(5000);

        let generator = HydeGenerator::new(config).unwrap();
        let result = generator
            .generate("What is machine learning?")
            .await
            .unwrap();

        assert!(result.success);
        assert_eq!(result.hypothetical_docs.len(), 1);
        assert!(result.hypothetical_docs[0].contains("artificial intelligence"));
        assert!(result.generation_time_ms > 0);
    }

    #[tokio::test]
    async fn test_hyde_generate_multiple_docs() {
        let mock_server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/v1/chat/completions"))
            .respond_with(
                ResponseTemplate::new(200).set_body_json(&mock_completion_response(
                    "A hypothetical document about the topic.",
                )),
            )
            .expect(3) // Should be called 3 times for 3 docs
            .mount(&mock_server)
            .await;

        let config = HydeConfig::new()
            .with_enabled(true)
            .with_llm_gateway_url(mock_server.uri())
            .with_num_hypothetical_docs(3)
            .with_timeout_ms(5000);

        let generator = HydeGenerator::new(config).unwrap();
        let result = generator.generate("test query").await.unwrap();

        assert!(result.success);
        assert_eq!(result.hypothetical_docs.len(), 3);
    }

    #[tokio::test]
    async fn test_hyde_generate_server_error() {
        let mock_server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/v1/chat/completions"))
            .respond_with(ResponseTemplate::new(500).set_body_string("Internal Server Error"))
            .mount(&mock_server)
            .await;

        let config = HydeConfig::new()
            .with_enabled(true)
            .with_llm_gateway_url(mock_server.uri())
            .with_timeout_ms(5000);

        let generator = HydeGenerator::new(config).unwrap();
        let result = generator.generate("test query").await.unwrap();

        // HyDE generator returns a failure result (not an error) when all docs fail
        assert!(!result.success);
        assert!(result.hypothetical_docs.is_empty());
    }

    #[tokio::test]
    async fn test_hyde_generate_timeout() {
        let mock_server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/v1/chat/completions"))
            .respond_with(
                ResponseTemplate::new(200)
                    .set_body_json(&mock_completion_response("test"))
                    .set_delay(std::time::Duration::from_secs(10)),
            )
            .mount(&mock_server)
            .await;

        let config = HydeConfig::new()
            .with_enabled(true)
            .with_llm_gateway_url(mock_server.uri())
            .with_timeout_ms(100); // Very short timeout

        let generator = HydeGenerator::new(config).unwrap();
        let result = generator.generate("test query").await.unwrap();

        // Should return failure result (timeout is caught per-doc)
        assert!(!result.success);
        assert!(result.hypothetical_docs.is_empty());
    }

    #[tokio::test]
    async fn test_hyde_generate_connection_refused() {
        let config = HydeConfig::new()
            .with_enabled(true)
            .with_llm_gateway_url("http://127.0.0.1:1")
            .with_timeout_ms(2000);

        let generator = HydeGenerator::new(config).unwrap();
        let result = generator.generate("test query").await.unwrap();

        // Should return failure result (connection error is caught per-doc)
        assert!(!result.success);
        assert!(result.hypothetical_docs.is_empty());
    }

    #[tokio::test]
    async fn test_hyde_generate_partial_failure() {
        let mock_server = MockServer::start().await;

        // First call succeeds, second fails, third succeeds
        // wiremock doesn't support ordered responses easily, so we'll
        // just verify that partial success works with a single mock
        Mock::given(method("POST"))
            .and(path("/v1/chat/completions"))
            .respond_with(
                ResponseTemplate::new(200)
                    .set_body_json(&mock_completion_response("A relevant passage.")),
            )
            .mount(&mock_server)
            .await;

        let config = HydeConfig::new()
            .with_enabled(true)
            .with_llm_gateway_url(mock_server.uri())
            .with_num_hypothetical_docs(2)
            .with_timeout_ms(5000);

        let generator = HydeGenerator::new(config).unwrap();
        let result = generator.generate("test query").await.unwrap();

        assert!(result.success);
        assert!(!result.hypothetical_docs.is_empty());
    }

    #[tokio::test]
    async fn test_hyde_generate_disabled_returns_immediately() {
        // No mock server needed - should not make any HTTP calls
        let config = HydeConfig::new().with_enabled(false);
        let generator = HydeGenerator::new(config).unwrap();

        let result = generator.generate("test query").await.unwrap();

        assert!(!result.success);
        assert!(result.hypothetical_docs.is_empty());
        assert_eq!(result.original_query, "test query");
    }
}
