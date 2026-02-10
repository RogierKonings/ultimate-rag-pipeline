//! Application state for the ingestion service.

use std::sync::Arc;
use tokio::sync::Mutex;

use rag_database::DatabasePool;

use crate::api::jobs::JobTracker;
use crate::cache_invalidation::CacheInvalidationPublisher;
use crate::embedding::EmbeddingClient;
use crate::indexing::IndexCoordinator;
use crate::worker::JobQueue;

/// Application state shared across all request handlers.
pub struct AppState {
    /// In-memory job tracker.
    pub job_tracker: Arc<JobTracker>,

    /// Index coordinator for multi-store writes (optional for tests).
    pub index_coordinator: Option<Arc<IndexCoordinator>>,

    /// Embedding client (optional for tests).
    pub embedding_client: Option<Arc<EmbeddingClient>>,

    /// Job queue for async processing (optional for tests).
    pub job_queue: Option<Arc<Mutex<JobQueue>>>,

    /// Database pool for `PostgreSQL` queries (optional for tests).
    pub database: Option<DatabasePool>,

    /// Cache invalidation publisher for notifying orchestrator of document changes.
    pub cache_invalidation: Option<Arc<CacheInvalidationPublisher>>,

    /// Service version string.
    pub version: String,
}

impl AppState {
    /// Create a new `AppState` builder.
    #[must_use]
    pub fn builder() -> AppStateBuilder {
        AppStateBuilder::new()
    }

    /// Get the service version.
    #[must_use]
    pub fn version(&self) -> &str {
        &self.version
    }

    /// Check if index coordinator is available.
    #[must_use]
    pub fn has_index_coordinator(&self) -> bool {
        self.index_coordinator.is_some()
    }

    /// Check if embedding client is available.
    #[must_use]
    pub fn has_embedding_client(&self) -> bool {
        self.embedding_client.is_some()
    }

    /// Check if job queue is available.
    #[must_use]
    pub fn has_job_queue(&self) -> bool {
        self.job_queue.is_some()
    }

    /// Check if database is available.
    #[must_use]
    pub fn has_database(&self) -> bool {
        self.database.is_some()
    }

    /// Check if cache invalidation publisher is available.
    #[must_use]
    pub fn has_cache_invalidation(&self) -> bool {
        self.cache_invalidation.is_some()
    }
}

impl std::fmt::Debug for AppState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("AppState")
            .field("has_index_coordinator", &self.index_coordinator.is_some())
            .field("has_embedding_client", &self.embedding_client.is_some())
            .field("has_job_queue", &self.job_queue.is_some())
            .field("has_database", &self.database.is_some())
            .field("has_cache_invalidation", &self.cache_invalidation.is_some())
            .field("active_jobs", &self.job_tracker.active_count())
            .field("version", &self.version)
            .finish()
    }
}

/// Builder for constructing `AppState`.
pub struct AppStateBuilder {
    job_tracker: Option<Arc<JobTracker>>,
    index_coordinator: Option<Arc<IndexCoordinator>>,
    embedding_client: Option<Arc<EmbeddingClient>>,
    job_queue: Option<Arc<Mutex<JobQueue>>>,
    database: Option<DatabasePool>,
    cache_invalidation: Option<Arc<CacheInvalidationPublisher>>,
    version: String,
}

impl AppStateBuilder {
    /// Create a new builder with default values.
    #[must_use]
    pub fn new() -> Self {
        Self {
            job_tracker: None,
            index_coordinator: None,
            embedding_client: None,
            job_queue: None,
            database: None,
            cache_invalidation: None,
            version: env!("CARGO_PKG_VERSION").to_string(),
        }
    }

    /// Set the job tracker.
    #[must_use]
    pub fn job_tracker(mut self, tracker: Arc<JobTracker>) -> Self {
        self.job_tracker = Some(tracker);
        self
    }

    /// Set the index coordinator.
    #[must_use]
    pub fn index_coordinator(mut self, coordinator: Arc<IndexCoordinator>) -> Self {
        self.index_coordinator = Some(coordinator);
        self
    }

    /// Set the embedding client.
    #[must_use]
    pub fn embedding_client(mut self, client: Arc<EmbeddingClient>) -> Self {
        self.embedding_client = Some(client);
        self
    }

    /// Set the job queue.
    #[must_use]
    pub fn job_queue(mut self, queue: Arc<Mutex<JobQueue>>) -> Self {
        self.job_queue = Some(queue);
        self
    }

    /// Set the database pool.
    #[must_use]
    pub fn database(mut self, pool: DatabasePool) -> Self {
        self.database = Some(pool);
        self
    }

    /// Set the cache invalidation publisher.
    #[must_use]
    pub fn cache_invalidation(mut self, publisher: Arc<CacheInvalidationPublisher>) -> Self {
        self.cache_invalidation = Some(publisher);
        self
    }

    /// Set the service version.
    #[must_use]
    pub fn version(mut self, version: impl Into<String>) -> Self {
        self.version = version.into();
        self
    }

    /// Build the `AppState`.
    ///
    /// # Errors
    ///
    /// Returns an error if the job tracker is not set.
    pub fn build(self) -> Result<AppState, AppStateBuilderError> {
        let job_tracker = self
            .job_tracker
            .ok_or(AppStateBuilderError::MissingComponent("job_tracker"))?;

        Ok(AppState {
            job_tracker,
            index_coordinator: self.index_coordinator,
            embedding_client: self.embedding_client,
            job_queue: self.job_queue,
            database: self.database,
            cache_invalidation: self.cache_invalidation,
            version: self.version,
        })
    }

    /// Build `AppState` with a new job tracker (convenience method).
    pub fn build_with_new_tracker(self) -> Result<AppState, AppStateBuilderError> {
        let builder = if self.job_tracker.is_none() {
            self.job_tracker(Arc::new(JobTracker::new()))
        } else {
            self
        };
        builder.build()
    }
}

impl Default for AppStateBuilder {
    fn default() -> Self {
        Self::new()
    }
}

/// Error when building `AppState`.
#[derive(Debug, Clone)]
pub enum AppStateBuilderError {
    /// A required component is missing.
    MissingComponent(&'static str),
}

impl std::fmt::Display for AppStateBuilderError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::MissingComponent(name) => {
                write!(f, "Missing required component: {name}")
            }
        }
    }
}

impl std::error::Error for AppStateBuilderError {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_app_state_builder_default() {
        let builder = AppStateBuilder::default();
        assert!(builder.job_tracker.is_none());
        assert!(builder.index_coordinator.is_none());
        assert!(builder.embedding_client.is_none());
        assert!(builder.job_queue.is_none());
    }

    #[test]
    fn test_app_state_builder_missing_job_tracker() {
        let result = AppStateBuilder::new().build();
        assert!(result.is_err());

        if let Err(AppStateBuilderError::MissingComponent(name)) = result {
            assert_eq!(name, "job_tracker");
        } else {
            panic!("Expected MissingComponent error");
        }
    }

    #[test]
    fn test_app_state_builder_with_tracker() {
        let tracker = Arc::new(JobTracker::new());
        let state = AppStateBuilder::new().job_tracker(tracker).build().unwrap();

        assert!(!state.has_index_coordinator());
        assert!(!state.has_embedding_client());
        assert!(!state.has_job_queue());
    }

    #[test]
    fn test_app_state_builder_convenience() {
        let state = AppStateBuilder::new().build_with_new_tracker().unwrap();
        assert_eq!(state.job_tracker.active_count(), 0);
    }

    #[test]
    fn test_app_state_builder_error_display() {
        let err = AppStateBuilderError::MissingComponent("test");
        assert_eq!(err.to_string(), "Missing required component: test");
    }

    #[test]
    fn test_app_state_debug() {
        let state = AppStateBuilder::new().build_with_new_tracker().unwrap();
        let debug = format!("{state:?}");
        assert!(debug.contains("AppState"));
        assert!(debug.contains("has_index_coordinator"));
    }

    #[test]
    fn test_app_state_version() {
        let state = AppStateBuilder::new().build_with_new_tracker().unwrap();
        // Version should match Cargo.toml
        let version = state.version();
        assert!(!version.is_empty());
    }
}
