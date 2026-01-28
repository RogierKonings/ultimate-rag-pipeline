//! Pipeline configuration.

use std::path::PathBuf;
use std::time::Duration;

use crate::clients::{SceneDetectionConfig, TranscriptionConfig};
use crate::extraction::{AudioConfig, KeyframeConfig};
use crate::fusion::FusionConfig;
use crate::indexer::VideoIndexerConfig;

/// Configuration for the video processing pipeline.
#[derive(Debug, Clone)]
pub struct PipelineConfig {
    /// Working directory for intermediate files.
    pub work_dir: PathBuf,
    /// Whether to clean up intermediate files after processing.
    pub cleanup_intermediate: bool,
    /// Whether to run parallel stages concurrently.
    pub enable_parallelism: bool,
    /// Overall pipeline timeout.
    pub timeout: Duration,
    /// Keyframe extraction configuration.
    pub keyframe_config: KeyframeConfig,
    /// Audio extraction configuration.
    pub audio_config: AudioConfig,
    /// Scene detection configuration.
    pub scene_detection_config: SceneDetectionConfig,
    /// Transcription configuration.
    pub transcription_config: TranscriptionConfig,
    /// Content fusion configuration.
    pub fusion_config: FusionConfig,
    /// Video indexer configuration.
    pub indexer_config: VideoIndexerConfig,
    /// Embedding service URL.
    pub embedding_url: String,
    /// Embedding batch size.
    pub embedding_batch_size: usize,
    /// Embedding timeout per batch.
    pub embedding_timeout: Duration,
}

impl Default for PipelineConfig {
    fn default() -> Self {
        Self {
            work_dir: PathBuf::from("/tmp/rag-video"),
            cleanup_intermediate: true,
            enable_parallelism: true,
            timeout: Duration::from_secs(600), // 10 minutes
            keyframe_config: KeyframeConfig::default(),
            audio_config: AudioConfig::default(),
            scene_detection_config: SceneDetectionConfig::default(),
            transcription_config: TranscriptionConfig::default(),
            fusion_config: FusionConfig::default(),
            indexer_config: VideoIndexerConfig::default(),
            embedding_url: "http://localhost:8080".to_string(),
            embedding_batch_size: 32,
            embedding_timeout: Duration::from_secs(30),
        }
    }
}

impl PipelineConfig {
    /// Create a new pipeline config with the specified work directory.
    #[must_use]
    pub fn new(work_dir: impl Into<PathBuf>) -> Self {
        Self {
            work_dir: work_dir.into(),
            ..Default::default()
        }
    }

    /// Builder: set cleanup intermediate files.
    #[must_use]
    pub const fn with_cleanup(mut self, cleanup: bool) -> Self {
        self.cleanup_intermediate = cleanup;
        self
    }

    /// Builder: set parallelism enabled.
    #[must_use]
    pub const fn with_parallelism(mut self, enabled: bool) -> Self {
        self.enable_parallelism = enabled;
        self
    }

    /// Builder: set overall timeout.
    #[must_use]
    pub const fn with_timeout(mut self, timeout: Duration) -> Self {
        self.timeout = timeout;
        self
    }

    /// Builder: set keyframe config.
    #[must_use]
    pub fn with_keyframe_config(mut self, config: KeyframeConfig) -> Self {
        self.keyframe_config = config;
        self
    }

    /// Builder: set audio config.
    #[must_use]
    pub fn with_audio_config(mut self, config: AudioConfig) -> Self {
        self.audio_config = config;
        self
    }

    /// Builder: set scene detection config.
    #[must_use]
    pub fn with_scene_detection_config(mut self, config: SceneDetectionConfig) -> Self {
        self.scene_detection_config = config;
        self
    }

    /// Builder: set transcription config.
    #[must_use]
    pub fn with_transcription_config(mut self, config: TranscriptionConfig) -> Self {
        self.transcription_config = config;
        self
    }

    /// Builder: set fusion config.
    #[must_use]
    pub fn with_fusion_config(mut self, config: FusionConfig) -> Self {
        self.fusion_config = config;
        self
    }

    /// Builder: set indexer config.
    #[must_use]
    pub fn with_indexer_config(mut self, config: VideoIndexerConfig) -> Self {
        self.indexer_config = config;
        self
    }

    /// Builder: set embedding URL.
    #[must_use]
    pub fn with_embedding_url(mut self, url: impl Into<String>) -> Self {
        self.embedding_url = url.into();
        self
    }

    /// Builder: set embedding batch size.
    #[must_use]
    pub const fn with_embedding_batch_size(mut self, size: usize) -> Self {
        self.embedding_batch_size = size;
        self
    }

    /// Get the path for a video's work directory.
    #[must_use]
    pub fn video_work_dir(&self, video_id: &str) -> PathBuf {
        self.work_dir.join(video_id)
    }

    /// Get the path for extracted keyframes.
    #[must_use]
    pub fn keyframes_dir(&self, video_id: &str) -> PathBuf {
        self.video_work_dir(video_id).join("keyframes")
    }

    /// Get the path for extracted audio.
    #[must_use]
    pub fn audio_path(&self, video_id: &str) -> PathBuf {
        self.video_work_dir(video_id).join("audio.wav")
    }

    /// Validate the configuration.
    ///
    /// # Errors
    ///
    /// Returns an error if validation fails.
    pub fn validate(&self) -> Result<(), String> {
        if self.embedding_batch_size == 0 {
            return Err("Embedding batch size must be greater than 0".to_string());
        }
        if self.embedding_url.is_empty() {
            return Err("Embedding URL must not be empty".to_string());
        }
        if self.timeout.is_zero() {
            return Err("Pipeline timeout must be greater than 0".to_string());
        }

        // Validate nested configs
        self.indexer_config.validate()?;
        self.fusion_config.validate()?;

        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_pipeline_config_default() {
        let config = PipelineConfig::default();
        assert!(config.cleanup_intermediate);
        assert!(config.enable_parallelism);
        assert_eq!(config.embedding_batch_size, 32);
    }

    #[test]
    fn test_pipeline_config_new() {
        let config = PipelineConfig::new("/custom/path");
        assert_eq!(config.work_dir, PathBuf::from("/custom/path"));
    }

    #[test]
    fn test_pipeline_config_builder() {
        let config = PipelineConfig::default()
            .with_cleanup(false)
            .with_parallelism(false)
            .with_timeout(Duration::from_secs(300))
            .with_embedding_batch_size(64)
            .with_embedding_url("http://custom:8080");

        assert!(!config.cleanup_intermediate);
        assert!(!config.enable_parallelism);
        assert_eq!(config.timeout, Duration::from_secs(300));
        assert_eq!(config.embedding_batch_size, 64);
        assert_eq!(config.embedding_url, "http://custom:8080");
    }

    #[test]
    fn test_video_work_dir() {
        let config = PipelineConfig::new("/tmp/rag");
        assert_eq!(
            config.video_work_dir("video123"),
            PathBuf::from("/tmp/rag/video123")
        );
    }

    #[test]
    fn test_keyframes_dir() {
        let config = PipelineConfig::new("/tmp/rag");
        assert_eq!(
            config.keyframes_dir("video123"),
            PathBuf::from("/tmp/rag/video123/keyframes")
        );
    }

    #[test]
    fn test_audio_path() {
        let config = PipelineConfig::new("/tmp/rag");
        assert_eq!(
            config.audio_path("video123"),
            PathBuf::from("/tmp/rag/video123/audio.wav")
        );
    }

    #[test]
    fn test_validate_success() {
        let config = PipelineConfig::default();
        assert!(config.validate().is_ok());
    }

    #[test]
    fn test_validate_zero_batch_size() {
        let config = PipelineConfig::default().with_embedding_batch_size(0);
        assert!(config.validate().is_err());
    }

    #[test]
    fn test_validate_empty_embedding_url() {
        let config = PipelineConfig::default().with_embedding_url("");
        assert!(config.validate().is_err());
    }

    #[test]
    fn test_validate_zero_timeout() {
        let config = PipelineConfig::default().with_timeout(Duration::ZERO);
        assert!(config.validate().is_err());
    }

    #[test]
    fn test_config_clone() {
        let config = PipelineConfig::default();
        let cloned = config.clone();
        assert_eq!(config.work_dir, cloned.work_dir);
        assert_eq!(config.embedding_batch_size, cloned.embedding_batch_size);
    }

    #[test]
    fn test_config_debug() {
        let config = PipelineConfig::default();
        let debug = format!("{config:?}");
        assert!(debug.contains("PipelineConfig"));
        assert!(debug.contains("work_dir"));
    }
}
