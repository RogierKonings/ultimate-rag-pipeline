//! Video models for the Video RAG Pipeline.
//!
//! This module defines database models for storing video metadata,
//! transcripts, and keyframes.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::FromRow;
use uuid::Uuid;

/// Video processing status.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum VideoStatus {
    Pending,
    Uploaded,
    Processing,
    Completed,
    Failed,
}

impl VideoStatus {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Pending => "pending",
            Self::Uploaded => "uploaded",
            Self::Processing => "processing",
            Self::Completed => "completed",
            Self::Failed => "failed",
        }
    }
}

impl std::fmt::Display for VideoStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

/// Video processing stages.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ProcessingStage {
    Uploaded,
    Validating,
    ExtractingAudio,
    Transcribing,
    DetectingScenes,
    ExtractingKeyframes,
    AnalyzingVision,
    ExtractingOcr,
    FusingContent,
    Embedding,
    Indexing,
    Completed,
    Failed,
}

impl ProcessingStage {
    pub fn as_str(&self) -> &'static str {
        match self {
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
        }
    }
}

/// Represents a source video in the Video RAG pipeline.
///
/// Stores metadata about uploaded videos including processing status,
/// video properties, and access control settings.
#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct SourceVideo {
    pub id: Uuid,
    pub tenant_id: Uuid,
    pub filename: String,
    pub title: Option<String>,
    pub description: Option<String>,
    pub duration_seconds: Option<f64>,
    pub width: Option<i32>,
    pub height: Option<i32>,
    pub fps: Option<f64>,
    pub codec: Option<String>,
    pub file_size_bytes: Option<i64>,
    pub content_hash: Option<String>,
    pub storage_path: String,
    pub thumbnail_path: Option<String>,
    pub status: String,
    pub processing_stage: Option<String>,
    pub processing_progress: i32,
    pub error_message: Option<String>,
    pub visibility: String,
    pub allowed_groups: serde_json::Value,
    pub processing_options: serde_json::Value,
    pub detected_language: Option<String>,
    pub keyframe_count: i32,
    pub chunk_count: i32,
    pub created_at: DateTime<Utc>,
    pub uploaded_at: Option<DateTime<Utc>>,
    pub processed_at: Option<DateTime<Utc>>,
}

impl SourceVideo {
    /// Get the video status as an enum.
    pub fn video_status(&self) -> Option<VideoStatus> {
        match self.status.as_str() {
            "pending" => Some(VideoStatus::Pending),
            "uploaded" => Some(VideoStatus::Uploaded),
            "processing" => Some(VideoStatus::Processing),
            "completed" => Some(VideoStatus::Completed),
            "failed" => Some(VideoStatus::Failed),
            _ => None,
        }
    }
}

/// Data for creating a new source video.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewSourceVideo {
    pub tenant_id: Uuid,
    pub filename: String,
    pub title: Option<String>,
    pub description: Option<String>,
    pub storage_path: String,
    pub visibility: Option<String>,
    pub allowed_groups: Option<serde_json::Value>,
    pub processing_options: Option<serde_json::Value>,
}

impl Default for NewSourceVideo {
    fn default() -> Self {
        Self {
            tenant_id: Uuid::nil(),
            filename: String::new(),
            title: None,
            description: None,
            storage_path: String::new(),
            visibility: Some("private".to_string()),
            allowed_groups: Some(serde_json::json!([])),
            processing_options: Some(serde_json::json!({})),
        }
    }
}

/// Represents a transcript segment from a video.
///
/// Stores speech-to-text transcription with word-level timestamps.
#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct VideoTranscript {
    pub id: Uuid,
    pub video_id: Uuid,
    pub segment_index: i32,
    pub start_ms: i32,
    pub end_ms: i32,
    pub text: String,
    pub words_json: serde_json::Value,
    pub language: Option<String>,
    pub confidence: Option<f64>,
    pub created_at: DateTime<Utc>,
}

/// Data for creating a new video transcript.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewVideoTranscript {
    pub video_id: Uuid,
    pub segment_index: i32,
    pub start_ms: i32,
    pub end_ms: i32,
    pub text: String,
    pub words_json: Option<serde_json::Value>,
    pub language: Option<String>,
    pub confidence: Option<f64>,
}

/// Represents an extracted keyframe from a video.
///
/// Stores keyframe metadata, scene descriptions from vision LLM,
/// and OCR-extracted text.
#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct VideoKeyframe {
    pub id: Uuid,
    pub video_id: Uuid,
    pub frame_index: i32,
    pub timestamp_ms: i32,
    pub storage_path: String,
    pub thumbnail_path: Option<String>,
    pub scene_description: Option<String>,
    pub ocr_text: Option<String>,
    pub is_scene_boundary: bool,
    pub scene_index: Option<i32>,
    pub created_at: DateTime<Utc>,
}

/// Data for creating a new video keyframe.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewVideoKeyframe {
    pub video_id: Uuid,
    pub frame_index: i32,
    pub timestamp_ms: i32,
    pub storage_path: String,
    pub thumbnail_path: Option<String>,
    pub scene_description: Option<String>,
    pub ocr_text: Option<String>,
    pub is_scene_boundary: Option<bool>,
    pub scene_index: Option<i32>,
}
