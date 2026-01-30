//! Configuration for secrets providers.

use serde::{Deserialize, Serialize};
use std::env;

/// Configuration for secrets management.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SecretsConfig {
    /// Vault configuration.
    pub vault: Option<VaultConfig>,
    /// Kubernetes configuration.
    pub kubernetes: Option<K8sConfig>,
    /// Whether to use environment variables as fallback.
    pub env_fallback: bool,
}

impl Default for SecretsConfig {
    fn default() -> Self {
        Self {
            vault: None,
            kubernetes: None,
            env_fallback: true,
        }
    }
}

impl SecretsConfig {
    /// Create configuration from environment variables.
    pub fn from_env() -> Self {
        let vault = VaultConfig::from_env();
        let kubernetes = K8sConfig::from_env();

        Self {
            vault,
            kubernetes,
            env_fallback: env::var("SECRETS_ENV_FALLBACK")
                .map(|v| v != "false" && v != "0")
                .unwrap_or(true),
        }
    }
}

/// Vault provider configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VaultConfig {
    /// Vault server address.
    pub address: String,
    /// Authentication token.
    pub token: Option<String>,
    /// Namespace (for Vault Enterprise).
    pub namespace: Option<String>,
    /// Secret engine mount path.
    pub mount_path: String,
    /// Path prefix for secrets.
    pub path_prefix: String,
}

impl VaultConfig {
    /// Create from environment variables.
    pub fn from_env() -> Option<Self> {
        let address = env::var("VAULT_ADDR").ok()?;

        Some(Self {
            address,
            token: env::var("VAULT_TOKEN").ok(),
            namespace: env::var("VAULT_NAMESPACE").ok(),
            mount_path: env::var("VAULT_MOUNT_PATH").unwrap_or_else(|_| "secret".into()),
            path_prefix: env::var("VAULT_PATH_PREFIX").unwrap_or_else(|_| "rag-pipeline".into()),
        })
    }
}

/// Kubernetes secrets configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct K8sConfig {
    /// Namespace to read secrets from.
    pub namespace: String,
    /// Secret name prefix.
    pub secret_prefix: String,
}

impl K8sConfig {
    /// Create from environment variables.
    pub fn from_env() -> Option<Self> {
        // Only enable if running in Kubernetes
        if env::var("KUBERNETES_SERVICE_HOST").is_err() {
            return None;
        }

        Some(Self {
            namespace: env::var("SECRETS_K8S_NAMESPACE")
                .or_else(|_| env::var("POD_NAMESPACE"))
                .unwrap_or_else(|_| "default".into()),
            secret_prefix: env::var("SECRETS_K8S_PREFIX").unwrap_or_else(|_| "rag-".into()),
        })
    }
}
