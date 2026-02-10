//! Token blocklist for revocation support.

use async_trait::async_trait;
use std::collections::HashMap;
use std::sync::{Arc, RwLock};
use std::time::{Duration, Instant};

use crate::{AuthError, Result};

/// Token blocklist trait for implementing revocation.
#[async_trait]
pub trait TokenBlocklist: Send + Sync {
    /// Add a token JTI to the blocklist.
    ///
    /// # Arguments
    /// * `jti` - Token JWT ID
    /// * `ttl` - Time-to-live (how long to keep blocked)
    async fn block(&self, jti: &str, ttl: Option<Duration>) -> Result<()>;

    /// Check if a token JTI is blocked.
    async fn is_blocked(&self, jti: &str) -> Result<bool>;

    /// Remove a token JTI from the blocklist.
    async fn unblock(&self, jti: &str) -> Result<()>;
}

/// In-memory token blocklist for development/testing.
///
/// Note: This is not suitable for production as it doesn't
/// persist across restarts and doesn't share state across instances.
#[derive(Debug, Default)]
pub struct InMemoryBlocklist {
    entries: Arc<RwLock<HashMap<String, Option<Instant>>>>,
}

impl InMemoryBlocklist {
    /// Create a new in-memory blocklist.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Remove expired entries from the blocklist.
    pub fn cleanup(&self) {
        let mut entries = self.entries.write().unwrap();
        let now = Instant::now();
        entries.retain(|_, expires_at| {
            expires_at.is_none_or(|exp| exp > now)
        });
    }
}

#[async_trait]
impl TokenBlocklist for InMemoryBlocklist {
    async fn block(&self, jti: &str, ttl: Option<Duration>) -> Result<()> {
        let expires_at = ttl.map(|d| Instant::now() + d);
        let mut entries = self.entries.write().unwrap();
        entries.insert(jti.to_string(), expires_at);
        Ok(())
    }

    async fn is_blocked(&self, jti: &str) -> Result<bool> {
        let entries = self.entries.read().unwrap();
        match entries.get(jti) {
            None => Ok(false),
            Some(None) => Ok(true), // No expiry, permanently blocked
            Some(Some(expires_at)) => Ok(*expires_at > Instant::now()),
        }
    }

    async fn unblock(&self, jti: &str) -> Result<()> {
        let mut entries = self.entries.write().unwrap();
        entries.remove(jti);
        Ok(())
    }
}

/// Redis-backed token blocklist for production use.
///
/// This blocklist uses Redis SETEX for automatic expiration
/// and works across multiple service instances.
pub struct RedisBlocklist {
    client: redis::Client,
    prefix: String,
}

impl RedisBlocklist {
    /// Create a new Redis blocklist.
    ///
    /// # Errors
    ///
    /// Returns an error if the Redis URL is invalid.
    pub fn new(redis_url: &str, prefix: impl Into<String>) -> Result<Self> {
        let client = redis::Client::open(redis_url)
            .map_err(|e| AuthError::Blocklist(format!("Failed to connect to Redis: {e}")))?;

        Ok(Self {
            client,
            prefix: prefix.into(),
        })
    }

    /// Create a new Redis blocklist with an existing client.
    #[must_use]
    pub fn with_client(client: redis::Client, prefix: impl Into<String>) -> Self {
        Self {
            client,
            prefix: prefix.into(),
        }
    }

    fn key(&self, jti: &str) -> String {
        format!("{}{}", self.prefix, jti)
    }
}

#[async_trait]
impl TokenBlocklist for RedisBlocklist {
    async fn block(&self, jti: &str, ttl: Option<Duration>) -> Result<()> {
        let mut conn = self
            .client
            .get_multiplexed_async_connection()
            .await
            .map_err(|e| AuthError::Blocklist(format!("Redis connection error: {e}")))?;

        let key = self.key(jti);

        match ttl {
            Some(duration) => {
                let seconds = duration.as_secs().max(1);
                let _: () = redis::cmd("SETEX")
                    .arg(&key)
                    .arg(seconds)
                    .arg("1")
                    .query_async(&mut conn)
                    .await
                    .map_err(|e| AuthError::Blocklist(format!("Redis SETEX error: {e}")))?;
            }
            None => {
                let _: () = redis::cmd("SET")
                    .arg(&key)
                    .arg("1")
                    .query_async(&mut conn)
                    .await
                    .map_err(|e| AuthError::Blocklist(format!("Redis SET error: {e}")))?;
            }
        }

        Ok(())
    }

    async fn is_blocked(&self, jti: &str) -> Result<bool> {
        let mut conn = self
            .client
            .get_multiplexed_async_connection()
            .await
            .map_err(|e| AuthError::Blocklist(format!("Redis connection error: {e}")))?;

        let key = self.key(jti);
        let exists: bool = redis::cmd("EXISTS")
            .arg(&key)
            .query_async(&mut conn)
            .await
            .map_err(|e| AuthError::Blocklist(format!("Redis EXISTS error: {e}")))?;

        Ok(exists)
    }

    async fn unblock(&self, jti: &str) -> Result<()> {
        let mut conn = self
            .client
            .get_multiplexed_async_connection()
            .await
            .map_err(|e| AuthError::Blocklist(format!("Redis connection error: {e}")))?;

        let key = self.key(jti);
        let _: () = redis::cmd("DEL")
            .arg(&key)
            .query_async(&mut conn)
            .await
            .map_err(|e| AuthError::Blocklist(format!("Redis DEL error: {e}")))?;

        Ok(())
    }
}

impl std::fmt::Debug for RedisBlocklist {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("RedisBlocklist")
            .field("prefix", &self.prefix)
            .finish_non_exhaustive()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_in_memory_blocklist() {
        let blocklist = InMemoryBlocklist::new();

        // Initially not blocked
        assert!(!blocklist.is_blocked("token-1").await.unwrap());

        // Block token
        blocklist.block("token-1", None).await.unwrap();
        assert!(blocklist.is_blocked("token-1").await.unwrap());

        // Unblock token
        blocklist.unblock("token-1").await.unwrap();
        assert!(!blocklist.is_blocked("token-1").await.unwrap());
    }

    #[tokio::test]
    async fn test_in_memory_blocklist_with_ttl() {
        let blocklist = InMemoryBlocklist::new();

        // Block with very short TTL
        blocklist
            .block("token-2", Some(Duration::from_millis(10)))
            .await
            .unwrap();

        // Should be blocked immediately
        assert!(blocklist.is_blocked("token-2").await.unwrap());

        // Wait for expiration
        tokio::time::sleep(Duration::from_millis(20)).await;

        // Should no longer be blocked
        assert!(!blocklist.is_blocked("token-2").await.unwrap());
    }
}
