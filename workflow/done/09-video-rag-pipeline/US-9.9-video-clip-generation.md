# US-9.9: On-Demand Video Clip Generation

> **Story ID:** US-9.9
> **Epic:** Video RAG Pipeline
> **Priority:** High
> **Estimated Effort:** 2 days
> **Dependencies:** US-9.1 (Video Storage), US-9.8 (Video Retrieval)

## User Story

**As a** user
**I want** to view video clips for matching moments
**So that** I can see the actual video content

## Context

When users find relevant video moments through search, they need to view the actual video content. This story implements on-demand clip generation using FFmpeg. Clips are cut from the original video at the requested timestamps, cached in MinIO for reuse, and streamed back to the user.

## Technical Requirements

### Clip Generation Service

```python
# processors/video/clip_generator.py
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID
import asyncio
import logging
import tempfile

logger = logging.getLogger(__name__)

@dataclass
class ClipConfig:
    """Configuration for clip generation."""
    padding_seconds: float = 2.0  # Add context before/after
    max_duration_seconds: float = 120.0  # Max clip length
    output_format: str = "mp4"
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    crf: int = 23  # Quality (lower = better)
    preset: str = "fast"
    use_stream_copy: bool = True  # Fast cutting when possible

@dataclass
class ClipResult:
    success: bool
    clip_path: Path | None = None
    duration_seconds: float = 0
    file_size_bytes: int = 0
    error: str | None = None

class ClipGenerator:
    """Generates video clips using FFmpeg."""

    def __init__(self, config: ClipConfig = None):
        self.config = config or ClipConfig()

    async def generate_clip(
        self,
        video_path: Path,
        start_ms: int,
        end_ms: int,
        output_path: Path
    ) -> ClipResult:
        """
        Generate a video clip from the source video.

        Uses stream copy (fast) when possible, falls back to re-encoding
        for precise cutting if needed.
        """
        # Apply padding
        padded_start_ms = max(0, start_ms - int(self.config.padding_seconds * 1000))
        padded_end_ms = end_ms + int(self.config.padding_seconds * 1000)

        # Check duration limit
        duration_ms = padded_end_ms - padded_start_ms
        if duration_ms > self.config.max_duration_seconds * 1000:
            return ClipResult(
                success=False,
                error=f"Clip duration {duration_ms/1000}s exceeds max {self.config.max_duration_seconds}s"
            )

        # Convert to seconds
        start_sec = padded_start_ms / 1000
        duration_sec = duration_ms / 1000

        # Try stream copy first (fast)
        if self.config.use_stream_copy:
            result = await self._generate_stream_copy(
                video_path, start_sec, duration_sec, output_path
            )
            if result.success:
                return result
            logger.info("Stream copy failed, falling back to re-encode")

        # Fall back to re-encoding (precise but slower)
        return await self._generate_reencode(
            video_path, start_sec, duration_sec, output_path
        )

    async def _generate_stream_copy(
        self,
        video_path: Path,
        start_sec: float,
        duration_sec: float,
        output_path: Path
    ) -> ClipResult:
        """Fast clip using stream copy (no re-encoding)."""
        cmd = [
            "ffmpeg",
            "-ss", str(start_sec),
            "-i", str(video_path),
            "-t", str(duration_sec),
            "-c", "copy",  # Stream copy
            "-avoid_negative_ts", "make_zero",
            "-y",
            str(output_path)
        ]

        return await self._run_ffmpeg(cmd, output_path)

    async def _generate_reencode(
        self,
        video_path: Path,
        start_sec: float,
        duration_sec: float,
        output_path: Path
    ) -> ClipResult:
        """Precise clip with re-encoding."""
        cmd = [
            "ffmpeg",
            "-ss", str(start_sec),
            "-i", str(video_path),
            "-t", str(duration_sec),
            "-c:v", self.config.video_codec,
            "-crf", str(self.config.crf),
            "-preset", self.config.preset,
            "-c:a", self.config.audio_codec,
            "-movflags", "+faststart",  # Enable streaming
            "-y",
            str(output_path)
        ]

        return await self._run_ffmpeg(cmd, output_path)

    async def _run_ffmpeg(self, cmd: list[str], output_path: Path) -> ClipResult:
        """Execute FFmpeg command and return result."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)

            if proc.returncode != 0:
                return ClipResult(
                    success=False,
                    error=f"FFmpeg error: {stderr.decode()[-500:]}"
                )

            if not output_path.exists():
                return ClipResult(success=False, error="Output file not created")

            # Get file info
            file_size = output_path.stat().st_size
            duration = await self._get_duration(output_path)

            return ClipResult(
                success=True,
                clip_path=output_path,
                duration_seconds=duration,
                file_size_bytes=file_size
            )

        except asyncio.TimeoutError:
            return ClipResult(success=False, error="FFmpeg timeout")
        except Exception as e:
            return ClipResult(success=False, error=str(e))

    async def _get_duration(self, video_path: Path) -> float:
        """Get video duration using ffprobe."""
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video_path)
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        return float(stdout.decode().strip())
```

### Clip Cache Service

```python
# processors/video/clip_cache.py
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

@dataclass
class CachedClip:
    storage_path: str
    url: str
    expires_at: datetime
    file_size_bytes: int

@dataclass
class ClipCacheConfig:
    ttl_hours: int = 24
    max_cache_size_gb: float = 50.0
    cleanup_interval_hours: int = 6

class ClipCacheService:
    """Manages cached video clips in MinIO."""

    def __init__(self, minio_client, config: ClipCacheConfig = None):
        self.minio = minio_client
        self.config = config or ClipCacheConfig()

    def get_cache_key(
        self,
        tenant_id: UUID,
        video_id: UUID,
        start_ms: int,
        end_ms: int
    ) -> str:
        """Generate cache key for a clip."""
        return f"videos/{tenant_id}/clips/{video_id}/{start_ms}_{end_ms}.mp4"

    async def get_cached(
        self,
        tenant_id: UUID,
        video_id: UUID,
        start_ms: int,
        end_ms: int
    ) -> CachedClip | None:
        """Check if clip exists in cache."""
        cache_key = self.get_cache_key(tenant_id, video_id, start_ms, end_ms)

        try:
            # Check if object exists
            stat = await self.minio.stat_object(cache_key)
            if not stat:
                return None

            # Check if expired (based on custom metadata or last modified)
            # For simplicity, we'll regenerate presigned URL each time
            url = await self.minio.presign_get(
                cache_key,
                expiry=timedelta(hours=4),
                response_content_type="video/mp4",
                response_content_disposition="inline"
            )

            return CachedClip(
                storage_path=cache_key,
                url=url,
                expires_at=datetime.utcnow() + timedelta(hours=4),
                file_size_bytes=stat.size
            )

        except Exception:
            return None

    async def cache_clip(
        self,
        tenant_id: UUID,
        video_id: UUID,
        start_ms: int,
        end_ms: int,
        local_path: Path
    ) -> CachedClip:
        """Upload clip to cache."""
        cache_key = self.get_cache_key(tenant_id, video_id, start_ms, end_ms)

        await self.minio.upload_file(
            local_path,
            cache_key,
            content_type="video/mp4"
        )

        url = await self.minio.presign_get(
            cache_key,
            expiry=timedelta(hours=4),
            response_content_type="video/mp4"
        )

        file_size = local_path.stat().st_size

        logger.info(f"Cached clip: {cache_key} ({file_size} bytes)")

        return CachedClip(
            storage_path=cache_key,
            url=url,
            expires_at=datetime.utcnow() + timedelta(hours=4),
            file_size_bytes=file_size
        )

    async def cleanup_expired(self) -> int:
        """Remove expired clips from cache."""
        # List all clips
        prefix = "videos/"
        deleted = 0

        # Implementation would iterate through clips and delete old ones
        # based on last modified time

        return deleted
```

### Clip API Endpoint

```python
# api/routes/clips.py
from fastapi import APIRouter, HTTPException, Depends, Query, Response
from fastapi.responses import RedirectResponse, StreamingResponse
from uuid import UUID
import tempfile
from pathlib import Path

router = APIRouter(tags=["Video Clips"])

@router.get("/videos/{video_id}/clip")
async def get_video_clip(
    video_id: UUID,
    start: int = Query(..., ge=0, description="Start time in milliseconds"),
    end: int = Query(..., gt=0, description="End time in milliseconds"),
    current_user: dict = Depends(get_current_user),
    video_service = Depends(get_video_service),
    clip_generator = Depends(get_clip_generator),
    clip_cache = Depends(get_clip_cache),
    storage = Depends(get_storage_service)
):
    """
    Get a video clip for a specific time range.

    **Behavior:**
    1. Check cache for existing clip
    2. If cached, redirect to presigned URL
    3. If not cached, generate clip on-demand
    4. Cache generated clip
    5. Return redirect or stream

    **Parameters:**
    - `start`: Start time in milliseconds
    - `end`: End time in milliseconds

    **Padding:**
    Clips include 2 seconds of padding before and after the requested range
    for better context.

    **Caching:**
    Generated clips are cached for 24 hours to avoid regeneration.
    """
    tenant_id = UUID(current_user["tenant_id"])

    # Verify video access
    video = await video_service.get_video(video_id, tenant_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    # Check ACL
    user_groups = current_user.get("groups", [])
    if not _check_video_access(video, user_groups):
        raise HTTPException(status_code=403, detail="Access denied")

    # Validate time range
    if end <= start:
        raise HTTPException(status_code=400, detail="End must be greater than start")

    video_duration_ms = int(video.duration_seconds * 1000) if video.duration_seconds else 0
    if start >= video_duration_ms:
        raise HTTPException(status_code=400, detail="Start time exceeds video duration")

    # Check cache
    cached = await clip_cache.get_cached(tenant_id, video_id, start, end)
    if cached:
        return RedirectResponse(
            url=cached.url,
            status_code=302,
            headers={"Cache-Control": "private, max-age=14400"}  # 4 hours
        )

    # Generate clip
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Download original video
        video_local = temp_path / "source.mp4"
        await storage.download_file(video.storage_path, video_local)

        # Generate clip
        clip_local = temp_path / "clip.mp4"
        result = await clip_generator.generate_clip(
            video_path=video_local,
            start_ms=start,
            end_ms=end,
            output_path=clip_local
        )

        if not result.success:
            raise HTTPException(status_code=500, detail=f"Clip generation failed: {result.error}")

        # Cache the clip
        cached = await clip_cache.cache_clip(
            tenant_id=tenant_id,
            video_id=video_id,
            start_ms=start,
            end_ms=end,
            local_path=clip_local
        )

        return RedirectResponse(
            url=cached.url,
            status_code=302,
            headers={"Cache-Control": "private, max-age=14400"}
        )

def _check_video_access(video, user_groups: list[str]) -> bool:
    """Check if user has access to video."""
    if video.visibility == "public":
        return True
    if video.visibility == "private":
        return True  # Already verified tenant
    if video.visibility == "group":
        return bool(set(user_groups) & set(video.allowed_groups or []))
    return False

@router.get("/videos/{video_id}/stream")
async def stream_full_video(
    video_id: UUID,
    current_user: dict = Depends(get_current_user),
    video_service = Depends(get_video_service),
    storage = Depends(get_storage_service)
):
    """
    Get streaming URL for full video.

    Returns presigned URL for direct video streaming.
    """
    tenant_id = UUID(current_user["tenant_id"])

    video = await video_service.get_video(video_id, tenant_id)
    if not video:
        raise HTTPException(status_code=404, detail="Video not found")

    url = await storage.get_stream_url(video.storage_path)

    return RedirectResponse(url=url, status_code=302)
```

### Background Clip Cleanup

```python
# tasks/clip_cleanup.py
from celery import shared_task
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

@shared_task(name="tasks.clip_cleanup")
def cleanup_expired_clips():
    """Periodic task to clean up expired clip cache."""
    import asyncio
    from processors.video.clip_cache import ClipCacheService, ClipCacheConfig

    async def run():
        cache = ClipCacheService(get_minio_client(), ClipCacheConfig())
        deleted = await cache.cleanup_expired()
        logger.info(f"Cleaned up {deleted} expired clips")
        return deleted

    return asyncio.run(run())

# Celery beat schedule
CELERYBEAT_SCHEDULE = {
    'cleanup-expired-clips': {
        'task': 'tasks.clip_cleanup',
        'schedule': timedelta(hours=6),
    },
}
```

## API Contract

### Request

```
GET /api/v1/videos/{video_id}/clip?start={ms}&end={ms}
```

### Response

| Status | Description |
|--------|-------------|
| 302 | Redirect to presigned clip URL |
| 400 | Invalid time range |
| 403 | Access denied |
| 404 | Video not found |
| 500 | Clip generation failed |

### Headers

```
Cache-Control: private, max-age=14400
Location: https://minio.../clip.mp4?signature=...
```

## Sequence Diagram

```
┌──────┐     ┌──────┐     ┌───────┐     ┌───────┐     ┌───────┐
│Client│     │  API │     │ Cache │     │FFmpeg │     │ MinIO │
└──┬───┘     └──┬───┘     └───┬───┘     └───┬───┘     └───┬───┘
   │            │             │             │             │
   │GET /clip?start&end       │             │             │
   │───────────>│             │             │             │
   │            │             │             │             │
   │            │ get_cached()│             │             │
   │            │────────────>│             │             │
   │            │             │             │             │
   │            │    null (not cached)      │             │
   │            │<────────────│             │             │
   │            │             │             │             │
   │            │ download source           │             │
   │            │────────────────────────────────────────>│
   │            │             │             │    video    │
   │            │<────────────────────────────────────────│
   │            │             │             │             │
   │            │ generate_clip()           │             │
   │            │──────────────────────────>│             │
   │            │             │    clip.mp4 │             │
   │            │<──────────────────────────│             │
   │            │             │             │             │
   │            │ cache_clip()│             │             │
   │            │────────────>│             │             │
   │            │             │ upload      │             │
   │            │             │────────────────────────────>
   │            │             │   url       │             │
   │            │<────────────│             │             │
   │            │             │             │             │
   │ 302 Redirect(url)        │             │             │
   │<───────────│             │             │             │
   │            │             │             │             │
   │ GET clip from MinIO      │             │             │
   │─────────────────────────────────────────────────────>│
   │            │             │             │    video    │
   │<─────────────────────────────────────────────────────│
```

## Configuration

```python
class ClipConfig(BaseSettings):
    clip_padding_seconds: float = 2.0
    clip_max_duration_seconds: float = 120.0
    clip_cache_ttl_hours: int = 24
    clip_video_codec: str = "libx264"
    clip_crf: int = 23
    clip_preset: str = "fast"

    class Config:
        env_prefix = "CLIP_"
```

## Acceptance Criteria

- [ ] Endpoint: `GET /api/v1/videos/{id}/clip?start={ms}&end={ms}`
- [ ] Check clip cache first (MinIO path)
- [ ] Generate clip using FFmpeg if not cached
- [ ] Use stream copy for fast cutting when possible
- [ ] Store generated clip in cache with TTL (24 hours)
- [ ] Return streaming URL or redirect to MinIO
- [ ] Support clip padding (e.g., 2 seconds before/after)

## Testing Requirements

```python
class TestClipGenerator:
    @pytest.mark.asyncio
    async def test_generates_clip(self, sample_video, tmp_path):
        generator = ClipGenerator()
        output = tmp_path / "clip.mp4"

        result = await generator.generate_clip(
            video_path=sample_video,
            start_ms=5000,
            end_ms=15000,
            output_path=output
        )

        assert result.success
        assert output.exists()
        assert result.duration_seconds > 0

    @pytest.mark.asyncio
    async def test_adds_padding(self, sample_video, tmp_path):
        config = ClipConfig(padding_seconds=3.0)
        generator = ClipGenerator(config)
        output = tmp_path / "clip.mp4"

        result = await generator.generate_clip(
            video_path=sample_video,
            start_ms=10000,
            end_ms=20000,
            output_path=output
        )

        # Clip should be ~16 seconds (10s content + 6s padding)
        assert result.duration_seconds >= 15

    @pytest.mark.asyncio
    async def test_respects_max_duration(self, sample_video, tmp_path):
        config = ClipConfig(max_duration_seconds=10.0)
        generator = ClipGenerator(config)

        result = await generator.generate_clip(
            video_path=sample_video,
            start_ms=0,
            end_ms=60000,  # 60 seconds
            output_path=tmp_path / "clip.mp4"
        )

        assert not result.success
        assert "exceeds max" in result.error

class TestClipCache:
    @pytest.mark.asyncio
    async def test_caches_clip(self, minio_client, tmp_path):
        cache = ClipCacheService(minio_client)

        # Create dummy clip
        clip_path = tmp_path / "test.mp4"
        clip_path.write_bytes(b"dummy video content")

        result = await cache.cache_clip(
            tenant_id=uuid4(),
            video_id=uuid4(),
            start_ms=0,
            end_ms=10000,
            local_path=clip_path
        )

        assert result.url
        assert result.storage_path

    @pytest.mark.asyncio
    async def test_returns_cached(self, minio_client, cached_clip):
        cache = ClipCacheService(minio_client)

        result = await cache.get_cached(
            tenant_id=cached_clip.tenant_id,
            video_id=cached_clip.video_id,
            start_ms=cached_clip.start_ms,
            end_ms=cached_clip.end_ms
        )

        assert result is not None
        assert result.url

class TestClipEndpoint:
    def test_returns_redirect(self, client, auth_headers, video_with_clip):
        response = client.get(
            f"/api/v1/videos/{video_with_clip.id}/clip?start=0&end=10000",
            headers=auth_headers,
            follow_redirects=False
        )

        assert response.status_code == 302
        assert "Location" in response.headers

    def test_validates_time_range(self, client, auth_headers, sample_video):
        response = client.get(
            f"/api/v1/videos/{sample_video.id}/clip?start=10000&end=5000",
            headers=auth_headers
        )

        assert response.status_code == 400

    def test_requires_auth(self, client, sample_video):
        response = client.get(f"/api/v1/videos/{sample_video.id}/clip?start=0&end=10000")
        assert response.status_code == 401
```

## Dependencies

```
ffmpeg (system)
```

## Definition of Done

- [ ] Clip endpoint returns presigned URLs
- [ ] Cache check before generation
- [ ] FFmpeg stream copy working
- [ ] Re-encode fallback working
- [ ] Clips cached in MinIO
- [ ] Cache cleanup task scheduled
- [ ] Padding applied correctly
- [ ] Max duration enforced
- [ ] ACL verified before generation
- [ ] >90% test coverage
