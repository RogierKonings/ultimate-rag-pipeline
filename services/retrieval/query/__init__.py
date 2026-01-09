"""Query preprocessing module for the Retrieval Service.

This module provides query preprocessing, expansion, and embedding
generation for optimal retrieval performance.
"""

from .models import (
    ProcessedQuery,
    QueryPreprocessorConfig,
    QueryType,
)
from .preprocessor import QueryPreprocessor
from .expander import QueryExpander, SynonymDatabase
from .hyde import HyDEGenerator, MultiQueryGenerator
from .cache import QueryCache

__all__ = [
    # Models
    "ProcessedQuery",
    "QueryPreprocessorConfig",
    "QueryType",
    # Preprocessor
    "QueryPreprocessor",
    # Expander
    "QueryExpander",
    "SynonymDatabase",
    # HyDE
    "HyDEGenerator",
    "MultiQueryGenerator",
    # Cache
    "QueryCache",
]
