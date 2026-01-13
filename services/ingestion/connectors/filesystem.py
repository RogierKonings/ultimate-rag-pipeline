"""Filesystem connector for local and S3-compatible storage.

This module provides a connector for ingesting documents from local
filesystem and S3-compatible storage (including MinIO).
"""

import mimetypes
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Literal

import aioboto3
import aiofiles
import aiofiles.os
from pydantic import BaseModel, Field

from .base import (
    BaseConnector,
    DocumentMetadata,
    RawDocument,
)

# Try to import python-magic for better MIME type detection
try:
    import magic

    HAS_MAGIC = True
except ImportError:
    HAS_MAGIC = False

# Register additional MIME types not in the standard library
mimetypes.add_type("text/markdown", ".md")
mimetypes.add_type("text/markdown", ".markdown")


class FilesystemConnectorConfig(BaseModel):
    """Configuration for the filesystem connector.

    Supports both local filesystem and S3-compatible storage like MinIO.
    """

    base_path: str = Field(
        ...,
        description="Base path for local storage or bucket name for S3",
    )
    storage_type: Literal["local", "s3"] = Field(
        default="local",
        description="Type of storage backend",
    )
    s3_endpoint: str | None = Field(
        default=None,
        description="S3/MinIO endpoint URL (e.g., 'http://localhost:9000')",
    )
    s3_access_key: str | None = Field(
        default=None,
        description="S3 access key ID",
    )
    s3_secret_key: str | None = Field(
        default=None,
        description="S3 secret access key",
    )
    s3_bucket: str | None = Field(
        default=None,
        description="S3 bucket name (overrides base_path for S3)",
    )
    s3_region: str | None = Field(
        default="us-east-1",
        description="S3 region name",
    )
    recursive: bool = Field(
        default=True,
        description="Whether to scan directories recursively",
    )
    file_extensions: list[str] | None = Field(
        default=None,
        description="List of file extensions to include (e.g., ['.pdf', '.docx'])",
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "base_path": "/data/documents",
                    "storage_type": "local",
                    "recursive": True,
                    "file_extensions": [".pdf", ".docx", ".txt"],
                },
                {
                    "base_path": "documents",
                    "storage_type": "s3",
                    "s3_endpoint": "http://localhost:9000",
                    "s3_access_key": "minioadmin",
                    "s3_secret_key": "minioadmin123",
                    "s3_bucket": "documents",
                    "s3_region": "us-east-1",
                },
            ],
        },
    }


class FilesystemConnector(BaseConnector):
    """Connector for local filesystem and S3-compatible storage.

    Supports reading documents from:
    - Local filesystem with async I/O (via aiofiles)
    - S3-compatible storage including MinIO (via aioboto3)

    Example:
        ```python
        # Local filesystem
        config = FilesystemConnectorConfig(
            base_path="/data/documents",
            storage_type="local",
            file_extensions=[".pdf", ".txt"]
        )
        async with FilesystemConnector(config) as connector:
            async for doc in connector.stream_documents():
                print(f"Loaded: {doc.metadata.filename}")

        # S3/MinIO
        config = FilesystemConnectorConfig(
            base_path="my-bucket",
            storage_type="s3",
            s3_endpoint="http://localhost:9000",
            s3_access_key="minioadmin",
            s3_secret_key="secret"
        )
        async with FilesystemConnector(config) as connector:
            async for doc in connector.stream_documents("prefix/"):
                process(doc)
        ```
    """

    def __init__(self, config: FilesystemConnectorConfig):
        """Initialize the filesystem connector.

        Args:
            config: Configuration for the connector.
        """
        self.config = config
        self._session: aioboto3.Session | None = None
        self._s3_client = None
        self._connected = False

    async def connect(self) -> None:
        """Establish connection to the storage backend.

        For local storage, this validates the base path exists.
        For S3, this initializes the aioboto3 session and client.

        Raises:
            ConnectionError: If the storage backend is not accessible.
        """
        if self.config.storage_type == "local":
            base = Path(self.config.base_path)
            if not base.exists():
                raise ConnectionError(
                    f"Base path does not exist: {self.config.base_path}",
                )
            self._connected = True
        else:
            # S3 storage
            self._session = aioboto3.Session()
            try:
                # Test connection by listing bucket
                async with self._session.client(
                    "s3",
                    endpoint_url=self.config.s3_endpoint,
                    aws_access_key_id=self.config.s3_access_key,
                    aws_secret_access_key=self.config.s3_secret_key,
                    region_name=self.config.s3_region,
                ) as client:
                    bucket = self.config.s3_bucket or self.config.base_path
                    await client.head_bucket(Bucket=bucket)
            except Exception as e:
                raise ConnectionError(f"Failed to connect to S3: {e}") from e
            self._connected = True

    async def disconnect(self) -> None:
        """Close connection to the storage backend.

        For S3, this cleans up the session.
        """
        self._session = None
        self._s3_client = None
        self._connected = False

    def _should_include_file(self, filename: str) -> bool:
        """Check if a file should be included based on extension filter.

        Args:
            filename: Name of the file to check.

        Returns:
            True if the file should be included, False otherwise.
        """
        if self.config.file_extensions is None:
            return True
        ext = Path(filename).suffix.lower()
        return ext in [e.lower() for e in self.config.file_extensions]

    def _detect_mime_type(self, content: bytes, filename: str | None = None) -> str:
        """Detect the MIME type of file content.

        Uses python-magic if available, falls back to mimetypes.

        Args:
            content: File content as bytes.
            filename: Optional filename for extension-based detection.

        Returns:
            MIME type string.
        """
        if HAS_MAGIC:
            try:
                return magic.from_buffer(content, mime=True)
            except Exception:  # noqa: S110
                pass

        if filename:
            mime_type, _ = mimetypes.guess_type(filename)
            if mime_type:
                return mime_type

        return "application/octet-stream"

    async def _list_local_files(
        self,
        path: str | None = None,
    ) -> AsyncIterator[DocumentMetadata]:
        """List files from local filesystem.

        Args:
            path: Optional subdirectory to list.

        Yields:
            DocumentMetadata for each file found.
        """
        base = Path(self.config.base_path)
        if path:
            base = base / path

        if not base.exists():
            return

        if base.is_file():
            if self._should_include_file(base.name):
                stat = await aiofiles.os.stat(base)
                yield DocumentMetadata(
                    source_id=str(base.relative_to(self.config.base_path)),
                    source_type="local",
                    filename=base.name,
                    created_at=datetime.fromtimestamp(stat.st_ctime, tz=UTC),
                    modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                    size_bytes=stat.st_size,
                    extra={"absolute_path": str(base.absolute())},
                )
            return

        # Directory traversal
        if self.config.recursive:
            for item in base.rglob("*"):
                if item.is_file() and self._should_include_file(item.name):
                    stat = await aiofiles.os.stat(item)
                    yield DocumentMetadata(
                        source_id=str(item.relative_to(self.config.base_path)),
                        source_type="local",
                        filename=item.name,
                        created_at=datetime.fromtimestamp(stat.st_ctime, tz=UTC),
                        modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                        size_bytes=stat.st_size,
                        extra={"absolute_path": str(item.absolute())},
                    )
        else:
            for item in base.iterdir():
                if item.is_file() and self._should_include_file(item.name):
                    stat = await aiofiles.os.stat(item)
                    yield DocumentMetadata(
                        source_id=str(item.relative_to(self.config.base_path)),
                        source_type="local",
                        filename=item.name,
                        created_at=datetime.fromtimestamp(stat.st_ctime, tz=UTC),
                        modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
                        size_bytes=stat.st_size,
                        extra={"absolute_path": str(item.absolute())},
                    )

    async def _list_s3_files(
        self,
        path: str | None = None,
    ) -> AsyncIterator[DocumentMetadata]:
        """List files from S3-compatible storage.

        Args:
            path: Optional prefix to filter objects. If not provided,
                  uses base_path from config as the default prefix.

        Yields:
            DocumentMetadata for each object found.
        """
        bucket = self.config.s3_bucket or self.config.base_path
        # Use base_path as default prefix when path not specified
        prefix = path if path is not None else self.config.base_path

        async with self._session.client(
            "s3",
            endpoint_url=self.config.s3_endpoint,
            aws_access_key_id=self.config.s3_access_key,
            aws_secret_access_key=self.config.s3_secret_key,
            region_name=self.config.s3_region,
        ) as client:
            paginator = client.get_paginator("list_objects_v2")
            async for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    filename = key.split("/")[-1] if "/" in key else key

                    # Skip "directory" markers
                    if key.endswith("/"):
                        continue

                    if not self._should_include_file(filename):
                        continue

                    yield DocumentMetadata(
                        source_id=key,
                        source_type="s3",
                        filename=filename,
                        modified_at=obj.get("LastModified"),
                        size_bytes=obj.get("Size"),
                        extra={
                            "bucket": bucket,
                            "etag": obj.get("ETag", "").strip('"'),
                            "storage_class": obj.get("StorageClass"),
                        },
                    )

    async def list_documents(
        self,
        path: str | None = None,
    ) -> AsyncIterator[DocumentMetadata]:
        """List available documents at the given path.

        Args:
            path: For local storage, a subdirectory path.
                  For S3, an object key prefix.

        Yields:
            DocumentMetadata for each document found.

        Raises:
            ConnectionError: If not connected to the storage backend.
        """
        if not self._connected:
            raise ConnectionError("Connector is not connected. Call connect() first.")

        if self.config.storage_type == "local":
            async for meta in self._list_local_files(path):
                yield meta
        else:
            async for meta in self._list_s3_files(path):
                yield meta

    async def _fetch_local_document(self, source_id: str) -> RawDocument:
        """Fetch a document from local filesystem.

        Args:
            source_id: Relative path to the file.

        Returns:
            RawDocument with content and metadata.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        file_path = Path(self.config.base_path) / source_id

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {source_id}")

        if not file_path.is_file():
            raise FileNotFoundError(f"Not a file: {source_id}")

        async with aiofiles.open(file_path, "rb") as f:
            content = await f.read()

        stat = await aiofiles.os.stat(file_path)
        mime_type = self._detect_mime_type(content, file_path.name)

        metadata = DocumentMetadata(
            source_id=source_id,
            source_type="local",
            filename=file_path.name,
            mime_type=mime_type,
            created_at=datetime.fromtimestamp(stat.st_ctime, tz=UTC),
            modified_at=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
            size_bytes=len(content),
            extra={"absolute_path": str(file_path.absolute())},
        )

        return RawDocument(content=content, metadata=metadata)

    async def _fetch_s3_document(self, source_id: str) -> RawDocument:
        """Fetch a document from S3-compatible storage.

        Args:
            source_id: Object key in the bucket.

        Returns:
            RawDocument with content and metadata.

        Raises:
            FileNotFoundError: If the object does not exist.
        """
        bucket = self.config.s3_bucket or self.config.base_path

        async with self._session.client(
            "s3",
            endpoint_url=self.config.s3_endpoint,
            aws_access_key_id=self.config.s3_access_key,
            aws_secret_access_key=self.config.s3_secret_key,
            region_name=self.config.s3_region,
        ) as client:
            try:
                # Get object content
                buffer = BytesIO()
                await client.download_fileobj(
                    Bucket=bucket,
                    Key=source_id,
                    Fileobj=buffer,
                )
                content = buffer.getvalue()

                # Get object metadata
                head = await client.head_object(Bucket=bucket, Key=source_id)

            except client.exceptions.NoSuchKey:
                raise FileNotFoundError(f"Object not found: {source_id}") from None
            except Exception as e:
                if "NoSuchKey" in str(e) or "404" in str(e):
                    raise FileNotFoundError(f"Object not found: {source_id}") from e
                raise

        # Prefer original filename from S3 metadata if available
        s3_metadata = head.get("Metadata", {})
        original_filename = s3_metadata.get("original-filename")
        if original_filename:
            filename = original_filename
        else:
            # Fall back to extracting from S3 key
            key_filename = source_id.split("/")[-1] if "/" in source_id else source_id
            # Strip timestamp prefix if present (format: {timestamp}-{filename})
            if "-" in key_filename and key_filename.split("-")[0].isdigit():
                filename = key_filename.split("-", 1)[1]
            else:
                filename = key_filename
        mime_type = head.get("ContentType") or self._detect_mime_type(content, filename)

        metadata = DocumentMetadata(
            source_id=source_id,
            source_type="s3",
            filename=filename,
            mime_type=mime_type,
            modified_at=head.get("LastModified"),
            size_bytes=len(content),
            extra={
                "bucket": bucket,
                "etag": head.get("ETag", "").strip('"'),
                "content_encoding": head.get("ContentEncoding"),
                "version_id": head.get("VersionId"),
                "original_filename": original_filename,
                "s3_key": source_id,
            },
        )

        return RawDocument(content=content, metadata=metadata)

    async def fetch_document(self, source_id: str) -> RawDocument:
        """Fetch a single document by its source ID.

        Args:
            source_id: For local storage, relative file path.
                       For S3, object key.

        Returns:
            RawDocument containing the document content and metadata.

        Raises:
            ConnectionError: If not connected to the storage backend.
            FileNotFoundError: If the document does not exist.
        """
        if not self._connected:
            raise ConnectionError("Connector is not connected. Call connect() first.")

        if self.config.storage_type == "local":
            return await self._fetch_local_document(source_id)
        return await self._fetch_s3_document(source_id)

    async def stream_documents(
        self,
        path: str | None = None,
    ) -> AsyncIterator[RawDocument]:
        """Stream all documents from the given path.

        Combines listing and fetching, yielding complete documents
        one at a time. This is memory-efficient for processing
        large numbers of documents.

        Args:
            path: For local storage, a subdirectory path.
                  For S3, an object key prefix.

        Yields:
            RawDocument for each document at the path.

        Raises:
            ConnectionError: If not connected to the storage backend.
        """
        if not self._connected:
            raise ConnectionError("Connector is not connected. Call connect() first.")

        async for metadata in self.list_documents(path):
            try:
                doc = await self.fetch_document(metadata.source_id)
                yield doc
            except FileNotFoundError:
                # File may have been deleted between listing and fetching
                continue
            except Exception as e:
                # Log error but continue with other documents
                # In production, this should use proper logging
                print(f"Error fetching {metadata.source_id}: {e}")
                continue
