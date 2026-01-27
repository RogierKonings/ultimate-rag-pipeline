# Phase 3.5: Rust Video Processing Pipeline Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a new `rag-video` crate that ports the Python video processing pipeline to Rust, with scene detection and transcription remaining as Python HTTP microservices.

**Architecture:** New `rag-video` crate with FFmpeg bindings for extraction, Tesseract bindings for OCR, HTTP clients for Python microservices (scene detection, transcription), and parallel batch processing via rayon. Pipeline executes stages in parallel where possible.

**Tech Stack:** Rust, ffmpeg-next (FFmpeg bindings), tesseract-rs (OCR), reqwest (HTTP), qdrant-client, rayon (parallelism), tokio (async)

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Scene detection | HTTP microservice (PySceneDetect) | No mature Rust equivalent |
| Transcription | HTTP microservice (Whisper) | whisper-rs less mature |
| FFmpeg | Rust bindings (ffmpeg-next) | Better performance than subprocess |
| OCR | Tesseract bindings | Parallel batch processing with rayon |
| Crate structure | New `rag-video` crate | Clean separation, dedicated workspace |
| Pipeline execution | Parallel where possible | tokio::join! for async, rayon for CPU |

---

## Crate Structure

```
crates/rag-video/
├── Cargo.toml
├── src/
│   ├── lib.rs
│   ├── error.rs              # VideoError enum
│   ├── extraction/
│   │   ├── mod.rs
│   │   ├── keyframe.rs       # FFmpeg keyframe extraction
│   │   ├── audio.rs          # Audio track extraction
│   │   └── metadata.rs       # Video probing
│   ├── clients/
│   │   ├── mod.rs
│   │   ├── scene_detection.rs  # HTTP client for PySceneDetect service
│   │   └── transcription.rs    # HTTP client for Whisper service
│   ├── ocr/
│   │   ├── mod.rs
│   │   └── processor.rs      # Tesseract OCR
│   ├── fusion/
│   │   ├── mod.rs
│   │   ├── config.rs
│   │   ├── types.rs          # VideoChunk
│   │   └── service.rs        # ContentFusionService
│   ├── indexer/
│   │   ├── mod.rs
│   │   ├── config.rs
│   │   └── service.rs        # VideoQdrantIndexer
│   └── pipeline/
│       ├── mod.rs
│       ├── stages.rs         # PipelineStage enum
│       ├── config.rs         # PipelineConfig
│       └── executor.rs       # VideoPipeline
└── tests/
    ├── fixtures/
    │   ├── sample_video.mp4
    │   ├── sample_keyframe.jpg
    │   ├── transcript_response.json
    │   └── scene_detection_response.json
    └── integration/
```

### Dependencies (Cargo.toml)

```toml
[package]
name = "rag-video"
version = "0.1.0"
edition = "2021"

[dependencies]
# Async runtime
tokio = { version = "1", features = ["full"] }

# FFmpeg bindings
ffmpeg-next = "7"

# OCR
tesseract = "0.14"

# HTTP client
reqwest = { version = "0.12", features = ["json"] }

# Qdrant
qdrant-client = "1"

# Parallelism
rayon = "1.10"

# Serialization
serde = { version = "1", features = ["derive"] }
serde_json = "1"

# Error handling
thiserror = "2"
anyhow = "1"

# Utilities
uuid = { version = "1", features = ["v4", "serde"] }
tracing = "0.1"
tempfile = "3"

[dev-dependencies]
wiremock = "0.6"
testcontainers = "0.21"
tokio-test = "0.4"
```

---

## Core Types & Error Handling

### error.rs

```rust
use thiserror::Error;

#[derive(Error, Debug)]
pub enum VideoError {
    #[error("Video file not found: {0}")]
    FileNotFound(String),

    #[error("Invalid video format: {0}")]
    InvalidFormat(String),

    #[error("FFmpeg error: {0}")]
    Ffmpeg(String),

    #[error("OCR error: {0}")]
    Ocr(String),

    #[error("Scene detection service error: {0}")]
    SceneDetection(String),

    #[error("Transcription service error: {0}")]
    Transcription(String),

    #[error("Indexing error: {0}")]
    Indexing(String),

    #[error("HTTP request failed: {0}")]
    Http(#[from] reqwest::Error),

    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("Timeout after {0}ms")]
    Timeout(u64),
}

pub type Result<T> = std::result::Result<T, VideoError>;
```

### Common Types

```rust
// extraction/types.rs
pub struct VideoMetadata {
    pub duration_ms: u64,
    pub width: u32,
    pub height: u32,
    pub fps: f32,
    pub codec: String,
    pub has_audio: bool,
}

pub struct ExtractedKeyframe {
    pub frame_index: u32,
    pub timestamp_ms: u64,
    pub image_path: PathBuf,
    pub thumbnail_path: Option<PathBuf>,
    pub width: u32,
    pub height: u32,
    pub file_size_bytes: u64,
    pub is_scene_boundary: bool,
}

// clients/types.rs
pub struct SceneBoundary {
    pub scene_index: u32,
    pub start_ms: u64,
    pub end_ms: u64,
    pub is_detected: bool,  // false = fallback interval
}

pub struct TranscriptSegment {
    pub start_ms: u64,
    pub end_ms: u64,
    pub text: String,
    pub confidence: Option<f32>,
}
```

---

## Extraction Module (FFmpeg Bindings)

### extraction/keyframe.rs

```rust
use ffmpeg_next as ffmpeg;

pub struct KeyframeConfig {
    pub output_width: u32,       // Default: 1280
    pub output_height: u32,      // Default: 720
    pub quality: u8,             // Default: 85 (1-100)
    pub generate_thumbnails: bool,
    pub thumbnail_width: u32,    // Default: 320
    pub thumbnail_height: u32,   // Default: 180
}

pub struct KeyframeExtractor {
    config: KeyframeConfig,
}

impl KeyframeExtractor {
    pub fn new(config: KeyframeConfig) -> Result<Self>;

    /// Extract keyframes at specified timestamps
    pub fn extract(
        &self,
        video_path: &Path,
        timestamps_ms: &[u64],
        output_dir: &Path,
    ) -> Result<Vec<ExtractedKeyframe>>;

    /// Extract keyframes in parallel using rayon
    pub fn extract_batch(
        &self,
        video_path: &Path,
        timestamps_ms: &[u64],
        output_dir: &Path,
    ) -> Vec<Result<ExtractedKeyframe>>;
}
```

### extraction/audio.rs

```rust
pub struct AudioConfig {
    pub sample_rate: u32,    // Default: 16000 (Whisper optimal)
    pub channels: u8,        // Default: 1 (mono)
    pub format: String,      // Default: "wav"
}

pub struct AudioExtractor {
    config: AudioConfig,
}

impl AudioExtractor {
    pub fn new(config: AudioConfig) -> Self;

    /// Extract audio track to WAV file
    pub fn extract(&self, video_path: &Path, output_path: &Path) -> Result<AudioMetadata>;
}

pub struct AudioMetadata {
    pub duration_ms: u64,
    pub sample_rate: u32,
    pub channels: u8,
    pub file_size_bytes: u64,
}
```

### extraction/metadata.rs

```rust
pub struct MetadataProbe;

impl MetadataProbe {
    /// Probe video file for metadata without full decode
    pub fn probe(video_path: &Path) -> Result<VideoMetadata>;

    /// Validate video file is processable
    pub fn validate(video_path: &Path) -> Result<()>;
}
```

---

## HTTP Clients (Scene Detection & Transcription)

### clients/scene_detection.rs

```rust
pub struct SceneDetectionConfig {
    pub base_url: String,           // e.g., "http://localhost:8010"
    pub timeout_seconds: u64,       // Default: 120
    pub threshold: f32,             // Default: 27.0
    pub min_scene_len_frames: u32,  // Default: 15
    pub fallback_interval_seconds: f32, // Default: 5.0
}

pub struct SceneDetectionClient {
    client: reqwest::Client,
    config: SceneDetectionConfig,
}

impl SceneDetectionClient {
    pub fn new(config: SceneDetectionConfig) -> Self;

    /// Detect scene boundaries in video
    pub async fn detect(&self, video_path: &Path) -> Result<SceneDetectionResult>;

    /// Health check
    pub async fn health(&self) -> Result<bool>;
}

pub struct SceneDetectionResult {
    pub scenes: Vec<SceneBoundary>,
    pub total_frames: u64,
    pub fps: f32,
    pub duration_ms: u64,
    pub detection_method: String,  // "content" or "fallback"
}

// Request/Response DTOs
#[derive(Serialize)]
struct DetectRequest {
    video_path: String,
    threshold: f32,
    min_scene_len_frames: u32,
    fallback_interval_seconds: f32,
}

#[derive(Deserialize)]
struct DetectResponse {
    scenes: Vec<SceneBoundaryDto>,
    total_frames: u64,
    fps: f32,
    duration_seconds: f64,
    detection_method: String,
}
```

### clients/transcription.rs

```rust
pub struct TranscriptionConfig {
    pub base_url: String,           // e.g., "http://localhost:8011"
    pub timeout_seconds: u64,       // Default: 300 (5 min for long videos)
    pub model: String,              // Default: "base"
    pub language: Option<String>,   // None = auto-detect
}

pub struct TranscriptionClient {
    client: reqwest::Client,
    config: TranscriptionConfig,
}

impl TranscriptionClient {
    pub fn new(config: TranscriptionConfig) -> Self;

    /// Transcribe audio file
    pub async fn transcribe(&self, audio_path: &Path) -> Result<TranscriptionResult>;

    /// Health check
    pub async fn health(&self) -> Result<bool>;
}

pub struct TranscriptionResult {
    pub segments: Vec<TranscriptSegment>,
    pub language: String,
    pub duration_ms: u64,
}

// Request/Response DTOs
#[derive(Serialize)]
struct TranscribeRequest {
    audio_path: String,
    model: String,
    language: Option<String>,
}

#[derive(Deserialize)]
struct TranscribeResponse {
    segments: Vec<TranscriptSegmentDto>,
    language: String,
    duration_seconds: f64,
}
```

---

## OCR Processing (Tesseract Bindings)

### ocr/processor.rs

```rust
use tesseract::Tesseract;

pub struct OcrConfig {
    pub language: String,        // Default: "eng"
    pub min_confidence: f32,     // Default: 60.0 (0-100)
    pub preprocessing: bool,     // Default: true (grayscale, threshold)
    pub parallel_workers: usize, // Default: num_cpus
}

pub struct OcrResult {
    pub text: String,
    pub confidence: f32,
    pub word_count: usize,
}

pub struct OcrProcessor {
    config: OcrConfig,
}

impl OcrProcessor {
    pub fn new(config: OcrConfig) -> Result<Self>;

    /// Extract text from single image
    pub fn extract_text(&self, image_path: &Path) -> Result<OcrResult>;

    /// Process batch of keyframes in parallel with rayon
    pub fn process_batch(&self, keyframes: &[ExtractedKeyframe]) -> Vec<Result<OcrResult>>;
}
```

---

## Content Fusion Module

### fusion/config.rs

```rust
pub struct FusionConfig {
    pub target_chunk_duration_ms: u64,  // Default: 20_000 (20 seconds)
    pub min_chunk_duration_ms: u64,     // Default: 10_000
    pub max_chunk_duration_ms: u64,     // Default: 30_000
    pub overlap_ms: u64,                // Default: 2_000
    pub include_modality_labels: bool,  // Default: true
    pub separator: String,              // Default: "\n\n"
}

impl Default for FusionConfig {
    fn default() -> Self {
        Self {
            target_chunk_duration_ms: 20_000,
            min_chunk_duration_ms: 10_000,
            max_chunk_duration_ms: 30_000,
            overlap_ms: 2_000,
            include_modality_labels: true,
            separator: "\n\n".to_string(),
        }
    }
}
```

### fusion/types.rs

```rust
#[derive(Debug, Clone)]
pub struct VideoChunk {
    pub id: Uuid,
    pub video_id: Uuid,
    pub tenant_id: Uuid,
    pub chunk_index: u32,
    pub start_time_ms: u64,
    pub end_time_ms: u64,
    pub transcript_text: String,
    pub scene_description: String,
    pub ocr_text: String,
    pub fused_text: String,
    pub keyframe_path: Option<String>,
    pub keyframe_index: Option<u32>,
    pub source_modalities: Vec<String>,  // ["speech", "visual", "ocr"]
}

impl VideoChunk {
    pub fn duration_ms(&self) -> u64 {
        self.end_time_ms - self.start_time_ms
    }
}

pub struct KeyframeWithContent {
    pub keyframe: ExtractedKeyframe,
    pub scene_description: String,
    pub ocr_text: String,
}
```

### fusion/service.rs

```rust
pub struct ContentFusionService {
    config: FusionConfig,
}

impl ContentFusionService {
    pub fn new(config: FusionConfig) -> Self;

    /// Create fused content chunks from video components
    pub fn create_chunks(
        &self,
        video_id: Uuid,
        tenant_id: Uuid,
        duration_ms: u64,
        transcript: &[TranscriptSegment],
        keyframes: &[KeyframeWithContent],
    ) -> Vec<VideoChunk>;

    /// Generate chunk time boundaries with overlap
    fn generate_chunk_boundaries(&self, duration_ms: u64) -> Vec<(u64, u64)>;

    /// Extract transcript text within time range
    fn get_transcript_in_range(
        &self,
        segments: &[TranscriptSegment],
        start_ms: u64,
        end_ms: u64,
    ) -> String;

    /// Combine modalities into fused text
    fn fuse_modalities(&self, transcript: &str, scene: &str, ocr: &str) -> String;

    /// Deduplicate similar text entries
    fn deduplicate_text(&self, texts: &[String]) -> String;
}
```

---

## Video Qdrant Indexer

### indexer/config.rs

```rust
pub struct VideoIndexerConfig {
    pub qdrant_url: String,
    pub collection_name: String,    // Default: "video_chunks"
    pub vector_size: usize,         // Default: 384 (all-MiniLM-L6-v2)
    pub batch_size: usize,          // Default: 100
    pub timeout_seconds: u64,       // Default: 60
    pub hnsw_m: u64,                // Default: 16
    pub hnsw_ef_construct: u64,     // Default: 100
}

impl Default for VideoIndexerConfig {
    fn default() -> Self {
        Self {
            qdrant_url: "http://localhost:6333".to_string(),
            collection_name: "video_chunks".to_string(),
            vector_size: 384,
            batch_size: 100,
            timeout_seconds: 60,
            hnsw_m: 16,
            hnsw_ef_construct: 100,
        }
    }
}
```

### indexer/service.rs

```rust
use qdrant_client::prelude::*;

pub struct VideoChunkPayload {
    pub tenant_id: String,
    pub video_id: String,
    pub chunk_index: u32,
    pub start_time_ms: u64,
    pub end_time_ms: u64,
    pub fused_text: String,         // First 1000 chars for preview
    pub video_title: String,
    pub visibility: String,         // "private", "group", "public"
    pub allowed_groups: Vec<String>,
    pub source_modalities: Vec<String>,
    pub keyframe_path: Option<String>,
}

pub struct IndexResult {
    pub indexed_count: usize,
    pub collection_name: String,
    pub video_id: Uuid,
}

pub struct SearchFilters {
    pub video_id: Option<Uuid>,
    pub allowed_groups: Vec<String>,
    pub score_threshold: Option<f32>,
}

pub struct SearchHit {
    pub id: String,
    pub score: f32,
    pub payload: VideoChunkPayload,
}

pub struct VideoQdrantIndexer {
    client: QdrantClient,
    config: VideoIndexerConfig,
}

impl VideoQdrantIndexer {
    pub async fn new(config: VideoIndexerConfig) -> Result<Self>;

    /// Ensure collection exists with proper configuration
    pub async fn ensure_collection(&self) -> Result<bool>;

    /// Index video chunks with embeddings
    pub async fn index_chunks(
        &self,
        chunks: &[VideoChunk],
        embeddings: &[(Uuid, Vec<f32>)],  // (chunk_id, vector)
        video_title: &str,
        visibility: &str,
        allowed_groups: &[String],
        progress: Option<Box<dyn Fn(usize, usize, &str)>>,
    ) -> Result<IndexResult>;

    /// Delete all chunks for a video
    pub async fn delete_by_video_id(&self, video_id: Uuid) -> Result<u64>;

    /// Search for similar video chunks with ACL filtering
    pub async fn search(
        &self,
        query_vector: &[f32],
        tenant_id: Uuid,
        top_k: usize,
        filters: SearchFilters,
    ) -> Result<Vec<SearchHit>>;

    /// Health check
    pub async fn health(&self) -> Result<bool>;

    /// Get collection info
    pub async fn get_collection_info(&self) -> Result<Option<CollectionInfo>>;
}

pub struct CollectionInfo {
    pub name: String,
    pub vectors_count: u64,
    pub points_count: u64,
    pub status: String,
}
```

---

## Pipeline Orchestration

### pipeline/stages.rs

```rust
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub enum PipelineStage {
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

impl PipelineStage {
    pub fn progress_percent(&self) -> u8 {
        match self {
            Self::Validating => 5,
            Self::ExtractingAudio => 15,
            Self::Transcribing => 25,
            Self::DetectingScenes => 35,
            Self::ExtractingKeyframes => 45,
            Self::AnalyzingVision => 55,
            Self::ExtractingOcr => 65,
            Self::FusingContent => 75,
            Self::Embedding => 85,
            Self::Indexing => 95,
            Self::Completed => 100,
            Self::Failed => 0,
        }
    }
}
```

### pipeline/config.rs

```rust
pub struct PipelineConfig {
    pub scene_detection_url: String,
    pub transcription_url: String,
    pub embedding_url: String,
    pub vision_provider: String,        // "openai" or "local"
    pub enable_ocr: bool,               // Default: true
    pub scene_threshold: f32,           // Default: 27.0
    pub keyframe_interval_seconds: f32, // Default: 5.0
    pub chunk_duration_seconds: f32,    // Default: 20.0
    pub chunk_overlap_seconds: f32,     // Default: 2.0
    pub embedding_batch_size: usize,    // Default: 32
}
```

### pipeline/executor.rs

```rust
pub type ProgressCallback = Box<dyn Fn(PipelineStage, u8, &str) + Send + Sync>;

pub struct PipelineResult {
    pub video_id: Uuid,
    pub success: bool,
    pub stage: PipelineStage,
    pub error_message: Option<String>,
    pub video_metadata: Option<VideoMetadata>,
    pub transcript_segments: usize,
    pub keyframes_extracted: usize,
    pub chunks_created: usize,
    pub vectors_indexed: usize,
    pub total_duration_ms: u64,
    pub stage_times: HashMap<PipelineStage, u64>,
}

pub struct VideoPipeline {
    config: PipelineConfig,
    extractor: KeyframeExtractor,
    audio_extractor: AudioExtractor,
    scene_client: SceneDetectionClient,
    transcription_client: TranscriptionClient,
    ocr_processor: OcrProcessor,
    fusion_service: ContentFusionService,
    indexer: VideoQdrantIndexer,
    embedding_client: EmbeddingClient,  // From rag-ingestion
}

impl VideoPipeline {
    pub async fn new(config: PipelineConfig) -> Result<Self>;

    /// Process video through full pipeline
    pub async fn process(
        &self,
        video_path: &Path,
        video_id: Uuid,
        tenant_id: Uuid,
        video_title: &str,
        visibility: &str,
        allowed_groups: &[String],
        progress: Option<ProgressCallback>,
    ) -> Result<PipelineResult>;
}
```

**Parallel execution strategy:**

```
Stage 1: Validate video (sequential)
    |
    v
Stage 2-3: Extract audio + Detect scenes (parallel via tokio::join!)
    |              |
    v              v
Stage 4: Transcribe   Stage 5: Extract keyframes (rayon parallel)
    |                      |
    +----------+-----------+
               |
               v
Stage 6-7: Vision analysis + OCR (parallel batch with rayon)
               |
               v
Stage 8: Content fusion (sequential)
               |
               v
Stage 9: Generate embeddings (batched)
               |
               v
Stage 10: Index in Qdrant (batched upserts)
```

---

## Testing Strategy

### Unit Tests

```rust
#[cfg(test)]
mod tests {
    // extraction/tests.rs
    #[test]
    fn test_probe_video_metadata() {
        let metadata = MetadataProbe::probe(Path::new("tests/fixtures/sample_video.mp4")).unwrap();
        assert!(metadata.duration_ms > 0);
        assert!(metadata.width > 0);
        assert!(metadata.has_audio);
    }

    #[test]
    fn test_extract_keyframe_at_timestamp() {
        let extractor = KeyframeExtractor::new(KeyframeConfig::default()).unwrap();
        let dir = tempfile::tempdir().unwrap();
        let frames = extractor.extract(
            Path::new("tests/fixtures/sample_video.mp4"),
            &[0, 1000, 2000],
            dir.path(),
        ).unwrap();
        assert_eq!(frames.len(), 3);
    }

    // ocr/tests.rs
    #[test]
    fn test_ocr_extract_text_from_image() {
        let processor = OcrProcessor::new(OcrConfig::default()).unwrap();
        let result = processor.extract_text(Path::new("tests/fixtures/sample_keyframe.jpg")).unwrap();
        assert!(!result.text.is_empty());
    }

    #[test]
    fn test_ocr_handles_empty_image() {
        let processor = OcrProcessor::new(OcrConfig::default()).unwrap();
        let result = processor.extract_text(Path::new("tests/fixtures/blank_image.jpg")).unwrap();
        assert!(result.text.is_empty() || result.confidence < 50.0);
    }

    // fusion/tests.rs
    #[test]
    fn test_generate_chunk_boundaries_with_overlap() {
        let service = ContentFusionService::new(FusionConfig {
            target_chunk_duration_ms: 20_000,
            overlap_ms: 2_000,
            ..Default::default()
        });
        let boundaries = service.generate_chunk_boundaries(60_000);

        // 60s video with 20s chunks and 2s overlap
        assert!(boundaries.len() >= 3);
        // Check overlap
        assert!(boundaries[1].0 < boundaries[0].1);
    }

    #[test]
    fn test_fuse_modalities_with_labels() {
        let service = ContentFusionService::new(FusionConfig {
            include_modality_labels: true,
            ..Default::default()
        });
        let fused = service.fuse_modalities("Hello world", "A person speaking", "TITLE");
        assert!(fused.contains("[Speech]"));
        assert!(fused.contains("[Visual]"));
        assert!(fused.contains("[Text on screen]"));
    }
}
```

### Integration Tests

```rust
#[cfg(test)]
mod integration {
    use wiremock::{MockServer, Mock, ResponseTemplate};
    use wiremock::matchers::{method, path};

    #[tokio::test]
    async fn test_scene_detection_client_parses_response() {
        let mock_server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/detect"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "scenes": [
                    {"scene_index": 0, "start_ms": 0, "end_ms": 5000, "is_detected": true}
                ],
                "total_frames": 150,
                "fps": 30.0,
                "duration_seconds": 5.0,
                "detection_method": "content"
            })))
            .mount(&mock_server)
            .await;

        let client = SceneDetectionClient::new(SceneDetectionConfig {
            base_url: mock_server.uri(),
            ..Default::default()
        });

        let result = client.detect(Path::new("/tmp/test.mp4")).await.unwrap();
        assert_eq!(result.scenes.len(), 1);
        assert_eq!(result.detection_method, "content");
    }

    #[tokio::test]
    async fn test_transcription_client_handles_timeout() {
        let mock_server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/transcribe"))
            .respond_with(ResponseTemplate::new(200).set_delay(Duration::from_secs(10)))
            .mount(&mock_server)
            .await;

        let client = TranscriptionClient::new(TranscriptionConfig {
            base_url: mock_server.uri(),
            timeout_seconds: 1,
            ..Default::default()
        });

        let result = client.transcribe(Path::new("/tmp/test.wav")).await;
        assert!(matches!(result, Err(VideoError::Timeout(_))));
    }

    #[tokio::test]
    async fn test_indexer_upserts_to_qdrant() {
        use testcontainers::{clients, images::qdrant::Qdrant};

        let docker = clients::Cli::default();
        let qdrant = docker.run(Qdrant::default());
        let port = qdrant.get_host_port_ipv4(6334);

        let indexer = VideoQdrantIndexer::new(VideoIndexerConfig {
            qdrant_url: format!("http://localhost:{}", port),
            ..Default::default()
        }).await.unwrap();

        indexer.ensure_collection().await.unwrap();

        let chunk = VideoChunk {
            id: Uuid::new_v4(),
            video_id: Uuid::new_v4(),
            tenant_id: Uuid::new_v4(),
            chunk_index: 0,
            start_time_ms: 0,
            end_time_ms: 20_000,
            fused_text: "Test content".to_string(),
            ..Default::default()
        };

        let embedding = vec![0.1f32; 384];

        let result = indexer.index_chunks(
            &[chunk.clone()],
            &[(chunk.id, embedding)],
            "Test Video",
            "private",
            &[],
            None,
        ).await.unwrap();

        assert_eq!(result.indexed_count, 1);
    }
}
```

### Test Fixtures

Located in `tests/fixtures/`:
- `sample_video.mp4` - 5-second test video with audio
- `sample_keyframe.jpg` - Keyframe image with text for OCR
- `blank_image.jpg` - Empty image for edge case testing
- `transcript_response.json` - Mock transcription API response
- `scene_detection_response.json` - Mock scene detection API response

### CI Configuration

```yaml
# .github/workflows/video-tests.yml
- name: Install FFmpeg
  run: sudo apt-get install -y ffmpeg libavcodec-dev libavformat-dev

- name: Install Tesseract
  run: sudo apt-get install -y tesseract-ocr libtesseract-dev

- name: Run tests
  run: cargo test -p rag-video

- name: Run integration tests (slow)
  run: cargo test -p rag-video --test integration -- --ignored
```

---

## Python Microservices (Existing)

The following Python services need HTTP API endpoints:

### Scene Detection Service (port 8010)

```python
# POST /detect
# Request: { "video_path": str, "threshold": float, "min_scene_len_frames": int, "fallback_interval_seconds": float }
# Response: { "scenes": [...], "total_frames": int, "fps": float, "duration_seconds": float, "detection_method": str }

# GET /health
# Response: { "status": "healthy" }
```

### Transcription Service (port 8011)

```python
# POST /transcribe
# Request: { "audio_path": str, "model": str, "language": str | null }
# Response: { "segments": [...], "language": str, "duration_seconds": float }

# GET /health
# Response: { "status": "healthy" }
```

These services wrap the existing `SceneDetector` and `WhisperTranscriber` classes with FastAPI endpoints.

---

## Implementation Order

1. **P3.5.1** - Core types and error handling (`error.rs`, common types)
2. **P3.5.2** - Extraction module (FFmpeg bindings for keyframe, audio, metadata)
3. **P3.5.3** - HTTP clients (scene detection, transcription)
4. **P3.5.4** - OCR processor (Tesseract bindings)
5. **P3.5.5** - Content fusion service
6. **P3.5.6** - Video Qdrant indexer
7. **P3.5.7** - Pipeline orchestrator

Each task follows TDD: write failing test → implement → verify → commit.
