//! Async worker system for background job processing.
//!
//! This module provides a Redis-backed job queue and worker pool
//! for processing ingestion tasks asynchronously.
//!
//! # Architecture
//!
//! - **JobQueue**: Redis-backed priority queue with DLQ support
//! - **WorkerPool**: Tokio-based worker pool with configurable concurrency
//! - **JobHandler**: Trait for implementing job processors
//!
//! # Example
//!
//! ```ignore
//! use rag_ingestion::worker::{Job, JobQueue, WorkerPool, WorkerPoolConfig, JobHandler};
//!
//! // Create a job handler
//! struct MyHandler;
//!
//! #[async_trait::async_trait]
//! impl JobHandler for MyHandler {
//!     async fn handle(&self, job: &Job) -> Result<serde_json::Value, String> {
//!         // Process the job
//!         Ok(serde_json::json!({"status": "done"}))
//!     }
//! }
//!
//! // Start the worker pool
//! let queue = JobQueue::new("redis://localhost:6379", "ingestion").await?;
//! let mut pool = WorkerPool::new(WorkerPoolConfig::default(), Arc::new(MyHandler));
//! pool.start(queue).await?;
//! ```

mod job;
mod pool;
mod queue;

pub use job::{Job, JobPriority, JobResult, JobStatus};
pub use pool::{JobHandler, RouterHandler, WorkerPool, WorkerPoolConfig};
pub use queue::{JobQueue, QueueError};
