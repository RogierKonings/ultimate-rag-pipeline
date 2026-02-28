//! Kubernetes secrets provider.

use crate::{config::K8sConfig, Result, SecretsError, SecretsProvider};
use async_trait::async_trait;
use base64::{engine::general_purpose::STANDARD as BASE64, Engine};
use k8s_openapi::api::core::v1::Secret;
use kube::{api::Api, Client};
use tracing::{debug, instrument};

/// Secrets provider that reads from Kubernetes secrets.
pub struct K8sProvider {
    client: Client,
    config: K8sConfig,
}

impl K8sProvider {
    /// Create a new Kubernetes secrets provider.
    ///
    /// Uses in-cluster configuration when running in Kubernetes.
    ///
    /// # Errors
    ///
    /// Returns an error if the Kubernetes client cannot be created.
    pub async fn new(config: K8sConfig) -> Result<Self> {
        let client = Client::try_default()
            .await
            .map_err(|e| SecretsError::ConfigError(e.to_string()))?;

        Ok(Self { client, config })
    }

    /// Create from environment variables.
    ///
    /// # Errors
    ///
    /// Returns an error if not running in Kubernetes or client creation fails.
    pub async fn from_env() -> Result<Self> {
        let config = K8sConfig::from_env()
            .ok_or_else(|| SecretsError::ConfigError("Not running in Kubernetes".into()))?;
        Self::new(config).await
    }

    /// Parse key in format "secret_name/key" or just "key".
    fn parse_key(&self, key: &str) -> (String, String) {
        match key.split_once('/') {
            Some((secret_name, data_key)) => (secret_name.into(), data_key.into()),
            None => {
                // Use prefix + key as secret name, "value" as data key
                let secret_name = format!(
                    "{}{}",
                    self.config.secret_prefix,
                    key.to_lowercase().replace('_', "-")
                );
                (secret_name, "value".into())
            }
        }
    }
}

#[async_trait]
impl SecretsProvider for K8sProvider {
    /// Get a secret from Kubernetes.
    ///
    /// Key format options:
    /// - "secret_name/key" - reads `key` from secret `secret_name`
    /// - "KEY_NAME" - reads `value` from secret `{prefix}key-name`
    #[instrument(skip(self))]
    async fn get_secret(&self, key: &str) -> Result<String> {
        let (secret_name, data_key) = self.parse_key(key);
        debug!(secret = %secret_name, key = %data_key, namespace = %self.config.namespace, "Reading Kubernetes secret");

        let secrets: Api<Secret> = Api::namespaced(self.client.clone(), &self.config.namespace);

        let secret = secrets.get(&secret_name).await.map_err(|e| match e {
            kube::Error::Api(ref ae) if ae.code == 404 => {
                SecretsError::NotFound(format!("{}/{}", secret_name, data_key))
            }
            _ => SecretsError::from(e),
        })?;

        let data = secret
            .data
            .ok_or_else(|| SecretsError::NotFound(format!("{secret_name}/{data_key}")))?;

        let value_bytes = data
            .get(&data_key)
            .ok_or_else(|| SecretsError::NotFound(format!("{secret_name}/{data_key}")))?;

        // Kubernetes secrets are base64-encoded in the API response
        // but kube-rs returns ByteString which is already decoded
        String::from_utf8(value_bytes.0.clone())
            .map_err(|e| SecretsError::InvalidValue(e.to_string()))
    }
}

impl std::fmt::Debug for K8sProvider {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("K8sProvider")
            .field("namespace", &self.config.namespace)
            .field("secret_prefix", &self.config.secret_prefix)
            .finish()
    }
}
