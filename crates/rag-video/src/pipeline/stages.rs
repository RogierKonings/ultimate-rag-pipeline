//! Pipeline stage definitions.

use std::fmt;

/// Pipeline stages in order of execution.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum PipelineStage {
    /// Probe video metadata (duration, resolution, codec, etc.).
    MetadataProbe,
    /// Extract keyframes at scene boundaries.
    KeyframeExtraction,
    /// Extract audio track to WAV file.
    AudioExtraction,
    /// Detect scene boundaries using `PySceneDetect` service.
    SceneDetection,
    /// Transcribe audio using Whisper service.
    Transcription,
    /// Fuse transcript, scene descriptions, and OCR into chunks.
    ContentFusion,
    /// Generate embeddings for fused chunks.
    EmbeddingGeneration,
    /// Index chunks in Qdrant vector database.
    QdrantIndexing,
}

impl PipelineStage {
    /// Get all stages in execution order.
    #[must_use]
    pub const fn all() -> &'static [Self] {
        &[
            Self::MetadataProbe,
            Self::KeyframeExtraction,
            Self::AudioExtraction,
            Self::SceneDetection,
            Self::Transcription,
            Self::ContentFusion,
            Self::EmbeddingGeneration,
            Self::QdrantIndexing,
        ]
    }

    /// Get the stage index (0-based).
    #[must_use]
    pub const fn index(&self) -> usize {
        match self {
            Self::MetadataProbe => 0,
            Self::KeyframeExtraction => 1,
            Self::AudioExtraction => 2,
            Self::SceneDetection => 3,
            Self::Transcription => 4,
            Self::ContentFusion => 5,
            Self::EmbeddingGeneration => 6,
            Self::QdrantIndexing => 7,
        }
    }

    /// Get the total number of stages.
    #[must_use]
    pub const fn total() -> usize {
        8
    }

    /// Check if this stage can run in parallel with another stage.
    ///
    /// Some stages can run concurrently for better performance:
    /// - `KeyframeExtraction` and `AudioExtraction` can run in parallel
    /// - `SceneDetection` and `Transcription` can run in parallel (after their inputs are ready)
    #[must_use]
    pub const fn can_parallel_with(&self, other: &Self) -> bool {
        matches!(
            (self, other),
            (Self::KeyframeExtraction, Self::AudioExtraction)
                | (Self::AudioExtraction, Self::KeyframeExtraction)
                | (Self::SceneDetection, Self::Transcription)
                | (Self::Transcription, Self::SceneDetection)
        )
    }

    /// Get the human-readable name of the stage.
    #[must_use]
    pub const fn name(&self) -> &'static str {
        match self {
            Self::MetadataProbe => "Metadata Probe",
            Self::KeyframeExtraction => "Keyframe Extraction",
            Self::AudioExtraction => "Audio Extraction",
            Self::SceneDetection => "Scene Detection",
            Self::Transcription => "Transcription",
            Self::ContentFusion => "Content Fusion",
            Self::EmbeddingGeneration => "Embedding Generation",
            Self::QdrantIndexing => "Qdrant Indexing",
        }
    }

    /// Get the stage description.
    #[must_use]
    pub const fn description(&self) -> &'static str {
        match self {
            Self::MetadataProbe => "Probing video metadata using ffprobe",
            Self::KeyframeExtraction => "Extracting keyframes at scene boundaries",
            Self::AudioExtraction => "Extracting audio track to WAV file",
            Self::SceneDetection => "Detecting scene boundaries",
            Self::Transcription => "Transcribing audio using Whisper",
            Self::ContentFusion => "Fusing transcript, scenes, and OCR",
            Self::EmbeddingGeneration => "Generating embeddings for chunks",
            Self::QdrantIndexing => "Indexing chunks in Qdrant",
        }
    }

    /// Check if the stage requires a video file.
    #[must_use]
    pub const fn requires_video(&self) -> bool {
        matches!(
            self,
            Self::MetadataProbe
                | Self::KeyframeExtraction
                | Self::AudioExtraction
                | Self::SceneDetection
        )
    }

    /// Check if the stage requires audio file.
    #[must_use]
    pub const fn requires_audio(&self) -> bool {
        matches!(self, Self::Transcription)
    }

    /// Check if the stage makes HTTP requests.
    #[must_use]
    pub const fn is_http_stage(&self) -> bool {
        matches!(
            self,
            Self::SceneDetection
                | Self::Transcription
                | Self::EmbeddingGeneration
                | Self::QdrantIndexing
        )
    }
}

impl fmt::Display for PipelineStage {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}", self.name())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_stage_all_count() {
        assert_eq!(PipelineStage::all().len(), PipelineStage::total());
    }

    #[test]
    fn test_stage_index_sequential() {
        let stages = PipelineStage::all();
        for (i, stage) in stages.iter().enumerate() {
            assert_eq!(stage.index(), i);
        }
    }

    #[test]
    fn test_stage_parallel_keyframe_audio() {
        assert!(
            PipelineStage::KeyframeExtraction.can_parallel_with(&PipelineStage::AudioExtraction)
        );
        assert!(
            PipelineStage::AudioExtraction.can_parallel_with(&PipelineStage::KeyframeExtraction)
        );
    }

    #[test]
    fn test_stage_parallel_scene_transcription() {
        assert!(PipelineStage::SceneDetection.can_parallel_with(&PipelineStage::Transcription));
        assert!(PipelineStage::Transcription.can_parallel_with(&PipelineStage::SceneDetection));
    }

    #[test]
    fn test_stage_not_parallel() {
        assert!(!PipelineStage::MetadataProbe.can_parallel_with(&PipelineStage::KeyframeExtraction));
        assert!(!PipelineStage::ContentFusion.can_parallel_with(&PipelineStage::QdrantIndexing));
    }

    #[test]
    fn test_stage_name() {
        assert_eq!(PipelineStage::MetadataProbe.name(), "Metadata Probe");
        assert_eq!(PipelineStage::QdrantIndexing.name(), "Qdrant Indexing");
    }

    #[test]
    fn test_stage_display() {
        let stage = PipelineStage::ContentFusion;
        assert_eq!(format!("{stage}"), "Content Fusion");
    }

    #[test]
    fn test_stage_requires_video() {
        assert!(PipelineStage::MetadataProbe.requires_video());
        assert!(PipelineStage::KeyframeExtraction.requires_video());
        assert!(!PipelineStage::Transcription.requires_video());
        assert!(!PipelineStage::QdrantIndexing.requires_video());
    }

    #[test]
    fn test_stage_requires_audio() {
        assert!(PipelineStage::Transcription.requires_audio());
        assert!(!PipelineStage::MetadataProbe.requires_audio());
    }

    #[test]
    fn test_stage_is_http() {
        assert!(PipelineStage::SceneDetection.is_http_stage());
        assert!(PipelineStage::Transcription.is_http_stage());
        assert!(PipelineStage::EmbeddingGeneration.is_http_stage());
        assert!(PipelineStage::QdrantIndexing.is_http_stage());
        assert!(!PipelineStage::MetadataProbe.is_http_stage());
        assert!(!PipelineStage::ContentFusion.is_http_stage());
    }

    #[test]
    fn test_stage_description() {
        assert!(!PipelineStage::MetadataProbe.description().is_empty());
        for stage in PipelineStage::all() {
            assert!(!stage.description().is_empty());
        }
    }
}
