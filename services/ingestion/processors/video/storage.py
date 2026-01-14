"""
Video storage service for MinIO operations.

This module provides video-specific storage operations including
upload, download, presigned URL generation, and path management.
"""

import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import BinaryIO
from uuid import UUID

from minio import Minio
from minio.error import S3Error
from processors.video.exceptions import VideoStorageError

logger = logging.getLogger(__name__)


@dataclass
class VideoStorageConfig:
    """Configuration for video storage.

    Attributes:
        endpoint: MinIO endpoint URL.
        access_key: MinIO access key.
        secret_key: MinIO secret key.
        secure: Whether to use HTTPS.
        bucket: Default bucket name for videos.
        presigned_url_expiry_hours: Presigned URL expiration time.
    """

    endpoint: str = field(default_factory=lambda: os.getenv("MINIO_ENDPOINT", "localhost:9000"))
    access_key: str = field(default_factory=lambda: os.getenv("MINIO_ACCESS_KEY", "minioadmin"))
    secret_key: str = field(default_factory=lambda: os.getenv("MINIO_SECRET_KEY", "minioadmin123"))
    secure: bool = field(
        default_factory=lambda: os.getenv("MINIO_SECURE", "false").lower() == "true"
    )
    bucket: str = field(default_factory=lambda: os.getenv("MINIO_VIDEO_BUCKET", "videos"))
    presigned_url_expiry_hours: int = 4


class VideoStorage:
    """Video storage service for MinIO operations.

    Provides video-specific storage operations with structured path
    management for multi-tenant video storage.

    Storage structure:
        videos/
        ├── {tenant_id}/
        │   ├── originals/{video_id}.{ext}
        │   ├── audio/{video_id}.wav
        │   ├── keyframes/{video_id}/{index:05d}.jpg
        │   ├── thumbnails/{video_id}/{index:05d}_thumb.jpg
        │   └── clips/{video_id}/{start_ms}_{end_ms}.mp4

    Example:
        storage = VideoStorage()
        path = await storage.upload_video(file, tenant_id, video_id, "video.mp4")
        url = storage.get_streaming_url(tenant_id, video_id, "mp4")
    """

    def __init__(self, config: VideoStorageConfig | None = None):
        """Initialize video storage.

        Args:
            config: Storage configuration. If None, uses environment variables.
        """
        self.config = config or VideoStorageConfig()
        self._client: Minio | None = None

    @property
    def client(self) -> Minio:
        """Get or create MinIO client."""
        if self._client is None:
            self._client = Minio(
                endpoint=self.config.endpoint,
                access_key=self.config.access_key,
                secret_key=self.config.secret_key,
                secure=self.config.secure,
            )
        return self._client

    async def ensure_bucket_exists(self) -> None:
        """Ensure the video bucket exists.

        Raises:
            VideoStorageError: If bucket creation fails.
        """
        try:
            if not self.client.bucket_exists(self.config.bucket):
                self.client.make_bucket(self.config.bucket)
                logger.info("Created video bucket: %s", self.config.bucket)
        except S3Error as e:
            raise VideoStorageError(
                f"Failed to create bucket: {e}",
                details={"bucket": self.config.bucket, "error": str(e)},
            ) from e

    # Path generation methods
    def _original_path(self, tenant_id: UUID | str, video_id: UUID | str, extension: str) -> str:
        """Generate path for original video file."""
        ext = extension.lstrip(".")
        return f"{tenant_id}/originals/{video_id}.{ext}"

    def _audio_path(self, tenant_id: UUID | str, video_id: UUID | str) -> str:
        """Generate path for extracted audio file."""
        return f"{tenant_id}/audio/{video_id}.wav"

    def _keyframe_path(
        self, tenant_id: UUID | str, video_id: UUID | str, frame_index: int
    ) -> str:
        """Generate path for keyframe image."""
        return f"{tenant_id}/keyframes/{video_id}/{frame_index:05d}.jpg"

    def _thumbnail_path(
        self, tenant_id: UUID | str, video_id: UUID | str, frame_index: int
    ) -> str:
        """Generate path for keyframe thumbnail."""
        return f"{tenant_id}/thumbnails/{video_id}/{frame_index:05d}_thumb.jpg"

    def _video_thumbnail_path(self, tenant_id: UUID | str, video_id: UUID | str) -> str:
        """Generate path for video thumbnail (first frame)."""
        return f"{tenant_id}/thumbnails/{video_id}/video_thumb.jpg"

    def _clip_path(
        self, tenant_id: UUID | str, video_id: UUID | str, start_ms: int, end_ms: int
    ) -> str:
        """Generate path for video clip."""
        return f"{tenant_id}/clips/{video_id}/{start_ms}_{end_ms}.mp4"

    # Upload methods
    async def upload_video(
        self,
        file_data: BinaryIO,
        tenant_id: UUID | str,
        video_id: UUID | str,
        filename: str,
        content_type: str = "video/mp4",
    ) -> str:
        """Upload original video file.

        Args:
            file_data: File-like object containing video data.
            tenant_id: Tenant identifier.
            video_id: Video identifier.
            filename: Original filename.
            content_type: MIME type of the video.

        Returns:
            Storage path of the uploaded video.

        Raises:
            VideoStorageError: If upload fails.
        """
        extension = Path(filename).suffix or ".mp4"
        object_name = self._original_path(tenant_id, video_id, extension)

        try:
            # Get file size
            file_data.seek(0, 2)
            file_size = file_data.tell()
            file_data.seek(0)

            self.client.put_object(
                bucket_name=self.config.bucket,
                object_name=object_name,
                data=file_data,
                length=file_size,
                content_type=content_type,
            )

            logger.info(
                "Uploaded video: %s (%d bytes)",
                object_name,
                file_size,
            )
            return object_name

        except S3Error as e:
            raise VideoStorageError(
                f"Failed to upload video: {e}",
                video_id=str(video_id),
                details={"object_name": object_name, "error": str(e)},
            ) from e

    async def upload_audio(
        self,
        file_path: Path,
        tenant_id: UUID | str,
        video_id: UUID | str,
    ) -> str:
        """Upload extracted audio file.

        Args:
            file_path: Local path to audio file.
            tenant_id: Tenant identifier.
            video_id: Video identifier.

        Returns:
            Storage path of the uploaded audio.

        Raises:
            VideoStorageError: If upload fails.
        """
        object_name = self._audio_path(tenant_id, video_id)

        try:
            self.client.fput_object(
                bucket_name=self.config.bucket,
                object_name=object_name,
                file_path=str(file_path),
                content_type="audio/wav",
            )
            logger.info("Uploaded audio: %s", object_name)
            return object_name

        except S3Error as e:
            raise VideoStorageError(
                f"Failed to upload audio: {e}",
                video_id=str(video_id),
                details={"object_name": object_name, "error": str(e)},
            ) from e

    async def upload_keyframe(
        self,
        file_path: Path,
        tenant_id: UUID | str,
        video_id: UUID | str,
        frame_index: int,
    ) -> str:
        """Upload keyframe image.

        Args:
            file_path: Local path to keyframe image.
            tenant_id: Tenant identifier.
            video_id: Video identifier.
            frame_index: Index of the keyframe.

        Returns:
            Storage path of the uploaded keyframe.

        Raises:
            VideoStorageError: If upload fails.
        """
        object_name = self._keyframe_path(tenant_id, video_id, frame_index)

        try:
            self.client.fput_object(
                bucket_name=self.config.bucket,
                object_name=object_name,
                file_path=str(file_path),
                content_type="image/jpeg",
            )
            logger.info("Uploaded keyframe: %s", object_name)
            return object_name

        except S3Error as e:
            raise VideoStorageError(
                f"Failed to upload keyframe: {e}",
                video_id=str(video_id),
                details={
                    "object_name": object_name,
                    "frame_index": frame_index,
                    "error": str(e),
                },
            ) from e

    async def upload_thumbnail(
        self,
        file_path: Path,
        tenant_id: UUID | str,
        video_id: UUID | str,
        frame_index: int,
    ) -> str:
        """Upload keyframe thumbnail.

        Args:
            file_path: Local path to thumbnail image.
            tenant_id: Tenant identifier.
            video_id: Video identifier.
            frame_index: Index of the keyframe.

        Returns:
            Storage path of the uploaded thumbnail.

        Raises:
            VideoStorageError: If upload fails.
        """
        object_name = self._thumbnail_path(tenant_id, video_id, frame_index)

        try:
            self.client.fput_object(
                bucket_name=self.config.bucket,
                object_name=object_name,
                file_path=str(file_path),
                content_type="image/jpeg",
            )
            logger.info("Uploaded thumbnail: %s", object_name)
            return object_name

        except S3Error as e:
            raise VideoStorageError(
                f"Failed to upload thumbnail: {e}",
                video_id=str(video_id),
                details={
                    "object_name": object_name,
                    "frame_index": frame_index,
                    "error": str(e),
                },
            ) from e

    async def upload_video_thumbnail(
        self,
        file_path: Path,
        tenant_id: UUID | str,
        video_id: UUID | str,
    ) -> str:
        """Upload video thumbnail (main preview image).

        Args:
            file_path: Local path to thumbnail image.
            tenant_id: Tenant identifier.
            video_id: Video identifier.

        Returns:
            Storage path of the uploaded thumbnail.

        Raises:
            VideoStorageError: If upload fails.
        """
        object_name = self._video_thumbnail_path(tenant_id, video_id)

        try:
            self.client.fput_object(
                bucket_name=self.config.bucket,
                object_name=object_name,
                file_path=str(file_path),
                content_type="image/jpeg",
            )
            logger.info("Uploaded video thumbnail: %s", object_name)
            return object_name

        except S3Error as e:
            raise VideoStorageError(
                f"Failed to upload video thumbnail: {e}",
                video_id=str(video_id),
                details={"object_name": object_name, "error": str(e)},
            ) from e

    async def upload_clip(
        self,
        file_path: Path,
        tenant_id: UUID | str,
        video_id: UUID | str,
        start_ms: int,
        end_ms: int,
    ) -> str:
        """Upload video clip.

        Args:
            file_path: Local path to clip file.
            tenant_id: Tenant identifier.
            video_id: Video identifier.
            start_ms: Clip start time in milliseconds.
            end_ms: Clip end time in milliseconds.

        Returns:
            Storage path of the uploaded clip.

        Raises:
            VideoStorageError: If upload fails.
        """
        object_name = self._clip_path(tenant_id, video_id, start_ms, end_ms)

        try:
            self.client.fput_object(
                bucket_name=self.config.bucket,
                object_name=object_name,
                file_path=str(file_path),
                content_type="video/mp4",
            )
            logger.info("Uploaded clip: %s", object_name)
            return object_name

        except S3Error as e:
            raise VideoStorageError(
                f"Failed to upload clip: {e}",
                video_id=str(video_id),
                details={
                    "object_name": object_name,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "error": str(e),
                },
            ) from e

    # Download methods
    async def download_video(
        self,
        tenant_id: UUID | str,
        video_id: UUID | str,
        extension: str = "mp4",
    ) -> Path:
        """Download video to a temporary file.

        Args:
            tenant_id: Tenant identifier.
            video_id: Video identifier.
            extension: File extension.

        Returns:
            Path to the downloaded temporary file.

        Raises:
            VideoStorageError: If download fails.
        """
        object_name = self._original_path(tenant_id, video_id, extension)
        return await self._download_to_temp(object_name, f".{extension.lstrip('.')}")

    async def download_audio(
        self,
        tenant_id: UUID | str,
        video_id: UUID | str,
    ) -> Path:
        """Download audio to a temporary file.

        Args:
            tenant_id: Tenant identifier.
            video_id: Video identifier.

        Returns:
            Path to the downloaded temporary file.

        Raises:
            VideoStorageError: If download fails.
        """
        object_name = self._audio_path(tenant_id, video_id)
        return await self._download_to_temp(object_name, ".wav")

    async def download_keyframe(
        self,
        tenant_id: UUID | str,
        video_id: UUID | str,
        frame_index: int,
    ) -> Path:
        """Download keyframe to a temporary file.

        Args:
            tenant_id: Tenant identifier.
            video_id: Video identifier.
            frame_index: Keyframe index.

        Returns:
            Path to the downloaded temporary file.

        Raises:
            VideoStorageError: If download fails.
        """
        object_name = self._keyframe_path(tenant_id, video_id, frame_index)
        return await self._download_to_temp(object_name, ".jpg")

    async def _download_to_temp(self, object_name: str, suffix: str) -> Path:
        """Download object to a temporary file.

        Args:
            object_name: Object path in storage.
            suffix: File suffix for temp file.

        Returns:
            Path to the temporary file.

        Raises:
            VideoStorageError: If download fails.
        """
        try:
            # Create temp file
            fd, temp_path = tempfile.mkstemp(suffix=suffix)
            os.close(fd)

            self.client.fget_object(
                bucket_name=self.config.bucket,
                object_name=object_name,
                file_path=temp_path,
            )

            logger.info("Downloaded to temp: %s -> %s", object_name, temp_path)
            return Path(temp_path)

        except S3Error as e:
            raise VideoStorageError(
                f"Failed to download: {e}",
                details={"object_name": object_name, "error": str(e)},
            ) from e

    # URL generation methods
    def get_streaming_url(
        self,
        tenant_id: UUID | str,
        video_id: UUID | str,
        extension: str = "mp4",
        expires_hours: int | None = None,
    ) -> str:
        """Get presigned URL for video streaming.

        Args:
            tenant_id: Tenant identifier.
            video_id: Video identifier.
            extension: File extension.
            expires_hours: URL expiration (default from config).

        Returns:
            Presigned URL for video streaming.

        Raises:
            VideoStorageError: If URL generation fails.
        """
        object_name = self._original_path(tenant_id, video_id, extension)
        expiry = expires_hours or self.config.presigned_url_expiry_hours
        return self._get_presigned_url(object_name, expiry)

    def get_keyframe_url(
        self,
        tenant_id: UUID | str,
        video_id: UUID | str,
        frame_index: int,
        expires_hours: int | None = None,
    ) -> str:
        """Get presigned URL for keyframe.

        Args:
            tenant_id: Tenant identifier.
            video_id: Video identifier.
            frame_index: Keyframe index.
            expires_hours: URL expiration (default from config).

        Returns:
            Presigned URL for keyframe image.
        """
        object_name = self._keyframe_path(tenant_id, video_id, frame_index)
        expiry = expires_hours or self.config.presigned_url_expiry_hours
        return self._get_presigned_url(object_name, expiry)

    def get_thumbnail_url(
        self,
        tenant_id: UUID | str,
        video_id: UUID | str,
        frame_index: int,
        expires_hours: int | None = None,
    ) -> str:
        """Get presigned URL for thumbnail.

        Args:
            tenant_id: Tenant identifier.
            video_id: Video identifier.
            frame_index: Keyframe index.
            expires_hours: URL expiration (default from config).

        Returns:
            Presigned URL for thumbnail image.
        """
        object_name = self._thumbnail_path(tenant_id, video_id, frame_index)
        expiry = expires_hours or self.config.presigned_url_expiry_hours
        return self._get_presigned_url(object_name, expiry)

    def get_video_thumbnail_url(
        self,
        tenant_id: UUID | str,
        video_id: UUID | str,
        expires_hours: int | None = None,
    ) -> str:
        """Get presigned URL for video thumbnail.

        Args:
            tenant_id: Tenant identifier.
            video_id: Video identifier.
            expires_hours: URL expiration (default from config).

        Returns:
            Presigned URL for video thumbnail.
        """
        object_name = self._video_thumbnail_path(tenant_id, video_id)
        expiry = expires_hours or self.config.presigned_url_expiry_hours
        return self._get_presigned_url(object_name, expiry)

    def get_clip_url(
        self,
        tenant_id: UUID | str,
        video_id: UUID | str,
        start_ms: int,
        end_ms: int,
        expires_hours: int | None = None,
    ) -> str:
        """Get presigned URL for video clip.

        Args:
            tenant_id: Tenant identifier.
            video_id: Video identifier.
            start_ms: Clip start time in milliseconds.
            end_ms: Clip end time in milliseconds.
            expires_hours: URL expiration (default from config).

        Returns:
            Presigned URL for video clip.
        """
        object_name = self._clip_path(tenant_id, video_id, start_ms, end_ms)
        expiry = expires_hours or self.config.presigned_url_expiry_hours
        return self._get_presigned_url(object_name, expiry)

    def get_presigned_upload_url(
        self,
        tenant_id: UUID | str,
        video_id: UUID | str,
        extension: str = "mp4",
        expires_hours: int = 1,
    ) -> str:
        """Get presigned URL for direct upload.

        Args:
            tenant_id: Tenant identifier.
            video_id: Video identifier.
            extension: File extension.
            expires_hours: URL expiration (default 1 hour).

        Returns:
            Presigned URL for PUT upload.

        Raises:
            VideoStorageError: If URL generation fails.
        """
        object_name = self._original_path(tenant_id, video_id, extension)

        try:
            return self.client.presigned_put_object(
                bucket_name=self.config.bucket,
                object_name=object_name,
                expires=timedelta(hours=expires_hours),
            )
        except S3Error as e:
            raise VideoStorageError(
                f"Failed to generate upload URL: {e}",
                video_id=str(video_id),
                details={"object_name": object_name, "error": str(e)},
            ) from e

    def _get_presigned_url(self, object_name: str, expires_hours: int) -> str:
        """Generate presigned URL for an object.

        Args:
            object_name: Object path in storage.
            expires_hours: URL expiration in hours.

        Returns:
            Presigned URL string.

        Raises:
            VideoStorageError: If URL generation fails.
        """
        try:
            return self.client.presigned_get_object(
                bucket_name=self.config.bucket,
                object_name=object_name,
                expires=timedelta(hours=expires_hours),
            )
        except S3Error as e:
            raise VideoStorageError(
                f"Failed to generate presigned URL: {e}",
                details={"object_name": object_name, "error": str(e)},
            ) from e

    # Deletion methods
    async def delete_video_files(
        self,
        tenant_id: UUID | str,
        video_id: UUID | str,
        extension: str = "mp4",
    ) -> dict:
        """Delete all files associated with a video.

        Args:
            tenant_id: Tenant identifier.
            video_id: Video identifier.
            extension: Video file extension.

        Returns:
            Dict with counts of deleted files by type.
        """
        deleted = {"originals": 0, "audio": 0, "keyframes": 0, "thumbnails": 0, "clips": 0}

        # Delete original
        try:
            self.client.remove_object(
                self.config.bucket,
                self._original_path(tenant_id, video_id, extension),
            )
            deleted["originals"] = 1
        except S3Error:
            pass

        # Delete audio
        try:
            self.client.remove_object(
                self.config.bucket,
                self._audio_path(tenant_id, video_id),
            )
            deleted["audio"] = 1
        except S3Error:
            pass

        # Delete keyframes and thumbnails (list by prefix)
        keyframe_prefix = f"{tenant_id}/keyframes/{video_id}/"
        thumbnail_prefix = f"{tenant_id}/thumbnails/{video_id}/"
        clip_prefix = f"{tenant_id}/clips/{video_id}/"

        for prefix, key in [
            (keyframe_prefix, "keyframes"),
            (thumbnail_prefix, "thumbnails"),
            (clip_prefix, "clips"),
        ]:
            try:
                objects = self.client.list_objects(
                    self.config.bucket,
                    prefix=prefix,
                    recursive=True,
                )
                for obj in objects:
                    self.client.remove_object(self.config.bucket, obj.object_name)
                    deleted[key] += 1
            except S3Error as e:
                logger.warning("Failed to delete %s: %s", prefix, e)

        logger.info(
            "Deleted video files for %s: %s",
            video_id,
            deleted,
        )
        return deleted

    # Utility methods
    def file_exists(
        self,
        tenant_id: UUID | str,
        video_id: UUID | str,
        extension: str = "mp4",
    ) -> bool:
        """Check if original video file exists.

        Args:
            tenant_id: Tenant identifier.
            video_id: Video identifier.
            extension: File extension.

        Returns:
            True if file exists.
        """
        object_name = self._original_path(tenant_id, video_id, extension)
        try:
            self.client.stat_object(self.config.bucket, object_name)
            return True
        except S3Error:
            return False

    def clip_exists(
        self,
        tenant_id: UUID | str,
        video_id: UUID | str,
        start_ms: int,
        end_ms: int,
    ) -> bool:
        """Check if a clip exists in cache.

        Args:
            tenant_id: Tenant identifier.
            video_id: Video identifier.
            start_ms: Clip start time.
            end_ms: Clip end time.

        Returns:
            True if clip exists.
        """
        object_name = self._clip_path(tenant_id, video_id, start_ms, end_ms)
        try:
            self.client.stat_object(self.config.bucket, object_name)
            return True
        except S3Error:
            return False

    async def health_check(self) -> bool:
        """Check storage connectivity.

        Returns:
            True if MinIO is accessible.
        """
        try:
            self.client.list_buckets()
            return True
        except Exception:
            return False
