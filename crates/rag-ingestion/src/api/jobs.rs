//! In-memory job tracker for background ingestion tasks.

use std::sync::atomic::{AtomicU32, Ordering};

use chrono::{DateTime, Utc};
use dashmap::DashMap;
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

use crate::api::types::{JobProgress, JobStatus};

/// State of a single ingestion job.
#[derive(Debug, Clone)]
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

/// Internal state including cancellation token.
struct InternalJobState {
    state: JobState,
    cancel_token: CancellationToken,
}

/// Thread-safe in-memory job tracker.
pub struct JobTracker {
    jobs: DashMap<Uuid, InternalJobState>,
    active_count: AtomicU32,
}

impl JobTracker {
    /// Create a new job tracker.
    #[must_use]
    pub fn new() -> Self {
        Self {
            jobs: DashMap::new(),
            active_count: AtomicU32::new(0),
        }
    }

    /// Create a new job and return its ID.
    pub fn create_job(&self, tenant_id: String) -> Uuid {
        let job_id = Uuid::new_v4();
        let state = InternalJobState {
            state: JobState::new(tenant_id),
            cancel_token: CancellationToken::new(),
        };
        self.jobs.insert(job_id, state);
        self.active_count.fetch_add(1, Ordering::SeqCst);
        job_id
    }

    /// Get a clone of the job state.
    pub fn get_job(&self, job_id: &Uuid) -> Option<JobState> {
        self.jobs.get(job_id).map(|r| r.state.clone())
    }

    /// Get the cancellation token for a job.
    pub fn get_cancel_token(&self, job_id: &Uuid) -> Option<CancellationToken> {
        self.jobs.get(job_id).map(|r| r.cancel_token.clone())
    }

    /// Update the status of a job.
    pub fn update_status(&self, job_id: &Uuid, status: JobStatus) {
        if let Some(mut entry) = self.jobs.get_mut(job_id) {
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
        }
    }

    /// Update job progress.
    pub fn update_progress(&self, job_id: &Uuid, current: u32, total: u32, stage: &str) {
        if let Some(mut entry) = self.jobs.get_mut(job_id) {
            entry.state.progress.current = current;
            entry.state.progress.total = total;
            entry.state.progress.stage = stage.into();
            entry.state.progress.percentage = if total > 0 {
                (current as f64 / total as f64) * 100.0
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
        }
    }

    /// Update document and chunk counts.
    pub fn update_counts(&self, job_id: &Uuid, docs: u32, chunks: u32) {
        if let Some(mut entry) = self.jobs.get_mut(job_id) {
            entry.state.documents_processed = docs;
            entry.state.chunks_created = chunks;
        }
    }

    /// Add an error to the job.
    pub fn add_error(&self, job_id: &Uuid, error: String) {
        if let Some(mut entry) = self.jobs.get_mut(job_id) {
            entry.state.errors.push(error);
        }
    }

    /// Mark job as failed with error message.
    pub fn fail_job(&self, job_id: &Uuid, error: String) {
        if let Some(mut entry) = self.jobs.get_mut(job_id) {
            let was_active = is_active(entry.state.status);
            entry.state.status = JobStatus::Failure;
            entry.state.error_message = Some(error);
            entry.state.completed_at = Some(Utc::now());
            if was_active {
                self.active_count.fetch_sub(1, Ordering::SeqCst);
            }
        }
    }

    /// Mark job as successful.
    pub fn complete_job(&self, job_id: &Uuid) {
        if let Some(mut entry) = self.jobs.get_mut(job_id) {
            let was_active = is_active(entry.state.status);
            entry.state.status = JobStatus::Success;
            entry.state.completed_at = Some(Utc::now());
            entry.state.progress.percentage = 100.0;
            if was_active {
                self.active_count.fetch_sub(1, Ordering::SeqCst);
            }
        }
    }

    /// Cancel a job. Returns true if the job was found and cancelled.
    pub fn cancel_job(&self, job_id: &Uuid) -> bool {
        if let Some(mut entry) = self.jobs.get_mut(job_id) {
            if is_active(entry.state.status) {
                entry.cancel_token.cancel();
                entry.state.status = JobStatus::Revoked;
                entry.state.completed_at = Some(Utc::now());
                self.active_count.fetch_sub(1, Ordering::SeqCst);
                return true;
            }
        }
        false
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
            v.state.completed_at.map(|t| t > cutoff).unwrap_or(true) // Keep active jobs
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
