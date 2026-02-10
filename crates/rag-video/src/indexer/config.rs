//! Configuration for video indexing operations.

/// Configuration for the video Qdrant indexer.
#[derive(Debug, Clone)]
pub struct VideoIndexerConfig {
    /// Qdrant server URL.
    pub qdrant_url: String,
    /// Name of the Qdrant collection for video chunks.
    pub collection_name: String,
    /// Vector dimension size (must match embedding model).
    pub vector_size: usize,
    /// Batch size for upsert operations.
    pub batch_size: usize,
    /// Timeout in seconds for Qdrant operations.
    pub timeout_seconds: u64,
    /// HNSW index parameter M (number of bi-directional links).
    pub hnsw_m: u64,
    /// HNSW index parameter `ef_construct` (size of dynamic candidate list).
    pub hnsw_ef_construct: u64,
}

impl Default for VideoIndexerConfig {
    fn default() -> Self {
        Self {
            qdrant_url: "http://localhost:6333".to_string(),
            collection_name: "video_chunks".to_string(),
            vector_size: 384, // bge-small-en-v1.5
            batch_size: 100,
            timeout_seconds: 60,
            hnsw_m: 16,
            hnsw_ef_construct: 100,
        }
    }
}

impl VideoIndexerConfig {
    /// Creates a new configuration with default values.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Sets the Qdrant URL.
    #[must_use]
    pub fn with_qdrant_url(mut self, url: impl Into<String>) -> Self {
        self.qdrant_url = url.into();
        self
    }

    /// Sets the collection name.
    #[must_use]
    pub fn with_collection_name(mut self, name: impl Into<String>) -> Self {
        self.collection_name = name.into();
        self
    }

    /// Sets the vector size.
    #[must_use]
    pub const fn with_vector_size(mut self, size: usize) -> Self {
        self.vector_size = size;
        self
    }

    /// Sets the batch size.
    #[must_use]
    pub const fn with_batch_size(mut self, size: usize) -> Self {
        self.batch_size = size;
        self
    }

    /// Sets the timeout in seconds.
    #[must_use]
    pub const fn with_timeout_seconds(mut self, timeout: u64) -> Self {
        self.timeout_seconds = timeout;
        self
    }

    /// Sets the HNSW M parameter.
    #[must_use]
    pub const fn with_hnsw_m(mut self, m: u64) -> Self {
        self.hnsw_m = m;
        self
    }

    /// Sets the HNSW `ef_construct` parameter.
    #[must_use]
    pub const fn with_hnsw_ef_construct(mut self, ef_construct: u64) -> Self {
        self.hnsw_ef_construct = ef_construct;
        self
    }

    /// Validates the configuration.
    ///
    /// # Returns
    ///
    /// Returns `Ok(())` if valid, otherwise returns an error message.
    pub fn validate(&self) -> Result<(), String> {
        if self.qdrant_url.is_empty() {
            return Err("qdrant_url cannot be empty".to_string());
        }

        if self.collection_name.is_empty() {
            return Err("collection_name cannot be empty".to_string());
        }

        if self.vector_size == 0 {
            return Err("vector_size must be greater than 0".to_string());
        }

        if self.batch_size == 0 {
            return Err("batch_size must be greater than 0".to_string());
        }

        if self.timeout_seconds == 0 {
            return Err("timeout_seconds must be greater than 0".to_string());
        }

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_video_indexer_config_default() {
        let config = VideoIndexerConfig::default();
        assert_eq!(config.qdrant_url, "http://localhost:6333");
        assert_eq!(config.collection_name, "video_chunks");
        assert_eq!(config.vector_size, 384);
        assert_eq!(config.batch_size, 100);
        assert_eq!(config.timeout_seconds, 60);
        assert_eq!(config.hnsw_m, 16);
        assert_eq!(config.hnsw_ef_construct, 100);
    }

    #[test]
    fn test_video_indexer_config_new() {
        let config = VideoIndexerConfig::new();
        assert_eq!(config.qdrant_url, "http://localhost:6333");
    }

    #[test]
    fn test_video_indexer_config_builder() {
        let config = VideoIndexerConfig::new()
            .with_qdrant_url("http://custom:6333")
            .with_collection_name("custom_collection")
            .with_vector_size(768)
            .with_batch_size(50)
            .with_timeout_seconds(120)
            .with_hnsw_m(32)
            .with_hnsw_ef_construct(200);

        assert_eq!(config.qdrant_url, "http://custom:6333");
        assert_eq!(config.collection_name, "custom_collection");
        assert_eq!(config.vector_size, 768);
        assert_eq!(config.batch_size, 50);
        assert_eq!(config.timeout_seconds, 120);
        assert_eq!(config.hnsw_m, 32);
        assert_eq!(config.hnsw_ef_construct, 200);
    }

    #[test]
    fn test_video_indexer_config_validate_success() {
        let config = VideoIndexerConfig::default();
        assert!(config.validate().is_ok());
    }

    #[test]
    fn test_video_indexer_config_validate_empty_url() {
        let config = VideoIndexerConfig::new().with_qdrant_url("");
        let result = config.validate();
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("qdrant_url"));
    }

    #[test]
    fn test_video_indexer_config_validate_empty_collection() {
        let config = VideoIndexerConfig::new().with_collection_name("");
        let result = config.validate();
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("collection_name"));
    }

    #[test]
    fn test_video_indexer_config_validate_zero_vector_size() {
        let config = VideoIndexerConfig::new().with_vector_size(0);
        let result = config.validate();
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("vector_size"));
    }

    #[test]
    fn test_video_indexer_config_validate_zero_batch_size() {
        let config = VideoIndexerConfig::new().with_batch_size(0);
        let result = config.validate();
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("batch_size"));
    }

    #[test]
    fn test_video_indexer_config_validate_zero_timeout() {
        let config = VideoIndexerConfig::new().with_timeout_seconds(0);
        let result = config.validate();
        assert!(result.is_err());
        assert!(result.unwrap_err().contains("timeout_seconds"));
    }

    #[test]
    fn test_video_indexer_config_clone() {
        let config = VideoIndexerConfig::default();
        let cloned = config.clone();
        assert_eq!(config.qdrant_url, cloned.qdrant_url);
        assert_eq!(config.collection_name, cloned.collection_name);
    }

    #[test]
    fn test_video_indexer_config_debug() {
        let config = VideoIndexerConfig::default();
        let debug = format!("{config:?}");
        assert!(debug.contains("VideoIndexerConfig"));
        assert!(debug.contains("qdrant_url"));
    }
}
