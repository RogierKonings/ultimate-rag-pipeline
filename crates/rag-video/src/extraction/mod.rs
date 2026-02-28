//! Video extraction types and operations.
//!
//! This module provides types for configuring and representing video extraction
//! operations including keyframe extraction and audio extraction.

pub mod audio;
pub mod keyframe;
pub mod metadata;
mod types;

pub use audio::AudioExtractor;
pub use keyframe::KeyframeExtractor;
pub use metadata::MetadataProbe;
pub use types::{AudioConfig, AudioMetadata, ExtractedKeyframe, KeyframeConfig, VideoMetadata};
