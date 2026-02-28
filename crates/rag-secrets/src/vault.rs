//! HashiCorp Vault secrets provider.

use crate::{config::VaultConfig, Result, SecretsError, SecretsProvider};
use async_trait::async_trait;
use reqwest::Client;
use serde::Deserialize;
use tracing::{debug, instrument, warn};

/// Vault KV v2 response format.
#[derive(Debug, Deserialize)]
struct VaultResponse {
    data: VaultData,
}

#[derive(Debug, Deserialize)]
struct VaultData {
    data: serde_json::Value,
}

/// Secrets provider that reads from HashiCorp Vault.
///
/// Uses the KV v2 secrets engine.
pub struct VaultProvider {
    client: Client,
    config: VaultConfig,
}

impl VaultProvider {
    /// Create a new Vault provider.
    ///
    /// # Errors
    ///
    /// Returns an error if the HTTP client cannot be created.
    pub fn new(config: VaultConfig) -> Result<Self> {
        let client = Client::builder()
            .danger_accept_invalid_certs(false)
            .build()
            .map_err(|e| SecretsError::ConfigError(e.to_string()))?;

        Ok(Self { client, config })
    }

    /// Create from environment variables.
    ///
    /// # Errors
    ///
    /// Returns an error if required environment variables are not set.
    pub fn from_env() -> Result<Self> {
        let config = VaultConfig::from_env()
            .ok_or_else(|| SecretsError::ConfigError("VAULT_ADDR not set".into()))?;
        Self::new(config)
    }

    /// Build the URL for a secret.
    fn secret_url(&self, path: &str) -> String {
        format!(
            "{}/v1/{}/data/{}/{}",
            self.config.address, self.config.mount_path, self.config.path_prefix, path
        )
    }

    /// Get a specific key from a secret path.
    #[instrument(skip(self))]
    pub async fn get_secret_key(&self, path: &str, key: &str) -> Result<String> {
        let data = self.read_secret(path).await?;

        data.get(key)
            .and_then(|v| v.as_str())
            .map(String::from)
            .ok_or_else(|| SecretsError::NotFound(format!("{path}/{key}")))
    }

    /// Read all data from a secret path.
    #[instrument(skip(self))]
    async fn read_secret(&self, path: &str) -> Result<serde_json::Value> {
        let url = self.secret_url(path);
        debug!(url = %url, "Reading secret from Vault");

        let mut request = self.client.get(&url);

        // Add token if available
        if let Some(token) = &self.config.token {
            request = request.header("X-Vault-Token", token);
        }

        // Add namespace if configured
        if let Some(namespace) = &self.config.namespace {
            request = request.header("X-Vault-Namespace", namespace);
        }

        let response = request.send().await?;

        if response.status() == reqwest::StatusCode::NOT_FOUND {
            return Err(SecretsError::NotFound(path.into()));
        }

        if response.status() == reqwest::StatusCode::FORBIDDEN {
            return Err(SecretsError::AuthError("Access denied".into()));
        }

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            warn!(status = %status, body = %body, "Vault request failed");
            return Err(SecretsError::ConnectionError(format!(
                "Vault returned {status}: {body}"
            )));
        }

        let vault_response: VaultResponse = response.json().await?;
        Ok(vault_response.data.data)
    }
}

#[async_trait]
impl SecretsProvider for VaultProvider {
    /// Get a secret from Vault.
    ///
    /// The key format is "path/key" where path is the secret path
    /// and key is the specific field within the secret.
    ///
    /// Example: "database/password" reads the "password" field from
    /// the secret at "{mount_path}/data/{prefix}/database".
    async fn get_secret(&self, key: &str) -> Result<String> {
        // Parse key as "path/field" or just "path" (returns first field)
        let (path, field) = match key.rsplit_once('/') {
            Some((p, f)) => (p, Some(f)),
            None => (key, None),
        };

        let data = self.read_secret(path).await?;

        match field {
            Some(f) => data
                .get(f)
                .and_then(|v| v.as_str())
                .map(String::from)
                .ok_or_else(|| SecretsError::NotFound(key.into())),
            None => {
                // Return first value if no field specified
                data.as_object()
                    .and_then(|obj| obj.values().next())
                    .and_then(|v| v.as_str())
                    .map(String::from)
                    .ok_or_else(|| SecretsError::NotFound(key.into()))
            }
        }
    }
}

impl std::fmt::Debug for VaultProvider {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("VaultProvider")
            .field("address", &self.config.address)
            .field("mount_path", &self.config.mount_path)
            .field("path_prefix", &self.config.path_prefix)
            .finish_non_exhaustive()
    }
}
