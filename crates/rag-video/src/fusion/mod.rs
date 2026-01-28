//! Content fusion module.
//!
//! Provides content fusion capabilities for combining transcript text,
//! scene descriptions, and OCR text into unified video chunks.

pub mod config;
pub mod service;
pub mod types;

pub use config::FusionConfig;
pub use service::ContentFusionService;
pub use types::{KeyframeWithContent, VideoChunk};
