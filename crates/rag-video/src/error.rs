//! Error types for video processing operations.

use thiserror::Error;

/// Errors that can occur during video processing operations.
#[derive(Debug, Error)]
pub enum VideoError {
    /// The specified video file was not found.
    #[error("Video file not found: {0}")]
    FileNotFound(String),

    /// The video format is invalid or unsupported.
    #[error("Invalid video format: {0}")]
    InvalidFormat(String),

    /// An error occurred during `FFmpeg` processing.
    #[error("FFmpeg error: {0}")]
    Ffmpeg(String),

    /// An error occurred during OCR processing.
    #[error("OCR error: {0}")]
    Ocr(String),

    /// An error occurred during scene detection.
    #[error("Scene detection error: {0}")]
    SceneDetection(String),

    /// An error occurred during transcription.
    #[error("Transcription error: {0}")]
    Transcription(String),

    /// An error occurred during indexing.
    #[error("Indexing error: {0}")]
    Indexing(String),

    /// An error occurred during embedding generation.
    #[error("Embedding error: {0}")]
    Embedding(String),

    /// An HTTP request error occurred.
    #[error("HTTP error: {0}")]
    Http(#[from] reqwest::Error),

    /// An I/O error occurred.
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),

    /// A timeout occurred during processing.
    #[error("Operation timed out after {0}ms")]
    Timeout(u64),

    /// An error occurred with Qdrant operations.
    #[error("Qdrant error: {0}")]
    Qdrant(String),
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_file_not_found_error() {
        let err = VideoError::FileNotFound("/path/to/video.mp4".to_string());
        assert_eq!(
            err.to_string(),
            "Video file not found: /path/to/video.mp4"
        );
    }

    #[test]
    fn test_invalid_format_error() {
        let err = VideoError::InvalidFormat("unsupported codec".to_string());
        assert_eq!(err.to_string(), "Invalid video format: unsupported codec");
    }

    #[test]
    fn test_ffmpeg_error() {
        let err = VideoError::Ffmpeg("exit code 1".to_string());
        assert_eq!(err.to_string(), "FFmpeg error: exit code 1");
    }

    #[test]
    fn test_ocr_error() {
        let err = VideoError::Ocr("tesseract failed".to_string());
        assert_eq!(err.to_string(), "OCR error: tesseract failed");
    }

    #[test]
    fn test_scene_detection_error() {
        let err = VideoError::SceneDetection("threshold exceeded".to_string());
        assert_eq!(
            err.to_string(),
            "Scene detection error: threshold exceeded"
        );
    }

    #[test]
    fn test_transcription_error() {
        let err = VideoError::Transcription("whisper failed".to_string());
        assert_eq!(err.to_string(), "Transcription error: whisper failed");
    }

    #[test]
    fn test_indexing_error() {
        let err = VideoError::Indexing("vector store unavailable".to_string());
        assert_eq!(
            err.to_string(),
            "Indexing error: vector store unavailable"
        );
    }

    #[test]
    fn test_embedding_error() {
        let err = VideoError::Embedding("service unavailable".to_string());
        assert_eq!(err.to_string(), "Embedding error: service unavailable");
    }

    #[test]
    fn test_io_error_conversion() {
        let io_err = std::io::Error::new(std::io::ErrorKind::NotFound, "file missing");
        let err: VideoError = io_err.into();
        assert!(matches!(err, VideoError::Io(_)));
        assert!(err.to_string().contains("file missing"));
    }

    #[test]
    fn test_timeout_error() {
        let err = VideoError::Timeout(5000);
        assert_eq!(err.to_string(), "Operation timed out after 5000ms");
    }

    #[test]
    fn test_qdrant_error() {
        let err = VideoError::Qdrant("connection refused".to_string());
        assert_eq!(err.to_string(), "Qdrant error: connection refused");
    }

    #[test]
    fn test_error_is_send_sync() {
        fn assert_send_sync<T: Send + Sync>() {}
        assert_send_sync::<VideoError>();
    }

    #[test]
    fn test_error_debug_impl() {
        let err = VideoError::FileNotFound("test.mp4".to_string());
        let debug_str = format!("{err:?}");
        assert!(debug_str.contains("FileNotFound"));
        assert!(debug_str.contains("test.mp4"));
    }
}
