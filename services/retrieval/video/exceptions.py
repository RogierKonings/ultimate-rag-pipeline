"""Video retrieval exceptions."""


class VideoRetrievalError(Exception):
    """Base exception for video retrieval errors."""


class VideoSearchError(VideoRetrievalError):
    """Error during video search operation."""


class VideoIndexError(VideoRetrievalError):
    """Error with video index operations."""


class VideoEmbeddingError(VideoRetrievalError):
    """Error generating query embeddings."""
