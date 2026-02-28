//! S3/MinIO storage client for the RAG Pipeline.
//!
//! This crate provides object storage functionality:
//! - Bucket management (create, delete, list)
//! - Object operations (upload, download, delete)
//! - Streaming upload/download for large files
//! - Presigned URL generation
//! - MinIO compatibility
//!
//! # Example
//!
//! ```no_run
//! use rag_storage::{StorageClient, StorageConfig};
//!
//! #[tokio::main]
//! async fn main() -> Result<(), Box<dyn std::error::Error>> {
//!     let config = StorageConfig::minio("http://localhost:9000", "minioadmin", "minioadmin");
//!     let client = StorageClient::new(&config).await?;
//!
//!     // Upload a file
//!     client.put_object(Some("my-bucket"), "file.txt", b"Hello, world!".to_vec()).await?;
//!
//!     // Download the file
//!     let data = client.get_object(Some("my-bucket"), "file.txt").await?;
//!
//!     // Generate presigned URL
//!     let url = client.presigned_get_url(Some("my-bucket"), "file.txt", 3600).await?;
//!
//!     Ok(())
//! }
//! ```

mod client;
mod config;
mod error;

pub use client::StorageClient;
pub use config::StorageConfig;
pub use error::{Result, StorageError};
