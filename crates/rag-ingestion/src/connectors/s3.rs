//! S3 connector for S3/MinIO documents.

use async_trait::async_trait;
use aws_config::BehaviorVersion;
use aws_sdk_s3::Client;
use bytes::Bytes;
use chrono::DateTime;
use serde::{Deserialize, Serialize};
use tracing::{debug, instrument};

use crate::error::{Error, Result};
use super::base::{Connector, DocumentMetadata, RawDocument, SourceType};

/// Configuration for the S3 connector.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct S3Config {
    /// S3 bucket name.
    pub bucket: String,
    /// Optional prefix to filter objects.
    pub prefix: Option<String>,
    /// Custom endpoint URL (for MinIO).
    pub endpoint_url: Option<String>,
    /// AWS region.
    #[serde(default = "default_region")]
    pub region: String,
    /// File extensions to include.
    pub file_extensions: Option<Vec<String>>,
    /// Force path-style URLs (required for MinIO).
    #[serde(default)]
    pub force_path_style: bool,
}

fn default_region() -> String {
    "us-east-1".to_string()
}

impl S3Config {
    /// Create a new configuration for the given bucket.
    pub fn new(bucket: impl Into<String>) -> Self {
        Self {
            bucket: bucket.into(),
            prefix: None,
            endpoint_url: None,
            region: default_region(),
            file_extensions: None,
            force_path_style: false,
        }
    }

    /// Set the prefix filter.
    #[must_use]
    pub fn with_prefix(mut self, prefix: impl Into<String>) -> Self {
        self.prefix = Some(prefix.into());
        self
    }

    /// Set custom endpoint URL (for MinIO).
    #[must_use]
    pub fn with_endpoint(mut self, endpoint_url: impl Into<String>) -> Self {
        self.endpoint_url = Some(endpoint_url.into());
        self.force_path_style = true; // MinIO requires path-style
        self
    }

    /// Set the region.
    #[must_use]
    pub fn with_region(mut self, region: impl Into<String>) -> Self {
        self.region = region.into();
        self
    }

    /// Set file extensions to filter.
    #[must_use]
    pub fn with_extensions(mut self, extensions: Vec<String>) -> Self {
        self.file_extensions = Some(extensions);
        self
    }
}

/// Connector for S3/MinIO documents.
pub struct S3Connector {
    config: S3Config,
    client: Option<Client>,
}

impl S3Connector {
    /// Create a new S3 connector.
    pub fn new(config: S3Config) -> Self {
        Self {
            config,
            client: None,
        }
    }

    /// Check if a key should be included based on extension filter.
    fn should_include(&self, key: &str) -> bool {
        match &self.config.file_extensions {
            None => true,
            Some(extensions) => {
                let key_lower = key.to_lowercase();
                extensions.iter().any(|ext| key_lower.ends_with(&ext.to_lowercase()))
            }
        }
    }

    /// Get filename from S3 key.
    fn get_filename(key: &str) -> String {
        key.rsplit('/').next().unwrap_or(key).to_string()
    }

    fn client(&self) -> Result<&Client> {
        self.client.as_ref().ok_or_else(|| Error::Connector("Not connected".to_string()))
    }
}

#[async_trait]
impl Connector for S3Connector {
    #[instrument(skip(self))]
    async fn connect(&mut self) -> Result<()> {
        let mut config_loader = aws_config::defaults(BehaviorVersion::latest())
            .region(aws_config::Region::new(self.config.region.clone()));

        if let Some(endpoint) = &self.config.endpoint_url {
            config_loader = config_loader.endpoint_url(endpoint);
        }

        let sdk_config = config_loader.load().await;

        let mut s3_config = aws_sdk_s3::config::Builder::from(&sdk_config);
        if self.config.force_path_style {
            s3_config = s3_config.force_path_style(true);
        }

        self.client = Some(Client::from_conf(s3_config.build()));

        // Verify bucket exists by trying to head it
        let client = self.client()?;
        client
            .head_bucket()
            .bucket(&self.config.bucket)
            .send()
            .await
            .map_err(|e| Error::Connector(format!(
                "Failed to connect to bucket {}: {}",
                self.config.bucket, e
            )))?;

        debug!(bucket = %self.config.bucket, "Connected to S3");
        Ok(())
    }

    async fn disconnect(&mut self) -> Result<()> {
        self.client = None;
        debug!("Disconnected from S3");
        Ok(())
    }

    #[instrument(skip(self))]
    async fn list_documents(&self, path: Option<&str>) -> Result<Vec<DocumentMetadata>> {
        let client = self.client()?;
        let mut documents = Vec::new();

        let prefix = match (path, &self.config.prefix) {
            (Some(p), Some(base)) => Some(format!("{}/{}", base.trim_end_matches('/'), p)),
            (Some(p), None) => Some(p.to_string()),
            (None, Some(base)) => Some(base.clone()),
            (None, None) => None,
        };

        let mut continuation_token: Option<String> = None;

        loop {
            let mut request = client
                .list_objects_v2()
                .bucket(&self.config.bucket);

            if let Some(ref p) = prefix {
                request = request.prefix(p);
            }

            if let Some(ref token) = continuation_token {
                request = request.continuation_token(token);
            }

            let response = request.send().await.map_err(|e| {
                Error::Connector(format!("Failed to list objects: {e}"))
            })?;

            if let Some(contents) = response.contents {
                for object in contents {
                    let key = object.key.unwrap_or_default();

                    // Skip directories (keys ending with /)
                    if key.ends_with('/') {
                        continue;
                    }

                    if !self.should_include(&key) {
                        continue;
                    }

                    let filename = Self::get_filename(&key);
                    let mime_type = mime_guess::from_path(&filename)
                        .first()
                        .map(|m| m.to_string());

                    let modified_at = object.last_modified
                        .and_then(|t| DateTime::from_timestamp(t.secs(), t.subsec_nanos()));

                    let mut meta = DocumentMetadata::new(&key, SourceType::S3, filename)
                        .with_size(object.size.unwrap_or(0) as u64);

                    if let Some(mime) = mime_type {
                        meta = meta.with_mime_type(mime);
                    }

                    if let Some(modified) = modified_at {
                        meta = meta.with_timestamps(None, Some(modified));
                    }

                    documents.push(meta);
                }
            }

            // Check for pagination
            if response.is_truncated.unwrap_or(false) {
                continuation_token = response.next_continuation_token;
            } else {
                break;
            }
        }

        Ok(documents)
    }

    #[instrument(skip(self))]
    async fn fetch_document(&self, source_id: &str) -> Result<RawDocument> {
        let client = self.client()?;

        let response = client
            .get_object()
            .bucket(&self.config.bucket)
            .key(source_id)
            .send()
            .await
            .map_err(|e| {
                if e.to_string().contains("NoSuchKey") {
                    Error::NotFound(format!("Document not found: {source_id}"))
                } else {
                    Error::Storage(format!("Failed to get object: {e}"))
                }
            })?;

        let content = response
            .body
            .collect()
            .await
            .map_err(|e| Error::Storage(format!("Failed to read object body: {e}")))?
            .into_bytes();

        let filename = Self::get_filename(source_id);
        let mime_type = mime_guess::from_path(&filename)
            .first()
            .map(|m| m.to_string());

        let modified_at = response.last_modified
            .and_then(|t| DateTime::from_timestamp(t.secs(), t.subsec_nanos()));

        let mut metadata = DocumentMetadata::new(source_id, SourceType::S3, filename)
            .with_size(content.len() as u64);

        if let Some(mime) = mime_type {
            metadata = metadata.with_mime_type(mime);
        }

        if let Some(modified) = modified_at {
            metadata = metadata.with_timestamps(None, Some(modified));
        }

        Ok(RawDocument::new(Bytes::from(content), metadata))
    }

    fn is_connected(&self) -> bool {
        self.client.is_some()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_s3_config_builder() {
        let config = S3Config::new("my-bucket")
            .with_prefix("documents/")
            .with_endpoint("http://localhost:9000")
            .with_extensions(vec![".pdf".to_string()]);

        assert_eq!(config.bucket, "my-bucket");
        assert_eq!(config.prefix, Some("documents/".to_string()));
        assert_eq!(config.endpoint_url, Some("http://localhost:9000".to_string()));
        assert!(config.force_path_style); // Auto-enabled for custom endpoint
        assert_eq!(config.file_extensions, Some(vec![".pdf".to_string()]));
    }

    #[test]
    fn test_should_include_no_filter() {
        let config = S3Config::new("bucket");
        let connector = S3Connector::new(config);

        assert!(connector.should_include("file.pdf"));
        assert!(connector.should_include("file.txt"));
        assert!(connector.should_include("anything"));
    }

    #[test]
    fn test_should_include_with_filter() {
        let config = S3Config::new("bucket")
            .with_extensions(vec![".pdf".to_string(), ".docx".to_string()]);
        let connector = S3Connector::new(config);

        assert!(connector.should_include("file.pdf"));
        assert!(connector.should_include("file.PDF")); // Case insensitive
        assert!(connector.should_include("path/to/file.docx"));
        assert!(!connector.should_include("file.txt"));
    }

    #[test]
    fn test_get_filename() {
        assert_eq!(S3Connector::get_filename("file.txt"), "file.txt");
        assert_eq!(S3Connector::get_filename("path/to/file.txt"), "file.txt");
        assert_eq!(S3Connector::get_filename("deep/nested/path/doc.pdf"), "doc.pdf");
    }

    // Note: Integration tests for S3 operations require MinIO/LocalStack
    // and should be in a separate integration test file
}
