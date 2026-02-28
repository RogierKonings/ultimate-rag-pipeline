//! S3/MinIO storage client.

use std::time::Duration;

use aws_sdk_s3::{
    config::{Credentials, Region},
    presigning::PresigningConfig,
    primitives::ByteStream,
    Client,
};
use bytes::Bytes;
use tracing::instrument;

use crate::{Result, StorageConfig, StorageError};

/// S3/MinIO storage client.
#[derive(Clone)]
pub struct StorageClient {
    client: Client,
    default_bucket: Option<String>,
}

impl StorageClient {
    /// Create a new storage client.
    ///
    /// # Errors
    ///
    /// Returns an error if the client cannot be configured.
    pub async fn new(config: &StorageConfig) -> Result<Self> {
        let mut sdk_config_builder = aws_config::defaults(aws_config::BehaviorVersion::latest())
            .region(Region::new(config.region.clone()));

        // Set endpoint URL for MinIO or custom S3-compatible services
        if let Some(endpoint) = &config.endpoint_url {
            sdk_config_builder = sdk_config_builder.endpoint_url(endpoint);
        }

        // Set credentials if provided
        if let (Some(access_key), Some(secret_key)) =
            (&config.access_key_id, &config.secret_access_key)
        {
            let credentials = Credentials::new(
                access_key,
                secret_key,
                None, // session token
                None, // expiry
                "rag-storage",
            );
            sdk_config_builder = sdk_config_builder.credentials_provider(credentials);
        }

        let sdk_config = sdk_config_builder.load().await;

        // Build S3 client with additional config
        let mut s3_config_builder = aws_sdk_s3::config::Builder::from(&sdk_config);

        if config.force_path_style {
            s3_config_builder = s3_config_builder.force_path_style(true);
        }

        let client = Client::from_conf(s3_config_builder.build());

        Ok(Self {
            client,
            default_bucket: config.default_bucket.clone(),
        })
    }

    fn resolve_bucket<'a>(&'a self, bucket: Option<&'a str>) -> Result<&'a str> {
        bucket.or(self.default_bucket.as_deref()).ok_or_else(|| {
            StorageError::Config("No bucket specified and no default bucket set".into())
        })
    }

    /// Create a bucket.
    ///
    /// # Errors
    ///
    /// Returns an error if bucket creation fails.
    #[instrument(skip(self))]
    pub async fn create_bucket(&self, bucket: &str) -> Result<()> {
        self.client.create_bucket().bucket(bucket).send().await?;

        tracing::info!(bucket, "Created bucket");
        Ok(())
    }

    /// Delete a bucket.
    ///
    /// # Errors
    ///
    /// Returns an error if bucket deletion fails.
    #[instrument(skip(self))]
    pub async fn delete_bucket(&self, bucket: &str) -> Result<()> {
        self.client.delete_bucket().bucket(bucket).send().await?;

        tracing::info!(bucket, "Deleted bucket");
        Ok(())
    }

    /// Check if a bucket exists.
    ///
    /// # Errors
    ///
    /// Returns an error if the check fails (other than not found).
    #[instrument(skip(self))]
    pub async fn bucket_exists(&self, bucket: &str) -> Result<bool> {
        match self.client.head_bucket().bucket(bucket).send().await {
            Ok(_) => Ok(true),
            Err(err) => {
                let service_err = err.into_service_error();
                if service_err.is_not_found() {
                    Ok(false)
                } else {
                    Err(StorageError::S3(format!("{service_err:?}")))
                }
            }
        }
    }

    /// List buckets.
    ///
    /// # Errors
    ///
    /// Returns an error if listing fails.
    #[instrument(skip(self))]
    pub async fn list_buckets(&self) -> Result<Vec<String>> {
        let response = self.client.list_buckets().send().await?;

        let buckets = response
            .buckets()
            .iter()
            .filter_map(|b| b.name().map(String::from))
            .collect();

        Ok(buckets)
    }

    /// Upload an object.
    ///
    /// # Errors
    ///
    /// Returns an error if upload fails.
    #[instrument(skip(self, data), fields(data_len = data.len()))]
    pub async fn put_object(&self, bucket: Option<&str>, key: &str, data: Vec<u8>) -> Result<()> {
        let bucket = self.resolve_bucket(bucket)?;
        let content_type = mime_guess::from_path(key)
            .first_or_octet_stream()
            .to_string();

        self.client
            .put_object()
            .bucket(bucket)
            .key(key)
            .body(ByteStream::from(data))
            .content_type(content_type)
            .send()
            .await?;

        tracing::debug!(bucket, key, "Uploaded object");
        Ok(())
    }

    /// Upload an object from bytes.
    ///
    /// # Errors
    ///
    /// Returns an error if upload fails.
    pub async fn put_object_bytes(
        &self,
        bucket: Option<&str>,
        key: &str,
        data: Bytes,
    ) -> Result<()> {
        let bucket = self.resolve_bucket(bucket)?;
        let content_type = mime_guess::from_path(key)
            .first_or_octet_stream()
            .to_string();

        self.client
            .put_object()
            .bucket(bucket)
            .key(key)
            .body(ByteStream::from(data))
            .content_type(content_type)
            .send()
            .await?;

        Ok(())
    }

    /// Download an object.
    ///
    /// # Errors
    ///
    /// Returns an error if download fails.
    #[instrument(skip(self))]
    pub async fn get_object(&self, bucket: Option<&str>, key: &str) -> Result<Vec<u8>> {
        let bucket = self.resolve_bucket(bucket)?;

        let response = self
            .client
            .get_object()
            .bucket(bucket)
            .key(key)
            .send()
            .await
            .map_err(|e| {
                let service_err = e.into_service_error();
                if service_err.is_no_such_key() {
                    StorageError::ObjectNotFound {
                        bucket: bucket.to_string(),
                        key: key.to_string(),
                    }
                } else {
                    StorageError::S3(format!("{service_err:?}"))
                }
            })?;

        let data = response
            .body
            .collect()
            .await
            .map_err(|e| StorageError::S3(e.to_string()))?
            .into_bytes()
            .to_vec();

        tracing::debug!(bucket, key, size = data.len(), "Downloaded object");
        Ok(data)
    }

    /// Download an object as bytes.
    ///
    /// # Errors
    ///
    /// Returns an error if download fails.
    pub async fn get_object_bytes(&self, bucket: Option<&str>, key: &str) -> Result<Bytes> {
        let bucket = self.resolve_bucket(bucket)?;

        let response = self
            .client
            .get_object()
            .bucket(bucket)
            .key(key)
            .send()
            .await
            .map_err(|e| {
                let service_err = e.into_service_error();
                if service_err.is_no_such_key() {
                    StorageError::ObjectNotFound {
                        bucket: bucket.to_string(),
                        key: key.to_string(),
                    }
                } else {
                    StorageError::S3(format!("{service_err:?}"))
                }
            })?;

        let bytes = response
            .body
            .collect()
            .await
            .map_err(|e| StorageError::S3(e.to_string()))?
            .into_bytes();

        Ok(bytes)
    }

    /// Delete an object.
    ///
    /// # Errors
    ///
    /// Returns an error if deletion fails.
    #[instrument(skip(self))]
    pub async fn delete_object(&self, bucket: Option<&str>, key: &str) -> Result<()> {
        let bucket = self.resolve_bucket(bucket)?;

        self.client
            .delete_object()
            .bucket(bucket)
            .key(key)
            .send()
            .await?;

        tracing::debug!(bucket, key, "Deleted object");
        Ok(())
    }

    /// Check if an object exists.
    ///
    /// # Errors
    ///
    /// Returns an error if the check fails (other than not found).
    #[instrument(skip(self))]
    pub async fn object_exists(&self, bucket: Option<&str>, key: &str) -> Result<bool> {
        let bucket = self.resolve_bucket(bucket)?;

        match self
            .client
            .head_object()
            .bucket(bucket)
            .key(key)
            .send()
            .await
        {
            Ok(_) => Ok(true),
            Err(err) => {
                let service_err = err.into_service_error();
                if service_err.is_not_found() {
                    Ok(false)
                } else {
                    Err(StorageError::S3(format!("{service_err:?}")))
                }
            }
        }
    }

    /// List objects in a bucket with optional prefix.
    ///
    /// # Errors
    ///
    /// Returns an error if listing fails.
    #[instrument(skip(self))]
    pub async fn list_objects(
        &self,
        bucket: Option<&str>,
        prefix: Option<&str>,
    ) -> Result<Vec<String>> {
        let bucket = self.resolve_bucket(bucket)?;

        let mut request = self.client.list_objects_v2().bucket(bucket);

        if let Some(p) = prefix {
            request = request.prefix(p);
        }

        let response = request.send().await?;

        let keys = response
            .contents()
            .iter()
            .filter_map(|obj| obj.key().map(String::from))
            .collect();

        Ok(keys)
    }

    /// Generate a presigned GET URL.
    ///
    /// # Errors
    ///
    /// Returns an error if URL generation fails.
    #[instrument(skip(self))]
    pub async fn presigned_get_url(
        &self,
        bucket: Option<&str>,
        key: &str,
        expires_in_secs: u64,
    ) -> Result<String> {
        let bucket = self.resolve_bucket(bucket)?;

        let presigning_config = PresigningConfig::expires_in(Duration::from_secs(expires_in_secs))
            .map_err(|e| StorageError::PresignedUrl(e.to_string()))?;

        let presigned = self
            .client
            .get_object()
            .bucket(bucket)
            .key(key)
            .presigned(presigning_config)
            .await
            .map_err(|e| StorageError::PresignedUrl(e.to_string()))?;

        Ok(presigned.uri().to_string())
    }

    /// Generate a presigned PUT URL.
    ///
    /// # Errors
    ///
    /// Returns an error if URL generation fails.
    #[instrument(skip(self))]
    pub async fn presigned_put_url(
        &self,
        bucket: Option<&str>,
        key: &str,
        expires_in_secs: u64,
    ) -> Result<String> {
        let bucket = self.resolve_bucket(bucket)?;

        let presigning_config = PresigningConfig::expires_in(Duration::from_secs(expires_in_secs))
            .map_err(|e| StorageError::PresignedUrl(e.to_string()))?;

        let presigned = self
            .client
            .put_object()
            .bucket(bucket)
            .key(key)
            .presigned(presigning_config)
            .await
            .map_err(|e| StorageError::PresignedUrl(e.to_string()))?;

        Ok(presigned.uri().to_string())
    }

    /// Copy an object within S3.
    ///
    /// # Errors
    ///
    /// Returns an error if copy fails.
    #[instrument(skip(self))]
    pub async fn copy_object(
        &self,
        source_bucket: Option<&str>,
        source_key: &str,
        dest_bucket: Option<&str>,
        dest_key: &str,
    ) -> Result<()> {
        let source_bucket = self.resolve_bucket(source_bucket)?;
        let dest_bucket = self.resolve_bucket(dest_bucket)?;

        let copy_source = format!("{source_bucket}/{source_key}");

        self.client
            .copy_object()
            .copy_source(&copy_source)
            .bucket(dest_bucket)
            .key(dest_key)
            .send()
            .await?;

        tracing::debug!(
            source_bucket,
            source_key,
            dest_bucket,
            dest_key,
            "Copied object"
        );
        Ok(())
    }
}

impl std::fmt::Debug for StorageClient {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("StorageClient")
            .field("default_bucket", &self.default_bucket)
            .finish_non_exhaustive()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // Integration tests would require a running MinIO instance.
    // These are placeholder tests.

    #[test]
    fn test_storage_client_debug() {
        // Just verify the Debug impl doesn't panic
        let config = StorageConfig::default();
        let _debug = format!("{config:?}");
    }
}
