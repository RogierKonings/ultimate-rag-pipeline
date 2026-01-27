//! Video extraction types and operations.
//!
//! This module provides types for configuring and representing video extraction
//! operations including keyframe extraction and audio extraction.

mod types;

pub use types::{
    AudioConfig, AudioMetadata, ExtractedKeyframe, KeyframeConfig, VideoMetadata,
};
