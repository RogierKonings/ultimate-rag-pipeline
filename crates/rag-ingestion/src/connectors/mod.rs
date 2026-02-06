//! Document connectors for various storage backends.
//!
//! This module provides connectors for loading documents from:
//! - Local filesystem ([`FilesystemConnector`])
//! - S3/MinIO object storage ([`S3Connector`])

mod base;
mod filesystem;
mod s3;

pub use base::{Connector, DocumentMetadata, RawDocument, StorageBackend};
pub use filesystem::{FilesystemConfig, FilesystemConnector};
pub use s3::{S3Config, S3Connector};
