//! Pipeline types.

use std::collections::HashMap;
use std::path::PathBuf;
use std::time::Duration;

use uuid::Uuid;

use super::stages::PipelineStage;
use crate::clients::{SceneDetectionResult, TranscriptionResult};
use crate::extraction::{ExtractedKeyframe, VideoMetadata};
use crate::fusion::VideoChunk;
use crate::indexer::IndexResult;

/// Result of a single pipeline stage.
#[derive(Debug, Clone)]
pub struct StageResult {
    /// Stage that was executed.
    pub stage: PipelineStage,
    /// Duration of the stage execution.
    pub duration: Duration,
    /// Whether the stage was successful.
    pub success: bool,
    /// Optional error message if failed.
    pub error: Option<String>,
}

impl StageResult {
    /// Create a successful stage result.
    #[must_use]
    pub fn success(stage: PipelineStage, duration: Duration) -> Self {
        Self {
            stage,
            duration,
            success: true,
            error: None,
        }
    }

    /// Create a failed stage result.
    #[must_use]
    pub fn failure(stage: PipelineStage, duration: Duration, error: impl Into<String>) -> Self {
        Self {
            stage,
            duration,
            success: false,
            error: Some(error.into()),
        }
    }
}

/// Progress information for the pipeline.
#[derive(Debug, Clone)]
pub struct PipelineProgress {
    /// Current stage being executed.
    pub current_stage: PipelineStage,
    /// Stage index (0-based).
    pub stage_index: usize,
    /// Total number of stages.
    pub total_stages: usize,
    /// Progress within the current stage (0.0 - 1.0).
    pub stage_progress: f32,
    /// Message describing current activity.
    pub message: String,
}

impl PipelineProgress {
    /// Create a new progress update.
    #[must_use]
    pub fn new(stage: PipelineStage, stage_progress: f32, message: impl Into<String>) -> Self {
        Self {
            current_stage: stage,
            stage_index: stage.index(),
            total_stages: PipelineStage::total(),
            stage_progress,
            message: message.into(),
        }
    }

    /// Get the overall progress (0.0 - 1.0).
    #[must_use]
    pub fn overall_progress(&self) -> f32 {
        let stage_weight = 1.0 / self.total_stages as f32;
        let completed_stages = self.stage_index as f32 * stage_weight;
        let current_progress = self.stage_progress * stage_weight;
        completed_stages + current_progress
    }

    /// Get progress as percentage (0 - 100).
    #[must_use]
    pub fn percentage(&self) -> u8 {
        #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
        let pct = (self.overall_progress() * 100.0).round() as u8;
        pct.min(100)
    }
}

/// Progress callback type for pipeline execution.
pub type ProgressCallback = Box<dyn Fn(PipelineProgress) + Send + Sync>;

/// Complete result of pipeline execution.
#[derive(Debug, Clone)]
pub struct PipelineResult {
    /// Video file that was processed.
    pub video_path: PathBuf,
    /// Video ID (UUID).
    pub video_id: Uuid,
    /// Tenant ID.
    pub tenant_id: Uuid,
    /// Total pipeline duration.
    pub total_duration: Duration,
    /// Results of each stage.
    pub stage_results: Vec<StageResult>,
    /// Whether all stages completed successfully.
    pub success: bool,
    /// First error encountered (if any).
    pub error: Option<String>,

    // Stage outputs
    /// Video metadata (from `MetadataProbe` stage).
    pub metadata: Option<VideoMetadata>,
    /// Extracted keyframes (from `KeyframeExtraction` stage).
    pub keyframes: Vec<ExtractedKeyframe>,
    /// Path to extracted audio (from `AudioExtraction` stage).
    pub audio_path: Option<PathBuf>,
    /// Scene detection result (from `SceneDetection` stage).
    pub scene_result: Option<SceneDetectionResult>,
    /// Transcription result (from Transcription stage).
    pub transcription_result: Option<TranscriptionResult>,
    /// Fused video chunks (from `ContentFusion` stage).
    pub chunks: Vec<VideoChunk>,
    /// Generated embeddings (`chunk_id` -> vector).
    pub embeddings: HashMap<Uuid, Vec<f32>>,
    /// Index result (from `QdrantIndexing` stage).
    pub index_result: Option<IndexResult>,
}

impl PipelineResult {
    /// Create a new pipeline result.
    #[must_use]
    pub fn new(video_path: PathBuf, video_id: Uuid, tenant_id: Uuid) -> Self {
        Self {
            video_path,
            video_id,
            tenant_id,
            total_duration: Duration::ZERO,
            stage_results: Vec::new(),
            success: false,
            error: None,
            metadata: None,
            keyframes: Vec::new(),
            audio_path: None,
            scene_result: None,
            transcription_result: None,
            chunks: Vec::new(),
            embeddings: HashMap::new(),
            index_result: None,
        }
    }

    /// Add a stage result.
    pub fn add_stage_result(&mut self, result: StageResult) {
        if !result.success && self.error.is_none() {
            self.error.clone_from(&result.error);
        }
        self.stage_results.push(result);
    }

    /// Finalize the result.
    pub fn finalize(&mut self, total_duration: Duration) {
        self.total_duration = total_duration;
        self.success = self.stage_results.iter().all(|r| r.success);
    }

    /// Get the number of successful stages.
    #[must_use]
    pub fn successful_stages(&self) -> usize {
        self.stage_results.iter().filter(|r| r.success).count()
    }

    /// Get the number of chunks that were indexed.
    #[must_use]
    pub fn indexed_count(&self) -> usize {
        self.index_result
            .as_ref()
            .map_or(0, |r| r.indexed_count)
    }
}

impl Default for PipelineResult {
    fn default() -> Self {
        Self::new(PathBuf::new(), Uuid::nil(), Uuid::nil())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_stage_result_success() {
        let result = StageResult::success(PipelineStage::MetadataProbe, Duration::from_millis(100));
        assert!(result.success);
        assert!(result.error.is_none());
        assert_eq!(result.duration, Duration::from_millis(100));
    }

    #[test]
    fn test_stage_result_failure() {
        let result = StageResult::failure(
            PipelineStage::SceneDetection,
            Duration::from_secs(5),
            "Service unavailable",
        );
        assert!(!result.success);
        assert_eq!(result.error, Some("Service unavailable".to_string()));
    }

    #[test]
    fn test_pipeline_progress_new() {
        let progress =
            PipelineProgress::new(PipelineStage::KeyframeExtraction, 0.5, "Extracting frame 10/20");
        assert_eq!(progress.current_stage, PipelineStage::KeyframeExtraction);
        assert_eq!(progress.stage_index, 1);
        assert_eq!(progress.total_stages, 8);
        assert!((progress.stage_progress - 0.5).abs() < f32::EPSILON);
    }

    #[test]
    fn test_pipeline_progress_overall() {
        // First stage (index 0), 50% complete
        let progress = PipelineProgress::new(PipelineStage::MetadataProbe, 0.5, "Probing");
        let overall = progress.overall_progress();
        // 0 completed stages + 0.5 * (1/8) = 0.0625
        assert!((overall - 0.0625).abs() < 0.001);

        // Fourth stage (index 3), 50% complete
        let progress = PipelineProgress::new(PipelineStage::SceneDetection, 0.5, "Detecting");
        let overall = progress.overall_progress();
        // 3/8 + 0.5/8 = 0.375 + 0.0625 = 0.4375
        assert!((overall - 0.4375).abs() < 0.001);
    }

    #[test]
    fn test_pipeline_progress_percentage() {
        let progress = PipelineProgress::new(PipelineStage::MetadataProbe, 0.0, "Starting");
        assert_eq!(progress.percentage(), 0);

        // Last stage, 100% complete
        let progress = PipelineProgress::new(PipelineStage::QdrantIndexing, 1.0, "Done");
        let pct = progress.percentage();
        assert!(pct >= 99); // Allow for rounding
    }

    #[test]
    fn test_pipeline_result_new() {
        let video_id = Uuid::new_v4();
        let tenant_id = Uuid::new_v4();
        let result = PipelineResult::new(PathBuf::from("/video.mp4"), video_id, tenant_id);

        assert_eq!(result.video_id, video_id);
        assert_eq!(result.tenant_id, tenant_id);
        assert!(!result.success);
        assert!(result.stage_results.is_empty());
    }

    #[test]
    fn test_pipeline_result_add_stage() {
        let mut result = PipelineResult::default();

        result.add_stage_result(StageResult::success(
            PipelineStage::MetadataProbe,
            Duration::from_millis(50),
        ));
        result.add_stage_result(StageResult::failure(
            PipelineStage::SceneDetection,
            Duration::from_secs(1),
            "Failed",
        ));

        assert_eq!(result.stage_results.len(), 2);
        assert_eq!(result.error, Some("Failed".to_string()));
    }

    #[test]
    fn test_pipeline_result_finalize() {
        let mut result = PipelineResult::default();
        result.add_stage_result(StageResult::success(
            PipelineStage::MetadataProbe,
            Duration::from_millis(50),
        ));
        result.add_stage_result(StageResult::success(
            PipelineStage::KeyframeExtraction,
            Duration::from_millis(100),
        ));

        result.finalize(Duration::from_millis(150));

        assert!(result.success);
        assert_eq!(result.total_duration, Duration::from_millis(150));
    }

    #[test]
    fn test_pipeline_result_finalize_with_failure() {
        let mut result = PipelineResult::default();
        result.add_stage_result(StageResult::success(
            PipelineStage::MetadataProbe,
            Duration::from_millis(50),
        ));
        result.add_stage_result(StageResult::failure(
            PipelineStage::SceneDetection,
            Duration::from_secs(1),
            "Service down",
        ));

        result.finalize(Duration::from_secs(1));

        assert!(!result.success);
    }

    #[test]
    fn test_pipeline_result_successful_stages() {
        let mut result = PipelineResult::default();
        result.add_stage_result(StageResult::success(
            PipelineStage::MetadataProbe,
            Duration::ZERO,
        ));
        result.add_stage_result(StageResult::success(
            PipelineStage::KeyframeExtraction,
            Duration::ZERO,
        ));
        result.add_stage_result(StageResult::failure(
            PipelineStage::SceneDetection,
            Duration::ZERO,
            "error",
        ));

        assert_eq!(result.successful_stages(), 2);
    }

    #[test]
    fn test_stage_result_clone() {
        let result = StageResult::success(PipelineStage::MetadataProbe, Duration::from_secs(1));
        let cloned = result.clone();
        assert_eq!(result.stage, cloned.stage);
        assert_eq!(result.duration, cloned.duration);
    }

    #[test]
    fn test_pipeline_progress_clone() {
        let progress = PipelineProgress::new(PipelineStage::ContentFusion, 0.75, "Fusing");
        let cloned = progress.clone();
        assert_eq!(progress.current_stage, cloned.current_stage);
        assert_eq!(progress.message, cloned.message);
    }
}
