//! Pipeline executor.
//!
//! Orchestrates the video processing pipeline stages.

use std::collections::HashMap;
use std::path::Path;
use std::sync::Arc;
use std::time::Instant;

use rag_ingestion::embedding::{EmbeddingClient, EmbeddingClientConfig};
use tracing::{info, warn};
use uuid::Uuid;

use super::config::PipelineConfig;
use super::stages::PipelineStage;
use super::types::{PipelineProgress, PipelineResult, ProgressCallback, StageResult};
use crate::clients::{SceneDetectionClient, TranscriptionClient};
use crate::extraction::{AudioExtractor, KeyframeExtractor, MetadataProbe};
use crate::fusion::ContentFusionService;
use crate::indexer::VideoQdrantIndexer;
use crate::{Result, VideoError};

/// Video processing pipeline executor.
pub struct VideoPipeline {
    config: PipelineConfig,
    indexer: Option<Arc<VideoQdrantIndexer>>,
}

impl VideoPipeline {
    /// Create a new video pipeline.
    #[must_use]
    pub fn new(config: PipelineConfig) -> Self {
        Self {
            config,
            indexer: None,
        }
    }

    /// Set the Qdrant indexer (pre-initialized).
    #[must_use]
    pub fn with_indexer(mut self, indexer: Arc<VideoQdrantIndexer>) -> Self {
        self.indexer = Some(indexer);
        self
    }

    /// Get the pipeline configuration.
    #[must_use]
    pub const fn config(&self) -> &PipelineConfig {
        &self.config
    }

    /// Process a video file through the pipeline.
    ///
    /// # Arguments
    ///
    /// * `video_path` - Path to the video file.
    /// * `video_id` - Unique ID for this video.
    /// * `tenant_id` - Tenant ID for multi-tenancy.
    /// * `video_title` - Title of the video.
    /// * `visibility` - Visibility level ("public", "private", "group").
    /// * `allowed_groups` - Groups that can access this video.
    /// * `progress` - Optional progress callback.
    ///
    /// # Errors
    ///
    /// Returns an error if any pipeline stage fails.
    #[allow(
        clippy::too_many_arguments,
        clippy::too_many_lines,
        clippy::missing_panics_doc
    )]
    pub async fn process(
        &self,
        video_path: impl AsRef<Path>,
        video_id: Uuid,
        tenant_id: Uuid,
        video_title: &str,
        visibility: &str,
        allowed_groups: &[String],
        progress: Option<ProgressCallback>,
    ) -> Result<PipelineResult> {
        let video_path = video_path.as_ref();
        let start = Instant::now();

        // Validate input
        if !video_path.exists() {
            return Err(VideoError::FileNotFound(video_path.display().to_string()));
        }

        // Validate config
        self.config
            .validate()
            .map_err(|e| VideoError::InvalidFormat(format!("Invalid config: {e}")))?;

        let mut result = PipelineResult::new(video_path.to_path_buf(), video_id, tenant_id);

        // Create work directory
        let work_dir = self.config.video_work_dir(&video_id.to_string());
        tokio::fs::create_dir_all(&work_dir).await?;

        // Stage 1: Metadata Probe
        self.report_progress(
            &progress,
            PipelineStage::MetadataProbe,
            0.0,
            "Starting metadata probe",
        );
        let stage_start = Instant::now();
        match MetadataProbe::probe(video_path).await {
            Ok(metadata) => {
                result.metadata = Some(metadata);
                result.add_stage_result(StageResult::success(
                    PipelineStage::MetadataProbe,
                    stage_start.elapsed(),
                ));
            }
            Err(e) => {
                result.add_stage_result(StageResult::failure(
                    PipelineStage::MetadataProbe,
                    stage_start.elapsed(),
                    e.to_string(),
                ));
                result.finalize(start.elapsed());
                return Ok(result);
            }
        }

        // Stage 2 & 3: Keyframe and Audio Extraction (can run in parallel)
        self.report_progress(
            &progress,
            PipelineStage::KeyframeExtraction,
            0.0,
            "Starting extraction",
        );

        let keyframes_dir = self.config.keyframes_dir(&video_id.to_string());
        let audio_path = self.config.audio_path(&video_id.to_string());

        if self.config.enable_parallelism {
            // Run in parallel
            let (keyframe_result, audio_result) = tokio::join!(
                self.extract_keyframes(video_path, &keyframes_dir, &result.metadata),
                self.extract_audio(video_path, &audio_path, &result.metadata)
            );

            match keyframe_result {
                Ok((keyframes, duration)) => {
                    result.keyframes = keyframes;
                    result.add_stage_result(StageResult::success(
                        PipelineStage::KeyframeExtraction,
                        duration,
                    ));
                }
                Err((e, duration)) => {
                    result.add_stage_result(StageResult::failure(
                        PipelineStage::KeyframeExtraction,
                        duration,
                        e,
                    ));
                }
            }

            match audio_result {
                Ok((path, duration)) => {
                    result.audio_path = Some(path);
                    result.add_stage_result(StageResult::success(
                        PipelineStage::AudioExtraction,
                        duration,
                    ));
                }
                Err((e, duration)) => {
                    result.add_stage_result(StageResult::failure(
                        PipelineStage::AudioExtraction,
                        duration,
                        e,
                    ));
                }
            }
        } else {
            // Run sequentially
            let stage_start = Instant::now();
            match self
                .extract_keyframes(video_path, &keyframes_dir, &result.metadata)
                .await
            {
                Ok((keyframes, _)) => {
                    result.keyframes = keyframes;
                    result.add_stage_result(StageResult::success(
                        PipelineStage::KeyframeExtraction,
                        stage_start.elapsed(),
                    ));
                }
                Err((e, _)) => {
                    result.add_stage_result(StageResult::failure(
                        PipelineStage::KeyframeExtraction,
                        stage_start.elapsed(),
                        e,
                    ));
                }
            }

            let stage_start = Instant::now();
            match self
                .extract_audio(video_path, &audio_path, &result.metadata)
                .await
            {
                Ok((path, _)) => {
                    result.audio_path = Some(path);
                    result.add_stage_result(StageResult::success(
                        PipelineStage::AudioExtraction,
                        stage_start.elapsed(),
                    ));
                }
                Err((e, _)) => {
                    result.add_stage_result(StageResult::failure(
                        PipelineStage::AudioExtraction,
                        stage_start.elapsed(),
                        e,
                    ));
                }
            }
        }

        // Check if we can continue (need either keyframes or audio for useful output)
        if result.keyframes.is_empty() && result.audio_path.is_none() {
            result.finalize(start.elapsed());
            return Ok(result);
        }

        // Stage 4 & 5: Scene Detection and Transcription (can run in parallel if inputs available)
        self.report_progress(
            &progress,
            PipelineStage::SceneDetection,
            0.0,
            "Starting scene detection",
        );

        let scene_client = SceneDetectionClient::new(self.config.scene_detection_config.clone());
        let transcription_client =
            TranscriptionClient::new(self.config.transcription_config.clone());

        if self.config.enable_parallelism && result.audio_path.is_some() {
            let (scene_result, transcription_result) = tokio::join!(
                self.run_scene_detection(&scene_client, video_path),
                self.run_transcription(&transcription_client, result.audio_path.as_ref().unwrap())
            );

            match scene_result {
                Ok((scene, duration)) => {
                    result.scene_result = Some(scene);
                    result.add_stage_result(StageResult::success(
                        PipelineStage::SceneDetection,
                        duration,
                    ));
                }
                Err((e, duration)) => {
                    result.add_stage_result(StageResult::failure(
                        PipelineStage::SceneDetection,
                        duration,
                        e,
                    ));
                }
            }

            match transcription_result {
                Ok((transcription, duration)) => {
                    result.transcription_result = Some(transcription);
                    result.add_stage_result(StageResult::success(
                        PipelineStage::Transcription,
                        duration,
                    ));
                }
                Err((e, duration)) => {
                    result.add_stage_result(StageResult::failure(
                        PipelineStage::Transcription,
                        duration,
                        e,
                    ));
                }
            }
        } else {
            // Run sequentially
            let stage_start = Instant::now();
            match self.run_scene_detection(&scene_client, video_path).await {
                Ok((scene, _)) => {
                    result.scene_result = Some(scene);
                    result.add_stage_result(StageResult::success(
                        PipelineStage::SceneDetection,
                        stage_start.elapsed(),
                    ));
                }
                Err((e, _)) => {
                    result.add_stage_result(StageResult::failure(
                        PipelineStage::SceneDetection,
                        stage_start.elapsed(),
                        e,
                    ));
                }
            }

            if let Some(ref audio) = result.audio_path {
                self.report_progress(
                    &progress,
                    PipelineStage::Transcription,
                    0.0,
                    "Starting transcription",
                );
                let stage_start = Instant::now();
                match self.run_transcription(&transcription_client, audio).await {
                    Ok((transcription, _)) => {
                        result.transcription_result = Some(transcription);
                        result.add_stage_result(StageResult::success(
                            PipelineStage::Transcription,
                            stage_start.elapsed(),
                        ));
                    }
                    Err((e, _)) => {
                        result.add_stage_result(StageResult::failure(
                            PipelineStage::Transcription,
                            stage_start.elapsed(),
                            e,
                        ));
                    }
                }
            }
        }

        // Stage 6: Content Fusion
        self.report_progress(
            &progress,
            PipelineStage::ContentFusion,
            0.0,
            "Fusing content",
        );
        let stage_start = Instant::now();
        let fusion_service = ContentFusionService::new(self.config.fusion_config.clone());

        let duration_ms = result.metadata.as_ref().map_or(0, |m| m.duration_ms);
        let transcript_segments = result
            .transcription_result
            .as_ref()
            .map_or(Vec::new(), |t| t.segments.clone());

        // Convert keyframes to KeyframeWithContent
        let keyframes_with_content: Vec<_> = result
            .keyframes
            .iter()
            .map(|kf| crate::fusion::KeyframeWithContent::from_keyframe(kf.clone()))
            .collect();

        let chunks = fusion_service.create_chunks(
            video_id,
            tenant_id,
            duration_ms,
            &transcript_segments,
            &keyframes_with_content,
        );
        result.chunks = chunks;
        result.add_stage_result(StageResult::success(
            PipelineStage::ContentFusion,
            stage_start.elapsed(),
        ));

        // Stage 7: Embedding Generation
        self.report_progress(
            &progress,
            PipelineStage::EmbeddingGeneration,
            0.0,
            "Generating embeddings",
        );
        let stage_start = Instant::now();
        match self.generate_embeddings(&result.chunks).await {
            Ok(embeddings) => {
                result.embeddings = embeddings;
                result.add_stage_result(StageResult::success(
                    PipelineStage::EmbeddingGeneration,
                    stage_start.elapsed(),
                ));
            }
            Err(e) => {
                result.add_stage_result(StageResult::failure(
                    PipelineStage::EmbeddingGeneration,
                    stage_start.elapsed(),
                    e.to_string(),
                ));
                result.finalize(start.elapsed());
                return Ok(result);
            }
        }

        // Stage 8: Qdrant Indexing
        self.report_progress(
            &progress,
            PipelineStage::QdrantIndexing,
            0.0,
            "Indexing in Qdrant",
        );
        let stage_start = Instant::now();

        if let Some(ref indexer) = self.indexer {
            let embeddings_vec: Vec<_> = result
                .embeddings
                .iter()
                .map(|(id, vec)| (*id, vec.clone()))
                .collect();

            match indexer
                .index_chunks(
                    &result.chunks,
                    &embeddings_vec,
                    video_title,
                    visibility,
                    allowed_groups,
                    None,
                )
                .await
            {
                Ok(index_result) => {
                    result.index_result = Some(index_result);
                    result.add_stage_result(StageResult::success(
                        PipelineStage::QdrantIndexing,
                        stage_start.elapsed(),
                    ));
                }
                Err(e) => {
                    result.add_stage_result(StageResult::failure(
                        PipelineStage::QdrantIndexing,
                        stage_start.elapsed(),
                        e.to_string(),
                    ));
                }
            }
        } else {
            result.add_stage_result(StageResult::failure(
                PipelineStage::QdrantIndexing,
                stage_start.elapsed(),
                "No indexer configured",
            ));
        }

        // Cleanup if configured
        if self.config.cleanup_intermediate {
            let _ = tokio::fs::remove_dir_all(&work_dir).await;
        }

        result.finalize(start.elapsed());
        Ok(result)
    }

    /// Report progress to the callback.
    #[allow(clippy::unused_self, clippy::ref_option)]
    fn report_progress(
        &self,
        callback: &Option<ProgressCallback>,
        stage: PipelineStage,
        progress: f32,
        message: &str,
    ) {
        if let Some(ref cb) = callback {
            cb(PipelineProgress::new(stage, progress, message));
        }
    }

    /// Extract keyframes from video.
    #[allow(clippy::ref_option, clippy::cast_possible_truncation)]
    async fn extract_keyframes(
        &self,
        video_path: &Path,
        output_dir: &Path,
        metadata: &Option<crate::extraction::VideoMetadata>,
    ) -> std::result::Result<
        (
            Vec<crate::extraction::ExtractedKeyframe>,
            std::time::Duration,
        ),
        (String, std::time::Duration),
    > {
        let start = Instant::now();
        let extractor = KeyframeExtractor::new(self.config.keyframe_config.clone());

        // Generate timestamps at regular intervals (every 5 seconds for now, or use scene boundaries)
        let duration_ms = metadata.as_ref().map_or(60000, |m| m.duration_ms);
        let interval_ms = 5000u64;
        let timestamps: Vec<u64> = (0..duration_ms).step_by(interval_ms as usize).collect();

        match extractor.extract(video_path, &timestamps, output_dir).await {
            Ok(keyframes) => Ok((keyframes, start.elapsed())),
            Err(e) => Err((e.to_string(), start.elapsed())),
        }
    }

    /// Extract audio from video.
    #[allow(clippy::ref_option)]
    async fn extract_audio(
        &self,
        video_path: &Path,
        output_path: &Path,
        metadata: &Option<crate::extraction::VideoMetadata>,
    ) -> std::result::Result<(std::path::PathBuf, std::time::Duration), (String, std::time::Duration)>
    {
        let start = Instant::now();

        // Check if video has audio
        if let Some(ref meta) = metadata {
            if !meta.has_audio {
                return Err(("Video has no audio track".to_string(), start.elapsed()));
            }
        }

        let extractor = AudioExtractor::new(self.config.audio_config.clone());
        match extractor.extract(video_path, output_path).await {
            Ok(_) => Ok((output_path.to_path_buf(), start.elapsed())),
            Err(e) => Err((e.to_string(), start.elapsed())),
        }
    }

    /// Run scene detection.
    async fn run_scene_detection(
        &self,
        client: &SceneDetectionClient,
        video_path: &Path,
    ) -> std::result::Result<
        (crate::clients::SceneDetectionResult, std::time::Duration),
        (String, std::time::Duration),
    > {
        let start = Instant::now();
        match client.detect(video_path).await {
            Ok(result) => Ok((result, start.elapsed())),
            Err(e) => Err((e.to_string(), start.elapsed())),
        }
    }

    /// Run transcription.
    async fn run_transcription(
        &self,
        client: &TranscriptionClient,
        audio_path: &Path,
    ) -> std::result::Result<
        (crate::clients::TranscriptionResult, std::time::Duration),
        (String, std::time::Duration),
    > {
        let start = Instant::now();
        match client.transcribe(audio_path).await {
            Ok(result) => Ok((result, start.elapsed())),
            Err(e) => Err((e.to_string(), start.elapsed())),
        }
    }

    /// Generate embeddings for chunks using the embedding service.
    ///
    /// Sends chunk texts to the embedding service in batches, with retry logic.
    /// Falls back to placeholder embeddings if the service is unavailable.
    async fn generate_embeddings(
        &self,
        chunks: &[crate::fusion::VideoChunk],
    ) -> Result<HashMap<Uuid, Vec<f32>>> {
        if chunks.is_empty() {
            return Ok(HashMap::new());
        }

        // Build the embedding client from pipeline config
        let embedding_config = EmbeddingClientConfig::new(&self.config.embedding_url)
            .with_timeout(self.config.embedding_timeout)
            .with_max_retries(2);

        let client = match EmbeddingClient::new(embedding_config) {
            Ok(c) => c,
            Err(e) => {
                warn!(
                    error = %e,
                    chunk_count = chunks.len(),
                    "Failed to create embedding client, falling back to placeholder embeddings"
                );
                return Ok(Self::generate_placeholder_embeddings(chunks));
            }
        };

        let batch_size = self.config.embedding_batch_size;
        let mut embeddings = HashMap::with_capacity(chunks.len());
        let total_batches = chunks.len().div_ceil(batch_size);

        info!(
            chunk_count = chunks.len(),
            batch_size,
            total_batches,
            embedding_url = %self.config.embedding_url,
            "Generating embeddings for video chunks"
        );

        for (batch_idx, batch) in chunks.chunks(batch_size).enumerate() {
            let texts: Vec<&str> = batch
                .iter()
                .map(|chunk| chunk.fused_text.as_str())
                .collect();

            match client.embed_batch(&texts).await {
                Ok((batch_embeddings, token_count)) => {
                    // Validate that we got the right number of embeddings
                    if batch_embeddings.len() == batch.len() {
                        // Validate embedding dimensions on the first result
                        if let Some(first) = batch_embeddings.first() {
                            if first.len() != 384 {
                                warn!(
                                    expected_dims = 384,
                                    actual_dims = first.len(),
                                    "Unexpected embedding dimensions"
                                );
                            }
                        }

                        for (chunk, embedding) in batch.iter().zip(batch_embeddings.into_iter()) {
                            embeddings.insert(chunk.id, embedding);
                        }
                    } else {
                        warn!(
                            expected = batch.len(),
                            got = batch_embeddings.len(),
                            batch_idx,
                            "Embedding count mismatch, falling back to placeholder for remaining chunks"
                        );
                        // Use what we got, fill rest with placeholders
                        for (i, chunk) in batch.iter().enumerate() {
                            if i < batch_embeddings.len() {
                                embeddings.insert(chunk.id, batch_embeddings[i].clone());
                            } else {
                                embeddings
                                    .insert(chunk.id, Self::placeholder_vector(&chunk.fused_text));
                            }
                        }
                    }

                    info!(
                        batch = batch_idx + 1,
                        total_batches, token_count, "Embedded batch successfully"
                    );
                }
                Err(e) => {
                    warn!(
                        error = %e,
                        batch_idx,
                        batch_size = batch.len(),
                        "Embedding batch failed, falling back to placeholder for this batch"
                    );
                    // Fall back to placeholder for this batch
                    for chunk in batch {
                        embeddings.insert(chunk.id, Self::placeholder_vector(&chunk.fused_text));
                    }
                }
            }
        }

        Ok(embeddings)
    }

    /// Generate placeholder embeddings for all chunks.
    ///
    /// Used as a fallback when the embedding service is unavailable.
    fn generate_placeholder_embeddings(
        chunks: &[crate::fusion::VideoChunk],
    ) -> HashMap<Uuid, Vec<f32>> {
        chunks
            .iter()
            .map(|chunk| (chunk.id, Self::placeholder_vector(&chunk.fused_text)))
            .collect()
    }

    /// Generate a single placeholder embedding vector from text content.
    ///
    /// Produces a deterministic 384-dimensional vector based on the text length.
    /// This is NOT suitable for semantic search but provides a consistent fallback.
    #[allow(clippy::cast_possible_truncation)]
    fn placeholder_vector(text: &str) -> Vec<f32> {
        (0..384)
            .map(|i| {
                let hash = text.len() as f32 + i as f32;
                f32::midpoint(hash.sin(), 1.0)
            })
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::fusion::VideoChunk;
    use serde_json::json;
    use wiremock::matchers::{method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    #[test]
    fn test_video_pipeline_new() {
        let config = PipelineConfig::default();
        let pipeline = VideoPipeline::new(config);
        assert!(pipeline.config().cleanup_intermediate);
    }

    #[test]
    fn test_video_pipeline_config() {
        let config = PipelineConfig::default()
            .with_cleanup(false)
            .with_parallelism(false);
        let pipeline = VideoPipeline::new(config);
        assert!(!pipeline.config().cleanup_intermediate);
        assert!(!pipeline.config().enable_parallelism);
    }

    #[tokio::test]
    async fn test_video_pipeline_missing_file() {
        let config = PipelineConfig::default();
        let pipeline = VideoPipeline::new(config);

        let result = pipeline
            .process(
                "/nonexistent/video.mp4",
                Uuid::new_v4(),
                Uuid::new_v4(),
                "Test Video",
                "public",
                &[],
                None,
            )
            .await;

        assert!(result.is_err());
    }

    #[allow(clippy::cast_possible_truncation)]
    fn create_test_chunks(count: usize) -> Vec<VideoChunk> {
        let video_id = Uuid::new_v4();
        let tenant_id = Uuid::new_v4();
        (0..count)
            .map(|i| {
                let mut chunk = VideoChunk::new(
                    video_id,
                    tenant_id,
                    i as u32,
                    (i as u64) * 10000,
                    ((i + 1) as u64) * 10000,
                );
                chunk.fused_text =
                    format!("This is test chunk number {i} with some content for embedding");
                chunk
            })
            .collect()
    }

    fn mock_embedding_response(count: usize, dims: usize) -> serde_json::Value {
        let data: Vec<serde_json::Value> = (0..count)
            .map(|i| {
                let embedding: Vec<f32> =
                    (0..dims).map(|d| (d as f32 + i as f32) * 0.001).collect();
                json!({
                    "embedding": embedding,
                    "index": i
                })
            })
            .collect();
        json!({
            "data": data,
            "usage": {"total_tokens": count * 10}
        })
    }

    #[tokio::test]
    async fn test_generate_embeddings_empty_chunks() {
        let config = PipelineConfig::default();
        let pipeline = VideoPipeline::new(config);

        let result = pipeline.generate_embeddings(&[]).await.unwrap();
        assert!(result.is_empty());
    }

    #[tokio::test]
    async fn test_generate_embeddings_success() {
        let mock_server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/v1/embeddings"))
            .respond_with(ResponseTemplate::new(200).set_body_json(mock_embedding_response(3, 384)))
            .mount(&mock_server)
            .await;

        let config = PipelineConfig::default()
            .with_embedding_url(mock_server.uri())
            .with_embedding_batch_size(32);
        let pipeline = VideoPipeline::new(config);

        let chunks = create_test_chunks(3);
        let result = pipeline.generate_embeddings(&chunks).await.unwrap();

        assert_eq!(result.len(), 3);
        for chunk in &chunks {
            assert!(result.contains_key(&chunk.id));
            assert_eq!(result[&chunk.id].len(), 384);
        }
    }

    #[tokio::test]
    async fn test_generate_embeddings_batching() {
        let mock_server = MockServer::start().await;

        // With batch_size=2 and 5 chunks, we expect 3 requests
        Mock::given(method("POST"))
            .and(path("/v1/embeddings"))
            .respond_with(|req: &wiremock::Request| {
                let body: serde_json::Value = req.body_json().unwrap();
                let input = body["input"].as_array().unwrap();
                let count = input.len();
                ResponseTemplate::new(200).set_body_json(mock_embedding_response(count, 384))
            })
            .expect(3)
            .mount(&mock_server)
            .await;

        let config = PipelineConfig::default()
            .with_embedding_url(mock_server.uri())
            .with_embedding_batch_size(2);
        let pipeline = VideoPipeline::new(config);

        let chunks = create_test_chunks(5);
        let result = pipeline.generate_embeddings(&chunks).await.unwrap();

        assert_eq!(result.len(), 5);
        for chunk in &chunks {
            assert!(result.contains_key(&chunk.id));
            assert_eq!(result[&chunk.id].len(), 384);
        }
    }

    #[tokio::test]
    async fn test_generate_embeddings_fallback_on_service_error() {
        let mock_server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/v1/embeddings"))
            .respond_with(ResponseTemplate::new(500).set_body_string("Internal Server Error"))
            .mount(&mock_server)
            .await;

        let config = PipelineConfig::default()
            .with_embedding_url(mock_server.uri())
            .with_embedding_batch_size(32);
        let pipeline = VideoPipeline::new(config);

        let chunks = create_test_chunks(2);
        let result = pipeline.generate_embeddings(&chunks).await.unwrap();

        // Should still return embeddings (placeholder fallback)
        assert_eq!(result.len(), 2);
        for chunk in &chunks {
            assert!(result.contains_key(&chunk.id));
            // Placeholder embeddings are 384-dimensional
            assert_eq!(result[&chunk.id].len(), 384);
        }
    }

    #[tokio::test]
    async fn test_generate_embeddings_dimension_check() {
        let mock_server = MockServer::start().await;

        // Return embeddings with correct dimensions
        Mock::given(method("POST"))
            .and(path("/v1/embeddings"))
            .respond_with(ResponseTemplate::new(200).set_body_json(mock_embedding_response(1, 384)))
            .mount(&mock_server)
            .await;

        let config = PipelineConfig::default().with_embedding_url(mock_server.uri());
        let pipeline = VideoPipeline::new(config);

        let chunks = create_test_chunks(1);
        let result = pipeline.generate_embeddings(&chunks).await.unwrap();

        assert_eq!(result.len(), 1);
        let embedding = result.values().next().unwrap();
        assert_eq!(embedding.len(), 384, "Embedding should have 384 dimensions");
    }

    #[tokio::test]
    async fn test_generate_embeddings_partial_batch_failure() {
        let mock_server = MockServer::start().await;

        // First batch succeeds, second batch fails
        let counter = std::sync::Arc::new(std::sync::atomic::AtomicU32::new(0));
        let counter_clone = counter.clone();

        Mock::given(method("POST"))
            .and(path("/v1/embeddings"))
            .respond_with(move |req: &wiremock::Request| {
                let call = counter_clone.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
                if call == 0 {
                    let body: serde_json::Value = req.body_json().unwrap();
                    let input = body["input"].as_array().unwrap();
                    let count = input.len();
                    ResponseTemplate::new(200).set_body_json(mock_embedding_response(count, 384))
                } else {
                    ResponseTemplate::new(500).set_body_string("Internal Server Error")
                }
            })
            .mount(&mock_server)
            .await;

        let config = PipelineConfig::default()
            .with_embedding_url(mock_server.uri())
            .with_embedding_batch_size(2);
        let pipeline = VideoPipeline::new(config);

        let chunks = create_test_chunks(4);
        let result = pipeline.generate_embeddings(&chunks).await.unwrap();

        // All chunks should have embeddings (some real, some placeholder)
        assert_eq!(result.len(), 4);
        for chunk in &chunks {
            assert!(result.contains_key(&chunk.id));
            assert_eq!(result[&chunk.id].len(), 384);
        }
    }

    #[test]
    fn test_placeholder_vector_deterministic() {
        let vec1 = VideoPipeline::placeholder_vector("hello world");
        let vec2 = VideoPipeline::placeholder_vector("hello world");
        assert_eq!(vec1, vec2, "Placeholder vectors should be deterministic");
        assert_eq!(vec1.len(), 384);
    }

    #[test]
    fn test_placeholder_vector_different_for_different_text() {
        let vec1 = VideoPipeline::placeholder_vector("hello");
        let vec2 = VideoPipeline::placeholder_vector("hello world");
        assert_ne!(
            vec1, vec2,
            "Different texts should produce different placeholder vectors"
        );
    }

    #[test]
    fn test_generate_placeholder_embeddings() {
        let chunks = create_test_chunks(3);
        let result = VideoPipeline::generate_placeholder_embeddings(&chunks);

        assert_eq!(result.len(), 3);
        for chunk in &chunks {
            assert!(result.contains_key(&chunk.id));
            assert_eq!(result[&chunk.id].len(), 384);
        }
    }
}
