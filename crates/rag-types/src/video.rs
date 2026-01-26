//! Video processing types.
//!
//! Types for video ingestion and processing in the RAG pipeline.

use crate::ids::{GroupId, TenantId, VideoId};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use validator::Validate;

/// Video processing status.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum VideoStatus {
    /// Waiting to be processed
    #[default]
    Pending,
    /// Video uploaded but not processed
    Uploaded,
    /// Currently being processed
    Processing,
    /// Processing completed successfully
    Completed,
    /// Processing failed
    Failed,
}

impl std::fmt::Display for VideoStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Pending => write!(f, "pending"),
            Self::Uploaded => write!(f, "uploaded"),
            Self::Processing => write!(f, "processing"),
            Self::Completed => write!(f, "completed"),
            Self::Failed => write!(f, "failed"),
        }
    }
}

/// Video processing stage.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProcessingStage {
    /// Video uploaded
    Uploaded,
    /// Validating video file
    Validating,
    /// Extracting audio track
    ExtractingAudio,
    /// Transcribing audio
    Transcribing,
    /// Detecting scene changes
    DetectingScenes,
    /// Extracting keyframes
    ExtractingKeyframes,
    /// Analyzing frames with vision model
    AnalyzingVision,
    /// Extracting text via OCR
    ExtractingOcr,
    /// Fusing content from all sources
    FusingContent,
    /// Generating embeddings
    Embedding,
    /// Indexing to vector store
    Indexing,
    /// Processing complete
    Completed,
    /// Processing failed
    Failed,
}

impl std::fmt::Display for ProcessingStage {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        let s = match self {
            Self::Uploaded => "uploaded",
            Self::Validating => "validating",
            Self::ExtractingAudio => "extracting_audio",
            Self::Transcribing => "transcribing",
            Self::DetectingScenes => "detecting_scenes",
            Self::ExtractingKeyframes => "extracting_keyframes",
            Self::AnalyzingVision => "analyzing_vision",
            Self::ExtractingOcr => "extracting_ocr",
            Self::FusingContent => "fusing_content",
            Self::Embedding => "embedding",
            Self::Indexing => "indexing",
            Self::Completed => "completed",
            Self::Failed => "failed",
        };
        write!(f, "{s}")
    }
}

/// Video processing options.
#[derive(Debug, Clone, Serialize, Deserialize, Validate)]
pub struct VideoProcessingOptions {
    /// Whisper model size
    #[serde(default = "default_whisper_model")]
    pub whisper_model: String,

    /// Language hint for transcription (ISO 639-1 code)
    pub whisper_language: Option<String>,

    /// Vision model provider
    #[serde(default = "default_vision_provider")]
    pub vision_provider: String,

    /// Enable vision analysis
    #[serde(default = "default_true")]
    pub enable_vision: bool,

    /// Enable OCR extraction
    #[serde(default = "default_true")]
    pub enable_ocr: bool,

    /// Scene detection threshold
    #[validate(range(min = 0.0, max = 100.0))]
    #[serde(default = "default_scene_threshold")]
    pub scene_detection_threshold: f32,

    /// Keyframe extraction interval in seconds
    #[validate(range(min = 0.5, max = 60.0))]
    #[serde(default = "default_keyframe_interval")]
    pub keyframe_interval_seconds: f32,

    /// Chunk duration in seconds
    #[validate(range(min = 5.0, max = 120.0))]
    #[serde(default = "default_chunk_duration")]
    pub chunk_duration_seconds: f32,
}

fn default_whisper_model() -> String {
    "base".to_string()
}

fn default_vision_provider() -> String {
    "openai".to_string()
}

const fn default_true() -> bool {
    true
}

const fn default_scene_threshold() -> f32 {
    27.0
}

const fn default_keyframe_interval() -> f32 {
    5.0
}

const fn default_chunk_duration() -> f32 {
    20.0
}

impl Default for VideoProcessingOptions {
    fn default() -> Self {
        Self {
            whisper_model: default_whisper_model(),
            whisper_language: None,
            vision_provider: default_vision_provider(),
            enable_vision: true,
            enable_ocr: true,
            scene_detection_threshold: default_scene_threshold(),
            keyframe_interval_seconds: default_keyframe_interval(),
            chunk_duration_seconds: default_chunk_duration(),
        }
    }
}

/// A source video in the RAG pipeline.
#[derive(Debug, Clone, Serialize, Deserialize, Validate)]
pub struct Video {
    /// Unique identifier
    pub id: VideoId,

    /// Owning tenant
    pub tenant_id: TenantId,

    /// Original filename
    #[validate(length(min = 1, max = 512))]
    pub filename: String,

    /// Video title
    #[validate(length(max = 512))]
    pub title: Option<String>,

    /// Description
    #[validate(length(max = 4096))]
    pub description: Option<String>,

    /// Duration in seconds
    pub duration_seconds: Option<f64>,

    /// Video width in pixels
    pub width: Option<u32>,

    /// Video height in pixels
    pub height: Option<u32>,

    /// Frames per second
    pub fps: Option<f64>,

    /// Video codec
    pub codec: Option<String>,

    /// File size in bytes
    pub file_size_bytes: Option<u64>,

    /// Content hash for deduplication
    #[validate(length(equal = 64))]
    pub content_hash: Option<String>,

    /// Path in object storage
    pub storage_path: String,

    /// Thumbnail path in object storage
    pub thumbnail_path: Option<String>,

    /// Processing status
    #[serde(default)]
    pub status: VideoStatus,

    /// Current processing stage
    pub processing_stage: Option<ProcessingStage>,

    /// Processing progress (0-100)
    #[validate(range(max = 100))]
    #[serde(default)]
    pub processing_progress: u8,

    /// Error message if failed
    pub error_message: Option<String>,

    /// Visibility level
    #[serde(default)]
    pub visibility: crate::document::Visibility,

    /// Groups with access
    #[serde(default)]
    pub allowed_groups: Vec<GroupId>,

    /// Processing options used
    #[serde(default)]
    pub processing_options: VideoProcessingOptions,

    /// Detected language
    pub detected_language: Option<String>,

    /// Number of keyframes extracted
    #[serde(default)]
    pub keyframe_count: u32,

    /// Number of chunks created
    #[serde(default)]
    pub chunk_count: u32,

    /// Tags for categorization
    #[serde(default)]
    pub tags: Vec<String>,

    /// Creation timestamp
    pub created_at: DateTime<Utc>,

    /// Upload completion timestamp
    pub uploaded_at: Option<DateTime<Utc>>,

    /// Processing completion timestamp
    pub processed_at: Option<DateTime<Utc>>,
}

impl Video {
    /// Create a new video with required fields.
    #[must_use]
    pub fn new(filename: String, storage_path: String, tenant_id: TenantId) -> Self {
        Self {
            id: VideoId::new(),
            tenant_id,
            filename,
            title: None,
            description: None,
            duration_seconds: None,
            width: None,
            height: None,
            fps: None,
            codec: None,
            file_size_bytes: None,
            content_hash: None,
            storage_path,
            thumbnail_path: None,
            status: VideoStatus::default(),
            processing_stage: None,
            processing_progress: 0,
            error_message: None,
            visibility: crate::document::Visibility::default(),
            allowed_groups: Vec::new(),
            processing_options: VideoProcessingOptions::default(),
            detected_language: None,
            keyframe_count: 0,
            chunk_count: 0,
            tags: Vec::new(),
            created_at: Utc::now(),
            uploaded_at: None,
            processed_at: None,
        }
    }

    /// Check if the video is ready for retrieval.
    #[must_use]
    pub const fn is_searchable(&self) -> bool {
        matches!(self.status, VideoStatus::Completed)
    }

    /// Check if the video is currently being processed.
    #[must_use]
    pub const fn is_processing(&self) -> bool {
        matches!(self.status, VideoStatus::Processing)
    }
}

/// A transcript segment from a video.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TranscriptSegment {
    /// Segment index
    pub segment_index: u32,

    /// Start time in milliseconds
    pub start_ms: u64,

    /// End time in milliseconds
    pub end_ms: u64,

    /// Transcribed text
    pub text: String,

    /// Word-level timestamps
    #[serde(default)]
    pub words: Vec<WordTimestamp>,

    /// Detected language
    pub language: Option<String>,

    /// Confidence score (0.0-1.0)
    pub confidence: Option<f32>,
}

/// Word-level timestamp in a transcript.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WordTimestamp {
    /// The word
    pub word: String,

    /// Start time in milliseconds
    pub start_ms: u64,

    /// End time in milliseconds
    pub end_ms: u64,
}

/// A keyframe extracted from a video.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Keyframe {
    /// Frame index
    pub frame_index: u32,

    /// Timestamp in milliseconds
    pub timestamp_ms: u64,

    /// Path in object storage
    pub storage_path: String,

    /// Thumbnail path
    pub thumbnail_path: Option<String>,

    /// Vision model description
    pub scene_description: Option<String>,

    /// OCR extracted text
    pub ocr_text: Option<String>,

    /// Is this frame a scene boundary?
    pub is_scene_boundary: bool,

    /// Scene index (if scene detection enabled)
    pub scene_index: Option<u32>,
}

/// A fused video chunk for indexing.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VideoChunk {
    /// Chunk index
    pub chunk_index: u32,

    /// Parent video ID
    pub video_id: VideoId,

    /// Tenant ID
    pub tenant_id: TenantId,

    /// Start time in milliseconds
    pub start_time_ms: u64,

    /// End time in milliseconds
    pub end_time_ms: u64,

    /// Fused text content (transcript + OCR + vision)
    pub fused_text: String,

    /// Transcript portion only
    pub transcript_text: Option<String>,

    /// OCR text only
    pub ocr_text: Option<String>,

    /// Vision description only
    pub vision_text: Option<String>,

    /// Associated keyframe paths
    #[serde(default)]
    pub keyframe_paths: Vec<String>,

    /// Additional metadata
    #[serde(default)]
    pub metadata: HashMap<String, serde_json::Value>,

    /// Creation timestamp
    pub created_at: DateTime<Utc>,
}

impl VideoChunk {
    /// Create a new video chunk.
    #[must_use]
    pub fn new(
        chunk_index: u32,
        video_id: VideoId,
        tenant_id: TenantId,
        start_time_ms: u64,
        end_time_ms: u64,
        fused_text: String,
    ) -> Self {
        Self {
            chunk_index,
            video_id,
            tenant_id,
            start_time_ms,
            end_time_ms,
            fused_text,
            transcript_text: None,
            ocr_text: None,
            vision_text: None,
            keyframe_paths: Vec::new(),
            metadata: HashMap::new(),
            created_at: Utc::now(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_video_status_default() {
        assert_eq!(VideoStatus::default(), VideoStatus::Pending);
    }

    #[test]
    fn test_processing_options_default() {
        let opts = VideoProcessingOptions::default();
        assert_eq!(opts.whisper_model, "base");
        assert!(opts.enable_vision);
        assert!(opts.enable_ocr);
        assert!((opts.scene_detection_threshold - 27.0).abs() < f32::EPSILON);
    }

    #[test]
    fn test_video_creation() {
        let tenant_id = TenantId::new();
        let video = Video::new(
            "test.mp4".to_string(),
            "/videos/test.mp4".to_string(),
            tenant_id,
        );

        assert_eq!(video.filename, "test.mp4");
        assert_eq!(video.status, VideoStatus::Pending);
        assert!(!video.is_searchable());
        assert!(!video.is_processing());
    }

    #[test]
    fn test_processing_stage_display() {
        assert_eq!(ProcessingStage::Transcribing.to_string(), "transcribing");
        assert_eq!(
            ProcessingStage::ExtractingKeyframes.to_string(),
            "extracting_keyframes"
        );
    }

    #[test]
    fn test_video_chunk_creation() {
        let video_id = VideoId::new();
        let tenant_id = TenantId::new();
        let chunk = VideoChunk::new(
            0,
            video_id,
            tenant_id,
            0,
            20000,
            "Hello world from video".to_string(),
        );

        assert_eq!(chunk.chunk_index, 0);
        assert_eq!(chunk.start_time_ms, 0);
        assert_eq!(chunk.end_time_ms, 20000);
    }
}
