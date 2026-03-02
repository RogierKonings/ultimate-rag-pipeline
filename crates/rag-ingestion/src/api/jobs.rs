//! Job tracker for background ingestion tasks.

use std::cmp::Reverse;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::Arc;

use chrono::{DateTime, Utc};
use dashmap::DashMap;
use redis::aio::ConnectionManager;
use redis::AsyncCommands;
use serde::{Deserialize, Serialize};
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

use crate::api::types::{JobProgress, JobStatus};

/// State of a single ingestion job.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JobState {
    /// Current job status.
    pub status: JobStatus,
    /// Progress information.
    pub progress: JobProgress,
    /// Number of documents processed.
    pub documents_processed: u32,
    /// Number of chunks created.
    pub chunks_created: u32,
    /// When the job started.
    pub started_at: Option<DateTime<Utc>>,
    /// When the job completed.
    pub completed_at: Option<DateTime<Utc>>,
    /// Error message if failed.
    pub error_message: Option<String>,
    /// List of non-fatal errors.
    pub errors: Vec<String>,
    /// Tenant that owns this job.
    pub tenant_id: String,
}

impl JobState {
    /// Create a new pending job state.
    pub fn new(tenant_id: String) -> Self {
        Self {
            status: JobStatus::Pending,
            progress: JobProgress::default(),
            documents_processed: 0,
            chunks_created: 0,
            started_at: None,
            completed_at: None,
            error_message: None,
            errors: Vec::new(),
            tenant_id,
        }
    }

    /// Calculate duration in seconds.
    pub fn duration_seconds(&self) -> Option<f64> {
        let started = self.started_at?;
        let ended = self.completed_at.unwrap_or_else(Utc::now);
        Some((ended - started).num_milliseconds() as f64 / 1000.0)
    }
}

/// Durable Redis payload for a tracked job.
#[derive(Debug, Clone, Serialize, Deserialize)]
struct DurableJobRecord {
    job_id: Uuid,
    state: JobState,
    updated_at: DateTime<Utc>,
}

/// Optional Redis-backed durable history store.
struct RedisJobHistoryStore {
    conn: ConnectionManager,
    prefix: String,
}

impl RedisJobHistoryStore {
    fn new(conn: ConnectionManager, prefix: String) -> Self {
        Self { conn, prefix }
    }

    fn job_key(&self, job_id: Uuid) -> String {
        format!("{}:job:{}", self.prefix, job_id)
    }

    fn index_key(&self) -> String {
        format!("{}:index", self.prefix)
    }

    async fn upsert_job(&self, job_id: Uuid, state: &JobState) -> Result<(), redis::RedisError> {
        let mut conn = self.conn.clone();

        let record = DurableJobRecord {
            job_id,
            state: state.clone(),
            updated_at: Utc::now(),
        };

        let record_json = serde_json::to_string(&record).map_err(|err| {
            redis::RedisError::from((
                redis::ErrorKind::Client,
                "Failed to serialize durable job record",
                err.to_string(),
            ))
        })?;

        let job_key = self.job_key(job_id);
        let index_key = self.index_key();
        let score = record.updated_at.timestamp_millis();

        let _: () = conn.set(job_key, record_json).await?;
        let _: () = conn.zadd(index_key, job_id.to_string(), score).await?;

        Ok(())
    }

    async fn get_job(&self, job_id: Uuid) -> Result<Option<JobState>, redis::RedisError> {
        let mut conn = self.conn.clone();
        let job_key = self.job_key(job_id);
        let job_json: Option<String> = conn.get(job_key).await?;

        let Some(raw) = job_json else {
            return Ok(None);
        };

        match serde_json::from_str::<DurableJobRecord>(&raw) {
            Ok(record) => Ok(Some(record.state)),
            Err(_) => {
                // Backward compatibility for any legacy payloads that may have
                // stored a bare JobState value.
                let state: JobState = serde_json::from_str(&raw).map_err(|err| {
                    redis::RedisError::from((
                        redis::ErrorKind::Client,
                        "Failed to deserialize durable job record",
                        err.to_string(),
                    ))
                })?;
                Ok(Some(state))
            }
        }
    }

    async fn list_jobs(
        &self,
        limit: usize,
        offset: usize,
    ) -> Result<(Vec<(Uuid, JobState)>, usize), redis::RedisError> {
        let mut conn = self.conn.clone();
        let index_key = self.index_key();
        let total: usize = conn.zcard(&index_key).await?;

        if limit == 0 || total == 0 || offset >= total {
            return Ok((Vec::new(), total));
        }

        let end = offset.saturating_add(limit).saturating_sub(1);
        let start = isize::try_from(offset).unwrap_or(isize::MAX);
        let stop = isize::try_from(end).unwrap_or(isize::MAX);
        let ids: Vec<String> = conn.zrevrange(&index_key, start, stop).await?;

        let mut jobs = Vec::with_capacity(ids.len());
        for id in ids {
            let Ok(job_id) = Uuid::parse_str(&id) else {
                continue;
            };
            if let Some(state) = self.get_job(job_id).await? {
                jobs.push((job_id, state));
            }
        }

        Ok((jobs, total))
    }
}

/// Internal state including cancellation token.
struct InternalJobState {
    state: JobState,
    cancel_token: CancellationToken,
}

/// Thread-safe job tracker with optional Redis durable history.
pub struct JobTracker {
    jobs: DashMap<Uuid, InternalJobState>,
    active_count: AtomicU32,
    history_store: Option<Arc<RedisJobHistoryStore>>,
}

impl JobTracker {
    /// Create a new in-memory job tracker.
    #[must_use]
    pub fn new() -> Self {
        Self {
            jobs: DashMap::new(),
            active_count: AtomicU32::new(0),
            history_store: None,
        }
    }

    /// Create a new job tracker with Redis-backed durable history.
    ///
    /// # Errors
    ///
    /// Returns an error if Redis connection setup fails.
    pub async fn new_with_redis(
        redis_url: &str,
        history_prefix: &str,
    ) -> Result<Self, redis::RedisError> {
        let client = redis::Client::open(redis_url)?;
        let conn = ConnectionManager::new(client).await?;

        Ok(Self {
            jobs: DashMap::new(),
            active_count: AtomicU32::new(0),
            history_store: Some(Arc::new(RedisJobHistoryStore::new(
                conn,
                history_prefix.to_string(),
            ))),
        })
    }

    /// Whether durable history is configured.
    #[must_use]
    pub fn has_durable_history(&self) -> bool {
        self.history_store.is_some()
    }

    /// Create a new job and return its ID.
    pub fn create_job(&self, tenant_id: String) -> Uuid {
        let job_id = Uuid::new_v4();
        self.insert_new_job(job_id, tenant_id);
        job_id
    }

    fn insert_new_job(&self, job_id: Uuid, tenant_id: String) {
        let state = InternalJobState {
            state: JobState::new(tenant_id),
            cancel_token: CancellationToken::new(),
        };
        let snapshot = state.state.clone();
        self.jobs.insert(job_id, state);
        self.active_count.fetch_add(1, Ordering::SeqCst);
        self.persist_snapshot(job_id, &snapshot);
    }

    /// Get a clone of the in-memory job state.
    pub fn get_job(&self, job_id: &Uuid) -> Option<JobState> {
        self.jobs.get(job_id).map(|r| r.state.clone())
    }

    /// Get a job from memory, or durable Redis history if memory does not contain it.
    pub async fn get_job_or_history(&self, job_id: &Uuid) -> Option<JobState> {
        if let Some(state) = self.get_job(job_id) {
            return Some(state);
        }

        let store = self.history_store.as_ref()?;
        match store.get_job(*job_id).await {
            Ok(state) => state,
            Err(err) => {
                tracing::warn!(error = %err, job_id = %job_id, "Failed to read durable job history");
                None
            }
        }
    }

    /// List tracked jobs from durable history (or memory fallback) with pagination.
    pub async fn list_job_history(
        &self,
        limit: usize,
        offset: usize,
    ) -> (Vec<(Uuid, JobState)>, usize) {
        if let Some(store) = &self.history_store {
            match store.list_jobs(limit, offset).await {
                Ok(result) => return result,
                Err(err) => {
                    tracing::warn!(error = %err, "Failed to read durable job history list");
                }
            }
        }

        let mut jobs: Vec<(Uuid, JobState)> = self
            .jobs
            .iter()
            .map(|entry| (*entry.key(), entry.state.clone()))
            .collect();
        jobs.sort_by_key(|(_, state)| {
            let ts = state
                .completed_at
                .as_ref()
                .map(DateTime::timestamp_millis)
                .or_else(|| state.started_at.as_ref().map(DateTime::timestamp_millis))
                .unwrap_or(0);
            Reverse(ts)
        });

        let total = jobs.len();
        let page = jobs
            .into_iter()
            .skip(offset)
            .take(limit)
            .collect::<Vec<_>>();

        (page, total)
    }

    /// Get the cancellation token for a job.
    pub fn get_cancel_token(&self, job_id: &Uuid) -> Option<CancellationToken> {
        self.jobs.get(job_id).map(|r| r.cancel_token.clone())
    }

    /// Update the status of a job.
    pub fn update_status(&self, job_id: &Uuid, status: JobStatus) {
        let snapshot = if let Some(mut entry) = self.jobs.get_mut(job_id) {
            let was_active = is_active(entry.state.status);
            entry.state.status = status;

            // Track started/completed times
            match status {
                JobStatus::Started | JobStatus::Progress => {
                    if entry.state.started_at.is_none() {
                        entry.state.started_at = Some(Utc::now());
                    }
                }
                JobStatus::Success | JobStatus::Failure | JobStatus::Revoked => {
                    entry.state.completed_at = Some(Utc::now());
                    if was_active {
                        self.active_count.fetch_sub(1, Ordering::SeqCst);
                    }
                }
                JobStatus::Pending => {}
            }

            Some(entry.state.clone())
        } else {
            None
        };

        if let Some(state) = snapshot {
            self.persist_snapshot(*job_id, &state);
        }
    }

    /// Update job progress.
    pub fn update_progress(&self, job_id: &Uuid, current: u32, total: u32, stage: &str) {
        let snapshot = if let Some(mut entry) = self.jobs.get_mut(job_id) {
            entry.state.progress.current = current;
            entry.state.progress.total = total;
            entry.state.progress.stage = stage.into();
            entry.state.progress.percentage = if total > 0 {
                (f64::from(current) / f64::from(total)) * 100.0
            } else {
                0.0
            };

            // Ensure status reflects progress
            if entry.state.status == JobStatus::Pending || entry.state.status == JobStatus::Started
            {
                entry.state.status = JobStatus::Progress;
                if entry.state.started_at.is_none() {
                    entry.state.started_at = Some(Utc::now());
                }
            }

            Some(entry.state.clone())
        } else {
            None
        };

        if let Some(state) = snapshot {
            self.persist_snapshot(*job_id, &state);
        }
    }

    /// Update document and chunk counts.
    pub fn update_counts(&self, job_id: &Uuid, docs: u32, chunks: u32) {
        let snapshot = if let Some(mut entry) = self.jobs.get_mut(job_id) {
            entry.state.documents_processed = docs;
            entry.state.chunks_created = chunks;
            Some(entry.state.clone())
        } else {
            None
        };

        if let Some(state) = snapshot {
            self.persist_snapshot(*job_id, &state);
        }
    }

    /// Add an error to the job.
    pub fn add_error(&self, job_id: &Uuid, error: String) {
        let snapshot = if let Some(mut entry) = self.jobs.get_mut(job_id) {
            entry.state.errors.push(error);
            Some(entry.state.clone())
        } else {
            None
        };

        if let Some(state) = snapshot {
            self.persist_snapshot(*job_id, &state);
        }
    }

    /// Mark job as failed with error message.
    pub fn fail_job(&self, job_id: &Uuid, error: String) {
        let snapshot = if let Some(mut entry) = self.jobs.get_mut(job_id) {
            let was_active = is_active(entry.state.status);
            entry.state.status = JobStatus::Failure;
            entry.state.error_message = Some(error);
            entry.state.completed_at = Some(Utc::now());
            if was_active {
                self.active_count.fetch_sub(1, Ordering::SeqCst);
            }
            Some(entry.state.clone())
        } else {
            None
        };

        if let Some(state) = snapshot {
            self.persist_snapshot(*job_id, &state);
        }
    }

    /// Mark job as successful.
    pub fn complete_job(&self, job_id: &Uuid) {
        let snapshot = if let Some(mut entry) = self.jobs.get_mut(job_id) {
            let was_active = is_active(entry.state.status);
            entry.state.status = JobStatus::Success;
            entry.state.completed_at = Some(Utc::now());
            entry.state.progress.percentage = 100.0;
            if was_active {
                self.active_count.fetch_sub(1, Ordering::SeqCst);
            }
            Some(entry.state.clone())
        } else {
            None
        };

        if let Some(state) = snapshot {
            self.persist_snapshot(*job_id, &state);
        }
    }

    /// Cancel a job. Returns true if the job was found and cancelled.
    pub fn cancel_job(&self, job_id: &Uuid) -> bool {
        let snapshot = if let Some(mut entry) = self.jobs.get_mut(job_id) {
            if is_active(entry.state.status) {
                entry.cancel_token.cancel();
                entry.state.status = JobStatus::Revoked;
                entry.state.completed_at = Some(Utc::now());
                self.active_count.fetch_sub(1, Ordering::SeqCst);
                Some(entry.state.clone())
            } else {
                None
            }
        } else {
            None
        };

        if let Some(state) = snapshot {
            self.persist_snapshot(*job_id, &state);
            return true;
        }

        false
    }

    /// Reset a tracked job to pending for replay. Creates it if missing.
    pub fn replay_job(&self, job_id: Uuid, tenant_id: String) {
        let snapshot = if let Some(mut entry) = self.jobs.get_mut(&job_id) {
            let was_active = is_active(entry.state.status);
            entry.state = JobState::new(tenant_id.clone());
            entry.cancel_token = CancellationToken::new();
            if !was_active {
                self.active_count.fetch_add(1, Ordering::SeqCst);
            }
            Some(entry.state.clone())
        } else {
            None
        };

        if let Some(state) = snapshot {
            self.persist_snapshot(job_id, &state);
            return;
        }

        self.insert_new_job(job_id, tenant_id);
    }

    /// List all active job IDs.
    pub fn list_active_jobs(&self) -> Vec<Uuid> {
        self.jobs
            .iter()
            .filter(|r| is_active(r.state.status))
            .map(|r| *r.key())
            .collect()
    }

    /// Get the count of active jobs.
    pub fn active_count(&self) -> u32 {
        self.active_count.load(Ordering::SeqCst)
    }

    /// Remove completed jobs older than the given duration.
    pub fn cleanup_old_jobs(&self, max_age: chrono::Duration) {
        let cutoff = Utc::now() - max_age;
        self.jobs.retain(|_, v| {
            v.state.completed_at.map_or(true, |t| t > cutoff) // Keep active jobs
        });
    }

    fn persist_snapshot(&self, job_id: Uuid, state: &JobState) {
        let Some(store) = &self.history_store else {
            return;
        };

        let Ok(handle) = tokio::runtime::Handle::try_current() else {
            tracing::warn!(
                job_id = %job_id,
                "No tokio runtime available to persist durable job snapshot"
            );
            return;
        };

        let store = Arc::clone(store);
        let snapshot = state.clone();

        handle.spawn(async move {
            if let Err(err) = store.upsert_job(job_id, &snapshot).await {
                tracing::warn!(error = %err, job_id = %job_id, "Failed to persist durable job snapshot");
            }
        });
    }
}

impl Default for JobTracker {
    fn default() -> Self {
        Self::new()
    }
}

/// Check if a job status is considered active.
fn is_active(status: JobStatus) -> bool {
    matches!(
        status,
        JobStatus::Pending | JobStatus::Started | JobStatus::Progress
    )
}

#[cfg(test)]
#[allow(clippy::float_cmp)]
mod tests {
    use super::*;

    #[test]
    fn test_job_state_new() {
        let state = JobState::new("tenant-1".into());
        assert_eq!(state.status, JobStatus::Pending);
        assert_eq!(state.tenant_id, "tenant-1");
        assert!(state.started_at.is_none());
    }

    #[test]
    fn test_tracker_create_and_get() {
        let tracker = JobTracker::new();
        let job_id = tracker.create_job("tenant-1".into());

        let state = tracker.get_job(&job_id).unwrap();
        assert_eq!(state.status, JobStatus::Pending);
        assert_eq!(tracker.active_count(), 1);
    }

    #[test]
    fn test_tracker_update_status() {
        let tracker = JobTracker::new();
        let job_id = tracker.create_job("tenant-1".into());

        tracker.update_status(&job_id, JobStatus::Started);
        let state = tracker.get_job(&job_id).unwrap();
        assert_eq!(state.status, JobStatus::Started);
        assert!(state.started_at.is_some());
    }

    #[test]
    fn test_tracker_update_progress() {
        let tracker = JobTracker::new();
        let job_id = tracker.create_job("tenant-1".into());

        tracker.update_progress(&job_id, 5, 10, "processing");
        let state = tracker.get_job(&job_id).unwrap();
        assert_eq!(state.status, JobStatus::Progress);
        assert_eq!(state.progress.current, 5);
        assert_eq!(state.progress.total, 10);
        assert_eq!(state.progress.percentage, 50.0);
    }

    #[test]
    fn test_tracker_complete_job() {
        let tracker = JobTracker::new();
        let job_id = tracker.create_job("tenant-1".into());
        assert_eq!(tracker.active_count(), 1);

        tracker.complete_job(&job_id);
        let state = tracker.get_job(&job_id).unwrap();
        assert_eq!(state.status, JobStatus::Success);
        assert!(state.completed_at.is_some());
        assert_eq!(tracker.active_count(), 0);
    }

    #[test]
    fn test_tracker_fail_job() {
        let tracker = JobTracker::new();
        let job_id = tracker.create_job("tenant-1".into());

        tracker.fail_job(&job_id, "Something went wrong".into());
        let state = tracker.get_job(&job_id).unwrap();
        assert_eq!(state.status, JobStatus::Failure);
        assert_eq!(state.error_message, Some("Something went wrong".into()));
    }

    #[test]
    fn test_tracker_cancel_job() {
        let tracker = JobTracker::new();
        let job_id = tracker.create_job("tenant-1".into());

        let cancelled = tracker.cancel_job(&job_id);
        assert!(cancelled);

        let state = tracker.get_job(&job_id).unwrap();
        assert_eq!(state.status, JobStatus::Revoked);

        // Can't cancel already cancelled job
        let cancelled_again = tracker.cancel_job(&job_id);
        assert!(!cancelled_again);
    }

    #[test]
    fn test_tracker_list_active_jobs() {
        let tracker = JobTracker::new();
        let job1 = tracker.create_job("tenant-1".into());
        let job2 = tracker.create_job("tenant-1".into());
        let _job3 = tracker.create_job("tenant-1".into());

        tracker.complete_job(&job1);

        let active = tracker.list_active_jobs();
        assert_eq!(active.len(), 2);
        assert!(!active.contains(&job1));
        assert!(active.contains(&job2));
    }

    #[test]
    fn test_replay_job_existing_id_resets_state() {
        let tracker = JobTracker::new();
        let job_id = tracker.create_job("tenant-1".into());
        tracker.complete_job(&job_id);
        assert_eq!(tracker.active_count(), 0);

        tracker.replay_job(job_id, "tenant-1".into());

        let state = tracker.get_job(&job_id).unwrap();
        assert_eq!(state.status, JobStatus::Pending);
        assert!(state.error_message.is_none());
        assert_eq!(tracker.active_count(), 1);
    }

    #[test]
    fn test_replay_job_creates_missing_id() {
        let tracker = JobTracker::new();
        let job_id = Uuid::new_v4();

        tracker.replay_job(job_id, "tenant-1".into());

        let state = tracker.get_job(&job_id).unwrap();
        assert_eq!(state.status, JobStatus::Pending);
        assert_eq!(tracker.active_count(), 1);
    }

    #[test]
    fn test_is_active() {
        assert!(is_active(JobStatus::Pending));
        assert!(is_active(JobStatus::Started));
        assert!(is_active(JobStatus::Progress));
        assert!(!is_active(JobStatus::Success));
        assert!(!is_active(JobStatus::Failure));
        assert!(!is_active(JobStatus::Revoked));
    }

    #[tokio::test]
    async fn test_create_job() {
        let tracker = JobTracker::new();
        let job_id = tracker.create_job("tenant-1".into());

        let state = tracker.get_job(&job_id).unwrap();
        assert_eq!(state.status, JobStatus::Pending);
        assert_eq!(state.tenant_id, "tenant-1");
    }

    #[tokio::test]
    async fn test_update_job_status() {
        let tracker = JobTracker::new();
        let job_id = tracker.create_job("tenant-1".into());

        tracker.update_status(&job_id, JobStatus::Started);
        let state = tracker.get_job(&job_id).unwrap();
        assert_eq!(state.status, JobStatus::Started);
    }

    #[tokio::test]
    async fn test_update_progress() {
        let tracker = JobTracker::new();
        let job_id = tracker.create_job("tenant-1".into());

        tracker.update_progress(&job_id, 5, 10, "processing");
        let state = tracker.get_job(&job_id).unwrap();
        assert_eq!(state.progress.current, 5);
        assert_eq!(state.progress.total, 10);
        assert_eq!(state.progress.percentage, 50.0);
    }

    #[tokio::test]
    async fn test_cancel_job() {
        let tracker = JobTracker::new();
        let job_id = tracker.create_job("tenant-1".into());

        let cancelled = tracker.cancel_job(&job_id);
        assert!(cancelled);

        let state = tracker.get_job(&job_id).unwrap();
        assert_eq!(state.status, JobStatus::Revoked);
    }

    #[tokio::test]
    async fn test_list_active_jobs() {
        let tracker = JobTracker::new();
        let job1 = tracker.create_job("tenant-1".into());
        let job2 = tracker.create_job("tenant-1".into());

        tracker.update_status(&job1, JobStatus::Success);

        let active = tracker.list_active_jobs();
        assert_eq!(active.len(), 1);
        assert_eq!(active[0], job2);
    }
}
