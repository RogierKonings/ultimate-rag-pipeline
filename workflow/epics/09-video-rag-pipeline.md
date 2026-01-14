# Epic 9: Video RAG Pipeline

> **Priority:** High
> **Dependencies:** Epic 2 (Ingestion Service), Epic 3 (Retrieval Service), Epic 1 (Infrastructure)

## Overview

Extend the RAG pipeline to support video files as a first-class content type. Users can upload videos (10-60 minutes), which are processed through multi-modal extraction (speech, visual scenes, OCR). Users can then query the video content and receive an interactive timeline showing all matching moments with on-demand video clip generation.

## Goals

- Support video file ingestion with multi-modal content extraction
- Enable semantic and keyword search across video content
- Return interactive timeline responses showing matching video moments
- Generate video clips on-demand using timestamps
- Maintain existing multi-tenancy and ACL patterns

## Architecture Overview

### New Components

1. **Video Processor** (Ingestion Service extension)
   - Multi-modal extraction: speech (Whisper), visual scenes (Vision LLM), OCR
   - Produces timestamped "video chunks" (10-30 second segments)
   - Stores original video in MinIO

2. **Video Chunk Indexing**
   - Fused text embeddings (transcript + scene description + OCR)
   - Indexed in Qdrant and OpenSearch like document chunks
   - Keyframe thumbnails stored in MinIO

3. **Video Clip Service** (Retrieval Service extension)
   - On-demand clip cutting using FFmpeg
   - Clip caching with TTL
   - Timeline response generation

### Data Flow

```
Ingestion:
Video Upload → Audio Extraction → Whisper Transcription ─┐
            → Scene Detection → Vision LLM Description ──┼→ Fusion → Chunks → Embedding → Index
            → Keyframe Extraction → OCR ─────────────────┘

Retrieval:
Query → Hybrid Search (video_chunks) → RRF + Rerank → Group by Video → Timeline Response
Timeline Click → Clip Service → FFmpeg Cut → Cached Clip URL → Stream to User
```

## User Stories

### US-9.1: Video Upload and Processing

**As a** user
**I want** to upload video files for processing
**So that** I can later search and query the video content

**Acceptance Criteria:**
- [ ] Support common video formats (MP4, MOV, AVI, MKV, WebM)
- [ ] Validate video duration (10-60 minutes initially)
- [ ] Store original video in MinIO under tenant path
- [ ] Create `source_videos` record with processing status
- [ ] Return job ID for status tracking
- [ ] Support async processing via Celery

### US-9.2: Audio Extraction and Transcription

**As a** system
**I want** to extract and transcribe audio from videos
**So that** spoken content is searchable

**Acceptance Criteria:**
- [ ] Extract audio track using FFmpeg
- [ ] Transcribe using Whisper (or faster-whisper)
- [ ] Produce word-level or segment-level timestamps
- [ ] Handle videos with no audio track gracefully
- [ ] Support multiple languages (language detection)
- [ ] Store transcript segments with timing metadata

### US-9.3: Scene Detection and Keyframe Extraction

**As a** system
**I want** to detect scene changes and extract keyframes
**So that** visual content can be analyzed

**Acceptance Criteria:**
- [ ] Detect scene boundaries using visual similarity thresholds
- [ ] Extract keyframes at scene changes
- [ ] Extract keyframes at fixed intervals (every 5 seconds) as fallback
- [ ] Group keyframes into logical segments (10-30 seconds)
- [ ] Store keyframe images in MinIO
- [ ] Generate thumbnail for each video chunk

### US-9.4: Visual Scene Understanding

**As a** system
**I want** to generate descriptions of visual content
**So that** visual events are searchable by text

**Acceptance Criteria:**
- [ ] Send keyframes to Vision LLM (GPT-4V, LLaVA, or Qwen-VL)
- [ ] Generate descriptive text for each scene segment
- [ ] Identify key actions, objects, and events
- [ ] Handle Vision LLM rate limits and errors
- [ ] Support configurable Vision LLM provider
- [ ] Cache Vision LLM responses

### US-9.5: OCR Text Extraction

**As a** system
**I want** to extract on-screen text from video frames
**So that** overlays, captions, and scoreboards are searchable

**Acceptance Criteria:**
- [ ] Run OCR on keyframes using Tesseract
- [ ] Extract text from scoreboards, titles, captions, overlays
- [ ] Associate OCR text with timestamps
- [ ] Deduplicate repeated text across frames
- [ ] Handle frames with no text gracefully

### US-9.6: Multi-Modal Content Fusion

**As a** system
**I want** to combine all extracted content into searchable chunks
**So that** users can find video moments using any modality

**Acceptance Criteria:**
- [ ] Align transcript, scene descriptions, and OCR by timestamp
- [ ] Create video chunks with combined `fused_text` field
- [ ] Each chunk has: start_time, end_time, transcript, scene_description, ocr_text, fused_text
- [ ] Preserve source attribution in chunk metadata
- [ ] Handle missing modalities (e.g., no speech, no OCR text)

### US-9.7: Video Chunk Embedding and Indexing

**As a** system
**I want** to embed and index video chunks
**So that** they are searchable via hybrid retrieval

**Acceptance Criteria:**
- [ ] Generate embeddings from `fused_text` using BGE-large
- [ ] Index in Qdrant `video_chunks` collection
- [ ] Index in OpenSearch `video_chunks` index
- [ ] Store chunk metadata in PostgreSQL `video_chunks` table
- [ ] Include tenant_id, video_id, timestamps in payload/fields
- [ ] Support ACL filtering (allowed_groups)

### US-9.8: Video Retrieval with Timeline Response

**As a** user
**I want** to search across my videos and see a timeline of matches
**So that** I can quickly find relevant moments

**Acceptance Criteria:**
- [ ] New endpoint: `POST /api/v1/retrieve/video`
- [ ] Hybrid search across video_chunks (semantic + keyword)
- [ ] RRF fusion and reranking
- [ ] Group results by video
- [ ] Sort matches by timestamp within each video
- [ ] Return timeline response with: video metadata, matching chunks, keyframe URLs, clip URLs
- [ ] Include relevance scores and preview text

### US-9.9: On-Demand Video Clip Generation

**As a** user
**I want** to view video clips for matching moments
**So that** I can see the actual video content

**Acceptance Criteria:**
- [ ] Endpoint: `GET /api/v1/videos/{id}/clip?start={ms}&end={ms}`
- [ ] Check clip cache first (MinIO path)
- [ ] Generate clip using FFmpeg if not cached
- [ ] Use stream copy for fast cutting when possible
- [ ] Store generated clip in cache with TTL (24 hours)
- [ ] Return streaming URL or redirect to MinIO
- [ ] Support clip padding (e.g., 2 seconds before/after)

### US-9.10: Video Management API

**As a** user
**I want** to list, view, and delete my videos
**So that** I can manage my video library

**Acceptance Criteria:**
- [ ] `GET /api/v1/videos` - list videos with pagination and filtering
- [ ] `GET /api/v1/videos/{id}` - get video metadata and processing status
- [ ] `DELETE /api/v1/videos/{id}` - delete video, chunks, keyframes, and cached clips
- [ ] `GET /api/v1/videos/{id}/chunks` - list video chunks with timestamps
- [ ] `GET /api/v1/videos/{id}/keyframes/{idx}` - get keyframe image
- [ ] Enforce tenant isolation and ACL

## Technical Tasks

### Database Schema

**New PostgreSQL Tables:**

```sql
-- Source videos table
CREATE TABLE source_videos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    filename VARCHAR(255) NOT NULL,
    title VARCHAR(500),
    description TEXT,
    duration_seconds INTEGER,
    width INTEGER,
    height INTEGER,
    storage_path VARCHAR(1000) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'processing',
    error_message TEXT,
    visibility VARCHAR(50) NOT NULL DEFAULT 'private',
    allowed_groups TEXT[],
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);

CREATE INDEX idx_source_videos_tenant ON source_videos(tenant_id);
CREATE INDEX idx_source_videos_status ON source_videos(status);

-- Video chunks table
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
    embedding_id VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(video_id, chunk_index)
);

CREATE INDEX idx_video_chunks_video ON video_chunks(video_id);
CREATE INDEX idx_video_chunks_time ON video_chunks(video_id, start_time_ms);
```

**Qdrant Collection:** `video_chunks`
- Vector size: 1024 (BGE-large)
- Distance: Cosine
- Payload: tenant_id, video_id, chunk_index, start_time_ms, end_time_ms, allowed_groups

**OpenSearch Index:** `video_chunks`
- Fields: chunk_id, video_id, tenant_id, fused_text, transcript_text, scene_description, ocr_text

### MinIO Storage Structure

```
videos/
├── {tenant_id}/
│   ├── originals/
│   │   └── {video_id}.mp4
│   ├── keyframes/
│   │   └── {video_id}/
│   │       ├── 0.jpg
│   │       ├── 1.jpg
│   │       └── ...
│   └── clips/
│       └── {video_id}/
│           └── {start_ms}_{end_ms}.mp4
```

### New Dependencies

**Python packages (add to ingestion service requirements.txt):**
```
faster-whisper>=0.10.0      # Speech transcription
ffmpeg-python>=0.2.0        # Video manipulation
scenedetect>=0.6.0          # Scene boundary detection
pytesseract>=0.3.10         # OCR extraction
Pillow>=10.0.0              # Image handling
```

**System packages (add to Dockerfile):**
```dockerfile
RUN apt-get update && apt-get install -y \
    ffmpeg \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*
```

### Implementation Order

1. Database migrations for new tables
2. MinIO bucket structure setup
3. Video upload endpoint and storage
4. Audio extraction and Whisper integration
5. Scene detection and keyframe extraction
6. Vision LLM integration for scene descriptions
7. OCR extraction pipeline
8. Multi-modal fusion logic
9. Video chunk embedding and indexing
10. Video retrieval endpoint with timeline response
11. Clip generation service
12. Video management API endpoints
13. Celery tasks for async processing
14. Integration tests

## API Schemas

### Video Upload Request

```python
class VideoUploadRequest(BaseModel):
    tenant_id: UUID
    title: str | None = None
    description: str | None = None
    visibility: str = "private"
    allowed_groups: list[str] = []
    processing_options: VideoProcessingOptions | None = None

class VideoProcessingOptions(BaseModel):
    extract_speech: bool = True
    extract_scenes: bool = True
    extract_ocr: bool = True
    chunk_duration_seconds: int = 20
    language: str | None = None  # Auto-detect if None
```

### Timeline Response

```python
class VideoMatch(BaseModel):
    chunk_id: UUID
    start_time_ms: int
    end_time_ms: int
    relevance_score: float
    preview_text: str
    keyframe_url: str
    clip_url: str

class VideoResult(BaseModel):
    video_id: UUID
    title: str
    duration_seconds: int
    thumbnail_url: str
    matches: list[VideoMatch]

class VideoTimelineResponse(BaseModel):
    query: str
    total_matches: int
    videos: list[VideoResult]
```

## Configuration

**New environment variables:**

```bash
# Video processing
VIDEO_MAX_DURATION_SECONDS=3600
VIDEO_CHUNK_DURATION_SECONDS=20
VIDEO_KEYFRAME_INTERVAL_SECONDS=5

# Whisper configuration
WHISPER_MODEL=base  # tiny, base, small, medium, large
WHISPER_DEVICE=cuda  # cuda or cpu
WHISPER_LANGUAGE=auto  # auto-detect or specific language code

# Vision LLM configuration
VISION_LLM_PROVIDER=openai  # openai, ollama
VISION_LLM_MODEL=gpt-4-vision-preview
VISION_LLM_MAX_TOKENS=300

# Clip generation
CLIP_CACHE_TTL_HOURS=24
CLIP_PADDING_SECONDS=2
```

## Definition of Done

- [ ] Video upload and storage working
- [ ] Multi-modal extraction pipeline complete (speech, vision, OCR)
- [ ] Video chunks indexed in Qdrant and OpenSearch
- [ ] Timeline retrieval endpoint returning ranked matches
- [ ] On-demand clip generation functional
- [ ] Video management API complete
- [ ] Tenant isolation and ACL enforced
- [ ] Processing status tracking via job API
- [ ] Integration tests for full pipeline
- [ ] API documentation updated
- [ ] Performance benchmarks for 30-minute video processing

## Future Enhancements

- Support for longer videos (1-4 hours) with streaming processing
- Real-time video processing during upload
- Specialized event detection models (sports, meetings, etc.)
- Multi-video search and cross-video timeline
- Video summarization endpoint
- Transcript export (SRT/VTT format)
- Speaker diarization for multi-speaker videos
- Frontend timeline visualization component
