//! Embedding cache for storing and retrieving vector embeddings.

use crate::client::CacheClient;
use crate::config::CacheConfig;
use crate::error::Result;
use crate::keys::{content_hash, CacheKey, KeyType, ServicePrefix};
use rag_types::{Embedding, TenantId};
use std::collections::HashMap;
use tracing::{debug, instrument};

/// Specialized cache for embedding vectors.
///
/// Embeddings are cached by content hash to avoid re-computing
/// embeddings for the same text.
#[derive(Clone)]
pub struct EmbeddingCache {
    client: CacheClient,
    service: ServicePrefix,
}

impl EmbeddingCache {
    /// Create a new embedding cache.
    #[must_use]
    pub fn new(client: CacheClient, service: ServicePrefix) -> Self {
        Self { client, service }
    }

    /// Connect and create an embedding cache.
    ///
    /// # Errors
    ///
    /// Returns an error if the connection fails.
    pub async fn connect(config: &CacheConfig, service: ServicePrefix) -> Result<Self> {
        let client = CacheClient::connect(config).await?;
        Ok(Self::new(client, service))
    }

    /// Get a cached embedding by content.
    ///
    /// # Errors
    ///
    /// Returns an error if the cache operation fails.
    #[instrument(skip(self, content), fields(content_len = content.len()))]
    pub async fn get(&self, tenant_id: TenantId, content: &str) -> Result<Option<Embedding>> {
        let key = CacheKey::embedding(self.service, tenant_id, content);
        let values: Option<Vec<f32>> = self.client.get_key(&key).await?;

        match values {
            Some(v) => {
                debug!(key = %key, "Embedding cache hit");
                Ok(Some(Embedding::new(v)))
            }
            None => {
                debug!(key = %key, "Embedding cache miss");
                Ok(None)
            }
        }
    }

    /// Get a cached embedding by content hash.
    ///
    /// Use this when you already have the content hash.
    #[instrument(skip(self))]
    pub async fn get_by_hash(&self, tenant_id: TenantId, hash: &str) -> Result<Option<Embedding>> {
        let key = CacheKey::new(self.service, KeyType::Embedding, tenant_id, hash);
        let values: Option<Vec<f32>> = self.client.get_key(&key).await?;
        Ok(values.map(Embedding::new))
    }

    /// Store an embedding in the cache.
    ///
    /// # Errors
    ///
    /// Returns an error if the cache operation fails.
    #[instrument(skip(self, content, embedding), fields(content_len = content.len(), dim = embedding.dimension()))]
    pub async fn set(
        &self,
        tenant_id: TenantId,
        content: &str,
        embedding: &Embedding,
    ) -> Result<()> {
        let key = CacheKey::embedding(self.service, tenant_id, content);
        let ttl = self.client.config().embedding_ttl();

        self.client
            .set_key(&key, &embedding.as_slice(), Some(ttl))
            .await?;

        debug!(key = %key, "Cached embedding");
        Ok(())
    }

    /// Store an embedding by content hash.
    ///
    /// Use this when you already have the content hash.
    #[instrument(skip(self, embedding), fields(dim = embedding.dimension()))]
    pub async fn set_by_hash(
        &self,
        tenant_id: TenantId,
        hash: &str,
        embedding: &Embedding,
    ) -> Result<()> {
        let key = CacheKey::new(self.service, KeyType::Embedding, tenant_id, hash);
        let ttl = self.client.config().embedding_ttl();

        self.client
            .set_key(&key, &embedding.as_slice(), Some(ttl))
            .await?;

        Ok(())
    }

    /// Get multiple embeddings by content.
    ///
    /// Returns a map from content hash to embedding for found entries.
    #[instrument(skip(self, contents), fields(count = contents.len()))]
    pub async fn get_many(
        &self,
        tenant_id: TenantId,
        contents: &[&str],
    ) -> Result<HashMap<String, Embedding>> {
        if contents.is_empty() {
            return Ok(HashMap::new());
        }

        // Build keys
        let hashes: Vec<String> = contents.iter().map(|c| content_hash(c)).collect();
        let keys: Vec<String> = hashes
            .iter()
            .map(|h| CacheKey::new(self.service, KeyType::Embedding, tenant_id, h).to_string())
            .collect();

        let key_refs: Vec<&str> = keys.iter().map(String::as_str).collect();
        let values: Vec<Option<Vec<f32>>> = self.client.mget(&key_refs).await?;

        let mut result = HashMap::new();
        for (hash, value) in hashes.into_iter().zip(values) {
            if let Some(v) = value {
                result.insert(hash, Embedding::new(v));
            }
        }

        debug!(
            found = result.len(),
            total = contents.len(),
            "Batch embedding cache lookup"
        );

        Ok(result)
    }

    /// Store multiple embeddings.
    ///
    /// The pairs should be (content, embedding).
    #[instrument(skip(self, pairs), fields(count = pairs.len()))]
    pub async fn set_many(&self, tenant_id: TenantId, pairs: &[(&str, &Embedding)]) -> Result<()> {
        if pairs.is_empty() {
            return Ok(());
        }

        let ttl = self.client.config().embedding_ttl();

        // Convert to key-value pairs
        let cache_pairs: Vec<(String, Vec<f32>)> = pairs
            .iter()
            .map(|(content, embedding)| {
                let key = CacheKey::embedding(self.service, tenant_id, content).to_string();
                (key, embedding.as_slice().to_vec())
            })
            .collect();

        let refs: Vec<(&str, &Vec<f32>)> =
            cache_pairs.iter().map(|(k, v)| (k.as_str(), v)).collect();

        self.client.mset(&refs, Some(ttl)).await?;

        debug!(count = pairs.len(), "Batch cached embeddings");
        Ok(())
    }

    /// Delete a cached embedding.
    #[instrument(skip(self, content))]
    pub async fn delete(&self, tenant_id: TenantId, content: &str) -> Result<bool> {
        let key = CacheKey::embedding(self.service, tenant_id, content);
        self.client.delete_key(&key).await
    }

    /// Get the underlying cache client.
    #[must_use]
    pub fn client(&self) -> &CacheClient {
        &self.client
    }
}

impl std::fmt::Debug for EmbeddingCache {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("EmbeddingCache")
            .field("service", &self.service)
            .finish_non_exhaustive()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    #[ignore = "requires Redis"]
    async fn test_embedding_cache() {
        let config = CacheConfig::default();
        let cache = EmbeddingCache::connect(&config, ServicePrefix::Ingestion)
            .await
            .unwrap();

        let tenant_id = TenantId::new();
        let content = "Hello, world!";
        let embedding = Embedding::new(vec![0.1, 0.2, 0.3, 0.4]);

        // Initially not cached
        let result = cache.get(tenant_id, content).await.unwrap();
        assert!(result.is_none());

        // Cache it
        cache.set(tenant_id, content, &embedding).await.unwrap();

        // Now it should be found
        let result = cache.get(tenant_id, content).await.unwrap();
        assert!(result.is_some());
        assert_eq!(result.unwrap().dimension(), 4);

        // Delete it
        let deleted = cache.delete(tenant_id, content).await.unwrap();
        assert!(deleted);

        // Should be gone
        let result = cache.get(tenant_id, content).await.unwrap();
        assert!(result.is_none());
    }

    #[tokio::test]
    #[ignore = "requires Redis"]
    async fn test_batch_operations() {
        let config = CacheConfig::default();
        let cache = EmbeddingCache::connect(&config, ServicePrefix::Retrieval)
            .await
            .unwrap();

        let tenant_id = TenantId::new();
        let contents = ["First text", "Second text", "Third text"];
        let embeddings = [
            Embedding::new(vec![0.1, 0.2]),
            Embedding::new(vec![0.3, 0.4]),
            Embedding::new(vec![0.5, 0.6]),
        ];

        // Store batch
        let pairs: Vec<(&str, &Embedding)> = contents
            .iter()
            .zip(embeddings.iter())
            .map(|(c, e)| (*c, e))
            .collect();
        cache.set_many(tenant_id, &pairs).await.unwrap();

        // Retrieve batch
        let refs: Vec<&str> = contents.to_vec();
        let found = cache.get_many(tenant_id, &refs).await.unwrap();
        assert_eq!(found.len(), 3);

        // Cleanup
        for content in contents {
            cache.delete(tenant_id, content).await.unwrap();
        }
    }
}
