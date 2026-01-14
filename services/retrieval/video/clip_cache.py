"""Clip caching service for video clips.

This module provides the ClipCacheService for caching generated
video clips in MinIO with presigned URL generation.
"""

import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

from minio import Minio
from minio.error import S3Error

logger = logging.getLogger(__name__)


@dataclass
class ClipCacheConfig:
    """Configuration for clip cache.

    Attributes:
        minio_url: MinIO server URL.
        access_key: MinIO access key.
        secret_key: MinIO secret key.
        bucket_name: Bucket for clip storage.
        secure: Use HTTPS.
        cache_ttl_hours: Time to live for cached clips.
        presigned_url_expiry_hours: Presigned URL expiry time.
    """

    minio_url: str = ""
    access_key: str = ""
    secret_key: str = ""
    bucket_name: str = "rag-pipeline"
    secure: bool = False
    cache_ttl_hours: int = 24
    presigned_url_expiry_hours: int = 4

    def __post_init__(self):
        if not self.minio_url:
            self.minio_url = os.getenv("MINIO_URL", "localhost:9000")
        if not self.access_key:
            self.access_key = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
        if not self.secret_key:
            self.secret_key = os.getenv("MINIO_SECRET_KEY", "minioadmin")


@dataclass
class CachedClip:
    """Information about a cached clip.

    Attributes:
        exists: Whether clip exists in cache.
        object_path: Full path in MinIO.
        presigned_url: Presigned URL for access.
        size_bytes: File size.
        created_at: When clip was cached.
        expires_at: When cache entry expires.
    """

    exists: bool
    object_path: str = ""
    presigned_url: str | None = None
    size_bytes: int = 0
    created_at: datetime | None = None
    expires_at: datetime | None = None


class ClipCacheService:
    """Manages caching of video clips in MinIO.

    Handles storage, retrieval, and expiration of generated video
    clips with presigned URL generation for client access.

    Example:
        cache = ClipCacheService()
        cached = await cache.get_cached_clip(
            tenant_id=tenant_uuid,
            video_id=video_uuid,
            start_ms=30000,
            end_ms=60000,
        )
        if cached.exists:
            return cached.presigned_url
    """

    def __init__(self, config: ClipCacheConfig | None = None):
        """Initialize clip cache service.

        Args:
            config: Cache configuration.
        """
        self.config = config or ClipCacheConfig()
        self._client: Minio | None = None

    @property
    def client(self) -> Minio:
        """Get or create MinIO client."""
        if self._client is None:
            self._client = Minio(
                self.config.minio_url,
                access_key=self.config.access_key,
                secret_key=self.config.secret_key,
                secure=self.config.secure,
            )
        return self._client

    def _get_clip_path(
        self,
        tenant_id: UUID,
        video_id: UUID,
        start_ms: int,
        end_ms: int,
    ) -> str:
        """Generate cache path for a clip.

        Args:
            tenant_id: Tenant UUID.
            video_id: Video UUID.
            start_ms: Clip start time.
            end_ms: Clip end time.

        Returns:
            Object path in format: videos/{tenant_id}/clips/{video_id}/{start}_{end}.mp4
        """
        return f"videos/{tenant_id}/clips/{video_id}/{start_ms}_{end_ms}.mp4"

    async def get_cached_clip(
        self,
        tenant_id: UUID,
        video_id: UUID,
        start_ms: int,
        end_ms: int,
    ) -> CachedClip:
        """Check if a clip is cached and get presigned URL.

        Args:
            tenant_id: Tenant UUID.
            video_id: Video UUID.
            start_ms: Clip start time.
            end_ms: Clip end time.

        Returns:
            CachedClip with status and URL if exists.
        """
        object_path = self._get_clip_path(tenant_id, video_id, start_ms, end_ms)

        try:
            # Check if object exists
            stat = self.client.stat_object(
                self.config.bucket_name,
                object_path,
            )

            # Check if expired based on metadata or last modified
            created_at = stat.last_modified
            expires_at = created_at + timedelta(hours=self.config.cache_ttl_hours)

            if datetime.now(UTC) > expires_at:
                logger.info("Cached clip expired: %s", object_path)
                return CachedClip(exists=False)

            # Generate presigned URL
            presigned_url = self.client.presigned_get_object(
                self.config.bucket_name,
                object_path,
                expires=timedelta(hours=self.config.presigned_url_expiry_hours),
            )

            return CachedClip(
                exists=True,
                object_path=object_path,
                presigned_url=presigned_url,
                size_bytes=stat.size,
                created_at=created_at,
                expires_at=expires_at,
            )

        except S3Error as e:
            if e.code == "NoSuchKey":
                return CachedClip(exists=False)
            logger.warning("Cache check failed for %s: %s", object_path, e)
            return CachedClip(exists=False)
        except Exception as e:
            logger.warning("Cache check error for %s: %s", object_path, e)
            return CachedClip(exists=False)

    async def store_clip(
        self,
        tenant_id: UUID,
        video_id: UUID,
        start_ms: int,
        end_ms: int,
        local_path: Path,
    ) -> CachedClip:
        """Store a clip in the cache.

        Args:
            tenant_id: Tenant UUID.
            video_id: Video UUID.
            start_ms: Clip start time.
            end_ms: Clip end time.
            local_path: Path to local clip file.

        Returns:
            CachedClip with presigned URL.
        """
        object_path = self._get_clip_path(tenant_id, video_id, start_ms, end_ms)

        try:
            # Upload file
            self.client.fput_object(
                self.config.bucket_name,
                object_path,
                str(local_path),
                content_type="video/mp4",
            )

            # Get presigned URL
            presigned_url = self.client.presigned_get_object(
                self.config.bucket_name,
                object_path,
                expires=timedelta(hours=self.config.presigned_url_expiry_hours),
            )

            file_size = local_path.stat().st_size
            now = datetime.now(UTC)

            logger.info(
                "Cached clip: %s (%d bytes)",
                object_path,
                file_size,
            )

            return CachedClip(
                exists=True,
                object_path=object_path,
                presigned_url=presigned_url,
                size_bytes=file_size,
                created_at=now,
                expires_at=now + timedelta(hours=self.config.cache_ttl_hours),
            )

        except Exception as e:
            logger.error("Failed to cache clip %s: %s", object_path, e)
            return CachedClip(exists=False)

    async def delete_clip(
        self,
        tenant_id: UUID,
        video_id: UUID,
        start_ms: int,
        end_ms: int,
    ) -> bool:
        """Delete a cached clip.

        Args:
            tenant_id: Tenant UUID.
            video_id: Video UUID.
            start_ms: Clip start time.
            end_ms: Clip end time.

        Returns:
            True if deleted successfully.
        """
        object_path = self._get_clip_path(tenant_id, video_id, start_ms, end_ms)

        try:
            self.client.remove_object(
                self.config.bucket_name,
                object_path,
            )
            logger.info("Deleted cached clip: %s", object_path)
            return True
        except Exception as e:
            logger.warning("Failed to delete clip %s: %s", object_path, e)
            return False

    async def delete_video_clips(
        self,
        tenant_id: UUID,
        video_id: UUID,
    ) -> int:
        """Delete all cached clips for a video.

        Args:
            tenant_id: Tenant UUID.
            video_id: Video UUID.

        Returns:
            Number of clips deleted.
        """
        prefix = f"videos/{tenant_id}/clips/{video_id}/"
        deleted_count = 0

        try:
            objects = self.client.list_objects(
                self.config.bucket_name,
                prefix=prefix,
                recursive=True,
            )

            for obj in objects:
                try:
                    self.client.remove_object(
                        self.config.bucket_name,
                        obj.object_name,
                    )
                    deleted_count += 1
                except Exception as e:
                    logger.warning("Failed to delete %s: %s", obj.object_name, e)

            logger.info(
                "Deleted %d clips for video_id=%s",
                deleted_count,
                video_id,
            )
            return deleted_count

        except Exception as e:
            logger.error("Failed to list clips for deletion: %s", e)
            return deleted_count

    async def cleanup_expired_clips(self) -> dict:
        """Remove all expired clips from cache.

        Returns:
            Dict with cleanup statistics.
        """
        prefix = "videos/"
        deleted_count = 0
        checked_count = 0
        errors = 0

        try:
            objects = self.client.list_objects(
                self.config.bucket_name,
                prefix=prefix,
                recursive=True,
            )

            for obj in objects:
                # Only process clip files
                if "/clips/" not in obj.object_name:
                    continue

                checked_count += 1

                # Check if expired
                expires_at = obj.last_modified + timedelta(
                    hours=self.config.cache_ttl_hours
                )

                if datetime.now(UTC) > expires_at:
                    try:
                        self.client.remove_object(
                            self.config.bucket_name,
                            obj.object_name,
                        )
                        deleted_count += 1
                    except Exception as e:
                        logger.warning(
                            "Failed to delete expired clip %s: %s",
                            obj.object_name,
                            e,
                        )
                        errors += 1

            logger.info(
                "Clip cleanup complete: checked=%d, deleted=%d, errors=%d",
                checked_count,
                deleted_count,
                errors,
            )

            return {
                "checked": checked_count,
                "deleted": deleted_count,
                "errors": errors,
            }

        except Exception as e:
            logger.error("Clip cleanup failed: %s", e)
            return {
                "checked": checked_count,
                "deleted": deleted_count,
                "errors": errors + 1,
            }

    async def get_video_stream_url(
        self,
        tenant_id: UUID,
        video_id: UUID,
        video_path: str,
    ) -> str | None:
        """Get presigned URL for full video streaming.

        Args:
            tenant_id: Tenant UUID.
            video_id: Video UUID.
            video_path: Path to video in MinIO.

        Returns:
            Presigned URL or None if not found.
        """
        try:
            # Verify object exists
            self.client.stat_object(
                self.config.bucket_name,
                video_path,
            )

            # Generate presigned URL
            return self.client.presigned_get_object(
                self.config.bucket_name,
                video_path,
                expires=timedelta(hours=self.config.presigned_url_expiry_hours),
            )

        except S3Error as e:
            if e.code == "NoSuchKey":
                logger.warning("Video not found: %s", video_path)
            else:
                logger.error("Failed to get stream URL: %s", e)
            return None
        except Exception as e:
            logger.error("Stream URL error: %s", e)
            return None

    def get_cache_stats(self) -> dict:
        """Get cache statistics.

        Returns:
            Dict with cache stats.
        """
        prefix = "videos/"
        total_clips = 0
        total_size = 0

        try:
            objects = self.client.list_objects(
                self.config.bucket_name,
                prefix=prefix,
                recursive=True,
            )

            for obj in objects:
                if "/clips/" in obj.object_name:
                    total_clips += 1
                    total_size += obj.size

            return {
                "total_clips": total_clips,
                "total_size_bytes": total_size,
                "total_size_mb": round(total_size / (1024 * 1024), 2),
            }

        except Exception as e:
            logger.error("Failed to get cache stats: %s", e)
            return {
                "total_clips": 0,
                "total_size_bytes": 0,
                "error": str(e),
            }
