//! Secrets management for the RAG Pipeline.
//!
//! This crate provides a unified interface for secrets retrieval from:
//! - HashiCorp Vault
//! - Kubernetes secrets (with `kubernetes` feature)
//! - Environment variables (fallback)
//!
//! # Example
//!
//! ```no_run
//! use rag_secrets::{SecretsProvider, EnvProvider, ChainedProvider};
//!
//! #[tokio::main]
//! async fn main() -> Result<(), Box<dyn std::error::Error>> {
//!     // Create an environment-based provider
//!     let provider = EnvProvider::new();
//!
//!     // Get a secret
//!     let secret = provider.get_secret("DATABASE_PASSWORD").await?;
//!     println!("Got secret: {}", secret);
//!
//!     Ok(())
//! }
//! ```

mod config;
mod env;
mod error;
mod provider;
mod vault;

#[cfg(feature = "kubernetes")]
mod k8s;

pub use config::SecretsConfig;
pub use env::EnvProvider;
pub use error::{Result, SecretsError};
pub use provider::{ChainedProvider, SecretsProvider};
pub use vault::VaultProvider;

#[cfg(feature = "kubernetes")]
pub use k8s::K8sProvider;
