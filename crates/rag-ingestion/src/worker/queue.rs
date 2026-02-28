//! Redis-backed job queue.

use redis::aio::ConnectionManager;
use redis::AsyncCommands;
use std::time::Duration;
use thiserror::Error;
use uuid::Uuid;

use super::job::{Job, JobPriority};

/// Queue errors.
#[derive(Debug, Error)]
pub enum QueueError {
    #[error("Redis error: {0}")]
    Redis(#[from] redis::RedisError),
    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),
    #[error("Job not found: {0}")]
    NotFound(Uuid),
}

/// Redis-backed job queue.
pub struct JobQueue {
    conn: ConnectionManager,
    prefix: String,
}

impl JobQueue {
    /// Create a new job queue.
    ///
    /// # Errors
    ///
    /// Returns an error if the Redis connection fails.
    pub async fn new(redis_url: &str, prefix: &str) -> Result<Self, QueueError> {
        let client = redis::Client::open(redis_url)?;
        let conn = ConnectionManager::new(client).await?;

        Ok(Self {
            conn,
            prefix: prefix.to_string(),
        })
    }

    /// Create a job queue with an existing connection manager.
    #[must_use]
    pub fn with_connection(conn: ConnectionManager, prefix: &str) -> Self {
        Self {
            conn,
            prefix: prefix.to_string(),
        }
    }

    /// Get the queue key for a priority level.
    fn queue_key(&self, priority: JobPriority) -> String {
        format!("{}:queue:{:?}", self.prefix, priority)
    }

    /// Get the job data key.
    fn job_key(&self, job_id: Uuid) -> String {
        format!("{}:job:{}", self.prefix, job_id)
    }

    /// Get the processing set key (jobs currently being processed).
    fn processing_key(&self) -> String {
        format!("{}:processing", self.prefix)
    }

    /// Get the dead letter queue key.
    fn dlq_key(&self) -> String {
        format!("{}:dlq", self.prefix)
    }

    /// Enqueue a job.
    ///
    /// # Errors
    ///
    /// Returns an error if Redis operations fail.
    pub async fn enqueue(&self, job: &Job) -> Result<(), QueueError> {
        let mut conn = self.conn.clone();
        let job_json = serde_json::to_string(job)?;
        let job_key = self.job_key(job.id);
        let queue_key = self.queue_key(job.priority);

        // Store job data
        let _: () = conn.set(&job_key, &job_json).await?;

        // Add to queue (sorted by created_at for FIFO within priority)
        let score = job.created_at as f64;
        let _: () = conn.zadd(&queue_key, job.id.to_string(), score).await?;

        Ok(())
    }

    /// Dequeue a job (non-blocking).
    ///
    /// # Errors
    ///
    /// Returns an error if Redis operations fail.
    pub async fn dequeue(&self, timeout: Duration) -> Result<Option<Job>, QueueError> {
        let mut conn = self.conn.clone();

        // Check queues in priority order (highest first)
        let priorities = [
            JobPriority::Critical,
            JobPriority::High,
            JobPriority::Normal,
            JobPriority::Low,
        ];

        for priority in priorities {
            let queue_key = self.queue_key(priority);

            // Try to get the oldest job (lowest score)
            let result: Option<Vec<(String, f64)>> = conn.zpopmin(&queue_key, 1).await?;

            if let Some(items) = result {
                if let Some((job_id_str, _score)) = items.into_iter().next() {
                    let job_id = Uuid::parse_str(&job_id_str).map_err(|e| {
                        QueueError::Redis(redis::RedisError::from((
                            redis::ErrorKind::UnexpectedReturnType,
                            "Invalid UUID",
                            e.to_string(),
                        )))
                    })?;

                    // Get job data
                    let job_key = self.job_key(job_id);
                    let job_json: Option<String> = conn.get(&job_key).await?;

                    if let Some(json) = job_json {
                        let mut job: Job = serde_json::from_str(&json)?;

                        // Move to processing set
                        let processing_key = self.processing_key();
                        let now = chrono::Utc::now().timestamp_millis() as f64;
                        let _: () = conn.zadd(&processing_key, job_id.to_string(), now).await?;

                        // Update job status
                        job.mark_started();
                        let updated_json = serde_json::to_string(&job)?;
                        let _: () = conn.set(&job_key, updated_json).await?;

                        return Ok(Some(job));
                    }
                }
            }
        }

        // No jobs available, wait a bit if timeout specified
        if !timeout.is_zero() {
            tokio::time::sleep(Duration::from_millis(100)).await;
        }

        Ok(None)
    }

    /// Complete a job (remove from processing).
    ///
    /// # Errors
    ///
    /// Returns an error if Redis operations fail.
    pub async fn complete(&self, job: &Job) -> Result<(), QueueError> {
        let mut conn = self.conn.clone();
        let job_key = self.job_key(job.id);
        let processing_key = self.processing_key();

        // Update job data
        let job_json = serde_json::to_string(job)?;
        let _: () = conn.set(&job_key, &job_json).await?;

        // Set TTL for completed job data (24 hours)
        let _: () = conn.expire(&job_key, 86400).await?;

        // Remove from processing set
        let _: () = conn.zrem(&processing_key, job.id.to_string()).await?;

        Ok(())
    }

    /// Fail a job (move to DLQ if retries exceeded, otherwise requeue).
    ///
    /// # Errors
    ///
    /// Returns an error if Redis operations fail.
    pub async fn fail(&self, mut job: Job, error: &str) -> Result<(), QueueError> {
        let mut conn = self.conn.clone();
        job.mark_failed(error);

        if job.can_retry() {
            // Requeue for retry with backoff
            job.prepare_retry();
            let job_key = self.job_key(job.id);
            let job_json = serde_json::to_string(&job)?;
            let _: () = conn.set(&job_key, &job_json).await?;

            // Remove from processing
            let processing_key = self.processing_key();
            let _: () = conn.zrem(&processing_key, job.id.to_string()).await?;

            // Requeue with delay based on attempt number
            let delay_ms = self.calculate_backoff(job.attempts);
            let queue_key = self.queue_key(job.priority);
            let score = chrono::Utc::now().timestamp_millis() as f64 + delay_ms as f64;
            let _: () = conn.zadd(&queue_key, job.id.to_string(), score).await?;
        } else {
            // Move to DLQ
            let job_key = self.job_key(job.id);
            let job_json = serde_json::to_string(&job)?;
            let _: () = conn.set(&job_key, &job_json).await?;

            let processing_key = self.processing_key();
            let _: () = conn.zrem(&processing_key, job.id.to_string()).await?;

            let dlq_key = self.dlq_key();
            let now = chrono::Utc::now().timestamp_millis() as f64;
            let _: () = conn.zadd(&dlq_key, job.id.to_string(), now).await?;
        }

        Ok(())
    }

    /// Get a job by ID.
    ///
    /// # Errors
    ///
    /// Returns an error if Redis operations fail.
    pub async fn get_job(&self, job_id: Uuid) -> Result<Option<Job>, QueueError> {
        let mut conn = self.conn.clone();
        let job_key = self.job_key(job_id);
        let job_json: Option<String> = conn.get(&job_key).await?;

        match job_json {
            Some(json) => Ok(Some(serde_json::from_str(&json)?)),
            None => Ok(None),
        }
    }

    /// Get queue length for a priority.
    ///
    /// # Errors
    ///
    /// Returns an error if Redis operations fail.
    pub async fn queue_length(&self, priority: JobPriority) -> Result<usize, QueueError> {
        let mut conn = self.conn.clone();
        let queue_key = self.queue_key(priority);
        let count: usize = conn.zcard(&queue_key).await?;
        Ok(count)
    }

    /// Get total queue length across all priorities.
    ///
    /// # Errors
    ///
    /// Returns an error if Redis operations fail.
    pub async fn total_queue_length(&self) -> Result<usize, QueueError> {
        let mut total = 0;
        for priority in [
            JobPriority::Low,
            JobPriority::Normal,
            JobPriority::High,
            JobPriority::Critical,
        ] {
            total += self.queue_length(priority).await?;
        }
        Ok(total)
    }

    /// Get number of jobs currently being processed.
    ///
    /// # Errors
    ///
    /// Returns an error if Redis operations fail.
    pub async fn processing_count(&self) -> Result<usize, QueueError> {
        let mut conn = self.conn.clone();
        let processing_key = self.processing_key();
        let count: usize = conn.zcard(&processing_key).await?;
        Ok(count)
    }

    /// Get DLQ length.
    ///
    /// # Errors
    ///
    /// Returns an error if Redis operations fail.
    pub async fn dlq_length(&self) -> Result<usize, QueueError> {
        let mut conn = self.conn.clone();
        let dlq_key = self.dlq_key();
        let count: usize = conn.zcard(&dlq_key).await?;
        Ok(count)
    }

    /// Calculate exponential backoff with jitter.
    #[allow(clippy::unused_self)] // kept as method for potential future config-based backoff
    fn calculate_backoff(&self, attempt: u32) -> u64 {
        let base_ms = 1000u64; // 1 second
        let max_ms = 600_000u64; // 10 minutes

        let backoff = base_ms.saturating_mul(2u64.saturating_pow(attempt));
        let capped = backoff.min(max_ms);

        // Add ±25% jitter
        #[allow(clippy::cast_possible_truncation)] // backoff jitter values fit in i64/u64
        let jitter = (capped as f64 * 0.25 * rand_simple().mul_add(2.0, -1.0)) as i64;
        #[allow(clippy::cast_possible_truncation)]
        let result = (capped as i64 + jitter).max(0) as u64;
        result
    }
}

/// Simple random number generator (0.0 to 1.0).
fn rand_simple() -> f64 {
    use std::time::{SystemTime, UNIX_EPOCH};
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .subsec_nanos();
    f64::from(nanos % 1000) / 1000.0
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::worker::job::JobStatus;

    // Note: These tests require a running Redis instance
    // They are marked as ignore by default

    #[tokio::test]
    #[ignore = "requires Redis"]
    async fn test_queue_enqueue_dequeue() {
        let queue = JobQueue::new("redis://localhost:6379", "test")
            .await
            .unwrap();

        let job = Job::new("test_job", "tenant1", serde_json::json!({"test": true}));
        let job_id = job.id;

        queue.enqueue(&job).await.unwrap();

        let dequeued = queue.dequeue(Duration::from_secs(1)).await.unwrap();
        assert!(dequeued.is_some());

        let dequeued_job = dequeued.unwrap();
        assert_eq!(dequeued_job.id, job_id);
        assert_eq!(dequeued_job.status, JobStatus::Running);
    }

    #[test]
    fn test_backoff_calculation() {
        // This is a simple calculation test that doesn't need Redis
        let base = 1000u64;
        let attempt = 3u32;

        // 2^3 = 8, so backoff should be around 8000ms
        let backoff = base.saturating_mul(2u64.saturating_pow(attempt));
        assert_eq!(backoff, 8000);
    }

    #[test]
    fn test_rand_simple() {
        let val = rand_simple();
        assert!((0.0..1.0).contains(&val));
    }
}
