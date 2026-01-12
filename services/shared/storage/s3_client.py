"""
S3-compatible storage client wrapper for MinIO.

Provides a unified interface for file upload, download, and management
with support for presigned URLs and multi-tenant object naming.
"""

import hashlib
import os
from datetime import timedelta
from typing import BinaryIO

from minio import Minio
from minio.error import S3Error


class S3Storage:
    """S3-compatible storage client for MinIO."""

    def __init__(
        self,
        endpoint: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        secure: bool | None = None,
        default_bucket: str | None = None,
    ):
        """
        Initialize S3 storage client.

        Args:
            endpoint: MinIO endpoint (default from MINIO_ENDPOINT env var)
            access_key: Access key (default from MINIO_ACCESS_KEY env var)
            secret_key: Secret key (default from MINIO_SECRET_KEY env var)
            secure: Use HTTPS (default from MINIO_SECURE env var)
            default_bucket: Default bucket name (default from MINIO_DEFAULT_BUCKET env var)
        """
        self.endpoint = endpoint or os.getenv("MINIO_ENDPOINT", "localhost:9000")
        self.access_key = access_key or os.getenv("MINIO_ACCESS_KEY", "minioadmin")
        self.secret_key = secret_key or os.getenv("MINIO_SECRET_KEY", "minioadmin123")
        self.secure = (
            secure if secure is not None else os.getenv("MINIO_SECURE", "false").lower() == "true"
        )
        self.default_bucket = default_bucket or os.getenv("MINIO_DEFAULT_BUCKET", "documents")

        self.client = Minio(
            endpoint=self.endpoint,
            access_key=self.access_key,
            secret_key=self.secret_key,
            secure=self.secure,
        )

    def upload_file(
        self,
        file_data: BinaryIO,
        object_name: str,
        bucket_name: str | None = None,
        content_type: str = "application/octet-stream",
        metadata: dict | None = None,
    ) -> str:
        """
        Upload a file to S3.

        Args:
            file_data: File-like object containing the data to upload
            object_name: Name/path of the object in the bucket
            bucket_name: Target bucket (defaults to default_bucket)
            content_type: MIME type of the file
            metadata: Optional metadata to attach to the object

        Returns:
            S3 URI of the uploaded object (s3://bucket/object_name)
        """
        bucket = bucket_name or self.default_bucket

        # Get file size
        file_data.seek(0, 2)
        file_size = file_data.tell()
        file_data.seek(0)

        self.client.put_object(
            bucket_name=bucket,
            object_name=object_name,
            data=file_data,
            length=file_size,
            content_type=content_type,
            metadata=metadata or {},
        )

        return f"s3://{bucket}/{object_name}"

    def download_file(
        self,
        object_name: str,
        bucket_name: str | None = None,
    ) -> bytes:
        """
        Download a file from S3.

        Args:
            object_name: Name/path of the object in the bucket
            bucket_name: Source bucket (defaults to default_bucket)

        Returns:
            File contents as bytes
        """
        bucket = bucket_name or self.default_bucket

        response = self.client.get_object(bucket, object_name)
        try:
            data = response.read()
        finally:
            response.close()
            response.release_conn()

        return data

    def get_presigned_url(
        self,
        object_name: str,
        bucket_name: str | None = None,
        expires: int = 3600,
    ) -> str:
        """
        Generate a presigned URL for secure download.

        Args:
            object_name: Name/path of the object in the bucket
            bucket_name: Source bucket (defaults to default_bucket)
            expires: URL expiration time in seconds (default 1 hour)

        Returns:
            Presigned URL string
        """
        bucket = bucket_name or self.default_bucket

        return self.client.presigned_get_object(
            bucket_name=bucket,
            object_name=object_name,
            expires=timedelta(seconds=expires),
        )

    def get_presigned_upload_url(
        self,
        object_name: str,
        bucket_name: str | None = None,
        expires: int = 3600,
    ) -> str:
        """
        Generate a presigned URL for upload.

        Args:
            object_name: Name/path for the object to upload
            bucket_name: Target bucket (defaults to default_bucket)
            expires: URL expiration time in seconds (default 1 hour)

        Returns:
            Presigned URL string for PUT upload
        """
        bucket = bucket_name or self.default_bucket

        return self.client.presigned_put_object(
            bucket_name=bucket,
            object_name=object_name,
            expires=timedelta(seconds=expires),
        )

    def delete_file(
        self,
        object_name: str,
        bucket_name: str | None = None,
    ) -> None:
        """
        Delete a file from S3.

        Args:
            object_name: Name/path of the object to delete
            bucket_name: Source bucket (defaults to default_bucket)
        """
        bucket = bucket_name or self.default_bucket
        self.client.remove_object(bucket, object_name)

    def file_exists(
        self,
        object_name: str,
        bucket_name: str | None = None,
    ) -> bool:
        """
        Check if a file exists in S3.

        Args:
            object_name: Name/path of the object to check
            bucket_name: Source bucket (defaults to default_bucket)

        Returns:
            True if the file exists, False otherwise
        """
        bucket = bucket_name or self.default_bucket
        try:
            self.client.stat_object(bucket, object_name)
            return True
        except S3Error:
            return False

    def list_files(
        self,
        prefix: str = "",
        bucket_name: str | None = None,
        recursive: bool = True,
    ) -> list[dict]:
        """
        List files with a given prefix.

        Args:
            prefix: Object name prefix to filter by
            bucket_name: Source bucket (defaults to default_bucket)
            recursive: Whether to list recursively (default True)

        Returns:
            List of dicts with name, size, and last_modified for each object
        """
        bucket = bucket_name or self.default_bucket

        objects = self.client.list_objects(bucket, prefix=prefix, recursive=recursive)
        return [
            {
                "name": obj.object_name,
                "size": obj.size,
                "last_modified": obj.last_modified,
            }
            for obj in objects
        ]

    def get_file_info(
        self,
        object_name: str,
        bucket_name: str | None = None,
    ) -> dict:
        """
        Get metadata for a file.

        Args:
            object_name: Name/path of the object
            bucket_name: Source bucket (defaults to default_bucket)

        Returns:
            Dict with size, last_modified, content_type, and metadata
        """
        bucket = bucket_name or self.default_bucket
        stat = self.client.stat_object(bucket, object_name)
        return {
            "name": stat.object_name,
            "size": stat.size,
            "last_modified": stat.last_modified,
            "content_type": stat.content_type,
            "metadata": stat.metadata,
        }

    @staticmethod
    def generate_object_name(
        tenant_id: str,
        filename: str,
        document_id: str | None = None,
    ) -> str:
        """
        Generate a structured object name for multi-tenant storage.

        Args:
            tenant_id: Tenant identifier for namespace isolation
            filename: Original filename
            document_id: Optional document ID for grouping

        Returns:
            Structured object path like "tenant_id/doc_id/filename"
            or "tenant_id/hash_filename" if no document_id
        """
        if document_id:
            return f"{tenant_id}/{document_id}/{filename}"

        # Generate hash for deduplication
        hash_val = hashlib.md5(filename.encode()).hexdigest()[:8]  # noqa: S324
        return f"{tenant_id}/{hash_val}_{filename}"

    def ensure_bucket_exists(
        self,
        bucket_name: str | None = None,
    ) -> bool:
        """
        Ensure a bucket exists, creating it if necessary.

        Args:
            bucket_name: Bucket to check/create (defaults to default_bucket)

        Returns:
            True if bucket exists or was created, False on error
        """
        bucket = bucket_name or self.default_bucket
        try:
            if not self.client.bucket_exists(bucket):
                self.client.make_bucket(bucket)
            return True
        except S3Error:
            return False

    def health_check(self) -> bool:
        """
        Check S3 connectivity.

        Returns:
            True if MinIO is accessible, False otherwise
        """
        try:
            self.client.list_buckets()
            return True
        except Exception:
            return False
