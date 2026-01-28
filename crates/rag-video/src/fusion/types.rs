//! Types for content fusion operations.

use std::path::PathBuf;
use uuid::Uuid;

use crate::extraction::ExtractedKeyframe;

/// A video chunk containing fused content from multiple modalities.
#[derive(Debug, Clone)]
pub struct VideoChunk {
    /// Unique identifier for this chunk.
    pub id: Uuid,
    /// ID of the source video.
    pub video_id: Uuid,
    /// Tenant ID for multi-tenancy.
    pub tenant_id: Uuid,
    /// Zero-based index of this chunk within the video.
    pub chunk_index: u32,
    /// Start time in milliseconds.
    pub start_time_ms: u64,
    /// End time in milliseconds.
    pub end_time_ms: u64,
    /// Transcript text for this time range.
    pub transcript_text: String,
    /// Scene description for this time range.
    pub scene_description: String,
    /// OCR text extracted from keyframes.
    pub ocr_text: String,
    /// Fused text combining all modalities.
    pub fused_text: String,
    /// Path to the representative keyframe (if any).
    pub keyframe_path: Option<PathBuf>,
    /// Index of the representative keyframe (if any).
    pub keyframe_index: Option<u32>,
    /// Which modalities contributed to this chunk.
    pub source_modalities: Vec<String>,
}

impl VideoChunk {
    /// Creates a new video chunk with the given parameters.
    #[must_use]
    pub fn new(
        video_id: Uuid,
        tenant_id: Uuid,
        chunk_index: u32,
        start_time_ms: u64,
        end_time_ms: u64,
    ) -> Self {
        Self {
            id: Uuid::new_v4(),
            video_id,
            tenant_id,
            chunk_index,
            start_time_ms,
            end_time_ms,
            transcript_text: String::new(),
            scene_description: String::new(),
            ocr_text: String::new(),
            fused_text: String::new(),
            keyframe_path: None,
            keyframe_index: None,
            source_modalities: Vec::new(),
        }
    }

    /// Creates a video chunk with a specific ID (useful for testing).
    #[must_use]
    pub fn with_id(
        id: Uuid,
        video_id: Uuid,
        tenant_id: Uuid,
        chunk_index: u32,
        start_time_ms: u64,
        end_time_ms: u64,
    ) -> Self {
        Self {
            id,
            video_id,
            tenant_id,
            chunk_index,
            start_time_ms,
            end_time_ms,
            transcript_text: String::new(),
            scene_description: String::new(),
            ocr_text: String::new(),
            fused_text: String::new(),
            keyframe_path: None,
            keyframe_index: None,
            source_modalities: Vec::new(),
        }
    }

    /// Returns the duration of this chunk in milliseconds.
    #[must_use]
    pub const fn duration_ms(&self) -> u64 {
        self.end_time_ms.saturating_sub(self.start_time_ms)
    }

    /// Returns the midpoint timestamp in milliseconds.
    #[must_use]
    pub const fn mid_time_ms(&self) -> u64 {
        self.start_time_ms + self.duration_ms() / 2
    }

    /// Checks if this chunk has any content.
    #[must_use]
    pub fn has_content(&self) -> bool {
        !self.transcript_text.is_empty()
            || !self.scene_description.is_empty()
            || !self.ocr_text.is_empty()
    }

    /// Checks if a timestamp falls within this chunk's time range.
    #[must_use]
    pub const fn contains_timestamp(&self, timestamp_ms: u64) -> bool {
        timestamp_ms >= self.start_time_ms && timestamp_ms < self.end_time_ms
    }
}

impl Default for VideoChunk {
    fn default() -> Self {
        Self {
            id: Uuid::nil(),
            video_id: Uuid::nil(),
            tenant_id: Uuid::nil(),
            chunk_index: 0,
            start_time_ms: 0,
            end_time_ms: 0,
            transcript_text: String::new(),
            scene_description: String::new(),
            ocr_text: String::new(),
            fused_text: String::new(),
            keyframe_path: None,
            keyframe_index: None,
            source_modalities: Vec::new(),
        }
    }
}

/// A keyframe with associated content (scene description and OCR text).
#[derive(Debug, Clone)]
pub struct KeyframeWithContent {
    /// The extracted keyframe.
    pub keyframe: ExtractedKeyframe,
    /// Scene description for this keyframe.
    pub scene_description: String,
    /// OCR text extracted from this keyframe.
    pub ocr_text: String,
}

impl KeyframeWithContent {
    /// Creates a new keyframe with content.
    #[must_use]
    pub fn new(keyframe: ExtractedKeyframe, scene_description: String, ocr_text: String) -> Self {
        Self {
            keyframe,
            scene_description,
            ocr_text,
        }
    }

    /// Creates a keyframe with empty content.
    #[must_use]
    pub fn from_keyframe(keyframe: ExtractedKeyframe) -> Self {
        Self {
            keyframe,
            scene_description: String::new(),
            ocr_text: String::new(),
        }
    }

    /// Checks if this keyframe has any content.
    #[must_use]
    pub fn has_content(&self) -> bool {
        !self.scene_description.is_empty() || !self.ocr_text.is_empty()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn test_video_chunk_new() {
        let video_id = Uuid::new_v4();
        let tenant_id = Uuid::new_v4();

        let chunk = VideoChunk::new(video_id, tenant_id, 0, 0, 20000);

        assert_eq!(chunk.video_id, video_id);
        assert_eq!(chunk.tenant_id, tenant_id);
        assert_eq!(chunk.chunk_index, 0);
        assert_eq!(chunk.start_time_ms, 0);
        assert_eq!(chunk.end_time_ms, 20000);
        assert!(chunk.transcript_text.is_empty());
        assert!(chunk.scene_description.is_empty());
        assert!(chunk.ocr_text.is_empty());
        assert!(chunk.fused_text.is_empty());
        assert!(chunk.keyframe_path.is_none());
        assert!(chunk.keyframe_index.is_none());
        assert!(chunk.source_modalities.is_empty());
    }

    #[test]
    fn test_video_chunk_with_id() {
        let id = Uuid::new_v4();
        let video_id = Uuid::new_v4();
        let tenant_id = Uuid::new_v4();

        let chunk = VideoChunk::with_id(id, video_id, tenant_id, 1, 10000, 30000);

        assert_eq!(chunk.id, id);
        assert_eq!(chunk.chunk_index, 1);
        assert_eq!(chunk.start_time_ms, 10000);
        assert_eq!(chunk.end_time_ms, 30000);
    }

    #[test]
    fn test_video_chunk_duration_ms() {
        let chunk = VideoChunk::new(Uuid::new_v4(), Uuid::new_v4(), 0, 5000, 25000);
        assert_eq!(chunk.duration_ms(), 20000);
    }

    #[test]
    fn test_video_chunk_duration_ms_saturating() {
        let mut chunk = VideoChunk::default();
        chunk.start_time_ms = 30000;
        chunk.end_time_ms = 10000;
        assert_eq!(chunk.duration_ms(), 0);
    }

    #[test]
    fn test_video_chunk_mid_time_ms() {
        let chunk = VideoChunk::new(Uuid::new_v4(), Uuid::new_v4(), 0, 10000, 30000);
        assert_eq!(chunk.mid_time_ms(), 20000);
    }

    #[test]
    fn test_video_chunk_has_content_empty() {
        let chunk = VideoChunk::default();
        assert!(!chunk.has_content());
    }

    #[test]
    fn test_video_chunk_has_content_with_transcript() {
        let mut chunk = VideoChunk::default();
        chunk.transcript_text = "Hello world".to_string();
        assert!(chunk.has_content());
    }

    #[test]
    fn test_video_chunk_has_content_with_scene() {
        let mut chunk = VideoChunk::default();
        chunk.scene_description = "A person speaking".to_string();
        assert!(chunk.has_content());
    }

    #[test]
    fn test_video_chunk_has_content_with_ocr() {
        let mut chunk = VideoChunk::default();
        chunk.ocr_text = "TITLE".to_string();
        assert!(chunk.has_content());
    }

    #[test]
    fn test_video_chunk_contains_timestamp() {
        let chunk = VideoChunk::new(Uuid::new_v4(), Uuid::new_v4(), 0, 10000, 30000);

        assert!(!chunk.contains_timestamp(5000)); // Before
        assert!(chunk.contains_timestamp(10000)); // At start (inclusive)
        assert!(chunk.contains_timestamp(20000)); // Middle
        assert!(!chunk.contains_timestamp(30000)); // At end (exclusive)
        assert!(!chunk.contains_timestamp(35000)); // After
    }

    #[test]
    fn test_video_chunk_default() {
        let chunk = VideoChunk::default();
        assert!(chunk.id.is_nil());
        assert!(chunk.video_id.is_nil());
        assert!(chunk.tenant_id.is_nil());
        assert_eq!(chunk.chunk_index, 0);
        assert_eq!(chunk.start_time_ms, 0);
        assert_eq!(chunk.end_time_ms, 0);
    }

    #[test]
    fn test_video_chunk_clone() {
        let chunk = VideoChunk::new(Uuid::new_v4(), Uuid::new_v4(), 0, 0, 20000);
        let cloned = chunk.clone();
        assert_eq!(chunk.id, cloned.id);
        assert_eq!(chunk.video_id, cloned.video_id);
    }

    #[test]
    fn test_video_chunk_debug() {
        let chunk = VideoChunk::default();
        let debug = format!("{chunk:?}");
        assert!(debug.contains("VideoChunk"));
        assert!(debug.contains("chunk_index"));
    }

    fn create_test_keyframe() -> ExtractedKeyframe {
        ExtractedKeyframe {
            frame_index: 0,
            timestamp_ms: 5000,
            image_path: PathBuf::from("/tmp/frame.jpg"),
            thumbnail_path: None,
            width: 1280,
            height: 720,
            file_size_bytes: 50000,
            is_scene_boundary: true,
        }
    }

    #[test]
    fn test_keyframe_with_content_new() {
        let keyframe = create_test_keyframe();
        let kwc = KeyframeWithContent::new(
            keyframe.clone(),
            "A person speaking".to_string(),
            "TITLE".to_string(),
        );

        assert_eq!(kwc.keyframe.frame_index, 0);
        assert_eq!(kwc.scene_description, "A person speaking");
        assert_eq!(kwc.ocr_text, "TITLE");
    }

    #[test]
    fn test_keyframe_with_content_from_keyframe() {
        let keyframe = create_test_keyframe();
        let kwc = KeyframeWithContent::from_keyframe(keyframe.clone());

        assert_eq!(kwc.keyframe.frame_index, 0);
        assert!(kwc.scene_description.is_empty());
        assert!(kwc.ocr_text.is_empty());
    }

    #[test]
    fn test_keyframe_with_content_has_content_empty() {
        let keyframe = create_test_keyframe();
        let kwc = KeyframeWithContent::from_keyframe(keyframe);
        assert!(!kwc.has_content());
    }

    #[test]
    fn test_keyframe_with_content_has_content_with_scene() {
        let keyframe = create_test_keyframe();
        let kwc = KeyframeWithContent::new(keyframe, "Scene".to_string(), String::new());
        assert!(kwc.has_content());
    }

    #[test]
    fn test_keyframe_with_content_has_content_with_ocr() {
        let keyframe = create_test_keyframe();
        let kwc = KeyframeWithContent::new(keyframe, String::new(), "Text".to_string());
        assert!(kwc.has_content());
    }

    #[test]
    fn test_keyframe_with_content_clone() {
        let keyframe = create_test_keyframe();
        let kwc = KeyframeWithContent::new(keyframe, "Scene".to_string(), "Text".to_string());
        let cloned = kwc.clone();
        assert_eq!(kwc.scene_description, cloned.scene_description);
        assert_eq!(kwc.ocr_text, cloned.ocr_text);
    }

    #[test]
    fn test_keyframe_with_content_debug() {
        let keyframe = create_test_keyframe();
        let kwc = KeyframeWithContent::from_keyframe(keyframe);
        let debug = format!("{kwc:?}");
        assert!(debug.contains("KeyframeWithContent"));
        assert!(debug.contains("scene_description"));
    }
}
