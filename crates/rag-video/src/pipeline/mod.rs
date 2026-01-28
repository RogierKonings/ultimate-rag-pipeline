//! Video processing pipeline module.
//!
//! Provides orchestration for the video processing pipeline stages:
//! - Metadata probing
//! - Keyframe extraction
//! - Audio extraction
//! - Scene detection
//! - Transcription
//! - Content fusion
//! - Embedding generation
//! - Qdrant indexing

pub mod config;
pub mod executor;
pub mod stages;
pub mod types;

pub use config::PipelineConfig;
pub use executor::VideoPipeline;
pub use stages::PipelineStage;
pub use types::{PipelineProgress, PipelineResult, StageResult};
