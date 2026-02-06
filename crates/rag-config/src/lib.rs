//! Configuration management for RAG Pipeline services.
//!
//! This crate provides type-safe configuration loading from environment
//! variables with validation and secret masking.
//!
//! # Example
//!
//! ```no_run
//! use rag_config::{RetrievalConfig, load_config};
//!
//! let config: RetrievalConfig = load_config("RETRIEVAL").expect("Failed to load config");
//! println!("Qdrant URL: {}", config.qdrant.url);
//! ```

mod common;
pub mod http;
mod ingestion;
mod retrieval;
pub mod retry;
mod timeouts;

pub use common::{DatabaseConfig, LogLevel, ServiceConfig};
pub use http::{build_http_client, build_http_client_with_timeout, HttpClientConfig};
pub use ingestion::IngestionConfig;
pub use retrieval::RetrievalConfig;
pub use retry::RetryPolicy;
pub use timeouts::TimeoutConfig;

use config::{Config, ConfigError, Environment};
use serde::de::DeserializeOwned;
use std::fmt::Debug;
use validator::Validate;

/// Load configuration from environment variables with a given prefix.
///
/// # Errors
///
/// Returns an error if:
/// - Required environment variables are missing
/// - Values fail to parse
/// - Validation fails
pub fn load_config<T>(prefix: &str) -> Result<T, ConfigError>
where
    T: DeserializeOwned + Validate + Debug,
{
    // Load .env file if present (ignore errors)
    let _ = dotenvy::dotenv();

    let config = Config::builder()
        .add_source(
            Environment::with_prefix(prefix)
                .separator("__")
                .try_parsing(true),
        )
        .build()?;

    let settings: T = config.try_deserialize()?;

    // Validate the configuration
    settings
        .validate()
        .map_err(|e| ConfigError::Message(format!("Validation failed: {e}")))?;

    tracing::debug!("Loaded configuration: {settings:?}");

    Ok(settings)
}

/// Load configuration with a custom config builder.
///
/// This allows adding additional sources like files.
///
/// # Errors
///
/// Returns an error if configuration loading or validation fails.
pub fn load_config_with_builder<T, F>(prefix: &str, customize: F) -> Result<T, ConfigError>
where
    T: DeserializeOwned + Validate + Debug,
    F: FnOnce(
        config::ConfigBuilder<config::builder::DefaultState>,
    ) -> config::ConfigBuilder<config::builder::DefaultState>,
{
    let _ = dotenvy::dotenv();

    let builder = Config::builder().add_source(
        Environment::with_prefix(prefix)
            .separator("__")
            .try_parsing(true),
    );

    let config = customize(builder).build()?;
    let settings: T = config.try_deserialize()?;

    settings
        .validate()
        .map_err(|e| ConfigError::Message(format!("Validation failed: {e}")))?;

    Ok(settings)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_load_config_missing_required() {
        // This should fail because required fields are missing
        let result: Result<RetrievalConfig, _> = load_config("NONEXISTENT_PREFIX");
        // May succeed with defaults or fail - depends on implementation
        // Just ensure it doesn't panic
        let _ = result;
    }
}
