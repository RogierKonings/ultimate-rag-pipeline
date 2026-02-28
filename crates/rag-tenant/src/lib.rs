//! Tenant configuration management for multi-tenancy.
//!
//! This crate provides:
//! - Tenant index configuration (Qdrant collection, OpenSearch index)
//! - Redis-backed caching for tenant configs
//! - Isolation mode management (shared vs dedicated indices)
//!
//! # Example
//!
//! ```no_run
//! use rag_tenant::{TenantConfigService, TenantIndexConfig, IsolationMode};
//! use uuid::Uuid;
//!
//! #[tokio::main]
//! async fn main() -> Result<(), Box<dyn std::error::Error>> {
//!     // Create service with database pool and redis client
//!     // let service = TenantConfigService::new(pool, redis);
//!
//!     // Get tenant configuration
//!     // let config = service.get_config(&tenant_id).await?;
//!     // println!("Qdrant collection: {}", config.qdrant_collection);
//!
//!     Ok(())
//! }
//! ```

mod cache;
mod config;
mod error;
mod service;

pub use cache::TenantConfigCache;
pub use config::{IsolationMode, TenantIndexConfig};
pub use error::{Result, TenantError};
pub use service::TenantConfigService;
