//! Field-level encryption implementation.

use crate::{EncryptionConfig, EncryptionError, KeyManager, Result};
use aes_gcm::{
    aead::{Aead, KeyInit},
    Aes256Gcm, Nonce,
};
use base64::{engine::general_purpose::STANDARD as BASE64, Engine};
use rand::RngCore;
use serde::{Deserialize, Serialize};
use tracing::{debug, instrument};

/// Nonce size for AES-GCM (96 bits).
const NONCE_SIZE: usize = 12;

/// Tag size for AES-GCM (128 bits).
const TAG_SIZE: usize = 16;

/// An encrypted value with metadata.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EncryptedValue {
    /// Base64-encoded ciphertext (includes nonce + ciphertext + tag).
    pub ciphertext: String,
    /// Key version used for encryption.
    pub key_version: u32,
    /// Key ID.
    pub key_id: String,
    /// Algorithm used.
    pub algorithm: String,
}

impl EncryptedValue {
    /// Parse an encrypted value from a compact string format.
    ///
    /// Format: `v{version}:{key_id}:{algorithm}:{ciphertext_base64}`
    ///
    /// # Errors
    ///
    /// Returns an error if the format is invalid.
    pub fn from_compact(s: &str) -> Result<Self> {
        let parts: Vec<&str> = s.splitn(4, ':').collect();
        if parts.len() != 4 {
            return Err(EncryptionError::InvalidCiphertext(
                "Invalid compact format".into(),
            ));
        }

        let version_str = parts[0]
            .strip_prefix('v')
            .ok_or_else(|| EncryptionError::InvalidCiphertext("Missing version prefix".into()))?;

        let key_version = version_str
            .parse()
            .map_err(|_| EncryptionError::InvalidCiphertext("Invalid version number".into()))?;

        Ok(Self {
            ciphertext: parts[3].to_string(),
            key_version,
            key_id: parts[1].to_string(),
            algorithm: parts[2].to_string(),
        })
    }

    /// Convert to compact string format.
    #[must_use]
    pub fn to_compact(&self) -> String {
        format!(
            "v{}:{}:{}:{}",
            self.key_version, self.key_id, self.algorithm, self.ciphertext
        )
    }
}

/// Field-level encryptor using AES-256-GCM.
pub struct FieldEncryptor {
    key_manager: KeyManager,
    config: EncryptionConfig,
}

impl FieldEncryptor {
    /// Create a new field encryptor.
    ///
    /// # Errors
    ///
    /// Returns an error if the configuration is invalid.
    #[instrument(skip(config))]
    pub fn new(config: EncryptionConfig) -> Result<Self> {
        config.validate()?;
        let key_manager = KeyManager::new(config.clone())?;

        debug!("Field encryptor initialized");

        Ok(Self {
            key_manager,
            config,
        })
    }

    /// Encrypt a plaintext string.
    ///
    /// # Errors
    ///
    /// Returns an error if encryption fails.
    #[instrument(skip(self, plaintext))]
    pub fn encrypt(&self, plaintext: &str) -> Result<EncryptedValue> {
        self.encrypt_bytes(plaintext.as_bytes())
    }

    /// Encrypt raw bytes.
    ///
    /// # Errors
    ///
    /// Returns an error if encryption fails.
    pub fn encrypt_bytes(&self, plaintext: &[u8]) -> Result<EncryptedValue> {
        let key = self.key_manager.get_current_key()?;

        // Generate random nonce
        let mut nonce_bytes = [0u8; NONCE_SIZE];
        rand::thread_rng().fill_bytes(&mut nonce_bytes);
        let nonce = Nonce::from_slice(&nonce_bytes);

        // Create cipher
        let cipher = Aes256Gcm::new_from_slice(key.key_bytes())
            .map_err(|e| EncryptionError::EncryptionFailed(e.to_string()))?;

        // Encrypt
        let ciphertext = cipher
            .encrypt(nonce, plaintext)
            .map_err(|e| EncryptionError::EncryptionFailed(e.to_string()))?;

        // Combine nonce + ciphertext
        let mut combined = Vec::with_capacity(NONCE_SIZE + ciphertext.len());
        combined.extend_from_slice(&nonce_bytes);
        combined.extend_from_slice(&ciphertext);

        let ciphertext_b64 = BASE64.encode(&combined);

        debug!(
            key_version = key.version,
            ciphertext_len = combined.len(),
            "Encrypted data"
        );

        Ok(EncryptedValue {
            ciphertext: ciphertext_b64,
            key_version: key.version,
            key_id: key.key_id.clone(),
            algorithm: "aes-256-gcm".into(),
        })
    }

    /// Decrypt an encrypted value.
    ///
    /// # Errors
    ///
    /// Returns an error if decryption fails.
    #[instrument(skip(self, encrypted))]
    pub fn decrypt(&self, encrypted: &EncryptedValue) -> Result<String> {
        let bytes = self.decrypt_bytes(encrypted)?;
        String::from_utf8(bytes)
            .map_err(|e| EncryptionError::DecryptionFailed(format!("Invalid UTF-8: {e}")))
    }

    /// Decrypt to raw bytes.
    ///
    /// # Errors
    ///
    /// Returns an error if decryption fails.
    pub fn decrypt_bytes(&self, encrypted: &EncryptedValue) -> Result<Vec<u8>> {
        let key = self.key_manager.get_key(encrypted.key_version)?;

        // Decode ciphertext
        let combined = BASE64.decode(&encrypted.ciphertext)?;

        if combined.len() < NONCE_SIZE + TAG_SIZE {
            return Err(EncryptionError::InvalidCiphertext(
                "Ciphertext too short".into(),
            ));
        }

        // Split nonce and ciphertext
        let (nonce_bytes, ciphertext) = combined.split_at(NONCE_SIZE);
        let nonce = Nonce::from_slice(nonce_bytes);

        // Create cipher
        let cipher = Aes256Gcm::new_from_slice(key.key_bytes())
            .map_err(|e| EncryptionError::DecryptionFailed(e.to_string()))?;

        // Decrypt
        let plaintext = cipher
            .decrypt(nonce, ciphertext)
            .map_err(|e| EncryptionError::DecryptionFailed(e.to_string()))?;

        debug!(
            key_version = encrypted.key_version,
            plaintext_len = plaintext.len(),
            "Decrypted data"
        );

        Ok(plaintext)
    }

    /// Decrypt from compact string format.
    ///
    /// # Errors
    ///
    /// Returns an error if decryption fails.
    pub fn decrypt_compact(&self, compact: &str) -> Result<String> {
        let encrypted = EncryptedValue::from_compact(compact)?;
        self.decrypt(&encrypted)
    }

    /// Re-encrypt data with the current key version.
    ///
    /// Useful for key rotation.
    ///
    /// # Errors
    ///
    /// Returns an error if re-encryption fails.
    #[instrument(skip(self, encrypted))]
    pub fn reencrypt(&self, encrypted: &EncryptedValue) -> Result<EncryptedValue> {
        if encrypted.key_version == self.key_manager.current_version() {
            return Ok(encrypted.clone());
        }

        let plaintext = self.decrypt_bytes(encrypted)?;
        self.encrypt_bytes(&plaintext)
    }

    /// Get the current key version.
    #[must_use]
    pub fn current_key_version(&self) -> u32 {
        self.key_manager.current_version()
    }

    /// Check if an encrypted value needs re-encryption.
    #[must_use]
    pub fn needs_reencryption(&self, encrypted: &EncryptedValue) -> bool {
        encrypted.key_version != self.key_manager.current_version()
    }

    /// Get a reference to the key manager.
    #[must_use]
    pub fn key_manager(&self) -> &KeyManager {
        &self.key_manager
    }

    /// Get a mutable reference to the key manager for key rotation.
    pub fn key_manager_mut(&mut self) -> &mut KeyManager {
        &mut self.key_manager
    }
}

impl std::fmt::Debug for FieldEncryptor {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("FieldEncryptor")
            .field("key_version", &self.key_manager.current_version())
            .field("key_id", &self.config.key_id)
            .field("algorithm", &self.config.algorithm)
            .finish()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_config() -> EncryptionConfig {
        let key = [42u8; 32];
        let key_b64 = BASE64.encode(key);
        EncryptionConfig::with_key(key_b64)
    }

    #[test]
    fn test_encrypt_decrypt() {
        let config = test_config();
        let encryptor = FieldEncryptor::new(config).unwrap();

        let plaintext = "sensitive-data-123";
        let encrypted = encryptor.encrypt(plaintext).unwrap();
        let decrypted = encryptor.decrypt(&encrypted).unwrap();

        assert_eq!(plaintext, decrypted);
    }

    #[test]
    fn test_encrypt_produces_different_ciphertexts() {
        let config = test_config();
        let encryptor = FieldEncryptor::new(config).unwrap();

        let plaintext = "same-data";
        let encrypted1 = encryptor.encrypt(plaintext).unwrap();
        let encrypted2 = encryptor.encrypt(plaintext).unwrap();

        // Different nonces should produce different ciphertexts
        assert_ne!(encrypted1.ciphertext, encrypted2.ciphertext);
    }

    #[test]
    fn test_compact_format() {
        let config = test_config();
        let encryptor = FieldEncryptor::new(config).unwrap();

        let plaintext = "test-data";
        let encrypted = encryptor.encrypt(plaintext).unwrap();
        let compact = encrypted.to_compact();

        let parsed = EncryptedValue::from_compact(&compact).unwrap();
        let decrypted = encryptor.decrypt(&parsed).unwrap();

        assert_eq!(plaintext, decrypted);
    }

    #[test]
    fn test_invalid_ciphertext() {
        let config = test_config();
        let encryptor = FieldEncryptor::new(config).unwrap();

        let invalid = EncryptedValue {
            ciphertext: BASE64.encode([0u8; 10]), // Too short
            key_version: 1,
            key_id: "default".into(),
            algorithm: "aes-256-gcm".into(),
        };

        assert!(encryptor.decrypt(&invalid).is_err());
    }

    #[test]
    fn test_tampered_ciphertext() {
        let config = test_config();
        let encryptor = FieldEncryptor::new(config).unwrap();

        let plaintext = "original-data";
        let mut encrypted = encryptor.encrypt(plaintext).unwrap();

        // Tamper with ciphertext
        let mut bytes = BASE64.decode(&encrypted.ciphertext).unwrap();
        bytes[NONCE_SIZE + 5] ^= 0xFF;
        encrypted.ciphertext = BASE64.encode(&bytes);

        // Should fail authentication
        assert!(encryptor.decrypt(&encrypted).is_err());
    }
}
