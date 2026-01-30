//! Integration with rag-secrets for key management.

use crate::{EncryptionConfig, EncryptionError, FieldEncryptor, Result};
use async_trait::async_trait;
use base64::{engine::general_purpose::STANDARD as BASE64, Engine};
use rag_secrets::SecretsProvider;
use std::sync::Arc;
use tracing::{debug, instrument};

/// Key provider that fetches encryption keys from secrets.
pub struct SecretsKeyProvider {
    secrets: Arc<dyn SecretsProvider>,
    key_secret_name: String,
}

impl SecretsKeyProvider {
    /// Create a new secrets-based key provider.
    pub fn new(secrets: Arc<dyn SecretsProvider>, key_secret_name: String) -> Self {
        Self {
            secrets,
            key_secret_name,
        }
    }

    /// Load an encryptor with the key from secrets.
    ///
    /// # Errors
    ///
    /// Returns an error if the key cannot be fetched or is invalid.
    #[instrument(skip(self))]
    pub async fn load_encryptor(&self) -> Result<FieldEncryptor> {
        let key_b64 = self
            .secrets
            .get_secret(&self.key_secret_name)
            .await
            .map_err(EncryptionError::from)?;

        // Validate the key
        let key_bytes = BASE64
            .decode(&key_b64)
            .map_err(|e| EncryptionError::InvalidKey(format!("Invalid base64: {e}")))?;

        if key_bytes.len() != 32 {
            return Err(EncryptionError::InvalidKey(format!(
                "Key must be 32 bytes, got {}",
                key_bytes.len()
            )));
        }

        let config = EncryptionConfig::with_key(key_b64);
        let encryptor = FieldEncryptor::new(config)?;

        debug!(secret_name = %self.key_secret_name, "Loaded encryption key from secrets");

        Ok(encryptor)
    }

    /// Load the raw key bytes from secrets.
    ///
    /// # Errors
    ///
    /// Returns an error if the key cannot be fetched.
    pub async fn load_key_bytes(&self) -> Result<Vec<u8>> {
        let key_b64 = self
            .secrets
            .get_secret(&self.key_secret_name)
            .await
            .map_err(EncryptionError::from)?;

        let key_bytes = BASE64
            .decode(&key_b64)
            .map_err(|e| EncryptionError::InvalidKey(format!("Invalid base64: {e}")))?;

        Ok(key_bytes)
    }
}

impl std::fmt::Debug for SecretsKeyProvider {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SecretsKeyProvider")
            .field("key_secret_name", &self.key_secret_name)
            .finish()
    }
}

/// Async key provider trait for extensibility.
#[async_trait]
pub trait AsyncKeyProvider: Send + Sync {
    /// Get the encryption key bytes.
    async fn get_key(&self) -> Result<Vec<u8>>;

    /// Get the key version.
    fn key_version(&self) -> u32 {
        1
    }

    /// Get the key ID.
    fn key_id(&self) -> &str {
        "default"
    }
}

#[async_trait]
impl AsyncKeyProvider for SecretsKeyProvider {
    async fn get_key(&self) -> Result<Vec<u8>> {
        self.load_key_bytes().await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use tokio::sync::RwLock;

    struct MockSecretsProvider {
        secrets: RwLock<HashMap<String, String>>,
    }

    impl MockSecretsProvider {
        fn new() -> Self {
            Self {
                secrets: RwLock::new(HashMap::new()),
            }
        }

        async fn set(&self, key: &str, value: &str) {
            self.secrets
                .write()
                .await
                .insert(key.to_string(), value.to_string());
        }
    }

    #[async_trait]
    impl SecretsProvider for MockSecretsProvider {
        async fn get_secret(&self, key: &str) -> rag_secrets::Result<String> {
            self.secrets
                .read()
                .await
                .get(key)
                .cloned()
                .ok_or_else(|| rag_secrets::SecretsError::NotFound(key.to_string()))
        }
    }

    #[tokio::test]
    async fn test_load_encryptor_from_secrets() {
        let mock = Arc::new(MockSecretsProvider::new());
        let key = [42u8; 32];
        let key_b64 = BASE64.encode(key);
        mock.set("encryption-key", &key_b64).await;

        let provider = SecretsKeyProvider::new(mock, "encryption-key".into());
        let encryptor = provider.load_encryptor().await.unwrap();

        let encrypted = encryptor.encrypt("test-data").unwrap();
        let decrypted = encryptor.decrypt(&encrypted).unwrap();
        assert_eq!("test-data", decrypted);
    }
}
