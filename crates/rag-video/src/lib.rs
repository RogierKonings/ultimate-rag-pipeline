//! Video processing pipeline for RAG.
//!
//! This crate provides functionality for processing video content in a RAG pipeline:
//! - Frame extraction using `FFmpeg`
//! - OCR text extraction from frames
//! - Scene detection and boundary identification
//! - Audio transcription integration
//! - Multi-modal fusion of text sources
//! - Vector indexing for semantic search

pub mod clients;
pub mod error;
pub mod extraction;
pub mod fusion;

pub use clients::{
    SceneBoundary, SceneDetectionClient, SceneDetectionConfig, SceneDetectionResult,
    TranscriptSegment, TranscriptionClient, TranscriptionConfig, TranscriptionResult,
};
pub use error::VideoError;
pub use extraction::{
    AudioConfig, AudioExtractor, AudioMetadata, ExtractedKeyframe, KeyframeConfig,
    KeyframeExtractor, MetadataProbe, VideoMetadata,
};
pub use fusion::{ContentFusionService, FusionConfig, KeyframeWithContent, VideoChunk};

/// A specialized Result type for video processing operations.
pub type Result<T> = std::result::Result<T, VideoError>;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_result_type_alias() {
        let ok_result: Result<i32> = Ok(42);
        assert_eq!(ok_result.unwrap(), 42);

        let err_result: Result<i32> = Err(VideoError::Timeout(1000));
        assert!(err_result.is_err());
    }

    #[test]
    fn test_error_reexport() {
        // Verify VideoError is accessible from crate root
        let err = VideoError::FileNotFound("video.mp4".to_string());
        assert!(err.to_string().contains("video.mp4"));
    }
}
