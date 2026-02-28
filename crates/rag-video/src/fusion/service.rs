//! Content fusion service for combining multiple modalities into video chunks.

use uuid::Uuid;

use super::config::FusionConfig;
use super::types::{KeyframeWithContent, VideoChunk};
use crate::clients::TranscriptSegment;

/// Service for fusing content from multiple modalities into video chunks.
pub struct ContentFusionService {
    config: FusionConfig,
}

impl ContentFusionService {
    /// Creates a new content fusion service with the given configuration.
    #[must_use]
    pub fn new(config: FusionConfig) -> Self {
        Self { config }
    }

    /// Creates a content fusion service with default configuration.
    #[must_use]
    pub fn with_default_config() -> Self {
        Self::new(FusionConfig::default())
    }

    /// Returns a reference to the service configuration.
    #[must_use]
    pub const fn config(&self) -> &FusionConfig {
        &self.config
    }

    /// Creates fused content chunks from video components.
    ///
    /// # Arguments
    ///
    /// * `video_id` - Unique identifier for the video.
    /// * `tenant_id` - Tenant ID for multi-tenancy.
    /// * `duration_ms` - Total video duration in milliseconds.
    /// * `transcript` - Transcript segments with timing.
    /// * `keyframes` - Keyframes with scene descriptions and OCR text.
    ///
    /// # Returns
    ///
    /// A vector of fused video chunks covering the entire video duration.
    #[must_use]
    #[allow(clippy::cast_possible_truncation)]
    pub fn create_chunks(
        &self,
        video_id: Uuid,
        tenant_id: Uuid,
        duration_ms: u64,
        transcript: &[TranscriptSegment],
        keyframes: &[KeyframeWithContent],
    ) -> Vec<VideoChunk> {
        let boundaries = self.generate_chunk_boundaries(duration_ms);

        boundaries
            .iter()
            .enumerate()
            .map(|(index, &(start_ms, end_ms))| {
                let mut chunk =
                    VideoChunk::new(video_id, tenant_id, index as u32, start_ms, end_ms);

                // Extract transcript text for this time range
                chunk.transcript_text = self.get_transcript_in_range(transcript, start_ms, end_ms);

                // Find keyframes within this time range
                let range_keyframes: Vec<_> = keyframes
                    .iter()
                    .filter(|kf| {
                        kf.keyframe.timestamp_ms >= start_ms && kf.keyframe.timestamp_ms < end_ms
                    })
                    .collect();

                // Combine scene descriptions from all keyframes in range
                chunk.scene_description = self.combine_scene_descriptions(&range_keyframes);

                // Combine OCR text from all keyframes in range
                chunk.ocr_text = self.combine_ocr_text(&range_keyframes);

                // Set representative keyframe (first scene boundary, or first keyframe)
                if let Some(kf) = range_keyframes
                    .iter()
                    .find(|kf| kf.keyframe.is_scene_boundary)
                    .or_else(|| range_keyframes.first())
                {
                    chunk.keyframe_path = Some(kf.keyframe.image_path.clone());
                    chunk.keyframe_index = Some(kf.keyframe.frame_index);
                }

                // Create fused text
                chunk.fused_text = self.fuse_modalities(
                    &chunk.transcript_text,
                    &chunk.scene_description,
                    &chunk.ocr_text,
                );

                // Track source modalities
                if !chunk.transcript_text.is_empty() {
                    chunk.source_modalities.push("speech".to_string());
                }
                if !chunk.scene_description.is_empty() {
                    chunk.source_modalities.push("visual".to_string());
                }
                if !chunk.ocr_text.is_empty() {
                    chunk.source_modalities.push("ocr".to_string());
                }

                chunk
            })
            .collect()
    }

    /// Generates chunk time boundaries with overlap.
    ///
    /// # Arguments
    ///
    /// * `duration_ms` - Total video duration in milliseconds.
    ///
    /// # Returns
    ///
    /// A vector of (`start_ms`, `end_ms`) tuples for each chunk.
    #[must_use]
    pub fn generate_chunk_boundaries(&self, duration_ms: u64) -> Vec<(u64, u64)> {
        if duration_ms == 0 {
            return vec![];
        }

        let target = self.config.target_chunk_duration_ms;
        let min = self.config.min_chunk_duration_ms;
        let max = self.config.max_chunk_duration_ms;
        let overlap = self.config.overlap_ms;

        let mut boundaries = Vec::new();
        let mut start = 0u64;

        while start < duration_ms {
            // Calculate end position
            let mut end = start + target;

            // If we'd leave a small remainder, extend this chunk or adjust
            let remaining = duration_ms.saturating_sub(end);
            if remaining > 0 && remaining < min {
                // Extend this chunk to include the remainder
                end = duration_ms;
            } else {
                // Clamp to video duration
                end = end.min(duration_ms);
            }

            // Ensure chunk doesn't exceed max duration
            if end - start > max {
                end = start + max;
            }

            boundaries.push((start, end));

            if end >= duration_ms {
                break;
            }

            // Move start position with overlap
            start = end.saturating_sub(overlap);
        }

        boundaries
    }

    /// Extracts transcript text within a time range.
    ///
    /// # Arguments
    ///
    /// * `segments` - Transcript segments.
    /// * `start_ms` - Start time in milliseconds.
    /// * `end_ms` - End time in milliseconds.
    ///
    /// # Returns
    ///
    /// Concatenated transcript text for segments that overlap with the time range.
    #[must_use]
    pub fn get_transcript_in_range(
        &self,
        segments: &[TranscriptSegment],
        start_ms: u64,
        end_ms: u64,
    ) -> String {
        let texts: Vec<&str> = segments
            .iter()
            .filter(|seg| {
                // Include segment if it overlaps with the time range
                seg.end_ms > start_ms && seg.start_ms < end_ms
            })
            .map(|seg| seg.text.as_str())
            .collect();

        texts.join(" ").trim().to_string()
    }

    /// Combines modalities into fused text.
    ///
    /// # Arguments
    ///
    /// * `transcript` - Speech transcript text.
    /// * `scene` - Scene description text.
    /// * `ocr` - OCR text from frames.
    ///
    /// # Returns
    ///
    /// Fused text combining all non-empty modalities.
    #[must_use]
    pub fn fuse_modalities(&self, transcript: &str, scene: &str, ocr: &str) -> String {
        let mut parts = Vec::new();

        if !transcript.trim().is_empty() {
            if self.config.include_modality_labels {
                parts.push(format!("[Speech] {}", transcript.trim()));
            } else {
                parts.push(transcript.trim().to_string());
            }
        }

        if !scene.trim().is_empty() {
            if self.config.include_modality_labels {
                parts.push(format!("[Visual] {}", scene.trim()));
            } else {
                parts.push(scene.trim().to_string());
            }
        }

        if !ocr.trim().is_empty() {
            if self.config.include_modality_labels {
                parts.push(format!("[Text on screen] {}", ocr.trim()));
            } else {
                parts.push(ocr.trim().to_string());
            }
        }

        parts.join(&self.config.separator)
    }

    /// Combines scene descriptions from multiple keyframes.
    fn combine_scene_descriptions(&self, keyframes: &[&KeyframeWithContent]) -> String {
        let descriptions: Vec<&str> = keyframes
            .iter()
            .filter(|kf| !kf.scene_description.is_empty())
            .map(|kf| kf.scene_description.as_str())
            .collect();

        self.deduplicate_text(&descriptions)
    }

    /// Combines OCR text from multiple keyframes.
    fn combine_ocr_text(&self, keyframes: &[&KeyframeWithContent]) -> String {
        let texts: Vec<&str> = keyframes
            .iter()
            .filter(|kf| !kf.ocr_text.is_empty())
            .map(|kf| kf.ocr_text.as_str())
            .collect();

        self.deduplicate_text(&texts)
    }

    /// Deduplicates similar text entries.
    ///
    /// # Arguments
    ///
    /// * `texts` - Vector of text strings.
    ///
    /// # Returns
    ///
    /// Deduplicated text joined with spaces.
    #[allow(clippy::unused_self)]
    fn deduplicate_text(&self, texts: &[&str]) -> String {
        if texts.is_empty() {
            return String::new();
        }

        let mut unique = Vec::new();
        for text in texts {
            let trimmed = text.trim();
            if trimmed.is_empty() {
                continue;
            }

            // Check if similar text already exists
            let is_duplicate = unique
                .iter()
                .any(|existing: &&str| existing.contains(trimmed) || trimmed.contains(*existing));

            if !is_duplicate {
                unique.push(trimmed);
            }
        }

        unique.join(" ")
    }
}

#[cfg(test)]
mod tests {
    use std::path::PathBuf;

    use super::*;
    use crate::extraction::ExtractedKeyframe;

    #[allow(clippy::cast_possible_truncation)]
    fn create_test_keyframe(timestamp_ms: u64, is_scene_boundary: bool) -> ExtractedKeyframe {
        ExtractedKeyframe {
            frame_index: (timestamp_ms / 1000) as u32,
            timestamp_ms,
            image_path: PathBuf::from(format!("/tmp/frame_{timestamp_ms}.jpg")),
            thumbnail_path: None,
            width: 1280,
            height: 720,
            file_size_bytes: 50_000,
            is_scene_boundary,
        }
    }

    fn create_keyframe_with_content(
        timestamp_ms: u64,
        is_scene_boundary: bool,
        scene: &str,
        ocr: &str,
    ) -> KeyframeWithContent {
        KeyframeWithContent::new(
            create_test_keyframe(timestamp_ms, is_scene_boundary),
            scene.to_string(),
            ocr.to_string(),
        )
    }

    fn create_transcript_segment(start_ms: u64, end_ms: u64, text: &str) -> TranscriptSegment {
        TranscriptSegment::new(start_ms, end_ms, text, Some(0.9))
    }

    #[test]
    fn test_content_fusion_service_new() {
        let config = FusionConfig::default();
        let service = ContentFusionService::new(config.clone());
        assert_eq!(
            service.config().target_chunk_duration_ms,
            config.target_chunk_duration_ms
        );
    }

    #[test]
    fn test_content_fusion_service_with_default_config() {
        let service = ContentFusionService::with_default_config();
        assert_eq!(service.config().target_chunk_duration_ms, 20_000);
    }

    #[test]
    fn test_generate_chunk_boundaries_empty() {
        let service = ContentFusionService::with_default_config();
        let boundaries = service.generate_chunk_boundaries(0);
        assert!(boundaries.is_empty());
    }

    #[test]
    fn test_generate_chunk_boundaries_single_chunk() {
        let service = ContentFusionService::with_default_config();
        // Video shorter than target chunk
        let boundaries = service.generate_chunk_boundaries(15_000);
        assert_eq!(boundaries.len(), 1);
        assert_eq!(boundaries[0], (0, 15_000));
    }

    #[test]
    fn test_generate_chunk_boundaries_multiple_chunks() {
        let service = ContentFusionService::with_default_config();
        // 60s video with 20s chunks and 2s overlap
        let boundaries = service.generate_chunk_boundaries(60_000);

        // Should have multiple chunks
        assert!(boundaries.len() >= 3);

        // First chunk starts at 0
        assert_eq!(boundaries[0].0, 0);

        // Chunks should overlap
        assert!(boundaries[1].0 < boundaries[0].1);

        // Last chunk should end at duration
        assert_eq!(boundaries.last().unwrap().1, 60_000);
    }

    #[test]
    fn test_generate_chunk_boundaries_with_overlap() {
        let config = FusionConfig::new()
            .with_target_duration_ms(20_000)
            .with_overlap_ms(2_000);
        let service = ContentFusionService::new(config);

        let boundaries = service.generate_chunk_boundaries(40_000);

        assert!(boundaries.len() >= 2);
        // Second chunk should start before first chunk ends (overlap)
        assert!(boundaries[1].0 < boundaries[0].1);
        // Overlap should be approximately 2 seconds
        let overlap = boundaries[0].1 - boundaries[1].0;
        assert_eq!(overlap, 2_000);
    }

    #[test]
    fn test_generate_chunk_boundaries_extends_for_small_remainder() {
        let config = FusionConfig::new()
            .with_target_duration_ms(20_000)
            .with_min_duration_ms(10_000);
        let service = ContentFusionService::new(config);

        // 25s video: should create one chunk that extends to include remainder
        // rather than leaving a 5s chunk which is less than min
        let boundaries = service.generate_chunk_boundaries(25_000);

        assert_eq!(boundaries.len(), 1);
        assert_eq!(boundaries[0], (0, 25_000));
    }

    #[test]
    fn test_get_transcript_in_range_empty() {
        let service = ContentFusionService::with_default_config();
        let transcript = service.get_transcript_in_range(&[], 0, 10_000);
        assert!(transcript.is_empty());
    }

    #[test]
    fn test_get_transcript_in_range_full_overlap() {
        let service = ContentFusionService::with_default_config();
        let segments = vec![
            create_transcript_segment(0, 5_000, "Hello"),
            create_transcript_segment(5_000, 10_000, "world"),
        ];

        let transcript = service.get_transcript_in_range(&segments, 0, 10_000);
        assert_eq!(transcript, "Hello world");
    }

    #[test]
    fn test_get_transcript_in_range_partial_overlap() {
        let service = ContentFusionService::with_default_config();
        let segments = vec![
            create_transcript_segment(0, 5_000, "First"),
            create_transcript_segment(5_000, 10_000, "Second"),
            create_transcript_segment(10_000, 15_000, "Third"),
        ];

        // Should include segments that overlap with 3s-8s
        let transcript = service.get_transcript_in_range(&segments, 3_000, 8_000);
        assert_eq!(transcript, "First Second");
    }

    #[test]
    fn test_get_transcript_in_range_no_overlap() {
        let service = ContentFusionService::with_default_config();
        let segments = vec![create_transcript_segment(20_000, 25_000, "Later")];

        let transcript = service.get_transcript_in_range(&segments, 0, 10_000);
        assert!(transcript.is_empty());
    }

    #[test]
    fn test_fuse_modalities_with_labels() {
        let config = FusionConfig::new().with_modality_labels(true);
        let service = ContentFusionService::new(config);

        let fused = service.fuse_modalities("Hello world", "A person speaking", "TITLE");

        assert!(fused.contains("[Speech] Hello world"));
        assert!(fused.contains("[Visual] A person speaking"));
        assert!(fused.contains("[Text on screen] TITLE"));
    }

    #[test]
    fn test_fuse_modalities_without_labels() {
        let config = FusionConfig::new().with_modality_labels(false);
        let service = ContentFusionService::new(config);

        let fused = service.fuse_modalities("Hello world", "A person speaking", "TITLE");

        assert!(!fused.contains("[Speech]"));
        assert!(!fused.contains("[Visual]"));
        assert!(!fused.contains("[Text on screen]"));
        assert!(fused.contains("Hello world"));
        assert!(fused.contains("A person speaking"));
        assert!(fused.contains("TITLE"));
    }

    #[test]
    fn test_fuse_modalities_with_custom_separator() {
        let config = FusionConfig::new()
            .with_modality_labels(false)
            .with_separator(" | ");
        let service = ContentFusionService::new(config);

        let fused = service.fuse_modalities("Hello", "Scene", "Text");

        assert_eq!(fused, "Hello | Scene | Text");
    }

    #[test]
    fn test_fuse_modalities_empty_modalities() {
        let service = ContentFusionService::with_default_config();

        // All empty
        assert!(service.fuse_modalities("", "", "").is_empty());

        // Partial empty
        let fused = service.fuse_modalities("Hello", "", "");
        assert!(fused.contains("Hello"));
        assert!(!fused.contains("[Visual]"));
        assert!(!fused.contains("[Text on screen]"));
    }

    #[test]
    fn test_fuse_modalities_trims_whitespace() {
        let service = ContentFusionService::with_default_config();

        let fused = service.fuse_modalities("  Hello  ", "  Scene  ", "  ");

        assert!(fused.contains("Hello"));
        assert!(fused.contains("Scene"));
        // Empty after trim should not appear
        assert!(!fused.contains("[Text on screen]"));
    }

    #[test]
    fn test_create_chunks_empty_video() {
        let service = ContentFusionService::with_default_config();
        let chunks = service.create_chunks(Uuid::new_v4(), Uuid::new_v4(), 0, &[], &[]);
        assert!(chunks.is_empty());
    }

    #[test]
    fn test_create_chunks_with_transcript_only() {
        let service = ContentFusionService::with_default_config();
        let video_id = Uuid::new_v4();
        let tenant_id = Uuid::new_v4();

        let transcript = vec![
            create_transcript_segment(0, 5_000, "Hello"),
            create_transcript_segment(5_000, 10_000, "world"),
        ];

        let chunks = service.create_chunks(video_id, tenant_id, 10_000, &transcript, &[]);

        assert_eq!(chunks.len(), 1);
        assert_eq!(chunks[0].video_id, video_id);
        assert_eq!(chunks[0].tenant_id, tenant_id);
        assert_eq!(chunks[0].transcript_text, "Hello world");
        assert!(chunks[0].scene_description.is_empty());
        assert!(chunks[0].ocr_text.is_empty());
        assert!(chunks[0].fused_text.contains("[Speech]"));
        assert_eq!(chunks[0].source_modalities, vec!["speech"]);
    }

    #[test]
    fn test_create_chunks_with_keyframes() {
        let service = ContentFusionService::with_default_config();
        let video_id = Uuid::new_v4();
        let tenant_id = Uuid::new_v4();

        let keyframes = vec![create_keyframe_with_content(
            5_000,
            true,
            "A person speaking",
            "TITLE",
        )];

        let chunks = service.create_chunks(video_id, tenant_id, 10_000, &[], &keyframes);

        assert_eq!(chunks.len(), 1);
        assert_eq!(chunks[0].scene_description, "A person speaking");
        assert_eq!(chunks[0].ocr_text, "TITLE");
        assert!(chunks[0].fused_text.contains("[Visual]"));
        assert!(chunks[0].fused_text.contains("[Text on screen]"));
        assert!(chunks[0].source_modalities.contains(&"visual".to_string()));
        assert!(chunks[0].source_modalities.contains(&"ocr".to_string()));
    }

    #[test]
    fn test_create_chunks_sets_representative_keyframe() {
        let service = ContentFusionService::with_default_config();

        let keyframes = vec![
            create_keyframe_with_content(2_000, false, "First", ""),
            create_keyframe_with_content(5_000, true, "Scene boundary", ""),
            create_keyframe_with_content(8_000, false, "Third", ""),
        ];

        let chunks = service.create_chunks(Uuid::new_v4(), Uuid::new_v4(), 10_000, &[], &keyframes);

        // Should pick the scene boundary keyframe
        assert_eq!(chunks[0].keyframe_index, Some(5)); // frame_index = timestamp/1000
        assert!(chunks[0]
            .keyframe_path
            .as_ref()
            .unwrap()
            .to_string_lossy()
            .contains("5000"));
    }

    #[test]
    fn test_create_chunks_assigns_keyframe_to_correct_chunk() {
        let config = FusionConfig::new()
            .with_target_duration_ms(10_000)
            .with_overlap_ms(0);
        let service = ContentFusionService::new(config);

        let keyframes = vec![
            create_keyframe_with_content(5_000, true, "First chunk", ""),
            create_keyframe_with_content(15_000, true, "Second chunk", ""),
        ];

        let chunks = service.create_chunks(Uuid::new_v4(), Uuid::new_v4(), 20_000, &[], &keyframes);

        assert_eq!(chunks.len(), 2);
        assert_eq!(chunks[0].scene_description, "First chunk");
        assert_eq!(chunks[1].scene_description, "Second chunk");
    }

    #[test]
    fn test_create_chunks_full_fusion() {
        let service = ContentFusionService::with_default_config();

        let transcript = vec![create_transcript_segment(0, 10_000, "Hello world")];
        let keyframes = vec![create_keyframe_with_content(
            5_000,
            true,
            "A person speaking",
            "SUBTITLE",
        )];

        let chunks = service.create_chunks(
            Uuid::new_v4(),
            Uuid::new_v4(),
            10_000,
            &transcript,
            &keyframes,
        );

        assert_eq!(chunks.len(), 1);
        assert_eq!(chunks[0].transcript_text, "Hello world");
        assert_eq!(chunks[0].scene_description, "A person speaking");
        assert_eq!(chunks[0].ocr_text, "SUBTITLE");

        // All modalities present
        assert_eq!(chunks[0].source_modalities.len(), 3);
        assert!(chunks[0].source_modalities.contains(&"speech".to_string()));
        assert!(chunks[0].source_modalities.contains(&"visual".to_string()));
        assert!(chunks[0].source_modalities.contains(&"ocr".to_string()));

        // Fused text contains all
        assert!(chunks[0].fused_text.contains("[Speech]"));
        assert!(chunks[0].fused_text.contains("[Visual]"));
        assert!(chunks[0].fused_text.contains("[Text on screen]"));
    }

    #[test]
    fn test_deduplicate_text_removes_duplicates() {
        let service = ContentFusionService::with_default_config();

        let texts = vec!["Hello", "Hello", "World"];
        let result = service.deduplicate_text(&texts);

        // Should not have duplicate "Hello"
        assert_eq!(result.matches("Hello").count(), 1);
        assert!(result.contains("World"));
    }

    #[test]
    fn test_deduplicate_text_removes_substrings() {
        let service = ContentFusionService::with_default_config();

        let texts = vec!["Hello World", "Hello"];
        let result = service.deduplicate_text(&texts);

        // "Hello" is a substring of "Hello World", should only keep "Hello World"
        assert!(result.contains("Hello World"));
        // Should not have standalone "Hello"
        assert!(!result.ends_with("Hello"));
    }

    #[test]
    fn test_chunk_index_sequential() {
        let config = FusionConfig::new()
            .with_target_duration_ms(10_000)
            .with_overlap_ms(0);
        let service = ContentFusionService::new(config);

        let chunks = service.create_chunks(Uuid::new_v4(), Uuid::new_v4(), 30_000, &[], &[]);

        assert_eq!(chunks.len(), 3);
        assert_eq!(chunks[0].chunk_index, 0);
        assert_eq!(chunks[1].chunk_index, 1);
        assert_eq!(chunks[2].chunk_index, 2);
    }
}
