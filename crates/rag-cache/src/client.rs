//! Redis cache client implementation.

use crate::config::CacheConfig;
use crate::error::{CacheError, Result};
use crate::keys::CacheKey;
use redis::aio::ConnectionManager;
use redis::{AsyncCommands, Client};
use serde::{de::DeserializeOwned, Serialize};
use std::time::Duration;
use tracing::{debug, instrument, warn};

/// Async Redis cache client with connection pooling.
#[derive(Clone)]
pub struct CacheClient {
    /// Connection manager (handles reconnection)
    conn: ConnectionManager,
    /// Configuration
    config: CacheConfig,
}

impl CacheClient {
    /// Connect to Redis with the given configuration.
    ///
    /// # Errors
    ///
    /// Returns an error if the connection fails.
    #[instrument(skip(config), fields(url = %config.url))]
    pub async fn connect(config: &CacheConfig) -> Result<Self> {
        debug!("Connecting to Redis");

        let client = Client::open(config.url.as_str())
            .map_err(|e| CacheError::connection(format!("Failed to create client: {e}")))?;

        let conn = ConnectionManager::new(client)
            .await
            .map_err(|e| CacheError::connection(format!("Failed to connect: {e}")))?;

        debug!("Successfully connected to Redis");

        Ok(Self {
            conn,
            config: config.clone(),
        })
    }

    /// Get the configuration.
    #[must_use]
    pub fn config(&self) -> &CacheConfig {
        &self.config
    }

    /// Check if the connection is healthy.
    #[instrument(skip(self))]
    pub async fn health_check(&self) -> Result<()> {
        let mut conn = self.conn.clone();
        let _: String = redis::cmd("PING")
            .query_async(&mut conn)
            .await
            .map_err(CacheError::Redis)?;
        Ok(())
    }

    // ─────────────────────────────────────────────────────────────────────────
    // Basic operations
    // ─────────────────────────────────────────────────────────────────────────

    /// Get a value by key.
    ///
    /// # Errors
    ///
    /// Returns an error if the operation fails or deserialization fails.
    #[instrument(skip(self))]
    pub async fn get<T: DeserializeOwned>(&self, key: &str) -> Result<Option<T>> {
        let mut conn = self.conn.clone();
        let full_key = self.prefixed_key(key);

        let value: Option<String> = conn.get(&full_key).await?;

        match value {
            Some(v) => {
                let parsed = serde_json::from_str(&v)?;
                Ok(Some(parsed))
            }
            None => Ok(None),
        }
    }

    /// Get a value using a structured cache key.
    #[instrument(skip(self))]
    pub async fn get_key<T: DeserializeOwned>(&self, key: &CacheKey) -> Result<Option<T>> {
        self.get(&key.to_string()).await
    }

    /// Set a value with optional TTL.
    ///
    /// If no TTL is provided, uses the default TTL from config.
    ///
    /// # Errors
    ///
    /// Returns an error if the operation fails or serialization fails.
    #[instrument(skip(self, value))]
    pub async fn set<T: Serialize>(
        &self,
        key: &str,
        value: &T,
        ttl: Option<Duration>,
    ) -> Result<()> {
        let mut conn = self.conn.clone();
        let full_key = self.prefixed_key(key);
        let serialized = serde_json::to_string(value)?;
        let ttl_secs = ttl.unwrap_or(self.config.default_ttl()).as_secs();

        conn.set_ex::<_, _, ()>(&full_key, &serialized, ttl_secs)
            .await?;

        debug!(key = %key, ttl_secs = ttl_secs, "Set cache value");
        Ok(())
    }

    /// Set a value using a structured cache key.
    #[instrument(skip(self, value))]
    pub async fn set_key<T: Serialize>(
        &self,
        key: &CacheKey,
        value: &T,
        ttl: Option<Duration>,
    ) -> Result<()> {
        self.set(&key.to_string(), value, ttl).await
    }

    /// Delete a key.
    ///
    /// # Errors
    ///
    /// Returns an error if the operation fails.
    #[instrument(skip(self))]
    pub async fn delete(&self, key: &str) -> Result<bool> {
        let mut conn = self.conn.clone();
        let full_key = self.prefixed_key(key);
        let deleted: i64 = conn.del(&full_key).await?;
        Ok(deleted > 0)
    }

    /// Delete a key using a structured cache key.
    #[instrument(skip(self))]
    pub async fn delete_key(&self, key: &CacheKey) -> Result<bool> {
        self.delete(&key.to_string()).await
    }

    /// Check if a key exists.
    #[instrument(skip(self))]
    pub async fn exists(&self, key: &str) -> Result<bool> {
        let mut conn = self.conn.clone();
        let full_key = self.prefixed_key(key);
        let exists: bool = conn.exists(&full_key).await?;
        Ok(exists)
    }

    /// Set the TTL on an existing key.
    #[instrument(skip(self))]
    pub async fn expire(&self, key: &str, ttl: Duration) -> Result<bool> {
        let mut conn = self.conn.clone();
        let full_key = self.prefixed_key(key);
        let set: bool = conn.expire(&full_key, ttl.as_secs() as i64).await?;
        Ok(set)
    }

    // ─────────────────────────────────────────────────────────────────────────
    // Hash operations
    // ─────────────────────────────────────────────────────────────────────────

    /// Get a field from a hash.
    #[instrument(skip(self))]
    pub async fn hget<T: DeserializeOwned>(&self, key: &str, field: &str) -> Result<Option<T>> {
        let mut conn = self.conn.clone();
        let full_key = self.prefixed_key(key);

        let value: Option<String> = conn.hget(&full_key, field).await?;

        match value {
            Some(v) => {
                let parsed = serde_json::from_str(&v)?;
                Ok(Some(parsed))
            }
            None => Ok(None),
        }
    }

    /// Set a field in a hash.
    #[instrument(skip(self, value))]
    pub async fn hset<T: Serialize>(&self, key: &str, field: &str, value: &T) -> Result<()> {
        let mut conn = self.conn.clone();
        let full_key = self.prefixed_key(key);
        let serialized = serde_json::to_string(value)?;

        conn.hset::<_, _, _, ()>(&full_key, field, &serialized)
            .await?;
        Ok(())
    }

    /// Get all fields from a hash.
    #[instrument(skip(self))]
    pub async fn hgetall<T: DeserializeOwned>(&self, key: &str) -> Result<Vec<(String, T)>> {
        let mut conn = self.conn.clone();
        let full_key = self.prefixed_key(key);

        let values: Vec<(String, String)> = conn.hgetall(&full_key).await?;

        let mut result = Vec::with_capacity(values.len());
        for (field, value) in values {
            match serde_json::from_str(&value) {
                Ok(parsed) => result.push((field, parsed)),
                Err(e) => {
                    warn!(field = %field, error = %e, "Failed to deserialize hash field");
                }
            }
        }

        Ok(result)
    }

    /// Delete a field from a hash.
    #[instrument(skip(self))]
    pub async fn hdel(&self, key: &str, field: &str) -> Result<bool> {
        let mut conn = self.conn.clone();
        let full_key = self.prefixed_key(key);
        let deleted: i64 = conn.hdel(&full_key, field).await?;
        Ok(deleted > 0)
    }

    // ─────────────────────────────────────────────────────────────────────────
    // Batch operations
    // ─────────────────────────────────────────────────────────────────────────

    /// Get multiple values by keys.
    #[instrument(skip(self, keys))]
    pub async fn mget<T: DeserializeOwned>(&self, keys: &[&str]) -> Result<Vec<Option<T>>> {
        if keys.is_empty() {
            return Ok(Vec::new());
        }

        let mut conn = self.conn.clone();
        let full_keys: Vec<String> = keys.iter().map(|k| self.prefixed_key(k)).collect();

        let values: Vec<Option<String>> = conn.mget(&full_keys).await?;

        let mut result = Vec::with_capacity(values.len());
        for value in values {
            match value {
                Some(v) => {
                    let parsed = serde_json::from_str(&v)?;
                    result.push(Some(parsed));
                }
                None => result.push(None),
            }
        }

        Ok(result)
    }

    /// Set multiple values.
    #[instrument(skip(self, pairs))]
    pub async fn mset<T: Serialize>(
        &self,
        pairs: &[(&str, &T)],
        ttl: Option<Duration>,
    ) -> Result<()> {
        if pairs.is_empty() {
            return Ok(());
        }

        let mut conn = self.conn.clone();
        let ttl_secs = ttl.unwrap_or(self.config.default_ttl()).as_secs();

        // Use pipeline for efficiency
        let mut pipe = redis::pipe();
        for (key, value) in pairs {
            let full_key = self.prefixed_key(key);
            let serialized = serde_json::to_string(value)?;
            pipe.set_ex(&full_key, &serialized, ttl_secs);
        }

        pipe.query_async::<()>(&mut conn).await?;

        debug!(count = pairs.len(), "Set multiple cache values");
        Ok(())
    }

    /// Delete all keys matching a glob pattern using Redis SCAN + DEL.
    ///
    /// Iterates with a cursor loop so it never blocks the Redis server.
    /// Returns the total number of keys deleted.
    ///
    /// # Errors
    ///
    /// Returns an error if the SCAN or DEL commands fail.
    #[instrument(skip(self), fields(pattern = %pattern))]
    pub async fn scan_delete(&self, pattern: &str) -> Result<u64> {
        let mut conn = self.conn.clone();
        let full_pattern = self.prefixed_key(pattern);
        let mut cursor: u64 = 0;
        let mut total_deleted: u64 = 0;

        loop {
            let (next_cursor, keys): (u64, Vec<String>) = redis::cmd("SCAN")
                .arg(cursor)
                .arg("MATCH")
                .arg(&full_pattern)
                .arg("COUNT")
                .arg(100u64)
                .query_async(&mut conn)
                .await
                .map_err(CacheError::Redis)?;

            if !keys.is_empty() {
                let deleted: i64 = conn.del(keys.as_slice()).await?;
                total_deleted += deleted as u64;
            }

            cursor = next_cursor;
            if cursor == 0 {
                break;
            }
        }

        debug!(pattern = %pattern, total_deleted = total_deleted, "SCAN-based key deletion complete");
        Ok(total_deleted)
    }

    // ─────────────────────────────────────────────────────────────────────────
    // Helpers
    // ─────────────────────────────────────────────────────────────────────────

    fn prefixed_key(&self, key: &str) -> String {
        if self.config.key_prefix.is_empty() {
            key.to_string()
        } else {
            format!("{}:{}", self.config.key_prefix, key)
        }
    }
}

impl std::fmt::Debug for CacheClient {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("CacheClient")
            .field("config", &self.config)
            .finish_non_exhaustive()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // Integration tests require a running Redis instance
    // These are marked as ignore by default

    #[tokio::test]
    #[ignore = "requires Redis"]
    async fn test_basic_operations() {
        let config = CacheConfig::default();
        let client = CacheClient::connect(&config).await.unwrap();

        // Health check
        client.health_check().await.unwrap();

        // Set and get
        client
            .set("test:key", &"hello world", Some(Duration::from_secs(60)))
            .await
            .unwrap();

        let value: Option<String> = client.get("test:key").await.unwrap();
        assert_eq!(value, Some("hello world".to_string()));

        // Delete
        let deleted = client.delete("test:key").await.unwrap();
        assert!(deleted);

        let value: Option<String> = client.get("test:key").await.unwrap();
        assert!(value.is_none());
    }

    #[tokio::test]
    #[ignore = "requires Redis"]
    async fn test_hash_operations() {
        let config = CacheConfig::default();
        let client = CacheClient::connect(&config).await.unwrap();

        // Set hash field
        client.hset("test:hash", "field1", &"value1").await.unwrap();
        client.hset("test:hash", "field2", &"value2").await.unwrap();

        // Get hash field
        let value: Option<String> = client.hget("test:hash", "field1").await.unwrap();
        assert_eq!(value, Some("value1".to_string()));

        // Get all fields
        let all: Vec<(String, String)> = client.hgetall("test:hash").await.unwrap();
        assert_eq!(all.len(), 2);

        // Cleanup
        client.delete("test:hash").await.unwrap();
    }
}
