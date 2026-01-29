//! Worker pool for processing jobs.

use async_trait::async_trait;
use serde_json::Value;
use std::collections::HashMap;
use std::future::Future;
use std::pin::Pin;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::{broadcast, Semaphore};
use tokio::task::JoinHandle;
use tracing::{error, info, warn};

use super::job::Job;
use super::queue::{JobQueue, QueueError};

/// Worker pool configuration.
#[derive(Debug, Clone)]
pub struct WorkerPoolConfig {
    /// Number of worker tasks.
    pub concurrency: usize,
    /// Timeout for dequeue operations.
    pub dequeue_timeout: Duration,
    /// Timeout for job processing.
    pub job_timeout: Duration,
    /// Graceful shutdown timeout.
    pub shutdown_timeout: Duration,
}

impl Default for WorkerPoolConfig {
    fn default() -> Self {
        Self {
            concurrency: 4,
            dequeue_timeout: Duration::from_secs(5),
            job_timeout: Duration::from_secs(300), // 5 minutes
            shutdown_timeout: Duration::from_secs(30),
        }
    }
}

/// Job handler trait.
#[async_trait]
pub trait JobHandler: Send + Sync {
    /// Handle a job and return the result.
    async fn handle(&self, job: &Job) -> Result<Value, String>;
}

/// Worker pool for processing jobs from a queue.
pub struct WorkerPool {
    config: WorkerPoolConfig,
    handler: Arc<dyn JobHandler>,
    shutdown_tx: broadcast::Sender<()>,
    handles: Vec<JoinHandle<()>>,
}

impl WorkerPool {
    /// Create a new worker pool.
    #[must_use]
    pub fn new(config: WorkerPoolConfig, handler: Arc<dyn JobHandler>) -> Self {
        let (shutdown_tx, _) = broadcast::channel(1);

        Self {
            config,
            handler,
            shutdown_tx,
            handles: Vec::new(),
        }
    }

    /// Start the worker pool.
    ///
    /// # Errors
    ///
    /// Returns an error if workers fail to start.
    pub async fn start(&mut self, queue: JobQueue) -> Result<(), QueueError> {
        let queue = Arc::new(tokio::sync::Mutex::new(queue));
        let semaphore = Arc::new(Semaphore::new(self.config.concurrency));

        info!(
            concurrency = self.config.concurrency,
            "Starting worker pool"
        );

        for worker_id in 0..self.config.concurrency {
            let queue = Arc::clone(&queue);
            let semaphore = Arc::clone(&semaphore);
            let handler = Arc::clone(&self.handler);
            let config = self.config.clone();
            let mut shutdown_rx = self.shutdown_tx.subscribe();

            let handle = tokio::spawn(async move {
                loop {
                    // Check for shutdown signal
                    if shutdown_rx.try_recv().is_ok() {
                        info!(worker_id, "Worker received shutdown signal");
                        break;
                    }

                    // Acquire semaphore permit
                    let _permit = semaphore.acquire().await.expect("Semaphore closed");

                    // Try to dequeue a job
                    let job = {
                        let mut queue = queue.lock().await;
                        match queue.dequeue(config.dequeue_timeout).await {
                            Ok(job) => job,
                            Err(e) => {
                                error!(worker_id, error = %e, "Failed to dequeue job");
                                tokio::time::sleep(Duration::from_secs(1)).await;
                                continue;
                            }
                        }
                    };

                    if let Some(job) = job {
                        let job_id = job.id;
                        let job_type = job.job_type.clone();

                        info!(worker_id, %job_id, %job_type, "Processing job");

                        // Process job with timeout
                        let start = std::time::Instant::now();
                        let result =
                            tokio::time::timeout(config.job_timeout, handler.handle(&job)).await;

                        let duration_ms = start.elapsed().as_millis() as u64;

                        let mut queue = queue.lock().await;

                        match result {
                            Ok(Ok(_data)) => {
                                let mut completed_job = job;
                                completed_job.mark_completed();

                                if let Err(e) = queue.complete(&completed_job).await {
                                    error!(
                                        worker_id,
                                        %job_id,
                                        error = %e,
                                        "Failed to mark job complete"
                                    );
                                }

                                info!(
                                    worker_id,
                                    %job_id,
                                    %job_type,
                                    duration_ms,
                                    "Job completed successfully"
                                );
                            }
                            Ok(Err(error)) => {
                                warn!(
                                    worker_id,
                                    %job_id,
                                    %job_type,
                                    %error,
                                    "Job failed"
                                );

                                if let Err(e) = queue.fail(job, &error).await {
                                    error!(
                                        worker_id,
                                        %job_id,
                                        error = %e,
                                        "Failed to mark job failed"
                                    );
                                }
                            }
                            Err(_) => {
                                warn!(
                                    worker_id,
                                    %job_id,
                                    %job_type,
                                    "Job timed out"
                                );

                                if let Err(e) = queue.fail(job, "Job timed out").await {
                                    error!(
                                        worker_id,
                                        %job_id,
                                        error = %e,
                                        "Failed to mark job failed after timeout"
                                    );
                                }
                            }
                        }
                    }
                }
            });

            self.handles.push(handle);
        }

        Ok(())
    }

    /// Gracefully shutdown the worker pool.
    pub async fn shutdown(&mut self) {
        info!("Initiating worker pool shutdown");

        // Send shutdown signal
        let _ = self.shutdown_tx.send(());

        // Wait for workers to finish with timeout
        let shutdown_future = async {
            for handle in self.handles.drain(..) {
                let _ = handle.await;
            }
        };

        match tokio::time::timeout(self.config.shutdown_timeout, shutdown_future).await {
            Ok(()) => info!("Worker pool shutdown complete"),
            Err(_) => warn!("Worker pool shutdown timed out, some workers may still be running"),
        }
    }
}

/// Type alias for handler functions.
type HandlerFn =
    Arc<dyn Fn(Job) -> Pin<Box<dyn Future<Output = Result<Value, String>> + Send>> + Send + Sync>;

/// A handler that routes jobs to specific functions by job type.
pub struct RouterHandler {
    handlers: HashMap<String, HandlerFn>,
}

impl RouterHandler {
    /// Create a new router handler.
    #[must_use]
    pub fn new() -> Self {
        Self {
            handlers: HashMap::new(),
        }
    }

    /// Register a handler for a job type.
    pub fn register<F, Fut>(&mut self, job_type: &str, handler: F)
    where
        F: Fn(Job) -> Fut + Send + Sync + 'static,
        Fut: Future<Output = Result<Value, String>> + Send + 'static,
    {
        let handler: HandlerFn = Arc::new(move |job: Job| Box::pin(handler(job)));
        self.handlers.insert(job_type.to_string(), handler);
    }
}

impl Default for RouterHandler {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl JobHandler for RouterHandler {
    async fn handle(&self, job: &Job) -> Result<Value, String> {
        match self.handlers.get(&job.job_type) {
            Some(handler) => handler(job.clone()).await,
            None => Err(format!("Unknown job type: {}", job.job_type)),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct TestHandler;

    #[async_trait]
    impl JobHandler for TestHandler {
        async fn handle(&self, job: &Job) -> Result<Value, String> {
            Ok(serde_json::json!({"job_id": job.id.to_string()}))
        }
    }

    #[test]
    fn test_worker_pool_config_default() {
        let config = WorkerPoolConfig::default();
        assert_eq!(config.concurrency, 4);
        assert_eq!(config.job_timeout, Duration::from_secs(300));
    }

    #[tokio::test]
    async fn test_router_handler_unknown_type() {
        let handler = RouterHandler::new();
        let job = Job::new("unknown", "tenant1", serde_json::json!({}));

        let result = handler.handle(&job).await;

        assert!(result.is_err());
        assert!(result.unwrap_err().contains("Unknown job type"));
    }

    #[tokio::test]
    async fn test_router_handler_registered() {
        let mut handler = RouterHandler::new();
        handler.register("test", |job| async move {
            Ok(serde_json::json!({"processed": job.id.to_string()}))
        });

        let job = Job::new("test", "tenant1", serde_json::json!({}));
        let result = handler.handle(&job).await;

        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn test_handler_returns_result() {
        let handler = TestHandler;
        let job = Job::new("test", "tenant1", serde_json::json!({}));

        let result = handler.handle(&job).await;

        assert!(result.is_ok());
        let data = result.unwrap();
        assert!(data.get("job_id").is_some());
    }
}
