# Epic 9: Video RAG Pipeline - Implementation Plan

> **Epic:** Video RAG Pipeline
> **Total Estimated Effort:** 3-4 weeks
> **Dependencies:** Epic 2 (Ingestion Service), Epic 3 (Retrieval Service), Epic 1 (Infrastructure)

## Executive Summary

This implementation plan details the deployment of a production-grade Video RAG Pipeline comprising video upload/processing, multi-modal content extraction (speech, vision, OCR), content fusion, embedding/indexing, video retrieval with timeline responses, on-demand clip generation, and a complete video management API. The plan is structured in 4 waves with clear checkpoints and integration tests.

---

## Implementation Waves

### Wave 1: Foundation (Parallel after DB/Storage setup)

**Duration:** 4-5 days
**User Stories:** US-9.1, US-9.2, US-9.3 (US-9.2 and US-9.3 can run in parallel after US-9.1 foundation)

#### Agent 1: Video Upload Infrastructure (US-9.1)

**Goal:** Establish video upload endpoint, storage, validation, and processing pipeline foundation

**Tasks:**

1. Create database migrations
   - `source_videos` table with all fields (id, tenant_id, filename, title, description, duration_seconds, width, height, fps, codec, file_size_bytes, storage_path, thumbnail_path, status enum, processing_stage, processing_progress, error_message, visibility, allowed_groups, processing_options JSONB, created_at, uploaded_at, processed_at)
   - `video_transcripts` table (id, video_id, segment_index, start_ms, end_ms, text, words_json, language, confidence)
   - `video_keyframes` table (id, video_id, frame_index, timestamp_ms, storage_path, thumbnail_path, scene_description, ocr_text, is_scene_boundary)
   - Add indexes for tenant_id, status, content_hash
   - Add foreign key constraints with ON DELETE CASCADE

2. Create MinIO storage structure
   ```
   videos/
   ├── {tenant_id}/
   │   ├── originals/{video_id}.mp4
   │   ├── audio/{video_id}.wav
   │   ├── keyframes/{video_id}/{index}.jpg
   │   ├── thumbnails/{video_id}/{index}_thumb.jpg
   │   └── clips/{video_id}/{start_ms}_{end_ms}.mp4
   ```

3. Implement VideoValidator service
   ```
   services/ingestion/processors/video/
   ├── validator.py          # VideoValidator class
   ├── metadata.py           # VideoMetadata dataclass
   └── exceptions.py         # VideoValidationError
   ```
   - Validate using FFprobe: duration (10s-3600s), codec support, file size
   - Extract metadata: resolution, fps, codec, has_audio, bitrate
   - Compute content hash (SHA-256) for deduplication

4. Implement VideoStorage service
   ```
   services/ingestion/processors/video/
   └── storage.py            # VideoStorage class
   ```
   - Upload to MinIO with correct content types
   - Generate presigned URLs for streaming (4-hour expiry)
   - Download for processing

5. Create Upload API endpoint
   ```
   services/ingestion/api/routes/
   └── video.py              # Video upload routes
   ```
   - `POST /api/v1/videos/upload` - multipart file upload
   - `POST /api/v1/videos/upload-url` - presigned upload URL
   - `GET /api/v1/videos/{id}/status` - processing status
   - Request validation, VideoValidator check
   - Store in MinIO, create DB record with status="uploaded"
   - Queue Celery task, return video_id and job_id

6. Implement VideoProcessingPipeline orchestrator
   ```
   services/ingestion/processors/video/
   └── pipeline.py           # VideoProcessingPipeline class
   ```
   - Orchestrate all processing stages
   - Progress tracking with database updates
   - Error handling with stage-specific recovery
   - Support partial reprocessing

7. Create Celery task for video processing
   ```
   services/ingestion/tasks/
   └── video_ingest.py       # process_video task
   ```
   - `process_video.delay(video_id, tenant_id, options)`
   - Call pipeline stages in sequence
   - Update status on completion/failure

**Exit Criteria:**
- [ ] Video upload stores file in MinIO
- [ ] Database records created with metadata
- [ ] Celery task queued and trackable
- [ ] Status endpoint returns processing progress
- [ ] Content hash deduplication working
- [ ] Validation rejects invalid videos

---

#### Agent 2: Audio Extraction & Transcription (US-9.2)

**Goal:** Extract audio and transcribe using faster-whisper with word-level timestamps

**Tasks:**

1. Implement AudioExtractor service
   ```
   services/ingestion/processors/video/
   └── audio_extractor.py    # AudioExtractor class
   ```
   - Extract audio track using FFmpeg subprocess
   - Output: WAV format, 16kHz, mono (Whisper requirements)
   - Store in MinIO: `videos/{tenant_id}/audio/{video_id}.wav`
   - Return None if no audio track present

2. Implement WhisperTranscriber service
   ```
   services/ingestion/processors/video/
   └── transcription.py      # WhisperTranscriber class
   ```
   - Use faster-whisper library
   - Support models: tiny, base, small, medium, large-v3
   - VAD filtering for silence removal
   - Word-level timestamp extraction
   - Language auto-detection with fallback to specified language
   - Configurable via environment: WHISPER_MODEL, WHISPER_DEVICE

3. Implement TranscriptStorage service
   ```
   services/ingestion/processors/video/
   └── transcript_storage.py # TranscriptStorage class
   ```
   - Store segments in `video_transcripts` table
   - Include: start_ms, end_ms, text, words_json (word-level timing)
   - Upsert handling for reprocessing
   - Batch insert for efficiency

4. Create TranscriptSegment data model
   ```python
   @dataclass
   class TranscriptSegment:
       segment_index: int
       start_ms: int
       end_ms: int
       text: str
       words: list[dict]  # [{"word": str, "start": float, "end": float}]
       language: str
       confidence: float
   ```

5. Pipeline integration
   - `_run_transcription_stage()` method in VideoProcessingPipeline
   - Progress updates during long transcriptions
   - Handle videos without audio gracefully (skip stage)
   - Store detected language in video record

**Exit Criteria:**
- [ ] Audio extracted to correct format (16kHz WAV mono)
- [ ] Transcription produces accurate text
- [ ] Word-level timestamps available
- [ ] Language detection working
- [ ] Segments stored in database
- [ ] Videos without audio handled gracefully

---

#### Agent 3: Scene Detection & Keyframe Extraction (US-9.3)

**Goal:** Detect scene boundaries and extract representative keyframes

**Tasks:**

1. Implement SceneDetector service
   ```
   services/ingestion/processors/video/
   └── scene_detection.py    # SceneDetector class
   ```
   - Use PySceneDetect library
   - ContentDetector for cuts/fades (threshold=27.0 default)
   - Configurable min_scene_len (default 15 frames)
   - Interval-based fallback (every 5 seconds) for static videos
   - Return list of scene boundaries with timestamps

2. Implement KeyframeExtractor service
   ```
   services/ingestion/processors/video/
   └── keyframe_extractor.py # KeyframeExtractor class
   ```
   - Extract frames at scene boundaries using FFmpeg
   - Extract frames at intervals for scenes longer than threshold
   - Output format: JPEG, 1280x720 max (preserve aspect ratio)
   - Generate thumbnails: 320x180 for UI previews
   - Batch processing with configurable concurrency

3. Implement KeyframeStorage service
   ```
   services/ingestion/processors/video/
   └── keyframe_storage.py   # KeyframeStorage class
   ```
   - Upload to MinIO: `keyframes/{video_id}/{index:05d}.jpg`
   - Upload thumbnails: `thumbnails/{video_id}/{index:05d}_thumb.jpg`
   - Store records in `video_keyframes` table
   - Generate video thumbnail from first keyframe

4. Create ExtractedKeyframe data model
   ```python
   @dataclass
   class ExtractedKeyframe:
       frame_index: int
       timestamp_ms: int
       image_path: Path  # Local temp path
       is_scene_boundary: bool
       scene_index: int | None
   ```

5. Pipeline integration
   - `_run_scene_detection_stage()` method
   - Return keyframes for subsequent visual analysis stages
   - Update video record with keyframe count

**Exit Criteria:**
- [ ] Scene boundaries detected accurately
- [ ] Keyframes extracted at all boundaries
- [ ] Interval fallback for static videos (every 5s)
- [ ] Thumbnails generated (320x180)
- [ ] All images stored in MinIO
- [ ] Records stored in database

---

### Wave 1 Checkpoint

**Integration Test:** `tests/integration/test_wave1_video_foundation.py`

```python
# Verify:
# 1. Video upload creates DB record and MinIO file
# 2. Audio extraction produces valid WAV (16kHz, mono)
# 3. Transcription returns segments with timestamps
# 4. Scene detection finds boundaries
# 5. Keyframes extracted and stored in MinIO
# 6. Pipeline orchestrates all stages with progress updates
# 7. Status endpoint reflects current processing stage
# 8. Error handling stores error_message in DB
```

---

### Wave 2: Content Analysis (Parallel)

**Duration:** 4-5 days
**User Stories:** US-9.4, US-9.5, US-9.6
**Dependencies:** Wave 1 completed (keyframes available)
**Parallelization:** US-9.4 and US-9.5 can run concurrently

#### Agent 4: Visual Scene Understanding (US-9.4)

**Goal:** Generate text descriptions of keyframes using Vision LLMs

**Tasks:**

1. Create Vision LLM provider abstraction
   ```
   services/ingestion/processors/video/vision/
   ├── __init__.py
   ├── base.py               # VisionLLMProvider ABC
   ├── openai_provider.py    # OpenAIVisionProvider (GPT-4V/GPT-4o)
   ├── anthropic_provider.py # AnthropicVisionProvider (Claude)
   ├── ollama_provider.py    # OllamaVisionProvider (LLaVA, Qwen-VL)
   └── models.py             # VisionAnalysisResult dataclass
   ```

2. Implement VisionAnalyzer service
   ```
   services/ingestion/processors/video/
   └── vision_analyzer.py    # VisionAnalyzer class
   ```
   - Orchestrate batch analysis of keyframes
   - Rate limiting with configurable RPM (requests per minute)
   - Retry logic with exponential backoff (3 retries, 2x backoff)
   - Concurrent processing with asyncio.Semaphore (default 5)
   - Progress callback for pipeline updates

3. Create scene analysis prompt
   ```python
   SCENE_ANALYSIS_PROMPT = """
   Analyze this video frame and provide:
   1. A concise description of the scene (2-3 sentences)
   2. Key objects visible
   3. Any actions or events occurring
   4. The type of scene (presentation, outdoor, interview, etc.)

   Focus on details useful for search and retrieval.
   """
   ```

4. Implement response caching
   ```
   services/ingestion/processors/video/
   └── vision_cache.py       # VisionResponseCache class
   ```
   - Cache by image content hash (SHA-256)
   - Redis-backed with configurable TTL (24 hours default)
   - Avoid re-analyzing identical frames
   - Reduce API costs on reprocessing

5. Pipeline integration
   - `_run_visual_analysis_stage()` method
   - Progress callback during batch processing
   - Update `video_keyframes.scene_description` field
   - Skip frames that have cached descriptions

**Exit Criteria:**
- [ ] OpenAI GPT-4V integration working
- [ ] Anthropic Claude Vision working (optional)
- [ ] Ollama local model working (for dev)
- [ ] Rate limiting prevents API throttling
- [ ] Caching reduces redundant API calls
- [ ] Descriptions stored per keyframe
- [ ] Latency < 3s per frame average

---

#### Agent 5: OCR Text Extraction (US-9.5)

**Goal:** Extract on-screen text from keyframes using OCR

**Tasks:**

1. Implement OCR engine abstraction
   ```
   services/ingestion/processors/video/ocr/
   ├── __init__.py
   ├── base.py               # OCREngine ABC
   ├── tesseract.py          # TesseractOCR class
   └── models.py             # OCRResult, TextRegion dataclasses
   ```

2. Implement image preprocessing
   ```
   services/ingestion/processors/video/ocr/
   └── preprocessing.py      # ImagePreprocessor class
   ```
   - Convert to grayscale
   - Contrast enhancement (CLAHE)
   - Sharpening for better OCR
   - Resize if needed (min 300 DPI equivalent)

3. Implement OCRBatchProcessor
   ```
   services/ingestion/processors/video/
   └── ocr_processor.py      # OCRBatchProcessor class
   ```
   - Parallel processing with ThreadPoolExecutor
   - Bounding box extraction for text regions
   - Confidence threshold filtering (default 60%)
   - Text deduplication across frames (remove watermarks, persistent UI)

4. Create OCRResult data model
   ```python
   @dataclass
   class TextRegion:
       text: str
       confidence: float
       bbox: tuple[int, int, int, int]  # x, y, width, height

   @dataclass
   class OCRResult:
       success: bool
       full_text: str
       regions: list[TextRegion]
       processing_time_ms: float
       error: str | None = None
   ```

5. Pipeline integration
   - `_run_ocr_stage()` method
   - Update `video_keyframes.ocr_text` field
   - Handle frames with no text gracefully (empty string)
   - Deduplicate repeated text across consecutive frames

**Exit Criteria:**
- [ ] Tesseract extracting text accurately
- [ ] Bounding boxes available for regions
- [ ] Low-confidence text filtered (< 60%)
- [ ] Repeated text (watermarks) deduplicated
- [ ] Results stored in database
- [ ] Latency < 500ms per frame

---

#### Agent 6: Multi-Modal Content Fusion (US-9.6)

**Goal:** Combine transcript, scene descriptions, and OCR into searchable chunks

**Tasks:**

1. Create database migration for video_chunks table
   ```sql
   CREATE TABLE video_chunks (
       id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
       video_id UUID NOT NULL REFERENCES source_videos(id) ON DELETE CASCADE,
       chunk_index INTEGER NOT NULL,
       start_time_ms INTEGER NOT NULL,
       end_time_ms INTEGER NOT NULL,
       transcript_text TEXT,
       scene_description TEXT,
       ocr_text TEXT,
       fused_text TEXT NOT NULL,
       keyframe_path VARCHAR(1000),
       source_modalities TEXT[],
       embedding_id VARCHAR(100),
       created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
       UNIQUE(video_id, chunk_index)
   );

   CREATE INDEX idx_video_chunks_video ON video_chunks(video_id);
   CREATE INDEX idx_video_chunks_time ON video_chunks(video_id, start_time_ms);
   CREATE INDEX idx_video_chunks_fused_text_gin ON video_chunks
       USING gin(to_tsvector('english', fused_text));
   ```

2. Implement FusionConfig and VideoChunk models
   ```
   services/ingestion/processors/video/
   └── fusion.py             # FusionConfig, VideoChunk dataclasses
   ```
   ```python
   @dataclass
   class FusionConfig:
       target_chunk_duration_ms: int = 20_000  # 20 seconds
       min_chunk_duration_ms: int = 10_000     # 10 seconds
       max_chunk_duration_ms: int = 30_000     # 30 seconds
       overlap_ms: int = 2_000                 # 2 second overlap
       include_modality_labels: bool = True
       separator: str = "\n\n"
   ```

3. Implement ContentFusionService
   ```
   services/ingestion/processors/video/
   └── content_fusion.py     # ContentFusionService class
   ```
   - Generate time-based chunk boundaries with overlap
   - Align transcript segments to chunk time ranges
   - Align keyframe content (scene + OCR) to chunks
   - Deduplicate repeated scene descriptions within chunk
   - Deduplicate OCR text within chunk

4. Implement fused text generation
   ```python
   def _generate_fused_text(self, transcript: str, scene: str, ocr: str) -> str:
       parts = []
       if transcript:
           parts.append(f"[Speech] {transcript}")
       if scene:
           parts.append(f"[Visual] {scene}")
       if ocr:
           parts.append(f"[Text on screen] {ocr}")
       return self.config.separator.join(parts)
   ```

5. Implement VideoChunkStorage
   ```
   services/ingestion/processors/video/
   └── chunk_storage.py      # VideoChunkStorage class
   ```
   - Store chunks in `video_chunks` table
   - Upsert handling for reprocessing
   - Track source modalities per chunk
   - Batch insert for efficiency

6. Pipeline integration
   - `_run_fusion_stage()` method
   - Update video record with chunk_count
   - Return chunks for embedding stage

**Exit Criteria:**
- [ ] Chunks created with correct time boundaries
- [ ] Transcript aligned to chunks
- [ ] Keyframe content aligned to chunks
- [ ] Duplicate content deduplicated
- [ ] Fused text generated with all modalities
- [ ] Missing modalities handled gracefully
- [ ] Chunks stored in PostgreSQL
- [ ] Source modalities tracked per chunk

---

### Wave 2 Checkpoint

**Integration Test:** `tests/integration/test_wave2_content_analysis.py`

```python
# Verify:
# 1. Vision LLM produces scene descriptions for keyframes
# 2. OCR extracts on-screen text accurately
# 3. Content fusion creates chunks with correct time boundaries
# 4. Fused text combines [Speech] + [Visual] + [Text on screen]
# 5. Chunk boundaries align with overlap
# 6. Missing modalities don't break fusion (graceful handling)
# 7. Deduplication removes repeated content
# 8. All data persisted to database
```

---

### Wave 3: Indexing & Retrieval

**Duration:** 3-4 days
**User Stories:** US-9.7, US-9.8
**Dependencies:** Wave 2 completed (video chunks with fused_text available)

#### Agent 7: Video Chunk Embedding & Indexing (US-9.7)

**Goal:** Embed video chunks and index in Qdrant + OpenSearch for hybrid search

**Tasks:**

1. Implement VideoChunkEmbedder
   ```
   services/ingestion/processors/video/
   └── embedding.py          # VideoChunkEmbedder class
   ```
   - Use existing embedding service (BGE-large-en-v1.5)
   - Batch processing (32 per batch)
   - Documents embedded WITHOUT instruction prefix
   - Progress callback for long videos
   - Return ChunkEmbedding objects with vectors

2. Implement QdrantVideoIndexer
   ```
   services/ingestion/processors/video/
   └── qdrant_indexer.py     # QdrantVideoIndexer class
   ```
   - Create `video_chunks` collection if not exists
   - Vector size: 1024, distance: Cosine
   - HNSW config: m=16, ef_construct=100
   - Payload indexes: tenant_id, video_id, allowed_groups
   - Upsert points in batches of 100
   - Delete by video_id filter

3. Implement OpenSearchVideoIndexer
   ```
   services/ingestion/processors/video/
   └── opensearch_indexer.py # OpenSearchVideoIndexer class
   ```
   - Create `video_chunks` index with mappings
   - Searchable text fields: fused_text, transcript_text, scene_description, ocr_text
   - Filter fields: tenant_id, video_id, visibility, allowed_groups
   - Bulk index with error handling
   - Delete by video_id query

4. Define Qdrant collection schema
   ```yaml
   Collection: video_chunks
   Vector:
     size: 1024
     distance: Cosine
   Payload Schema:
     tenant_id: keyword (indexed)
     video_id: keyword (indexed)
     chunk_index: integer
     start_time_ms: integer
     end_time_ms: integer
     fused_text: text (first 1000 chars)
     video_title: text
     visibility: keyword
     allowed_groups: keyword[] (indexed)
     created_at: datetime
   HNSW Config:
     m: 16
     ef_construct: 100
   ```

5. Define OpenSearch index mapping
   ```json
   {
     "mappings": {
       "properties": {
         "chunk_id": {"type": "keyword"},
         "video_id": {"type": "keyword"},
         "tenant_id": {"type": "keyword"},
         "chunk_index": {"type": "integer"},
         "start_time_ms": {"type": "integer"},
         "end_time_ms": {"type": "integer"},
         "fused_text": {"type": "text", "analyzer": "standard"},
         "transcript_text": {"type": "text", "analyzer": "standard"},
         "scene_description": {"type": "text", "analyzer": "standard"},
         "ocr_text": {"type": "text", "analyzer": "standard"},
         "video_title": {"type": "text"},
         "visibility": {"type": "keyword"},
         "allowed_groups": {"type": "keyword"},
         "created_at": {"type": "date"}
       }
     }
   }
   ```

6. Pipeline integration
   - `_run_embedding_indexing_stage()` method
   - Index in both Qdrant and OpenSearch
   - Update chunk records with embedding_id
   - Handle partial failures gracefully

**Exit Criteria:**
- [ ] BGE-large embeddings generated (1024 dims)
- [ ] Qdrant collection created with correct schema
- [ ] OpenSearch index created with correct mappings
- [ ] Chunks indexed in both stores
- [ ] ACL fields included in payloads
- [ ] Embedding IDs stored in PostgreSQL
- [ ] Delete cascade works correctly

---

#### Agent 8: Video Retrieval with Timeline Response (US-9.8)

**Goal:** Implement hybrid search endpoint returning grouped timeline results

**Tasks:**

1. Implement VideoRetriever service
   ```
   services/retrieval/video/
   ├── __init__.py
   ├── retriever.py          # VideoRetriever class
   ├── models.py             # RetrievalMetrics, RetrievalResult
   └── exceptions.py         # VideoRetrievalError
   ```
   - Orchestrate search pipeline
   - Support modes: hybrid, semantic, keyword
   - Query embedding with BGE instruction prefix

2. Implement semantic search (Qdrant)
   - `_semantic_search()` method
   - ACL filtering (tenant_id + visibility + allowed_groups)
   - Optional video_id filter for single-video search
   - Return top-K with cosine similarity scores

3. Implement keyword search (OpenSearch)
   - `_keyword_search()` method
   - Multi-match across fused_text, transcript, scene, OCR fields
   - Field boosting: fused_text^3, transcript^2, scene^1, ocr^1
   - ACL filtering in query DSL
   - Normalize scores to 0-1 range

4. Implement RRF fusion
   - `_rrf_fusion()` method
   - Configurable weights (default: semantic=0.7, keyword=0.3)
   - k=60 constant
   - Merge scores and metadata from both sources
   - Preserve individual scores for debugging

5. Implement reranking
   - `_rerank()` method using existing reranker service
   - Rerank top-50, return top-K
   - Cross-encoder scoring on fused_text
   - Add rerank_score to results

6. Implement result grouping and formatting
   - `_group_and_format()` method
   - Group by video_id
   - Sort matches by timestamp within each video
   - Limit matches per video (configurable, default 10)
   - Generate keyframe URLs and clip URLs
   - Calculate video-level scores (max, avg relevance)

7. Create API endpoint
   ```
   services/retrieval/api/routes/
   └── video_retrieve.py     # Video retrieval routes
   ```
   - `POST /api/v1/retrieve/video`
   - Request: query, mode, top_k, weights, rerank flag, filters
   - Response: VideoTimelineResponse with grouped results
   - Include timing metrics for all stages

8. Create request/response schemas
   ```
   services/retrieval/api/schemas/
   └── video_retrieve.py     # Pydantic models
   ```
   - VideoRetrieveRequest (query, mode, top_k, weights, filters)
   - VideoMatch (chunk_id, timestamps, scores, preview, URLs)
   - VideoResult (video metadata, list of matches)
   - VideoTimelineResponse (query, videos, metrics)
   - VideoSearchMetrics (timing for each stage)

**Exit Criteria:**
- [ ] `/api/v1/retrieve/video` endpoint working
- [ ] Hybrid search combining semantic + keyword
- [ ] RRF fusion producing ranked results
- [ ] Reranking improving relevance
- [ ] Results grouped by video
- [ ] Timestamps sorted within videos
- [ ] Clip URLs included in response
- [ ] ACL filtering enforced
- [ ] Metrics tracking all stages
- [ ] p95 latency < 300ms

---

### Wave 3 Checkpoint

**Integration Test:** `tests/integration/test_wave3_indexing_retrieval.py`

```python
# Verify:
# 1. Embeddings generated for all chunks (1024 dims)
# 2. Qdrant semantic search returns relevant results
# 3. OpenSearch keyword search returns relevant results
# 4. RRF fusion combines both result sets correctly
# 5. Reranking improves result ordering
# 6. Results grouped by video correctly
# 7. ACL filters exclude unauthorized content
# 8. Timeline response format matches schema
# 9. Clip URLs generated correctly
# 10. Timing metrics recorded for all stages
```

**Performance Validation:**

| Metric | Target |
|--------|--------|
| Query embedding | <20ms |
| Semantic search | <50ms |
| Keyword search | <30ms |
| Reranking | <150ms |
| Total E2E | <300ms (p95) |

---

### Wave 4: User-Facing Features (Parallel)

**Duration:** 3-4 days
**User Stories:** US-9.9, US-9.10
**Dependencies:** Wave 3 completed (retrieval working)
**Parallelization:** US-9.9 and US-9.10 can run concurrently

#### Agent 9: On-Demand Video Clip Generation (US-9.9)

**Goal:** Generate and cache video clips for retrieved moments

**Tasks:**

1. Implement ClipGenerator service
   ```
   services/retrieval/video/
   └── clip_generator.py     # ClipGenerator class
   ```
   - FFmpeg subprocess for clip cutting
   - Stream copy mode (fast, no re-encode) as primary
   - Re-encode fallback for precise cuts
   - Configurable padding (default 2s before/after)
   - Max duration limit (120s default)
   - Timeout handling (300s max)

2. Implement ClipCacheService
   ```
   services/retrieval/video/
   └── clip_cache.py         # ClipCacheService class
   ```
   - Cache key: `videos/{tenant_id}/clips/{video_id}/{start_ms}_{end_ms}.mp4`
   - Check cache before generation (MinIO stat)
   - TTL-based expiration (24 hours)
   - Presigned URL generation (4-hour expiry)
   - Track cache size for monitoring

3. Create Clip API endpoint
   ```
   services/retrieval/api/routes/
   └── clips.py              # Clip routes
   ```
   - `GET /api/v1/videos/{video_id}/clip?start={ms}&end={ms}`
   - Verify video access (tenant_id + ACL check)
   - Check cache first
   - Generate if not cached, store in cache
   - Return 302 redirect to presigned URL
   - Include Cache-Control headers

4. Create full video streaming endpoint
   - `GET /api/v1/videos/{video_id}/stream`
   - Return presigned URL for original video
   - Support for range requests via MinIO

5. Implement cache cleanup Celery task
   ```
   services/retrieval/tasks/
   └── clip_cleanup.py       # cleanup_expired_clips task
   ```
   - Celery beat schedule: every 6 hours
   - Delete clips older than TTL
   - Track deletion metrics

6. Create ClipConfig
   ```python
   @dataclass
   class ClipConfig:
       padding_seconds: float = 2.0
       max_duration_seconds: float = 120.0
       output_format: str = "mp4"
       video_codec: str = "libx264"
       audio_codec: str = "aac"
       crf: int = 23
       preset: str = "fast"
       use_stream_copy: bool = True
       cache_ttl_hours: int = 24
   ```

**Exit Criteria:**
- [ ] Clip endpoint returns presigned URLs (302 redirect)
- [ ] Cache check before generation
- [ ] FFmpeg stream copy working (fast)
- [ ] Re-encode fallback working (precise)
- [ ] Clips cached in MinIO
- [ ] Cache cleanup task scheduled (every 6h)
- [ ] Padding applied correctly (2s default)
- [ ] Max duration enforced (120s)
- [ ] ACL verified before generation

---

#### Agent 10: Video Management API (US-9.10)

**Goal:** Complete CRUD API for video library management

**Tasks:**

1. Implement List Videos endpoint
   ```
   services/ingestion/api/routes/video_management.py
   ```
   - `GET /api/v1/videos`
   - Pagination: page, page_size (max 100)
   - Filtering: status, search (title/description)
   - Sorting: created_at, title, duration (asc/desc)
   - Return VideoListResponse with total count

2. Implement Get Video Details endpoint
   - `GET /api/v1/videos/{video_id}`
   - Full metadata including processing status
   - Chunk count from database
   - Thumbnail URL and stream URL (presigned)
   - Return VideoDetailResponse

3. Implement Update Video endpoint
   - `PATCH /api/v1/videos/{video_id}`
   - Updatable fields: title, description, visibility, allowed_groups, tags
   - Return updated VideoResponse

4. Implement Delete Video endpoint
   - `DELETE /api/v1/videos/{video_id}`
   - Cascade delete order:
     1. Delete vectors from Qdrant (video_chunks collection)
     2. Delete documents from OpenSearch (video_chunks index)
     3. Delete chunk records from PostgreSQL (CASCADE handles this)
     4. Delete video record from PostgreSQL
     5. Delete files from MinIO (original, keyframes, clips)
   - Return deletion summary with counts

5. Implement Get Video Chunks endpoint
   - `GET /api/v1/videos/{video_id}/chunks`
   - Paginated list of chunks
   - Include timestamps, fused_text preview (500 chars), modalities
   - Return list of VideoChunkResponse

6. Implement Get Keyframe endpoint
   - `GET /api/v1/videos/{video_id}/keyframes/{frame_index}`
   - Optional `thumbnail=true` query param
   - Return 302 redirect to presigned URL

7. Implement Reprocess Video endpoint
   - `POST /api/v1/videos/{video_id}/reprocess`
   - Clear existing chunks and keyframes
   - Reset status to "processing"
   - Re-queue Celery task
   - Return VideoResponse

8. Extend VideoService
   ```
   services/ingestion/services/
   └── video_service.py      # VideoService class extensions
   ```
   - `list_videos()` with filters, pagination, sorting
   - `update_video()` for metadata updates
   - `get_chunk_count()` for detail response
   - `reprocess_video()` clearing and re-queueing

9. Extend StorageService
   ```
   services/ingestion/services/
   └── storage_service.py    # StorageService extensions
   ```
   - `delete_video_files()` removing all associated MinIO files
   - Handle missing files gracefully (log warning, continue)

10. Create request/response schemas
    ```
    services/ingestion/api/schemas/
    └── video_management.py   # Pydantic models
    ```
    - VideoUpdateRequest
    - VideoResponse, VideoDetailResponse
    - VideoListResponse (with pagination metadata)
    - VideoDeleteResponse (with deletion counts)
    - VideoChunkResponse

**Exit Criteria:**
- [ ] List endpoint with pagination, filtering, sorting
- [ ] Detail endpoint with full metadata
- [ ] Update endpoint for editable fields
- [ ] Delete endpoint with cascade to all stores
- [ ] Chunks endpoint with timestamps
- [ ] Keyframe endpoint with presigned URLs
- [ ] Reprocess endpoint for failed videos
- [ ] Tenant isolation enforced on all endpoints
- [ ] ACL checked for group-visibility videos
- [ ] >90% test coverage

---

### Wave 4 Checkpoint

**Integration Test:** `tests/integration/test_wave4_user_facing.py`

```python
# Verify:
# 1. Clip generation produces valid video file
# 2. Clips cached and reused on subsequent requests
# 3. List videos returns paginated, filtered results
# 4. Get video returns full metadata with URLs
# 5. Update video persists changes
# 6. Delete video cascades to all stores (Qdrant, OpenSearch, PostgreSQL, MinIO)
# 7. Get chunks returns correct timeline data
# 8. Keyframe URLs work correctly
# 9. Tenant isolation enforced (404 for other tenant's videos)
# 10. Reprocess clears old data and re-queues
```

---

## Final Integration & Documentation

### End-to-End Test Suite

**File:** `tests/e2e/test_video_rag_pipeline.py`

```python
# Full E2E test covering:
# 1. Upload video via API
# 2. Poll status until processing complete
# 3. Verify chunks created in database
# 4. Verify vectors in Qdrant
# 5. Verify documents in OpenSearch
# 6. Query via /retrieve/video endpoint
# 7. Verify timeline response format
# 8. Request clip generation
# 9. Verify clip URL works
# 10. Delete video and verify cascade
```

### Performance Validation

| Metric | Target | Test Method |
|--------|--------|-------------|
| Video upload (100MB) | <30s | Upload timing |
| Audio extraction | <0.5x realtime | FFmpeg benchmark |
| Transcription | <0.3x realtime | Whisper benchmark |
| Scene detection | <0.2x realtime | PySceneDetect benchmark |
| Vision analysis | <3s/frame | API timing |
| OCR extraction | <500ms/frame | Tesseract benchmark |
| Embedding (32 chunks) | <500ms | Batch timing |
| Retrieval E2E | <300ms (p95) | Load test |
| Clip generation | <5s (stream copy) | FFmpeg benchmark |

### Load Testing

```bash
# Run load test against video retrieval
locust -f tests/load/video_locustfile.py --host http://retrieval:8002

# Target: 50 concurrent users
# Duration: 10 minutes
# Success criteria: <1% error rate, p95 < 500ms
```

---

## Documentation Updates

### Required Documentation Changes

After implementation is complete, update the following documentation:

1. **`docs/architecture.md`**
   - Add Video Processing section under Service Architecture
   - Add Video RAG Pipeline data flow diagram
   - Add video_chunks to Data Schemas section
   - Add video retrieval endpoint to API Contracts
   - Update Technology Stack with new dependencies (faster-whisper, PySceneDetect, etc.)

2. **`README.md`**
   - Add Video RAG to Key Capabilities section
   - Add video endpoints to API Reference
   - Add video-specific performance targets
   - Update Getting Started with video-specific setup

3. **New Documentation Files**
   - `docs/video-rag/README.md` - Video RAG Pipeline overview
   - `docs/video-rag/processing-pipeline.md` - Detailed processing stages
   - `docs/video-rag/api-reference.md` - Video API documentation
   - `docs/video-rag/configuration.md` - Configuration options

---

## Deployment Checklist

### Pre-deployment

- [ ] FFmpeg installed in Docker images (apt-get install ffmpeg)
- [ ] Tesseract OCR installed (apt-get install tesseract-ocr tesseract-ocr-eng)
- [ ] faster-whisper model downloaded or accessible
- [ ] Vision LLM API keys configured (OpenAI/Anthropic)
- [ ] MinIO buckets created with correct permissions
- [ ] PostgreSQL migrations applied
- [ ] Qdrant video_chunks collection created
- [ ] OpenSearch video_chunks index created

### Wave 1 Deployment

- [ ] Apply database migrations
- [ ] Deploy ingestion service with video processing
- [ ] Verify video upload endpoint
- [ ] Test transcription pipeline
- [ ] Test scene detection pipeline
- [ ] Run Wave 1 integration tests

### Wave 2 Deployment

- [ ] Configure Vision LLM provider
- [ ] Deploy with OCR support
- [ ] Verify vision analysis
- [ ] Verify OCR extraction
- [ ] Verify content fusion
- [ ] Run Wave 2 integration tests

### Wave 3 Deployment

- [ ] Create Qdrant collection (if not exists)
- [ ] Create OpenSearch index (if not exists)
- [ ] Deploy retrieval service with video support
- [ ] Verify embedding generation
- [ ] Verify hybrid search
- [ ] Run Wave 3 integration tests

### Wave 4 Deployment

- [ ] Deploy clip generation service
- [ ] Configure clip cache TTL
- [ ] Schedule cache cleanup task
- [ ] Deploy management API
- [ ] Run Wave 4 integration tests
- [ ] Run full E2E tests

### Post-deployment

- [ ] Run full E2E test suite
- [ ] Run performance benchmarks
- [ ] Verify Prometheus metrics exported
- [ ] Create Grafana dashboard for video metrics
- [ ] Update documentation
- [ ] Document any deviations from plan

---

## Rollback Plan

### Per-Service Rollback

```bash
# Rollback individual service deployments
kubectl rollout undo deployment/ingestion-service -n rag-pipeline
kubectl rollout undo deployment/retrieval-service -n rag-pipeline
```

### Database Rollback

```bash
# Rollback migrations (in reverse order)
cd services/shared/database/migrations
alembic downgrade -1  # Repeat as needed
```

### Index Cleanup

```bash
# Delete Qdrant collection
curl -X DELETE http://qdrant:6333/collections/video_chunks

# Delete OpenSearch index
curl -X DELETE http://opensearch:9200/video_chunks
```

### Storage Cleanup

```bash
# Remove video files from MinIO (use mc client)
mc rm --recursive minio/rag-bucket/videos/
```

---

## Definition of Done (Epic Level)

### Functional Requirements

- [ ] Video upload supporting MP4, MOV, AVI, MKV, WebM
- [ ] Duration validation (10s - 3600s)
- [ ] Audio extraction and Whisper transcription
- [ ] Scene detection and keyframe extraction
- [ ] Vision LLM scene descriptions
- [ ] OCR text extraction from keyframes
- [ ] Multi-modal content fusion into chunks
- [ ] Video chunk embedding (BGE-large, 1024 dims)
- [ ] Hybrid search (semantic + keyword)
- [ ] RRF fusion and cross-encoder reranking
- [ ] Timeline response with grouped results
- [ ] On-demand clip generation with caching
- [ ] Video management API (CRUD operations)
- [ ] Cascade delete to all stores

### Non-Functional Requirements

- [ ] Tenant isolation enforced on all endpoints
- [ ] ACL filtering in retrieval
- [ ] Processing status tracking via API
- [ ] Health check endpoints
- [ ] Prometheus metrics exported
- [ ] Structured logging with correlation IDs
- [ ] Error handling with meaningful messages
- [ ] >90% test coverage per service

### Performance Requirements

- [ ] Video retrieval p95 < 300ms
- [ ] Clip generation (stream copy) < 5s
- [ ] Processing throughput: 1 hour video in < 30 minutes

### Documentation Requirements

- [ ] docs/architecture.md updated with Video RAG
- [ ] README.md updated with video capabilities
- [ ] API documentation for all video endpoints
- [ ] Configuration reference documented

---

## Appendix: Environment Variables

### Ingestion Service (Video Processing)

```bash
# Video validation
VIDEO_MAX_DURATION_SECONDS=3600
VIDEO_MIN_DURATION_SECONDS=10
VIDEO_MAX_FILE_SIZE_MB=5000

# Audio extraction
AUDIO_SAMPLE_RATE=16000
AUDIO_CHANNELS=1

# Whisper configuration
WHISPER_MODEL=base  # tiny, base, small, medium, large-v3
WHISPER_DEVICE=cuda  # cuda or cpu
WHISPER_COMPUTE_TYPE=float16  # float16, int8
WHISPER_LANGUAGE=auto  # auto or language code

# Scene detection
SCENE_THRESHOLD=27.0
SCENE_MIN_LENGTH_FRAMES=15
KEYFRAME_INTERVAL_SECONDS=5

# Vision LLM
VISION_LLM_PROVIDER=openai  # openai, anthropic, ollama
VISION_LLM_MODEL=gpt-4o
VISION_LLM_MAX_TOKENS=300
VISION_LLM_RPM_LIMIT=60
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

# OCR
OCR_ENGINE=tesseract
OCR_LANGUAGES=eng
OCR_CONFIDENCE_THRESHOLD=60

# Fusion
FUSION_CHUNK_DURATION_SECONDS=20
FUSION_CHUNK_OVERLAP_SECONDS=2
FUSION_INCLUDE_MODALITY_LABELS=true
```

### Retrieval Service (Video Search)

```bash
# Video retrieval
VIDEO_SEMANTIC_WEIGHT=0.7
VIDEO_KEYWORD_WEIGHT=0.3
VIDEO_RRF_K=60
VIDEO_SEMANTIC_TOP_K=50
VIDEO_KEYWORD_TOP_K=50
VIDEO_RERANK_TOP_K=20
VIDEO_FINAL_TOP_K=10

# Clip generation
CLIP_PADDING_SECONDS=2.0
CLIP_MAX_DURATION_SECONDS=120
CLIP_CACHE_TTL_HOURS=24
CLIP_VIDEO_CODEC=libx264
CLIP_CRF=23
CLIP_PRESET=fast
```

---

## Appendix: Service Ports

| Service | Internal Port | External Port | Protocol |
|---------|--------------|---------------|----------|
| Ingestion Service | 8001 | 8001 | HTTP |
| Retrieval Service | 8002 | 8002 | HTTP |
| Orchestrator Service | 8003 | 8003 | HTTP |
| LLM Gateway | 8004 | 8004 | HTTP |
| Embedding Service | 8080 | - | HTTP |
| PostgreSQL | 5432 | 5432 | TCP |
| Qdrant | 6333 | 6333 | HTTP |
| OpenSearch | 9200 | 9200 | HTTP |
| Redis | 6379 | 6379 | TCP |
| MinIO | 9000 | 9000 | HTTP |

---

## Appendix: New Dependencies

### Python Packages (ingestion service)

```
# requirements.txt additions
faster-whisper>=1.0.0      # Speech transcription
scenedetect>=0.6.0         # Scene boundary detection
pytesseract>=0.3.10        # OCR extraction
Pillow>=10.0.0             # Image handling
ffmpeg-python>=0.2.0       # FFmpeg wrapper (optional, for complex operations)
```

### System Packages (Dockerfile)

```dockerfile
# Add to ingestion service Dockerfile
RUN apt-get update && apt-get install -y \
    ffmpeg \
    tesseract-ocr \
    tesseract-ocr-eng \
    libsm6 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*
```

### Python Packages (retrieval service)

```
# No new packages required - uses existing embedding and reranker services
```
