//! Types for video indexing operations.

use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// Payload stored with each video chunk vector in Qdrant.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct VideoChunkPayload {
    /// Tenant ID for multi-tenancy.
    pub tenant_id: String,
    /// ID of the source video.
    pub video_id: String,
    /// Zero-based chunk index within the video.
    pub chunk_index: u32,
    /// Start time in milliseconds.
    pub start_time_ms: u64,
    /// End time in milliseconds.
    pub end_time_ms: u64,
    /// Fused text content (first 1000 chars for preview).
    pub fused_text: String,
    /// Title of the video.
    pub video_title: String,
    /// Visibility level: "private", "group", or "public".
    pub visibility: String,
    /// List of group IDs that can access this chunk.
    pub allowed_groups: Vec<String>,
    /// Source modalities: "speech", "visual", "ocr".
    pub source_modalities: Vec<String>,
    /// Path to the keyframe image (if any).
    pub keyframe_path: Option<String>,
}

impl VideoChunkPayload {
    /// Creates a new video chunk payload.
    #[must_use]
    pub fn new(
        tenant_id: Uuid,
        video_id: Uuid,
        chunk_index: u32,
        start_time_ms: u64,
        end_time_ms: u64,
    ) -> Self {
        Self {
            tenant_id: tenant_id.to_string(),
            video_id: video_id.to_string(),
            chunk_index,
            start_time_ms,
            end_time_ms,
            fused_text: String::new(),
            video_title: String::new(),
            visibility: "private".to_string(),
            allowed_groups: Vec::new(),
            source_modalities: Vec::new(),
            keyframe_path: None,
        }
    }

    /// Truncates fused text to the maximum preview length.
    pub fn set_fused_text(&mut self, text: &str, max_length: usize) {
        if text.len() <= max_length {
            self.fused_text = text.to_string();
        } else {
            self.fused_text = text.chars().take(max_length).collect();
        }
    }

    /// Returns the duration of this chunk in milliseconds.
    #[must_use]
    pub const fn duration_ms(&self) -> u64 {
        self.end_time_ms.saturating_sub(self.start_time_ms)
    }
}

impl Default for VideoChunkPayload {
    fn default() -> Self {
        Self {
            tenant_id: String::new(),
            video_id: String::new(),
            chunk_index: 0,
            start_time_ms: 0,
            end_time_ms: 0,
            fused_text: String::new(),
            video_title: String::new(),
            visibility: "private".to_string(),
            allowed_groups: Vec::new(),
            source_modalities: Vec::new(),
            keyframe_path: None,
        }
    }
}

/// Result of an indexing operation.
#[derive(Debug, Clone)]
pub struct IndexResult {
    /// Number of chunks indexed.
    pub indexed_count: usize,
    /// Name of the collection.
    pub collection_name: String,
    /// ID of the indexed video.
    pub video_id: Uuid,
}

impl IndexResult {
    /// Creates a new index result.
    #[must_use]
    pub fn new(indexed_count: usize, collection_name: impl Into<String>, video_id: Uuid) -> Self {
        Self {
            indexed_count,
            collection_name: collection_name.into(),
            video_id,
        }
    }
}

/// Filters for search operations.
#[derive(Debug, Clone, Default)]
pub struct SearchFilters {
    /// Filter by video ID.
    pub video_id: Option<Uuid>,
    /// Groups the searcher belongs to (for ACL filtering).
    pub allowed_groups: Vec<String>,
    /// Minimum score threshold.
    pub score_threshold: Option<f32>,
}

impl SearchFilters {
    /// Creates new search filters.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Sets the video ID filter.
    #[must_use]
    pub const fn with_video_id(mut self, video_id: Uuid) -> Self {
        self.video_id = Some(video_id);
        self
    }

    /// Sets the allowed groups.
    #[must_use]
    pub fn with_allowed_groups(mut self, groups: Vec<String>) -> Self {
        self.allowed_groups = groups;
        self
    }

    /// Sets the score threshold.
    #[must_use]
    pub const fn with_score_threshold(mut self, threshold: f32) -> Self {
        self.score_threshold = Some(threshold);
        self
    }

    /// Checks if any filters are set.
    #[must_use]
    pub fn has_filters(&self) -> bool {
        self.video_id.is_some() || !self.allowed_groups.is_empty() || self.score_threshold.is_some()
    }
}

/// A search result hit.
#[derive(Debug, Clone)]
pub struct SearchHit {
    /// Point ID in Qdrant.
    pub id: String,
    /// Similarity score.
    pub score: f32,
    /// Payload data.
    pub payload: VideoChunkPayload,
}

impl SearchHit {
    /// Creates a new search hit.
    #[must_use]
    pub fn new(id: impl Into<String>, score: f32, payload: VideoChunkPayload) -> Self {
        Self {
            id: id.into(),
            score,
            payload,
        }
    }
}

/// Information about a Qdrant collection.
#[derive(Debug, Clone)]
pub struct CollectionInfo {
    /// Collection name.
    pub name: String,
    /// Number of vectors in the collection.
    pub vectors_count: u64,
    /// Number of points in the collection.
    pub points_count: u64,
    /// Collection status.
    pub status: String,
}

impl CollectionInfo {
    /// Creates new collection info.
    #[must_use]
    pub fn new(
        name: impl Into<String>,
        vectors_count: u64,
        points_count: u64,
        status: impl Into<String>,
    ) -> Self {
        Self {
            name: name.into(),
            vectors_count,
            points_count,
            status: status.into(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_video_chunk_payload_new() {
        let tenant_id = Uuid::new_v4();
        let video_id = Uuid::new_v4();

        let payload = VideoChunkPayload::new(tenant_id, video_id, 0, 0, 20000);

        assert_eq!(payload.tenant_id, tenant_id.to_string());
        assert_eq!(payload.video_id, video_id.to_string());
        assert_eq!(payload.chunk_index, 0);
        assert_eq!(payload.start_time_ms, 0);
        assert_eq!(payload.end_time_ms, 20000);
        assert!(payload.fused_text.is_empty());
        assert!(payload.video_title.is_empty());
        assert_eq!(payload.visibility, "private");
        assert!(payload.allowed_groups.is_empty());
        assert!(payload.source_modalities.is_empty());
        assert!(payload.keyframe_path.is_none());
    }

    #[test]
    fn test_video_chunk_payload_set_fused_text_short() {
        let mut payload = VideoChunkPayload::default();
        payload.set_fused_text("Hello world", 1000);
        assert_eq!(payload.fused_text, "Hello world");
    }

    #[test]
    fn test_video_chunk_payload_set_fused_text_long() {
        let mut payload = VideoChunkPayload::default();
        let long_text = "a".repeat(2000);
        payload.set_fused_text(&long_text, 1000);
        assert_eq!(payload.fused_text.len(), 1000);
    }

    #[test]
    fn test_video_chunk_payload_duration_ms() {
        let payload = VideoChunkPayload::new(Uuid::new_v4(), Uuid::new_v4(), 0, 5000, 25_000);
        assert_eq!(payload.duration_ms(), 20_000);
    }

    #[test]
    fn test_video_chunk_payload_duration_ms_saturating() {
        let payload = VideoChunkPayload {
            start_time_ms: 30_000,
            end_time_ms: 10_000,
            ..VideoChunkPayload::default()
        };
        assert_eq!(payload.duration_ms(), 0);
    }

    #[test]
    fn test_video_chunk_payload_default() {
        let payload = VideoChunkPayload::default();
        assert!(payload.tenant_id.is_empty());
        assert!(payload.video_id.is_empty());
        assert_eq!(payload.visibility, "private");
    }

    #[test]
    fn test_video_chunk_payload_serialize() {
        let payload = VideoChunkPayload::new(Uuid::new_v4(), Uuid::new_v4(), 1, 0, 10000);
        let json = serde_json::to_string(&payload).unwrap();
        assert!(json.contains("\"chunk_index\":1"));
        assert!(json.contains("\"visibility\":\"private\""));
    }

    #[test]
    fn test_video_chunk_payload_deserialize() {
        let json = r#"{
            "tenant_id": "123",
            "video_id": "456",
            "chunk_index": 2,
            "start_time_ms": 0,
            "end_time_ms": 5000,
            "fused_text": "Test",
            "video_title": "Video",
            "visibility": "public",
            "allowed_groups": ["group1"],
            "source_modalities": ["speech"],
            "keyframe_path": "/path/to/frame.jpg"
        }"#;

        let payload: VideoChunkPayload = serde_json::from_str(json).unwrap();
        assert_eq!(payload.chunk_index, 2);
        assert_eq!(payload.visibility, "public");
        assert_eq!(payload.allowed_groups, vec!["group1"]);
        assert_eq!(payload.keyframe_path, Some("/path/to/frame.jpg".to_string()));
    }

    #[test]
    fn test_video_chunk_payload_clone() {
        let payload = VideoChunkPayload::new(Uuid::new_v4(), Uuid::new_v4(), 0, 0, 10000);
        let cloned = payload.clone();
        assert_eq!(payload, cloned);
    }

    #[test]
    fn test_index_result_new() {
        let video_id = Uuid::new_v4();
        let result = IndexResult::new(10, "video_chunks", video_id);

        assert_eq!(result.indexed_count, 10);
        assert_eq!(result.collection_name, "video_chunks");
        assert_eq!(result.video_id, video_id);
    }

    #[test]
    fn test_index_result_clone() {
        let result = IndexResult::new(5, "test", Uuid::new_v4());
        let cloned = result.clone();
        assert_eq!(result.indexed_count, cloned.indexed_count);
    }

    #[test]
    fn test_search_filters_new() {
        let filters = SearchFilters::new();
        assert!(filters.video_id.is_none());
        assert!(filters.allowed_groups.is_empty());
        assert!(filters.score_threshold.is_none());
    }

    #[test]
    fn test_search_filters_builder() {
        let video_id = Uuid::new_v4();
        let filters = SearchFilters::new()
            .with_video_id(video_id)
            .with_allowed_groups(vec!["group1".to_string(), "group2".to_string()])
            .with_score_threshold(0.7);

        assert_eq!(filters.video_id, Some(video_id));
        assert_eq!(filters.allowed_groups.len(), 2);
        assert_eq!(filters.score_threshold, Some(0.7));
    }

    #[test]
    fn test_search_filters_has_filters_empty() {
        let filters = SearchFilters::new();
        assert!(!filters.has_filters());
    }

    #[test]
    fn test_search_filters_has_filters_with_video_id() {
        let filters = SearchFilters::new().with_video_id(Uuid::new_v4());
        assert!(filters.has_filters());
    }

    #[test]
    fn test_search_filters_has_filters_with_groups() {
        let filters = SearchFilters::new().with_allowed_groups(vec!["group".to_string()]);
        assert!(filters.has_filters());
    }

    #[test]
    fn test_search_filters_has_filters_with_threshold() {
        let filters = SearchFilters::new().with_score_threshold(0.5);
        assert!(filters.has_filters());
    }

    #[test]
    fn test_search_hit_new() {
        let payload = VideoChunkPayload::default();
        let hit = SearchHit::new("point_123", 0.85, payload.clone());

        assert_eq!(hit.id, "point_123");
        assert!((hit.score - 0.85).abs() < f32::EPSILON);
        assert_eq!(hit.payload, payload);
    }

    #[test]
    fn test_search_hit_clone() {
        let hit = SearchHit::new("id", 0.9, VideoChunkPayload::default());
        let cloned = hit.clone();
        assert_eq!(hit.id, cloned.id);
        assert!((hit.score - cloned.score).abs() < f32::EPSILON);
    }

    #[test]
    fn test_collection_info_new() {
        let info = CollectionInfo::new("video_chunks", 1000, 500, "green");

        assert_eq!(info.name, "video_chunks");
        assert_eq!(info.vectors_count, 1000);
        assert_eq!(info.points_count, 500);
        assert_eq!(info.status, "green");
    }

    #[test]
    fn test_collection_info_clone() {
        let info = CollectionInfo::new("test", 100, 50, "green");
        let cloned = info.clone();
        assert_eq!(info.name, cloned.name);
        assert_eq!(info.vectors_count, cloned.vectors_count);
    }

    #[test]
    fn test_collection_info_debug() {
        let info = CollectionInfo::new("test", 0, 0, "green");
        let debug = format!("{info:?}");
        assert!(debug.contains("CollectionInfo"));
        assert!(debug.contains("vectors_count"));
    }
}
