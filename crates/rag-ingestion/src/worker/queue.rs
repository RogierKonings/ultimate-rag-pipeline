//! Redis-backed job queue.

use redis::aio::ConnectionManager;
use redis::{AsyncCommands, Script};
use std::time::Duration;
use thiserror::Error;
use tracing::warn;
use uuid::Uuid;

use super::job::{Job, JobPriority, JobStatus};

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

    /// Ping Redis to verify connectivity.
    ///
    /// # Errors
    ///
    /// Returns an error if the Redis PING command fails.
    pub async fn ping(&self) -> Result<(), QueueError> {
        let mut conn = self.conn.clone();
        redis::cmd("PING").query_async::<String>(&mut conn).await?;
        Ok(())
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

    /// Get the notification list key used to wake blocking dequeue callers.
    fn notify_key(&self) -> String {
        format!("{}:notify", self.prefix)
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

        // Wake any workers that are blocking on dequeue
        let notify_key = self.notify_key();
        let _: () = conn.lpush(&notify_key, "1").await?;

        Ok(())
    }

    /// Dequeue a job, blocking up to `timeout`.
    ///
    /// Checks all priority queues for ready jobs (those with score <= now).
    /// If no ready jobs exist, blocks efficiently using Redis `BLPOP` on a
    /// notification list, waking either when a new job is enqueued or when
    /// the next delayed job becomes ready (whichever comes first).
    ///
    /// # Errors
    ///
    /// Returns an error if Redis operations fail.
    #[allow(clippy::too_many_lines)]
    pub async fn dequeue(&self, timeout: Duration) -> Result<Option<Job>, QueueError> {
        let mut conn = self.conn.clone();
        let deadline = std::time::Instant::now() + timeout;

        let priorities = [
            JobPriority::Critical,
            JobPriority::High,
            JobPriority::Normal,
            JobPriority::Low,
        ];

        // Lua script that atomically peeks and pops only if the lowest-scored
        // member has a score <= the current timestamp. This respects the backoff
        // delay set by `fail` which uses a future timestamp as the score.
        let dequeue_script = Script::new(
            r"
            local result = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, 1)
            if #result > 0 then
                redis.call('ZREM', KEYS[1], result[1])
                return result[1]
            end
            return nil
            ",
        );

        // Lua script that returns the minimum score across the given sorted-set
        // keys. Returns nil when all sets are empty.
        let min_score_script = Script::new(
            r"
            local min = nil
            for i = 1, #KEYS do
                local members = redis.call('ZRANGE', KEYS[i], 0, 0, 'WITHSCORES')
                if #members == 2 then
                    local score = tonumber(members[2])
                    if min == nil or score < min then
                        min = score
                    end
                end
            end
            if min then
                return tostring(min)
            end
            return nil
            ",
        );

        loop {
            let now_ms = chrono::Utc::now().timestamp_millis();

            // Check all priority queues for a ready job
            for priority in priorities {
                let queue_key = self.queue_key(priority);

                let result: Option<String> = dequeue_script
                    .key(&queue_key)
                    .arg(now_ms)
                    .invoke_async(&mut conn)
                    .await?;

                if let Some(job_id_str) = result {
                    let job_id = Uuid::parse_str(&job_id_str).map_err(|e| {
                        QueueError::Redis(redis::RedisError::from((
                            redis::ErrorKind::UnexpectedReturnType,
                            "Invalid UUID",
                            e.to_string(),
                        )))
                    })?;

                    let job_key = self.job_key(job_id);
                    let job_json: Option<String> = conn.get(&job_key).await?;

                    if let Some(json) = job_json {
                        let mut job: Job = serde_json::from_str(&json)?;

                        let processing_key = self.processing_key();
                        let now = chrono::Utc::now().timestamp_millis() as f64;
                        let _: () = conn.zadd(&processing_key, job_id.to_string(), now).await?;

                        job.mark_started();
                        let updated_json = serde_json::to_string(&job)?;
                        let _: () = conn.set(&job_key, updated_json).await?;

                        return Ok(Some(job));
                    }
                }
            }

            // No ready jobs — check remaining timeout
            let now_instant = std::time::Instant::now();
            if now_instant >= deadline {
                return Ok(None);
            }
            let remaining = deadline - now_instant;

            // Peek at the earliest delayed job across all priority queues
            let queue_keys: Vec<String> = priorities.iter().map(|p| self.queue_key(*p)).collect();
            let earliest_score: Option<String> = {
                let mut inv = min_score_script.prepare_invoke();
                for k in &queue_keys {
                    inv.key(k);
                }
                inv.invoke_async(&mut conn).await?
            };

            // Calculate how long to wait
            let wait_duration = if let Some(score_str) = earliest_score {
                if let Ok(score) = score_str.parse::<f64>() {
                    let now_ms_f = chrono::Utc::now().timestamp_millis() as f64;
                    let delay_ms = (score - now_ms_f).max(0.0);
                    #[allow(clippy::cast_possible_truncation)]
                    // delay_ms is non-negative and bounded
                    let delay = Duration::from_millis(delay_ms as u64);
                    remaining.min(delay)
                } else {
                    remaining
                }
            } else {
                // Queues are completely empty — wait the full remaining timeout
                remaining
            };

            // Block-wait on the notification list. A new enqueue will wake us
            // via LPUSH, or we'll time out and re-check for delayed jobs.
            if wait_duration.is_zero() {
                // Delayed job is now ready — loop immediately
                continue;
            }

            let notify_key = self.notify_key();
            // BLPOP timeout is in seconds (fractional since Redis 6.0)
            let wait_secs = wait_duration.as_secs_f64();
            let _: Option<(String, String)> = redis::cmd("BLPOP")
                .arg(&notify_key)
                .arg(wait_secs)
                .query_async(&mut conn)
                .await?;
        }
    }

    /// Reclaim jobs that have been stuck in processing beyond `stale_after`.
    ///
    /// This recovers jobs after worker crashes by turning stale running jobs
    /// into retry attempts (or DLQ entries when retries are exhausted).
    ///
    /// # Errors
    ///
    /// Returns an error if Redis operations fail.
    pub async fn reclaim_stuck_processing(
        &self,
        stale_after: Duration,
        batch_size: usize,
    ) -> Result<usize, QueueError> {
        if batch_size == 0 {
            return Ok(0);
        }

        let mut conn = self.conn.clone();
        let processing_key = self.processing_key();

        #[allow(clippy::cast_possible_truncation)] // bounded to i64::MAX
        let stale_after_ms = stale_after.as_millis().min(i64::MAX as u128) as i64;
        let cutoff_ms = chrono::Utc::now()
            .timestamp_millis()
            .saturating_sub(stale_after_ms);

        // Atomically claim stale IDs by removing them from the processing set.
        let reclaim_script = Script::new(
            r"
            local stale = redis.call('ZRANGEBYSCORE', KEYS[1], '-inf', ARGV[1], 'LIMIT', 0, ARGV[2])
            local claimed = {}
            for i = 1, #stale do
                if redis.call('ZREM', KEYS[1], stale[i]) == 1 then
                    table.insert(claimed, stale[i])
                end
            end
            return claimed
            ",
        );

        let claimed_ids: Vec<String> = reclaim_script
            .key(&processing_key)
            .arg(cutoff_ms)
            .arg(batch_size)
            .invoke_async(&mut conn)
            .await?;

        let mut reclaimed = 0usize;

        for job_id_str in claimed_ids {
            let Ok(job_id) = Uuid::parse_str(&job_id_str) else {
                warn!(
                    job_id = %job_id_str,
                    "Skipping invalid job ID while reclaiming stuck jobs"
                );
                continue;
            };

            let Some(job) = self.get_job(job_id).await? else {
                warn!(
                    %job_id,
                    "Stale processing entry had no job payload; skipping reclaim"
                );
                continue;
            };

            if job.status != JobStatus::Running {
                warn!(
                    %job_id,
                    status = ?job.status,
                    "Skipping reclaim for non-running job state"
                );
                continue;
            }

            self.fail(
                job,
                "Job reclaimed after worker crash or stale processing timeout",
            )
            .await?;
            reclaimed += 1;
        }

        Ok(reclaimed)
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

            // Wake blocked workers so they can recalculate earliest ready job.
            let notify_key = self.notify_key();
            let _: () = conn.lpush(&notify_key, "1").await?;
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
    use uuid::Uuid;

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

    #[tokio::test]
    #[ignore = "requires Redis"]
    async fn test_reclaim_stuck_processing_retries_job() {
        let prefix = format!("test-reclaim-{}", Uuid::new_v4());
        let queue = JobQueue::new("redis://localhost:6379", &prefix)
            .await
            .unwrap();

        let job =
            Job::new("test_job", "tenant1", serde_json::json!({"test": true})).with_max_retries(3);
        let job_id = job.id;

        queue.enqueue(&job).await.unwrap();

        let running = queue
            .dequeue(Duration::from_secs(1))
            .await
            .unwrap()
            .unwrap();
        assert_eq!(running.id, job_id);
        assert_eq!(running.status, JobStatus::Running);
        assert_eq!(running.attempts, 1);

        let reclaimed = queue
            .reclaim_stuck_processing(Duration::from_millis(0), 10)
            .await
            .unwrap();
        assert_eq!(reclaimed, 1);

        tokio::time::sleep(Duration::from_secs(4)).await;

        let retried = queue
            .dequeue(Duration::from_secs(1))
            .await
            .unwrap()
            .unwrap();
        assert_eq!(retried.id, job_id);
        assert_eq!(retried.status, JobStatus::Running);
        assert_eq!(retried.attempts, 2);

        let mut completed = retried;
        completed.mark_completed();
        queue.complete(&completed).await.unwrap();
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
