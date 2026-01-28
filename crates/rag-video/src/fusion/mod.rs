//! Content fusion module.
//!
//! Provides content fusion capabilities for combining transcript text,
//! scene descriptions, and OCR text into unified video chunks.

pub mod config;
pub mod types;

pub use config::FusionConfig;
pub use types::{KeyframeWithContent, VideoChunk};
