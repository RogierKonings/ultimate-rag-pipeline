//! Cache key management.
//!
//! Keys follow the pattern: `{service}:{type}:{tenant_id}:{identifier}`

use crate::error::{CacheError, Result};
use rag_types::TenantId;
use sha2::{Digest, Sha256};
use std::fmt;

/// Service prefix for cache keys.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ServicePrefix {
    /// Ingestion service
    Ingestion,
    /// Retrieval service
    Retrieval,
    /// Orchestrator service
    Orchestrator,
    /// Celery workers
    Celery,
}

impl fmt::Display for ServicePrefix {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Ingestion => write!(f, "ing"),
            Self::Retrieval => write!(f, "ret"),
            Self::Orchestrator => write!(f, "orc"),
            Self::Celery => write!(f, "cel"),
        }
    }
}

/// Type of cached data.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum KeyType {
    /// Embedding vectors
    Embedding,
    /// Query results
    Query,
    /// Session data
    Session,
    /// Job status
    Job,
    /// Distributed lock
    Lock,
}

impl fmt::Display for KeyType {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Embedding => write!(f, "emb"),
            Self::Query => write!(f, "query"),
            Self::Session => write!(f, "sess"),
            Self::Job => write!(f, "job"),
            Self::Lock => write!(f, "lock"),
        }
    }
}

/// A structured cache key.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CacheKey {
    /// Service prefix
    pub service: ServicePrefix,
    /// Key type
    pub key_type: KeyType,
    /// Tenant identifier
    pub tenant_id: TenantId,
    /// Unique identifier within the type
    pub identifier: String,
}

impl CacheKey {
    /// Create a new cache key.
    #[must_use]
    pub fn new(
        service: ServicePrefix,
        key_type: KeyType,
        tenant_id: TenantId,
        identifier: impl Into<String>,
    ) -> Self {
        Self {
            service,
            key_type,
            tenant_id,
            identifier: identifier.into(),
        }
    }

    /// Create an embedding cache key from content.
    ///
    /// The identifier is the SHA-256 hash of the content.
    #[must_use]
    pub fn embedding(service: ServicePrefix, tenant_id: TenantId, content: &str) -> Self {
        let hash = content_hash(content);
        Self::new(service, KeyType::Embedding, tenant_id, hash)
    }

    /// Create a query cache key.
    ///
    /// The identifier is the SHA-256 hash of the query and filters.
    #[must_use]
    pub fn query(tenant_id: TenantId, query: &str, filters: Option<&serde_json::Value>) -> Self {
        let mut hasher = Sha256::new();
        hasher.update(query.as_bytes());
        if let Some(f) = filters {
            hasher.update(f.to_string().as_bytes());
        }
        let hash = hex::encode(hasher.finalize());
        Self::new(ServicePrefix::Retrieval, KeyType::Query, tenant_id, hash)
    }

    /// Create a session cache key.
    #[must_use]
    pub fn session(tenant_id: TenantId, session_id: impl Into<String>) -> Self {
        Self::new(
            ServicePrefix::Orchestrator,
            KeyType::Session,
            tenant_id,
            session_id,
        )
    }

    /// Create a job status cache key.
    #[must_use]
    pub fn job(service: ServicePrefix, tenant_id: TenantId, job_id: impl Into<String>) -> Self {
        Self::new(service, KeyType::Job, tenant_id, job_id)
    }

    /// Create a lock key.
    #[must_use]
    pub fn lock(service: ServicePrefix, tenant_id: TenantId, resource: impl Into<String>) -> Self {
        Self::new(service, KeyType::Lock, tenant_id, resource)
    }

    /// Convert to the Redis key string.
    #[must_use]
    pub fn to_string_with_prefix(&self, prefix: &str) -> String {
        if prefix.is_empty() {
            self.to_string()
        } else {
            format!("{prefix}:{self}")
        }
    }

    /// Parse a cache key from a string.
    ///
    /// # Errors
    ///
    /// Returns an error if the key format is invalid.
    pub fn parse(s: &str) -> Result<Self> {
        let parts: Vec<&str> = s.split(':').collect();
        if parts.len() < 4 {
            return Err(CacheError::InvalidKey(format!(
                "Expected at least 4 parts, got {}",
                parts.len()
            )));
        }

        let service = match parts[0] {
            "ing" => ServicePrefix::Ingestion,
            "ret" => ServicePrefix::Retrieval,
            "orc" => ServicePrefix::Orchestrator,
            "cel" => ServicePrefix::Celery,
            other => {
                return Err(CacheError::InvalidKey(format!(
                    "Unknown service prefix: {other}"
                )))
            }
        };

        let key_type = match parts[1] {
            "emb" => KeyType::Embedding,
            "query" => KeyType::Query,
            "sess" => KeyType::Session,
            "job" => KeyType::Job,
            "lock" => KeyType::Lock,
            other => return Err(CacheError::InvalidKey(format!("Unknown key type: {other}"))),
        };

        let tenant_id = TenantId::parse_str(parts[2])
            .map_err(|e| CacheError::InvalidKey(format!("Invalid tenant ID: {e}")))?;

        // Join remaining parts as the identifier (may contain colons)
        let identifier = parts[3..].join(":");

        Ok(Self {
            service,
            key_type,
            tenant_id,
            identifier,
        })
    }
}

impl fmt::Display for CacheKey {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{}:{}:{}:{}",
            self.service, self.key_type, self.tenant_id, self.identifier
        )
    }
}

/// Compute SHA-256 hash of content.
#[must_use]
pub fn content_hash(content: &str) -> String {
    let mut hasher = Sha256::new();
    hasher.update(content.as_bytes());
    hex::encode(hasher.finalize())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_cache_key_display() {
        let tenant_id = TenantId::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap();
        let key = CacheKey::new(
            ServicePrefix::Ingestion,
            KeyType::Embedding,
            tenant_id,
            "abc123",
        );

        assert_eq!(
            key.to_string(),
            "ing:emb:550e8400-e29b-41d4-a716-446655440000:abc123"
        );
    }

    #[test]
    fn test_embedding_key() {
        let tenant_id = TenantId::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap();
        let key = CacheKey::embedding(ServicePrefix::Ingestion, tenant_id, "Hello, world!");

        assert_eq!(key.service, ServicePrefix::Ingestion);
        assert_eq!(key.key_type, KeyType::Embedding);
        assert_eq!(key.identifier.len(), 64); // SHA-256 hex
    }

    #[test]
    fn test_content_hash() {
        let hash1 = content_hash("Hello, world!");
        let hash2 = content_hash("Hello, world!");
        let hash3 = content_hash("Different content");

        assert_eq!(hash1, hash2);
        assert_ne!(hash1, hash3);
        assert_eq!(hash1.len(), 64);
    }

    #[test]
    fn test_cache_key_parse() {
        let tenant_id = TenantId::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap();
        let original = CacheKey::new(
            ServicePrefix::Retrieval,
            KeyType::Query,
            tenant_id,
            "hash123",
        );

        let parsed = CacheKey::parse(&original.to_string()).unwrap();
        assert_eq!(original, parsed);
    }

    #[test]
    fn test_cache_key_with_prefix() {
        let tenant_id = TenantId::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap();
        let key = CacheKey::new(
            ServicePrefix::Ingestion,
            KeyType::Embedding,
            tenant_id,
            "abc123",
        );

        assert_eq!(
            key.to_string_with_prefix("rag"),
            "rag:ing:emb:550e8400-e29b-41d4-a716-446655440000:abc123"
        );
    }
}
