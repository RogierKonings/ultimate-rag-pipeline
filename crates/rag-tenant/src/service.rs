//! Tenant configuration service.

use crate::{IsolationMode, Result, TenantConfigCache, TenantError, TenantIndexConfig};
use rag_database::{DatabasePool, Tenant};
use std::sync::Arc;
use std::time::Duration;
use tracing::{debug, instrument, warn};
use uuid::Uuid;

/// Service for managing tenant configurations.
///
/// Provides cached access to tenant index configurations,
/// with fallback to database lookup on cache miss.
pub struct TenantConfigService<C: TenantConfigCache> {
    pool: DatabasePool,
    cache: Arc<C>,
    default_ttl: Duration,
}

impl<C: TenantConfigCache> TenantConfigService<C> {
    /// Create a new tenant config service.
    pub fn new(pool: DatabasePool, cache: C) -> Self {
        Self {
            pool,
            cache: Arc::new(cache),
            default_ttl: Duration::from_secs(300),
        }
    }

    /// Create with custom cache TTL.
    pub fn with_ttl(pool: DatabasePool, cache: C, ttl: Duration) -> Self {
        Self {
            pool,
            cache: Arc::new(cache),
            default_ttl: ttl,
        }
    }

    /// Get tenant index configuration with caching.
    ///
    /// First checks the cache, then falls back to database lookup.
    /// Caches the result on database hit.
    #[instrument(skip(self))]
    pub async fn get_config(&self, tenant_id: Uuid) -> Result<TenantIndexConfig> {
        // Try cache first
        if let Some(config) = self.cache.get(tenant_id).await? {
            debug!(tenant_id = %tenant_id, "Got tenant config from cache");
            return Ok(config);
        }

        // Cache miss - load from database
        debug!(tenant_id = %tenant_id, "Cache miss, loading from database");
        let config = self.load_from_database(tenant_id).await?;

        // Cache the result
        if let Err(e) = self.cache.set(&config, Some(self.default_ttl)).await {
            warn!(tenant_id = %tenant_id, error = %e, "Failed to cache tenant config");
        }

        Ok(config)
    }

    /// Create or update tenant index configuration.
    #[instrument(skip(self))]
    pub async fn create_config(&self, config: TenantIndexConfig) -> Result<()> {
        // For now, we just cache the config
        // In a full implementation, this would also persist to database
        self.cache.set(&config, Some(self.default_ttl)).await?;

        debug!(tenant_id = %config.tenant_id, "Created tenant config");
        Ok(())
    }

    /// Invalidate cached configuration for a tenant.
    #[instrument(skip(self))]
    pub async fn invalidate_cache(&self, tenant_id: Uuid) -> Result<()> {
        self.cache.invalidate(tenant_id).await?;
        debug!(tenant_id = %tenant_id, "Invalidated tenant config cache");
        Ok(())
    }

    /// Get the Qdrant collection name for a tenant.
    #[instrument(skip(self))]
    pub async fn get_qdrant_collection(&self, tenant_id: Uuid) -> Result<String> {
        let config = self.get_config(tenant_id).await?;
        Ok(config.qdrant_collection)
    }

    /// Get the OpenSearch index name for a tenant.
    #[instrument(skip(self))]
    pub async fn get_opensearch_index(&self, tenant_id: Uuid) -> Result<String> {
        let config = self.get_config(tenant_id).await?;
        Ok(config.opensearch_index)
    }

    /// Check if a tenant uses dedicated indices.
    #[instrument(skip(self))]
    pub async fn is_dedicated(&self, tenant_id: Uuid) -> Result<bool> {
        let config = self.get_config(tenant_id).await?;
        Ok(config.is_dedicated())
    }

    /// Load configuration from database.
    async fn load_from_database(&self, tenant_id: Uuid) -> Result<TenantIndexConfig> {
        let tenant: Option<Tenant> = sqlx::query_as(
            "SELECT * FROM tenants WHERE id = $1 AND deleted_at IS NULL",
        )
        .bind(tenant_id)
        .fetch_optional(self.pool.inner())
        .await
        .map_err(|e| TenantError::Database(e.to_string()))?;

        match tenant {
            Some(t) => Ok(self.build_config_from_tenant(&t)),
            None => Err(TenantError::NotFound(tenant_id)),
        }
    }

    /// Build index configuration from tenant record.
    fn build_config_from_tenant(&self, tenant: &Tenant) -> TenantIndexConfig {
        let isolation_mode = tenant
            .isolation_mode
            .parse::<IsolationMode>()
            .unwrap_or_default();

        match isolation_mode {
            IsolationMode::Shared => TenantIndexConfig::shared(tenant.id),
            IsolationMode::Dedicated => {
                let qdrant_collection = tenant
                    .qdrant_collection_name
                    .clone()
                    .unwrap_or_else(|| format!("documents_{}", tenant.id));
                let opensearch_index = tenant
                    .opensearch_index_name
                    .clone()
                    .unwrap_or_else(|| format!("documents-{}", tenant.id));

                let mut config = TenantIndexConfig::custom(
                    tenant.id,
                    qdrant_collection,
                    opensearch_index,
                    IsolationMode::Dedicated,
                );

                if let Some(settings) = &tenant.qdrant_settings {
                    config = config.with_qdrant_settings(settings.clone());
                }
                if let Some(settings) = &tenant.opensearch_settings {
                    config = config.with_opensearch_settings(settings.clone());
                }

                config
            }
        }
    }
}

impl<C: TenantConfigCache> std::fmt::Debug for TenantConfigService<C> {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("TenantConfigService")
            .field("default_ttl", &self.default_ttl)
            .finish_non_exhaustive()
    }
}
