//! Job definitions for the worker system.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashMap;
use uuid::Uuid;

/// Job status.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum JobStatus {
    /// Job is waiting in queue.
    Pending,
    /// Job is currently being processed.
    Running,
    /// Job completed successfully.
    Completed,
    /// Job failed.
    Failed,
    /// Job was cancelled.
    Cancelled,
    /// Job is being retried.
    Retrying,
}

/// Job priority levels.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
#[derive(Default)]
pub enum JobPriority {
    Low = 0,
    #[default]
    Normal = 1,
    High = 2,
    Critical = 3,
}

/// A job to be processed by a worker.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Job {
    /// Unique job ID.
    pub id: Uuid,
    /// Job type (e.g., "`ingest_document`", "reembed").
    pub job_type: String,
    /// Tenant ID for multi-tenancy.
    pub tenant_id: String,
    /// Job payload (serialized task data).
    pub payload: Value,
    /// Job priority.
    pub priority: JobPriority,
    /// Current status.
    pub status: JobStatus,
    /// Number of attempts.
    pub attempts: u32,
    /// Maximum retry attempts.
    pub max_retries: u32,
    /// Created timestamp (Unix ms).
    pub created_at: i64,
    /// Started timestamp (Unix ms).
    pub started_at: Option<i64>,
    /// Completed timestamp (Unix ms).
    pub completed_at: Option<i64>,
    /// Error message if failed.
    pub error: Option<String>,
    /// Progress percentage (0-100).
    pub progress: u8,
    /// Additional metadata.
    pub metadata: HashMap<String, Value>,
}

impl Job {
    /// Create a new job.
    pub fn new(job_type: impl Into<String>, tenant_id: impl Into<String>, payload: Value) -> Self {
        Self {
            id: Uuid::new_v4(),
            job_type: job_type.into(),
            tenant_id: tenant_id.into(),
            payload,
            priority: JobPriority::default(),
            status: JobStatus::Pending,
            attempts: 0,
            max_retries: 3,
            created_at: chrono::Utc::now().timestamp_millis(),
            started_at: None,
            completed_at: None,
            error: None,
            progress: 0,
            metadata: HashMap::new(),
        }
    }

    /// Set job priority.
    #[must_use]
    pub fn with_priority(mut self, priority: JobPriority) -> Self {
        self.priority = priority;
        self
    }

    /// Set max retries.
    #[must_use]
    pub fn with_max_retries(mut self, max_retries: u32) -> Self {
        self.max_retries = max_retries;
        self
    }

    /// Add metadata.
    #[must_use]
    pub fn with_metadata(mut self, key: impl Into<String>, value: Value) -> Self {
        self.metadata.insert(key.into(), value);
        self
    }

    /// Mark job as started.
    pub fn mark_started(&mut self) {
        self.status = JobStatus::Running;
        self.started_at = Some(chrono::Utc::now().timestamp_millis());
        self.attempts += 1;
    }

    /// Mark job as completed.
    pub fn mark_completed(&mut self) {
        self.status = JobStatus::Completed;
        self.completed_at = Some(chrono::Utc::now().timestamp_millis());
        self.progress = 100;
    }

    /// Mark job as failed.
    pub fn mark_failed(&mut self, error: impl Into<String>) {
        self.status = JobStatus::Failed;
        self.completed_at = Some(chrono::Utc::now().timestamp_millis());
        self.error = Some(error.into());
    }

    /// Check if job can be retried.
    pub fn can_retry(&self) -> bool {
        self.attempts < self.max_retries
    }

    /// Prepare for retry.
    pub fn prepare_retry(&mut self) {
        self.status = JobStatus::Retrying;
        self.error = None;
    }

    /// Update progress.
    pub fn update_progress(&mut self, progress: u8) {
        self.progress = progress.min(100);
    }
}

/// Result of job processing.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JobResult {
    /// Job ID.
    pub job_id: Uuid,
    /// Whether processing succeeded.
    pub success: bool,
    /// Result data if successful.
    pub data: Option<Value>,
    /// Error message if failed.
    pub error: Option<String>,
    /// Processing duration in milliseconds.
    pub duration_ms: u64,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_job_creation() {
        let job = Job::new("test", "tenant1", serde_json::json!({"doc": "test.pdf"}));

        assert_eq!(job.job_type, "test");
        assert_eq!(job.tenant_id, "tenant1");
        assert_eq!(job.status, JobStatus::Pending);
        assert_eq!(job.attempts, 0);
    }

    #[test]
    fn test_job_with_priority() {
        let job =
            Job::new("test", "tenant1", serde_json::json!({})).with_priority(JobPriority::High);

        assert_eq!(job.priority, JobPriority::High);
    }

    #[test]
    fn test_job_lifecycle() {
        let mut job = Job::new("test", "tenant1", serde_json::json!({}));

        assert_eq!(job.status, JobStatus::Pending);

        job.mark_started();
        assert_eq!(job.status, JobStatus::Running);
        assert_eq!(job.attempts, 1);
        assert!(job.started_at.is_some());

        job.mark_completed();
        assert_eq!(job.status, JobStatus::Completed);
        assert!(job.completed_at.is_some());
        assert_eq!(job.progress, 100);
    }

    #[test]
    fn test_job_failure_and_retry() {
        let mut job = Job::new("test", "tenant1", serde_json::json!({})).with_max_retries(3);

        job.mark_started();
        job.mark_failed("Connection error");

        assert_eq!(job.status, JobStatus::Failed);
        assert!(job.error.is_some());
        assert!(job.can_retry());

        job.prepare_retry();
        assert_eq!(job.status, JobStatus::Retrying);
    }

    #[test]
    fn test_job_max_retries_exceeded() {
        let mut job = Job::new("test", "tenant1", serde_json::json!({})).with_max_retries(1);

        job.mark_started();
        job.mark_failed("Error");

        assert!(!job.can_retry());
    }

    #[test]
    fn test_job_priority_ordering() {
        assert!(JobPriority::Critical > JobPriority::High);
        assert!(JobPriority::High > JobPriority::Normal);
        assert!(JobPriority::Normal > JobPriority::Low);
    }

    #[test]
    fn test_job_with_metadata() {
        let job = Job::new("test", "tenant1", serde_json::json!({}))
            .with_metadata("source", serde_json::json!("s3://bucket/file.pdf"));

        assert!(job.metadata.contains_key("source"));
    }

    #[test]
    fn test_job_update_progress() {
        let mut job = Job::new("test", "tenant1", serde_json::json!({}));

        job.update_progress(50);
        assert_eq!(job.progress, 50);

        job.update_progress(150); // Should be capped at 100
        assert_eq!(job.progress, 100);
    }
}
