//! Storage configuration.

use serde::{Deserialize, Serialize};

/// Storage configuration.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StorageConfig {
    /// S3/MinIO endpoint URL (e.g., "http://localhost:9000" for MinIO).
    pub endpoint_url: Option<String>,

    /// AWS region (default: "us-east-1").
    pub region: String,

    /// Access key ID.
    pub access_key_id: Option<String>,

    /// Secret access key.
    pub secret_access_key: Option<String>,

    /// Use path-style addressing (required for MinIO).
    pub force_path_style: bool,

    /// Default bucket for operations.
    pub default_bucket: Option<String>,
}

impl Default for StorageConfig {
    fn default() -> Self {
        Self {
            endpoint_url: None,
            region: "us-east-1".into(),
            access_key_id: None,
            secret_access_key: None,
            force_path_style: false,
            default_bucket: None,
        }
    }
}

impl StorageConfig {
    /// Create a configuration for MinIO.
    #[must_use]
    pub fn minio(
        endpoint: impl Into<String>,
        access_key: impl Into<String>,
        secret_key: impl Into<String>,
    ) -> Self {
        Self {
            endpoint_url: Some(endpoint.into()),
            region: "us-east-1".into(),
            access_key_id: Some(access_key.into()),
            secret_access_key: Some(secret_key.into()),
            force_path_style: true,
            default_bucket: None,
        }
    }

    /// Create a configuration for AWS S3.
    #[must_use]
    pub fn aws(region: impl Into<String>) -> Self {
        Self {
            region: region.into(),
            ..Default::default()
        }
    }

    /// Set the default bucket.
    #[must_use]
    pub fn with_default_bucket(mut self, bucket: impl Into<String>) -> Self {
        self.default_bucket = Some(bucket.into());
        self
    }

    /// Set credentials.
    #[must_use]
    pub fn with_credentials(
        mut self,
        access_key: impl Into<String>,
        secret_key: impl Into<String>,
    ) -> Self {
        self.access_key_id = Some(access_key.into());
        self.secret_access_key = Some(secret_key.into());
        self
    }

    /// Load configuration from environment variables.
    ///
    /// Environment variables:
    /// - `AWS_ENDPOINT_URL` or `S3_ENDPOINT_URL`: Endpoint URL
    /// - `AWS_REGION` or `AWS_DEFAULT_REGION`: Region
    /// - `AWS_ACCESS_KEY_ID`: Access key
    /// - `AWS_SECRET_ACCESS_KEY`: Secret key
    /// - `S3_FORCE_PATH_STYLE`: Use path-style addressing
    /// - `S3_DEFAULT_BUCKET`: Default bucket
    #[must_use]
    pub fn from_env() -> Self {
        let mut config = Self::default();

        if let Ok(endpoint) = std::env::var("AWS_ENDPOINT_URL")
            .or_else(|_| std::env::var("S3_ENDPOINT_URL"))
        {
            config.endpoint_url = Some(endpoint);
        }

        if let Ok(region) = std::env::var("AWS_REGION")
            .or_else(|_| std::env::var("AWS_DEFAULT_REGION"))
        {
            config.region = region;
        }

        if let Ok(key) = std::env::var("AWS_ACCESS_KEY_ID") {
            config.access_key_id = Some(key);
        }

        if let Ok(secret) = std::env::var("AWS_SECRET_ACCESS_KEY") {
            config.secret_access_key = Some(secret);
        }

        if let Ok(path_style) = std::env::var("S3_FORCE_PATH_STYLE") {
            config.force_path_style = path_style.parse().unwrap_or(false);
        }

        if let Ok(bucket) = std::env::var("S3_DEFAULT_BUCKET") {
            config.default_bucket = Some(bucket);
        }

        config
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        let config = StorageConfig::default();
        assert_eq!(config.region, "us-east-1");
        assert!(!config.force_path_style);
    }

    #[test]
    fn test_minio_config() {
        let config = StorageConfig::minio("http://localhost:9000", "admin", "secret");
        assert_eq!(config.endpoint_url, Some("http://localhost:9000".into()));
        assert!(config.force_path_style);
        assert_eq!(config.access_key_id, Some("admin".into()));
    }
}
