//! Key management utilities.

use crate::{EncryptionConfig, EncryptionError, Result};
use hkdf::Hkdf;
use sha2::Sha256;
use std::collections::HashMap;
use std::sync::RwLock;
use tracing::{debug, instrument};

/// A versioned encryption key.
#[derive(Debug, Clone)]
pub struct KeyVersion {
    /// The key version number.
    pub version: u32,
    /// The key ID.
    pub key_id: String,
    /// The raw key bytes.
    key_bytes: Vec<u8>,
}

impl KeyVersion {
    /// Create a new key version.
    pub fn new(version: u32, key_id: String, key_bytes: Vec<u8>) -> Self {
        Self {
            version,
            key_id,
            key_bytes,
        }
    }

    /// Get the key bytes.
    #[must_use]
    pub fn key_bytes(&self) -> &[u8] {
        &self.key_bytes
    }
}

/// A key derived for a specific purpose.
#[derive(Debug, Clone)]
pub struct DerivedKey {
    /// The derived key bytes.
    key_bytes: Vec<u8>,
    /// The purpose this key was derived for.
    pub purpose: String,
    /// The parent key version.
    pub parent_version: u32,
}

impl DerivedKey {
    /// Get the key bytes.
    #[must_use]
    pub fn key_bytes(&self) -> &[u8] {
        &self.key_bytes
    }
}

/// Manages encryption keys and key rotation.
pub struct KeyManager {
    /// Current key version.
    current_version: u32,
    /// All available key versions.
    keys: RwLock<HashMap<u32, KeyVersion>>,
    /// Derived keys cache.
    derived_keys: RwLock<HashMap<String, DerivedKey>>,
    /// Configuration.
    config: EncryptionConfig,
}

impl KeyManager {
    /// Create a new key manager from configuration.
    ///
    /// # Errors
    ///
    /// Returns an error if the master key is invalid.
    #[instrument(skip(config))]
    pub fn new(config: EncryptionConfig) -> Result<Self> {
        let key_bytes = config.get_master_key_bytes()?;
        let current_version = config.key_version;
        let key_id = config.key_id.clone();

        let key_version = KeyVersion::new(current_version, key_id, key_bytes);

        let mut keys = HashMap::new();
        keys.insert(current_version, key_version);

        debug!(version = current_version, "Key manager initialized");

        Ok(Self {
            current_version,
            keys: RwLock::new(keys),
            derived_keys: RwLock::new(HashMap::new()),
            config,
        })
    }

    /// Get the current key version.
    #[must_use]
    pub fn current_version(&self) -> u32 {
        self.current_version
    }

    /// Get a key by version.
    ///
    /// # Errors
    ///
    /// Returns an error if the key version is not found.
    pub fn get_key(&self, version: u32) -> Result<KeyVersion> {
        let keys = self.keys.read().map_err(|e| {
            EncryptionError::ConfigError(format!("Failed to acquire key lock: {e}"))
        })?;

        keys.get(&version)
            .cloned()
            .ok_or_else(|| EncryptionError::KeyNotFound(format!("Key version {version} not found")))
    }

    /// Get the current key.
    ///
    /// # Errors
    ///
    /// Returns an error if the current key is not found.
    pub fn get_current_key(&self) -> Result<KeyVersion> {
        self.get_key(self.current_version)
    }

    /// Add a new key version (for key rotation).
    ///
    /// # Errors
    ///
    /// Returns an error if the lock cannot be acquired.
    #[instrument(skip(self, key_bytes))]
    pub fn add_key_version(
        &self,
        version: u32,
        key_id: String,
        key_bytes: Vec<u8>,
    ) -> Result<()> {
        let key_version = KeyVersion::new(version, key_id, key_bytes);

        let mut keys = self.keys.write().map_err(|e| {
            EncryptionError::ConfigError(format!("Failed to acquire key lock: {e}"))
        })?;

        keys.insert(version, key_version);
        debug!(version, "Added new key version");

        Ok(())
    }

    /// Derive a key for a specific purpose using HKDF.
    ///
    /// # Errors
    ///
    /// Returns an error if key derivation fails.
    #[instrument(skip(self))]
    pub fn derive_key(&self, purpose: &str) -> Result<DerivedKey> {
        // Check cache first
        let cache_key = format!("{}:{}", self.current_version, purpose);

        {
            let derived = self.derived_keys.read().map_err(|e| {
                EncryptionError::ConfigError(format!("Failed to acquire derived key lock: {e}"))
            })?;

            if let Some(key) = derived.get(&cache_key) {
                return Ok(key.clone());
            }
        }

        // Derive new key
        let master_key = self.get_current_key()?;
        let salt = self
            .config
            .derivation_salt
            .as_deref()
            .unwrap_or("rag-encryption-default-salt");

        let hkdf = Hkdf::<Sha256>::new(Some(salt.as_bytes()), master_key.key_bytes());
        let mut okm = [0u8; 32];
        hkdf.expand(purpose.as_bytes(), &mut okm)
            .map_err(|e| EncryptionError::KeyDerivationFailed(e.to_string()))?;

        let derived_key = DerivedKey {
            key_bytes: okm.to_vec(),
            purpose: purpose.to_string(),
            parent_version: self.current_version,
        };

        // Cache the derived key
        {
            let mut derived = self.derived_keys.write().map_err(|e| {
                EncryptionError::ConfigError(format!("Failed to acquire derived key lock: {e}"))
            })?;
            derived.insert(cache_key, derived_key.clone());
        }

        debug!(purpose, "Derived key for purpose");
        Ok(derived_key)
    }

    /// Rotate to a new key version.
    ///
    /// # Errors
    ///
    /// Returns an error if the new key is invalid.
    #[instrument(skip(self, new_key_bytes))]
    pub fn rotate_key(&mut self, new_version: u32, key_id: String, new_key_bytes: Vec<u8>) -> Result<()> {
        if new_key_bytes.len() != 32 {
            return Err(EncryptionError::InvalidKey(format!(
                "Key must be 32 bytes, got {}",
                new_key_bytes.len()
            )));
        }

        self.add_key_version(new_version, key_id, new_key_bytes)?;
        self.current_version = new_version;

        // Clear derived key cache
        let mut derived = self.derived_keys.write().map_err(|e| {
            EncryptionError::ConfigError(format!("Failed to acquire derived key lock: {e}"))
        })?;
        derived.clear();

        debug!(new_version, "Rotated to new key version");
        Ok(())
    }

    /// List all available key versions.
    ///
    /// # Errors
    ///
    /// Returns an error if the lock cannot be acquired.
    pub fn list_versions(&self) -> Result<Vec<u32>> {
        let keys = self.keys.read().map_err(|e| {
            EncryptionError::ConfigError(format!("Failed to acquire key lock: {e}"))
        })?;

        let mut versions: Vec<u32> = keys.keys().copied().collect();
        versions.sort_unstable();
        Ok(versions)
    }
}

impl std::fmt::Debug for KeyManager {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("KeyManager")
            .field("current_version", &self.current_version)
            .field("key_id", &self.config.key_id)
            .finish_non_exhaustive()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use base64::{engine::general_purpose::STANDARD, Engine};

    fn test_config() -> EncryptionConfig {
        let key = [0u8; 32];
        let key_b64 = STANDARD.encode(key);
        EncryptionConfig::with_key(key_b64)
    }

    #[test]
    fn test_key_manager_creation() {
        let config = test_config();
        let manager = KeyManager::new(config).unwrap();
        assert_eq!(manager.current_version(), 1);
    }

    #[test]
    fn test_key_derivation() {
        let config = test_config();
        let manager = KeyManager::new(config).unwrap();

        let derived = manager.derive_key("test-purpose").unwrap();
        assert_eq!(derived.purpose, "test-purpose");
        assert_eq!(derived.key_bytes().len(), 32);
    }

    #[test]
    fn test_key_rotation() {
        let config = test_config();
        let mut manager = KeyManager::new(config).unwrap();

        let new_key = [1u8; 32];
        manager
            .rotate_key(2, "rotated".into(), new_key.to_vec())
            .unwrap();

        assert_eq!(manager.current_version(), 2);
        assert!(manager.list_versions().unwrap().contains(&1));
        assert!(manager.list_versions().unwrap().contains(&2));
    }
}
