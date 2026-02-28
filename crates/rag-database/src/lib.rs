//! PostgreSQL database client for the RAG Pipeline.
//!
//! This crate provides database functionality:
//! - Connection pooling with sqlx
//! - Repository pattern for domain entities
//! - Transaction support
//! - Query building utilities
//!
//! # Example
//!
//! ```no_run
//! use rag_database::{DatabaseConfig, DatabasePool};
//!
//! #[tokio::main]
//! async fn main() -> Result<(), Box<dyn std::error::Error>> {
//!     let config = DatabaseConfig::from_env();
//!     let pool = DatabasePool::connect(&config).await?;
//!
//!     // Use the pool for queries
//!     let row: (i64,) = sqlx::query_as("SELECT 1")
//!         .fetch_one(pool.inner())
//!         .await?;
//!
//!     Ok(())
//! }
//! ```

mod config;
mod error;
mod models;
mod pool;
mod repositories;

pub use config::DatabaseConfig;
pub use error::{DatabaseError, Result};
pub use models::*;
pub use pool::DatabasePool;
pub use repositories::*;

// Re-export sqlx types for convenience
pub use sqlx::{FromRow, PgPool, Row};
