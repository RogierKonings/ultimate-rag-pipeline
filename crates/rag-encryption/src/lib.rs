//! Field-level encryption for the RAG Pipeline.
#![allow(clippy::significant_drop_tightening)] // Lock guards need to be held for consistency
#![allow(clippy::missing_const_for_fn)] // Too strict for this crate
#![allow(clippy::redundant_clone)] // Sometimes needed for borrow checker
#![allow(clippy::must_use_candidate)] // Too noisy
//!
//! This crate provides encryption utilities for sensitive data:
//! - AES-GCM encryption for field-level data protection
//! - Key management with support for key rotation
//! - Integration with secrets providers
//!
//! # Example
//!
//! ```no_run
//! use rag_encryption::{FieldEncryptor, EncryptionConfig};
//!
//! #[tokio::main]
//! async fn main() -> Result<(), Box<dyn std::error::Error>> {
//!     let config = EncryptionConfig::from_env()?;
//!     let encryptor = FieldEncryptor::new(config)?;
//!
//!     // Encrypt sensitive data
//!     let plaintext = "sensitive-api-key";
//!     let encrypted = encryptor.encrypt(plaintext)?;
//!
//!     // Decrypt when needed
//!     let decrypted = encryptor.decrypt(&encrypted)?;
//!     assert_eq!(plaintext, decrypted);
//!
//!     Ok(())
//! }
//! ```

mod config;
mod encryptor;
mod error;
mod key_management;

pub use config::EncryptionConfig;
pub use encryptor::{EncryptedValue, FieldEncryptor};
pub use error::{EncryptionError, Result};
pub use key_management::{DerivedKey, KeyManager, KeyVersion};

#[cfg(feature = "secrets-integration")]
mod secrets_key_provider;

#[cfg(feature = "secrets-integration")]
pub use secrets_key_provider::{AsyncKeyProvider, SecretsKeyProvider};
