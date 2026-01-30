//! Environment variable secrets provider.

use crate::{Result, SecretsError, SecretsProvider};
use async_trait::async_trait;
use std::env;
use tracing::debug;

/// Secrets provider that reads from environment variables.
///
/// This is the simplest provider and is typically used as a fallback.
#[derive(Debug, Default, Clone)]
pub struct EnvProvider {
    /// Optional prefix to add to key names.
    prefix: Option<String>,
}

impl EnvProvider {
    /// Create a new environment provider.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Create with a prefix for environment variable names.
    ///
    /// For example, with prefix "RAG_", looking up "DATABASE_PASSWORD"
    /// will read "RAG_DATABASE_PASSWORD".
    #[must_use]
    pub fn with_prefix(prefix: impl Into<String>) -> Self {
        Self {
            prefix: Some(prefix.into()),
        }
    }

    /// Get the full environment variable name.
    fn env_key(&self, key: &str) -> String {
        match &self.prefix {
            Some(prefix) => format!("{prefix}{key}"),
            None => key.to_string(),
        }
    }
}

#[async_trait]
impl SecretsProvider for EnvProvider {
    async fn get_secret(&self, key: &str) -> Result<String> {
        let env_key = self.env_key(key);
        debug!(key = key, env_key = %env_key, "Reading secret from environment");

        env::var(&env_key).map_err(|_| SecretsError::NotFound(key.into()))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_env_provider() {
        // Set a test environment variable
        env::set_var("TEST_SECRET_KEY", "test_value");

        let provider = EnvProvider::new();
        assert_eq!(
            provider.get_secret("TEST_SECRET_KEY").await.unwrap(),
            "test_value"
        );

        // Clean up
        env::remove_var("TEST_SECRET_KEY");
    }

    #[tokio::test]
    async fn test_env_provider_with_prefix() {
        env::set_var("PREFIX_MY_SECRET", "prefixed_value");

        let provider = EnvProvider::with_prefix("PREFIX_");
        assert_eq!(
            provider.get_secret("MY_SECRET").await.unwrap(),
            "prefixed_value"
        );

        env::remove_var("PREFIX_MY_SECRET");
    }

    #[tokio::test]
    async fn test_env_provider_not_found() {
        let provider = EnvProvider::new();
        let result = provider.get_secret("NONEXISTENT_KEY_12345").await;
        assert!(matches!(result, Err(SecretsError::NotFound(_))));
    }
}
