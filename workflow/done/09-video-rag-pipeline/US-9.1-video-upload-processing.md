# US-9.1: Video Upload and Processing

> **Story ID:** US-9.1
> **Epic:** Video RAG Pipeline
> **Priority:** Critical
> **Estimated Effort:** 3 days
> **Dependencies:** US-2.8 (Ingestion API), US-1.5 (Object Storage)

## User Story

**As a** user
**I want** to upload video files for processing
**So that** I can later search and query the video content

## Context

This user story establishes the foundation for video ingestion into the RAG pipeline. Users upload videos through a dedicated API endpoint, which validates the file, stores it in MinIO, creates a database record, and queues an async processing job.

## Technical Requirements

### Database Schema

```sql
CREATE TYPE video_status AS ENUM (
    'uploading', 'uploaded', 'processing', 'extracting_audio',
    'transcribing', 'extracting_scenes', 'analyzing_visuals',
    'extracting_ocr', 'fusing_content', 'embedding', 'indexing',
    'completed', 'failed', 'cancelled'
);

CREATE TABLE source_videos (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    filename VARCHAR(255) NOT NULL,
    original_filename VARCHAR(255) NOT NULL,
    mime_type VARCHAR(100) NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    content_hash VARCHAR(64),
    duration_seconds DECIMAL(10, 3),
    width INTEGER,
    height INTEGER,
    fps DECIMAL(6, 3),
    codec VARCHAR(50),
    bitrate_kbps INTEGER,
    has_audio BOOLEAN DEFAULT true,
    audio_codec VARCHAR(50),
    title VARCHAR(500),
    description TEXT,
    storage_path VARCHAR(1000) NOT NULL,
    thumbnail_path VARCHAR(1000),
    status video_status NOT NULL DEFAULT 'uploading',
    processing_progress DECIMAL(5, 2) DEFAULT 0.0,
    error_message TEXT,
    processing_options JSONB DEFAULT '{}',
    visibility VARCHAR(50) NOT NULL DEFAULT 'private',
    allowed_groups TEXT[],
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    processed_at TIMESTAMPTZ
);

CREATE INDEX idx_source_videos_tenant ON source_videos(tenant_id);
CREATE INDEX idx_source_videos_status ON source_videos(status);
CREATE INDEX idx_source_videos_content_hash ON source_videos(content_hash);
```

### API Schemas

```python
# api/schemas/video.py
from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from enum import Enum

class VideoStatus(str, Enum):
    UPLOADING = "uploading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"

class VideoProcessingOptions(BaseModel):
    extract_speech: bool = True
    extract_scenes: bool = True
    extract_ocr: bool = True
    chunk_duration_seconds: int = Field(default=20, ge=5, le=60)
    language: str | None = None

class VideoUploadMetadata(BaseModel):
    title: str | None = Field(None, max_length=500)
    description: str | None = None
    visibility: str = "private"
    allowed_groups: list[str] = []
    processing_options: VideoProcessingOptions = VideoProcessingOptions()

class VideoUploadResponse(BaseModel):
    video_id: UUID
    status: VideoStatus
    message: str
    job_id: UUID | None = None
    created_at: datetime

class VideoResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    filename: str
    title: str | None
    duration_seconds: float | None
    width: int | None
    height: int | None
    status: VideoStatus
    processing_progress: float = 0.0
    thumbnail_url: str | None = None
    chunk_count: int = 0
    created_at: datetime
    processed_at: datetime | None
```

### Video Validator

```python
# processors/video/validator.py
from dataclasses import dataclass
from pathlib import Path
import subprocess
import json
import hashlib
import asyncio

@dataclass
class VideoValidationResult:
    valid: bool
    error: str | None = None
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    codec: str | None = None
    has_audio: bool = False
    content_hash: str | None = None

@dataclass
class VideoValidatorConfig:
    min_duration_seconds: float = 10.0
    max_duration_seconds: float = 3600.0
    max_file_size_bytes: int = 10_737_418_240  # 10GB
    allowed_codecs: list[str] = None

    def __post_init__(self):
        if self.allowed_codecs is None:
            self.allowed_codecs = ["h264", "h265", "hevc", "vp8", "vp9", "av1"]

class VideoValidator:
    def __init__(self, config: VideoValidatorConfig = None):
        self.config = config or VideoValidatorConfig()

    async def validate(self, file_path: Path) -> VideoValidationResult:
        if not file_path.exists():
            return VideoValidationResult(valid=False, error="File not found")

        file_size = file_path.stat().st_size
        if file_size > self.config.max_file_size_bytes:
            return VideoValidationResult(valid=False, error="File too large")

        try:
            probe = await self._run_ffprobe(file_path)
        except Exception as e:
            return VideoValidationResult(valid=False, error=f"FFprobe failed: {e}")

        video_stream = next(
            (s for s in probe.get("streams", []) if s["codec_type"] == "video"),
            None
        )
        if not video_stream:
            return VideoValidationResult(valid=False, error="No video stream")

        duration = float(probe["format"].get("duration", 0))
        if duration < self.config.min_duration_seconds:
            return VideoValidationResult(valid=False, error="Video too short")
        if duration > self.config.max_duration_seconds:
            return VideoValidationResult(valid=False, error="Video too long")

        codec = video_stream.get("codec_name", "").lower()
        if codec not in self.config.allowed_codecs:
            return VideoValidationResult(valid=False, error=f"Unsupported codec: {codec}")

        content_hash = await self._compute_hash(file_path)

        return VideoValidationResult(
            valid=True,
            duration_seconds=duration,
            width=video_stream.get("width"),
            height=video_stream.get("height"),
            fps=self._parse_fps(video_stream.get("r_frame_rate", "0/1")),
            codec=codec,
            has_audio=any(s["codec_type"] == "audio" for s in probe.get("streams", [])),
            content_hash=content_hash
        )

    async def _run_ffprobe(self, file_path: Path) -> dict:
        cmd = ["ffprobe", "-v", "quiet", "-print_format", "json",
               "-show_format", "-show_streams", str(file_path)]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return json.loads(stdout)

    def _parse_fps(self, fps_str: str) -> float:
        if "/" in fps_str:
            num, den = fps_str.split("/")
            return float(num) / float(den) if float(den) > 0 else 0.0
        return float(fps_str)

    async def _compute_hash(self, file_path: Path) -> str:
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192 * 1024), b""):
                sha256.update(chunk)
        return sha256.hexdigest()
```

### Upload API Route

```python
# api/routes/videos.py
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from uuid import UUID, uuid4
from datetime import datetime
import tempfile
import shutil
from pathlib import Path

router = APIRouter(prefix="/videos", tags=["Videos"])

@router.post("/upload", response_model=VideoUploadResponse, status_code=202)
async def upload_video(
    file: UploadFile = File(...),
    metadata: str = Form(default="{}"),
    current_user: dict = Depends(get_current_user),
    video_service = Depends(get_video_service),
    video_storage = Depends(get_video_storage),
    video_validator = Depends(get_video_validator)
):
    """Upload a video file for RAG processing."""
    tenant_id = UUID(current_user["tenant_id"])
    video_id = uuid4()

    meta = VideoUploadMetadata.model_validate_json(metadata)

    allowed_types = ["video/mp4", "video/quicktime", "video/x-msvideo",
                     "video/x-matroska", "video/webm"]
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=415, detail="Unsupported format")

    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(file.filename).suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)

    try:
        validation = await video_validator.validate(tmp_path)
        if not validation.valid:
            raise HTTPException(status_code=422, detail=validation.error)

        storage_path = await video_storage.upload_video(
            tenant_id=tenant_id,
            video_id=video_id,
            file_path=tmp_path,
            filename=f"{video_id}{Path(file.filename).suffix.lower()}",
            content_type=file.content_type
        )

        video = await video_service.create_video(
            video_id=video_id,
            tenant_id=tenant_id,
            filename=file.filename,
            storage_path=storage_path,
            validation=validation,
            metadata=meta
        )

        task = process_video.delay(str(video_id), str(tenant_id),
                                   meta.processing_options.model_dump())

        return VideoUploadResponse(
            video_id=video_id,
            status=VideoStatus.PROCESSING,
            message="Video uploaded and queued for processing",
            job_id=UUID(task.id),
            created_at=datetime.utcnow()
        )
    finally:
        tmp_path.unlink(missing_ok=True)

@router.get("/{video_id}/status", response_model=VideoJobStatusResponse)
async def get_video_status(
    video_id: UUID,
    current_user: dict = Depends(get_current_user),
    video_service = Depends(get_video_service)
):
    """Get processing status for a video."""
    tenant_id = UUID(current_user["tenant_id"])
    video = await video_service.get_video(video_id, tenant_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")
    return video
```

### Celery Task

```python
# tasks/video_ingest.py
from celery import shared_task
from uuid import UUID

@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_video(self, video_id: str, tenant_id: str, processing_options: dict):
    """Main Celery task for video processing pipeline."""
    from processors.video.pipeline import VideoProcessingPipeline
    import asyncio

    async def run():
        pipeline = VideoProcessingPipeline(
            video_id=UUID(video_id),
            tenant_id=UUID(tenant_id),
            options=processing_options
        )
        await pipeline.run()

    asyncio.run(run())
```

## MinIO Storage Structure

```
videos/
├── {tenant_id}/
│   ├── originals/{video_id}/{filename}
│   ├── keyframes/{video_id}/{index}.jpg
│   ├── thumbnails/{video_id}/thumb.jpg
│   └── clips/{video_id}/{start_ms}_{end_ms}.mp4
```

## Acceptance Criteria

- [ ] Support common video formats (MP4, MOV, AVI, MKV, WebM)
- [ ] Validate video duration (10-60 minutes initially)
- [ ] Store original video in MinIO under tenant path
- [ ] Create `source_videos` record with processing status
- [ ] Return job ID for status tracking
- [ ] Support async processing via Celery

## Testing Requirements

```python
def test_upload_requires_auth(client):
    response = client.post("/api/v1/videos/upload", files={"file": ("test.mp4", b"data", "video/mp4")})
    assert response.status_code == 401

def test_upload_rejects_invalid_format(client, auth_headers):
    response = client.post("/api/v1/videos/upload",
        files={"file": ("test.txt", b"hello", "text/plain")},
        headers=auth_headers)
    assert response.status_code == 415

def test_upload_validates_duration(client, auth_headers):
    # Test with too-short video
    pass

def test_upload_success_returns_job_id(client, auth_headers, mock_video):
    response = client.post("/api/v1/videos/upload",
        files={"file": ("test.mp4", mock_video, "video/mp4")},
        headers=auth_headers)
    assert response.status_code == 202
    assert "job_id" in response.json()
```

## Definition of Done

- [ ] Video upload endpoint accepts common formats
- [ ] FFprobe metadata extraction working
- [ ] Content hash computed for deduplication
- [ ] Videos stored in MinIO with correct paths
- [ ] Database records created with full metadata
- [ ] Celery task queued and tracked
- [ ] Tenant isolation enforced
- [ ] >90% test coverage
