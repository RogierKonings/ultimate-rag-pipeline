//! Redis-backed cache for tenant configurations.

use crate::{Result, TenantError, TenantIndexConfig};
use async_trait::async_trait;
use std::time::Duration;
use tracing::{debug, instrument, warn};
use uuid::Uuid;

/// Cache key prefix for tenant configs.
const CACHE_PREFIX: &str = "tenant:config:";

/// Default cache TTL (5 minutes).
const DEFAULT_TTL: Duration = Duration::from_secs(300);

/// Trait for tenant config caching.
#[async_trait]
pub trait TenantConfigCache: Send + Sync {
    /// Get a cached tenant configuration.
    async fn get(&self, tenant_id: Uuid) -> Result<Option<TenantIndexConfig>>;

    /// Set a tenant configuration in cache.
    async fn set(&self, config: &TenantIndexConfig, ttl: Option<Duration>) -> Result<()>;

    /// Invalidate a cached tenant configuration.
    async fn invalidate(&self, tenant_id: Uuid) -> Result<()>;
}

/// In-memory cache implementation for testing.
#[derive(Debug, Default)]
pub struct InMemoryCache {
    cache: std::sync::RwLock<std::collections::HashMap<Uuid, TenantIndexConfig>>,
}

impl InMemoryCache {
    /// Create a new in-memory cache.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }
}

#[async_trait]
impl TenantConfigCache for InMemoryCache {
    #[instrument(skip(self))]
    async fn get(&self, tenant_id: Uuid) -> Result<Option<TenantIndexConfig>> {
        let cache = self.cache.read().map_err(|e| TenantError::Cache(e.to_string()))?;
        Ok(cache.get(&tenant_id).cloned())
    }

    #[instrument(skip(self))]
    async fn set(&self, config: &TenantIndexConfig, _ttl: Option<Duration>) -> Result<()> {
        let mut cache = self.cache.write().map_err(|e| TenantError::Cache(e.to_string()))?;
        cache.insert(config.tenant_id, config.clone());
        Ok(())
    }

    #[instrument(skip(self))]
    async fn invalidate(&self, tenant_id: Uuid) -> Result<()> {
        let mut cache = self.cache.write().map_err(|e| TenantError::Cache(e.to_string()))?;
        cache.remove(&tenant_id);
        Ok(())
    }
}

/// Redis-backed cache implementation.
pub struct RedisCache {
    client: rag_cache::CacheClient,
    ttl: Duration,
}

impl RedisCache {
    /// Create a new Redis cache.
    #[must_use]
    pub fn new(client: rag_cache::CacheClient) -> Self {
        Self {
            client,
            ttl: DEFAULT_TTL,
        }
    }

    /// Create with custom TTL.
    #[must_use]
    pub fn with_ttl(client: rag_cache::CacheClient, ttl: Duration) -> Self {
        Self { client, ttl }
    }

    /// Build the cache key for a tenant.
    fn cache_key(tenant_id: Uuid) -> String {
        format!("{}{}", CACHE_PREFIX, tenant_id)
    }
}

#[async_trait]
impl TenantConfigCache for RedisCache {
    #[instrument(skip(self))]
    async fn get(&self, tenant_id: Uuid) -> Result<Option<TenantIndexConfig>> {
        let key = Self::cache_key(tenant_id);
        debug!(key = %key, "Getting tenant config from cache");

        match self.client.get::<TenantIndexConfig>(&key).await {
            Ok(Some(config)) => {
                debug!(tenant_id = %tenant_id, "Cache hit for tenant config");
                Ok(Some(config))
            }
            Ok(None) => {
                debug!(tenant_id = %tenant_id, "Cache miss for tenant config");
                Ok(None)
            }
            Err(e) => {
                warn!(tenant_id = %tenant_id, error = %e, "Cache error, treating as miss");
                Ok(None)
            }
        }
    }

    #[instrument(skip(self))]
    async fn set(&self, config: &TenantIndexConfig, ttl: Option<Duration>) -> Result<()> {
        let key = Self::cache_key(config.tenant_id);
        let cache_ttl = ttl.unwrap_or(self.ttl);

        debug!(key = %key, ttl_secs = cache_ttl.as_secs(), "Setting tenant config in cache");

        self.client
            .set(&key, config, Some(cache_ttl))
            .await
            .map_err(|e| TenantError::Cache(e.to_string()))?;

        Ok(())
    }

    #[instrument(skip(self))]
    async fn invalidate(&self, tenant_id: Uuid) -> Result<()> {
        let key = Self::cache_key(tenant_id);
        debug!(key = %key, "Invalidating tenant config cache");

        self.client
            .delete(&key)
            .await
            .map_err(|e| TenantError::Cache(e.to_string()))?;

        Ok(())
    }
}

impl std::fmt::Debug for RedisCache {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("RedisCache")
            .field("ttl", &self.ttl)
            .finish_non_exhaustive()
    }
}
