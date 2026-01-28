//! HTTP clients for video processing services.
//!
//! This module provides HTTP clients for communicating with external services
//! used in the video processing pipeline.

pub mod scene_detection;
pub mod transcription;
pub mod types;

pub use scene_detection::{SceneDetectionClient, SceneDetectionConfig, SceneDetectionResult};
pub use transcription::{TranscriptionClient, TranscriptionConfig, TranscriptionResult};
pub use types::{SceneBoundary, TranscriptSegment};
