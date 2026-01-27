//! HTTP clients for video processing services.
//!
//! This module provides HTTP clients for communicating with external services
//! used in the video processing pipeline.

pub mod scene_detection;
pub mod types;

pub use scene_detection::{SceneDetectionClient, SceneDetectionConfig, SceneDetectionResult};
pub use types::{SceneBoundary, TranscriptSegment};
