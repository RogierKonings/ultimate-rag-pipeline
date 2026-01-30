//! Encryption configuration.

use crate::{EncryptionError, Result};
use serde::{Deserialize, Serialize};
use std::env;

/// Encryption algorithm to use.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum EncryptionAlgorithm {
    /// AES-256-GCM (recommended).
    #[default]
    Aes256Gcm,
    /// ChaCha20-Poly1305.
    ChaCha20Poly1305,
}

/// Configuration for field-level encryption.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EncryptionConfig {
    /// Master key in base64 format (32 bytes for AES-256).
    /// Can be loaded from secrets provider.
    pub master_key_base64: Option<String>,

    /// Key ID for the master key (used for key rotation).
    pub key_id: String,

    /// Current key version.
    pub key_version: u32,

    /// Encryption algorithm.
    #[serde(default)]
    pub algorithm: EncryptionAlgorithm,

    /// Whether to include key version in ciphertext.
    #[serde(default = "default_true")]
    pub include_key_version: bool,

    /// Salt for key derivation (optional).
    pub derivation_salt: Option<String>,
}

fn default_true() -> bool {
    true
}

impl EncryptionConfig {
    /// Create configuration from environment variables.
    ///
    /// Required:
    /// - `ENCRYPTION_MASTER_KEY`: Base64-encoded 32-byte key
    ///
    /// Optional:
    /// - `ENCRYPTION_KEY_ID`: Key identifier (default: "default")
    /// - `ENCRYPTION_KEY_VERSION`: Key version (default: 1)
    /// - `ENCRYPTION_ALGORITHM`: "aes256gcm" or "chacha20poly1305"
    /// - `ENCRYPTION_DERIVATION_SALT`: Salt for key derivation
    ///
    /// # Errors
    ///
    /// Returns an error if the master key is not set.
    pub fn from_env() -> Result<Self> {
        let master_key_base64 = env::var("ENCRYPTION_MASTER_KEY").ok();

        let key_id = env::var("ENCRYPTION_KEY_ID").unwrap_or_else(|_| "default".into());

        let key_version = env::var("ENCRYPTION_KEY_VERSION")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(1);

        let algorithm = env::var("ENCRYPTION_ALGORITHM")
            .ok()
            .map(|v| match v.to_lowercase().as_str() {
                "chacha20poly1305" | "chacha20" => EncryptionAlgorithm::ChaCha20Poly1305,
                _ => EncryptionAlgorithm::Aes256Gcm,
            })
            .unwrap_or_default();

        let derivation_salt = env::var("ENCRYPTION_DERIVATION_SALT").ok();

        Ok(Self {
            master_key_base64,
            key_id,
            key_version,
            algorithm,
            include_key_version: true,
            derivation_salt,
        })
    }

    /// Create configuration with a specific master key.
    #[must_use]
    pub fn with_key(master_key_base64: String) -> Self {
        Self {
            master_key_base64: Some(master_key_base64),
            key_id: "default".into(),
            key_version: 1,
            algorithm: EncryptionAlgorithm::Aes256Gcm,
            include_key_version: true,
            derivation_salt: None,
        }
    }

    /// Validate the configuration.
    ///
    /// # Errors
    ///
    /// Returns an error if the master key is missing.
    pub fn validate(&self) -> Result<()> {
        if self.master_key_base64.is_none() {
            return Err(EncryptionError::ConfigError(
                "Master key is required".into(),
            ));
        }
        Ok(())
    }

    /// Get the master key bytes.
    ///
    /// # Errors
    ///
    /// Returns an error if the key is not set or invalid base64.
    pub fn get_master_key_bytes(&self) -> Result<Vec<u8>> {
        use base64::{engine::general_purpose::STANDARD, Engine};

        let key_b64 = self
            .master_key_base64
            .as_ref()
            .ok_or_else(|| EncryptionError::KeyNotFound("master key not configured".into()))?;

        let bytes = STANDARD.decode(key_b64)?;

        // Validate key length for AES-256
        if bytes.len() != 32 {
            return Err(EncryptionError::InvalidKey(format!(
                "Key must be 32 bytes, got {}",
                bytes.len()
            )));
        }

        Ok(bytes)
    }
}

impl Default for EncryptionConfig {
    fn default() -> Self {
        Self {
            master_key_base64: None,
            key_id: "default".into(),
            key_version: 1,
            algorithm: EncryptionAlgorithm::Aes256Gcm,
            include_key_version: true,
            derivation_salt: None,
        }
    }
}
