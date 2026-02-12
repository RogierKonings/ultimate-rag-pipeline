//! Cache invalidation publisher for notifying the orchestrator of document changes.
//!
//! Uses Redis pub/sub to send invalidation events when documents are deleted,
//! reindexed, or otherwise mutated. The orchestrator subscribes to these events
//! and invalidates its answer cache accordingly.

use redis::aio::ConnectionManager;
use redis::AsyncCommands;
use serde::Serialize;
use std::sync::atomic::{AtomicU64, Ordering};
use tracing::{debug, info, instrument, warn};

/// Redis pub/sub channel for cache invalidation events.
pub const INVALIDATION_CHANNEL: &str = "rag:cache_invalidation";

/// Types of cache invalidation events.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum InvalidationEventType {
    /// A single document was deleted.
    DocumentDeleted,
    /// A single document was reindexed (content changed).
    DocumentReindexed,
    /// Multiple documents were deleted in a batch.
    BatchDeleted,
    /// All data for a tenant should be invalidated.
    TenantInvalidation,
}

/// Cache invalidation event published to Redis pub/sub.
#[derive(Debug, Clone, Serialize)]
pub struct InvalidationEvent {
    /// Type of invalidation.
    pub event_type: InvalidationEventType,
    /// Tenant ID scope.
    pub tenant_id: String,
    /// Document IDs affected (empty for tenant-wide invalidation).
    pub document_ids: Vec<String>,
    /// Timestamp of the event (Unix seconds).
    pub timestamp: i64,
}

impl InvalidationEvent {
    /// Create a document-scoped invalidation event.
    pub fn document(event_type: InvalidationEventType, tenant_id: &str, document_id: &str) -> Self {
        Self {
            event_type,
            tenant_id: tenant_id.to_string(),
            document_ids: vec![document_id.to_string()],
            timestamp: chrono::Utc::now().timestamp(),
        }
    }

    /// Create a batch invalidation event for multiple documents.
    pub fn batch(tenant_id: &str, document_ids: Vec<String>) -> Self {
        Self {
            event_type: InvalidationEventType::BatchDeleted,
            tenant_id: tenant_id.to_string(),
            document_ids,
            timestamp: chrono::Utc::now().timestamp(),
        }
    }

    /// Create a tenant-wide invalidation event.
    pub fn tenant(tenant_id: &str) -> Self {
        Self {
            event_type: InvalidationEventType::TenantInvalidation,
            tenant_id: tenant_id.to_string(),
            document_ids: vec![],
            timestamp: chrono::Utc::now().timestamp(),
        }
    }
}

/// Metrics for cache invalidation publishing.
#[derive(Debug, Default)]
pub struct InvalidationMetrics {
    /// Total events published successfully.
    pub events_published: AtomicU64,
    /// Total events that failed to publish.
    pub events_failed: AtomicU64,
}

impl InvalidationMetrics {
    /// Get the count of successfully published events.
    pub fn published_count(&self) -> u64 {
        self.events_published.load(Ordering::Relaxed)
    }

    /// Get the count of failed publish attempts.
    pub fn failed_count(&self) -> u64 {
        self.events_failed.load(Ordering::Relaxed)
    }
}

/// Publishes cache invalidation events to Redis pub/sub.
///
/// The orchestrator's `CacheInvalidationListener` subscribes to these events
/// and invalidates its answer cache for the affected documents/tenants.
pub struct CacheInvalidationPublisher {
    conn: ConnectionManager,
    metrics: InvalidationMetrics,
}

impl CacheInvalidationPublisher {
    /// Create a new publisher connected to Redis.
    ///
    /// # Errors
    ///
    /// Returns an error if the Redis connection fails.
    pub async fn new(redis_url: &str) -> Result<Self, redis::RedisError> {
        let client = redis::Client::open(redis_url)?;
        let conn = ConnectionManager::new(client).await?;

        info!("Cache invalidation publisher connected to Redis");

        Ok(Self {
            conn,
            metrics: InvalidationMetrics::default(),
        })
    }

    /// Create a publisher with an existing connection manager.
    #[must_use]
    pub fn with_connection(conn: ConnectionManager) -> Self {
        Self {
            conn,
            metrics: InvalidationMetrics::default(),
        }
    }

    /// Publish an invalidation event to the Redis pub/sub channel.
    ///
    /// This is fire-and-forget: errors are logged but do not propagate to the
    /// caller since cache invalidation should not block mutation operations.
    #[instrument(skip(self, event), fields(
        event_type = ?event.event_type,
        tenant_id = %event.tenant_id,
        document_count = event.document_ids.len(),
    ))]
    pub async fn publish(&self, event: InvalidationEvent) {
        let payload = match serde_json::to_string(&event) {
            Ok(json) => json,
            Err(e) => {
                warn!(error = %e, "Failed to serialize invalidation event");
                self.metrics.events_failed.fetch_add(1, Ordering::Relaxed);
                return;
            }
        };

        let mut conn = self.conn.clone();
        match conn
            .publish::<_, _, i64>(INVALIDATION_CHANNEL, &payload)
            .await
        {
            Ok(subscribers) => {
                self.metrics
                    .events_published
                    .fetch_add(1, Ordering::Relaxed);
                debug!(
                    subscribers = subscribers,
                    channel = INVALIDATION_CHANNEL,
                    "Cache invalidation event published"
                );
            }
            Err(e) => {
                warn!(
                    error = %e,
                    channel = INVALIDATION_CHANNEL,
                    "Failed to publish cache invalidation event"
                );
                self.metrics.events_failed.fetch_add(1, Ordering::Relaxed);
            }
        }
    }

    /// Publish a document deletion invalidation event.
    pub async fn publish_document_deleted(&self, tenant_id: &str, document_id: &str) {
        let event = InvalidationEvent::document(
            InvalidationEventType::DocumentDeleted,
            tenant_id,
            document_id,
        );
        self.publish(event).await;
    }

    /// Publish a document reindex invalidation event.
    pub async fn publish_document_reindexed(&self, tenant_id: &str, document_id: &str) {
        let event = InvalidationEvent::document(
            InvalidationEventType::DocumentReindexed,
            tenant_id,
            document_id,
        );
        self.publish(event).await;
    }

    /// Publish a batch deletion invalidation event.
    pub async fn publish_batch_deleted(&self, tenant_id: &str, document_ids: Vec<String>) {
        if document_ids.is_empty() {
            return;
        }
        let event = InvalidationEvent::batch(tenant_id, document_ids);
        self.publish(event).await;
    }

    /// Publish a tenant-wide invalidation event.
    pub async fn publish_tenant_invalidation(&self, tenant_id: &str) {
        let event = InvalidationEvent::tenant(tenant_id);
        self.publish(event).await;
    }

    /// Get reference to the metrics.
    pub fn metrics(&self) -> &InvalidationMetrics {
        &self.metrics
    }
}

impl std::fmt::Debug for CacheInvalidationPublisher {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("CacheInvalidationPublisher")
            .field("events_published", &self.metrics.published_count())
            .field("events_failed", &self.metrics.failed_count())
            .finish_non_exhaustive()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_invalidation_event_document() {
        let event = InvalidationEvent::document(
            InvalidationEventType::DocumentDeleted,
            "tenant-1",
            "doc-123",
        );
        assert_eq!(event.tenant_id, "tenant-1");
        assert_eq!(event.document_ids, vec!["doc-123"]);
        assert!(event.timestamp > 0);
    }

    #[test]
    fn test_invalidation_event_batch() {
        let event =
            InvalidationEvent::batch("tenant-1", vec!["doc-1".to_string(), "doc-2".to_string()]);
        assert_eq!(event.document_ids.len(), 2);
    }

    #[test]
    fn test_invalidation_event_tenant() {
        let event = InvalidationEvent::tenant("tenant-1");
        assert!(event.document_ids.is_empty());
        assert_eq!(event.tenant_id, "tenant-1");
    }

    #[test]
    fn test_invalidation_event_serialization() {
        let event = InvalidationEvent::document(
            InvalidationEventType::DocumentDeleted,
            "tenant-1",
            "doc-123",
        );
        let json = serde_json::to_string(&event).unwrap();
        assert!(json.contains("document_deleted"));
        assert!(json.contains("tenant-1"));
        assert!(json.contains("doc-123"));
    }

    #[test]
    fn test_metrics_default() {
        let metrics = InvalidationMetrics::default();
        assert_eq!(metrics.published_count(), 0);
        assert_eq!(metrics.failed_count(), 0);
    }

    #[test]
    fn test_metrics_increment() {
        let metrics = InvalidationMetrics::default();
        metrics.events_published.fetch_add(5, Ordering::Relaxed);
        metrics.events_failed.fetch_add(2, Ordering::Relaxed);
        assert_eq!(metrics.published_count(), 5);
        assert_eq!(metrics.failed_count(), 2);
    }
}
