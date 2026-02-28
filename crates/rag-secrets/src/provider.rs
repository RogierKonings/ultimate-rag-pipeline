//! Secrets provider trait and chained provider.

use crate::{Result, SecretsError};
use async_trait::async_trait;
use std::sync::Arc;
use tracing::{debug, warn};

/// Trait for secrets providers.
#[async_trait]
pub trait SecretsProvider: Send + Sync {
    /// Get a secret by key.
    ///
    /// Returns the secret value as a string.
    async fn get_secret(&self, key: &str) -> Result<String>;

    /// Get a secret, returning None if not found.
    ///
    /// Unlike `get_secret`, this returns `None` for `NotFound` errors.
    async fn get_secret_optional(&self, key: &str) -> Result<Option<String>> {
        match self.get_secret(key).await {
            Ok(value) => Ok(Some(value)),
            Err(SecretsError::NotFound(_)) => Ok(None),
            Err(e) => Err(e),
        }
    }

    /// Check if a secret exists.
    async fn exists(&self, key: &str) -> Result<bool> {
        match self.get_secret_optional(key).await {
            Ok(Some(_)) => Ok(true),
            Ok(None) => Ok(false),
            Err(e) => Err(e),
        }
    }

    /// Get multiple secrets at once.
    async fn get_secrets(&self, keys: &[&str]) -> Result<Vec<(String, Option<String>)>> {
        let mut results = Vec::with_capacity(keys.len());
        for key in keys {
            let value = self.get_secret_optional(key).await?;
            results.push((key.to_string(), value));
        }
        Ok(results)
    }
}

/// Provider that chains multiple providers, trying each in order.
pub struct ChainedProvider {
    providers: Vec<Arc<dyn SecretsProvider>>,
}

impl ChainedProvider {
    /// Create a new chained provider with the given providers.
    ///
    /// Providers are tried in order until one succeeds.
    pub fn new(providers: Vec<Arc<dyn SecretsProvider>>) -> Self {
        Self { providers }
    }

    /// Add a provider to the chain.
    pub fn add_provider(mut self, provider: Arc<dyn SecretsProvider>) -> Self {
        self.providers.push(provider);
        self
    }
}

#[async_trait]
impl SecretsProvider for ChainedProvider {
    async fn get_secret(&self, key: &str) -> Result<String> {
        let mut last_error = None;

        for (i, provider) in self.providers.iter().enumerate() {
            debug!(provider_index = i, key = key, "Trying provider");

            match provider.get_secret(key).await {
                Ok(value) => {
                    debug!(provider_index = i, key = key, "Provider succeeded");
                    return Ok(value);
                }
                Err(SecretsError::NotFound(_)) => {
                    debug!(
                        provider_index = i,
                        key = key,
                        "Secret not found, trying next"
                    );
                    continue;
                }
                Err(e) => {
                    warn!(provider_index = i, key = key, error = %e, "Provider failed");
                    last_error = Some(e);
                }
            }
        }

        // All providers failed
        Err(last_error.unwrap_or_else(|| {
            SecretsError::AllProvidersFailed(format!("No provider found secret: {key}"))
        }))
    }
}

impl std::fmt::Debug for ChainedProvider {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("ChainedProvider")
            .field("provider_count", &self.providers.len())
            .finish()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct MockProvider {
        secrets: std::collections::HashMap<String, String>,
    }

    impl MockProvider {
        fn new(secrets: Vec<(&str, &str)>) -> Self {
            Self {
                secrets: secrets
                    .into_iter()
                    .map(|(k, v)| (k.into(), v.into()))
                    .collect(),
            }
        }
    }

    #[async_trait]
    impl SecretsProvider for MockProvider {
        async fn get_secret(&self, key: &str) -> Result<String> {
            self.secrets
                .get(key)
                .cloned()
                .ok_or_else(|| SecretsError::NotFound(key.into()))
        }
    }

    #[tokio::test]
    async fn test_chained_provider() {
        let p1 = Arc::new(MockProvider::new(vec![("key1", "value1")]));
        let p2 = Arc::new(MockProvider::new(vec![("key2", "value2")]));

        let chained = ChainedProvider::new(vec![p1, p2]);

        assert_eq!(chained.get_secret("key1").await.unwrap(), "value1");
        assert_eq!(chained.get_secret("key2").await.unwrap(), "value2");
        assert!(chained.get_secret("key3").await.is_err());
    }
}
