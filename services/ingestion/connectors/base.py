"""Base connector interface and common models.

This module defines the abstract base class that all source connectors must
implement, along with the common data models for documents and metadata.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, AsyncIterator, Optional

from pydantic import BaseModel, Field


class DocumentMetadata(BaseModel):
    """Metadata about a document from a source connector.
    
    This model captures essential information about a document's origin,
    type, and properties that downstream processors may need.
    """
    
    source_id: str = Field(
        ..., 
        description="Unique identifier for the document within its source"
    )
    source_type: str = Field(
        ..., 
        description="Type of source connector (e.g., 'filesystem', 's3', 'postgresql')"
    )
    filename: Optional[str] = Field(
        default=None, 
        description="Original filename if available"
    )
    mime_type: Optional[str] = Field(
        default=None, 
        description="MIME type of the document content"
    )
    created_at: Optional[datetime] = Field(
        default=None, 
        description="Document creation timestamp"
    )
    modified_at: Optional[datetime] = Field(
        default=None, 
        description="Document last modification timestamp"
    )
    size_bytes: Optional[int] = Field(
        default=None, 
        ge=0,
        description="Size of the document content in bytes"
    )
    extra: dict[str, Any] = Field(
        default_factory=dict, 
        description="Additional source-specific metadata"
    )
    
    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "source_id": "documents/report.pdf",
                    "source_type": "s3",
                    "filename": "report.pdf",
                    "mime_type": "application/pdf",
                    "created_at": "2024-01-15T10:30:00Z",
                    "modified_at": "2024-01-20T14:45:00Z",
                    "size_bytes": 1048576,
                    "extra": {"bucket": "my-bucket", "version_id": "abc123"}
                }
            ]
        }
    }


class RawDocument(BaseModel):
    """A raw document fetched from a source connector.
    
    Contains the document's binary content along with its metadata.
    The content is kept as raw bytes to preserve the original format
    for downstream parsing.
    """
    
    content: bytes = Field(
        ..., 
        description="Raw binary content of the document"
    )
    metadata: DocumentMetadata = Field(
        ..., 
        description="Metadata about the document"
    )
    
    model_config = {
        "arbitrary_types_allowed": True,
    }


class BaseConnector(ABC):
    """Abstract base class for all source connectors.
    
    Each connector must implement methods for connecting to a data source,
    listing available documents, and fetching document content. Connectors
    support both individual document fetching and batch streaming.
    
    Connectors implement the async context manager protocol for proper
    resource management.
    
    Example:
        ```python
        async with FilesystemConnector(config) as connector:
            async for doc in connector.stream_documents("/data"):
                process(doc)
        ```
    """
    
    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to the data source.
        
        This method should initialize any clients, connection pools,
        or sessions needed to communicate with the data source.
        
        Raises:
            ConnectionError: If the connection cannot be established.
        """
        pass
    
    @abstractmethod
    async def disconnect(self) -> None:
        """Close connection to the data source.
        
        This method should properly release all resources including
        connection pools, sessions, and file handles.
        """
        pass
    
    @abstractmethod
    async def list_documents(
        self, 
        path: Optional[str] = None
    ) -> AsyncIterator[DocumentMetadata]:
        """List available documents at the given path.
        
        Args:
            path: Optional path or query to filter documents.
                  Interpretation depends on the connector type.
                  
        Yields:
            DocumentMetadata for each available document.
            
        Raises:
            ConnectionError: If not connected to the data source.
        """
        pass
    
    @abstractmethod
    async def fetch_document(self, source_id: str) -> RawDocument:
        """Fetch a single document by its source ID.
        
        Args:
            source_id: Unique identifier for the document within the source.
            
        Returns:
            RawDocument containing the document content and metadata.
            
        Raises:
            ConnectionError: If not connected to the data source.
            FileNotFoundError: If the document does not exist.
        """
        pass
    
    @abstractmethod
    async def stream_documents(
        self, 
        path: Optional[str] = None
    ) -> AsyncIterator[RawDocument]:
        """Stream all documents from the given path.
        
        This method combines listing and fetching for convenience,
        yielding complete documents one at a time.
        
        Args:
            path: Optional path or query to filter documents.
                  Interpretation depends on the connector type.
                  
        Yields:
            RawDocument for each document at the path.
            
        Raises:
            ConnectionError: If not connected to the data source.
        """
        pass
    
    async def __aenter__(self) -> "BaseConnector":
        """Enter the async context manager, establishing connection."""
        await self.connect()
        return self
    
    async def __aexit__(
        self, 
        exc_type: Optional[type], 
        exc_val: Optional[BaseException], 
        exc_tb: Optional[Any]
    ) -> None:
        """Exit the async context manager, closing connection."""
        await self.disconnect()
