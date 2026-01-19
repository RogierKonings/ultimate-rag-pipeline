# Unified Shared Configuration

> **User Story**: US-10.6.2 - Unified Shared Configuration
> **Priority**: P2
> **Status**: Done

This document describes the shared configuration system that provides a single source of truth for configuration values across all RAG pipeline services.

## Overview

The shared configuration module (`services/shared/config/defaults.py`) ensures that all services use consistent defaults for chunking, embedding, and retrieval parameters. This prevents configuration drift and diverging defaults that can cause subtle bugs.

## Configuration Categories

### Chunking Configuration

Controls how documents are split into chunks for embedding and retrieval.

| Parameter | Default | Env Variable | Description |
|-----------|---------|--------------|-------------|
| `target_tokens` | 300 | `CHUNKING_TARGET_TOKENS` | Target chunk size in tokens |
| `max_tokens` | 512 | `CHUNKING_MAX_TOKENS` | Maximum chunk size (hard limit) |
| `chunk_overlap` | 50 | `CHUNKING_CHUNK_OVERLAP` | Token overlap between chunks |
| `min_chunk_size` | 50 | - | Minimum tokens per chunk |
| `separators` | `["\n\n", "\n", ". ", " "]` | - | Separators for recursive splitting |
| `tokenizer` | `cl100k_base` | - | Tokenizer (compatible with BGE) |
| `preserve_sentences` | `true` | - | Avoid splitting mid-sentence |
| `preserve_paragraphs` | `false` | - | Avoid splitting paragraphs |

### Embedding Configuration

Controls the embedding model and its parameters.

| Parameter | Default | Env Variable | Description |
|-----------|---------|--------------|-------------|
| `model_name` | `BAAI/bge-large-en-v1.5` | `EMBEDDING_MODEL` | Embedding model identifier |
| `dimensions` | 1024 | `EMBEDDING_DIMENSIONS` | Embedding vector dimensions |
| `batch_size` | 32 | `EMBEDDING_BATCH_SIZE` | Batch size for embedding |
| `normalize` | `true` | `EMBEDDING_NORMALIZE` | Normalize for cosine similarity |
| `query_prefix` | `Represent this sentence...` | `EMBEDDING_QUERY_PREFIX` | Prefix for query embeddings |
| `max_sequence_length` | 512 | - | Maximum input sequence length |

### Retrieval Configuration

Controls the hybrid search and reranking parameters.

| Parameter | Default | Env Variable | Description |
|-----------|---------|--------------|-------------|
| `semantic_top_k` | 50 | `RETRIEVAL_SEMANTIC_TOP_K` | Candidates from semantic search |
| `keyword_top_k` | 50 | `RETRIEVAL_KEYWORD_TOP_K` | Candidates from keyword search |
| `rrf_k` | 60 | `RETRIEVAL_RRF_K` | RRF constant (prevents high-ranked dominance) |
| `semantic_weight` | 0.7 | `RETRIEVAL_SEMANTIC_WEIGHT` | Weight for semantic results |
| `keyword_weight` | 0.3 | `RETRIEVAL_KEYWORD_WEIGHT` | Weight for keyword results |
| `rerank_top_k` | 10 | `RETRIEVAL_RERANK_TOP_K` | Final results after reranking |
| `reranker_model` | `BAAI/bge-reranker-v2-m3` | `RETRIEVAL_RERANKER_MODEL` | Cross-encoder reranker model |

## Usage

### Importing Configuration

Services should import configuration using the factory functions:

```python
from shared.config.defaults import (
    get_chunking_config,
    get_embedding_config,
    get_retrieval_config,
)

# Get configuration with defaults
chunking = get_chunking_config()
embedding = get_embedding_config()
retrieval = get_retrieval_config()

# Override specific values
chunking = get_chunking_config(target_tokens=500, max_tokens=1024)
```

### Priority Order

Configuration values are resolved in this order (highest priority first):

1. **Explicit overrides**: Values passed to factory functions
2. **Environment variables**: OS environment variables
3. **Defaults**: Hard-coded default values

### Example: Ingestion Service

```python
# services/ingestion/chunking/splitter.py
from shared.config.defaults import get_chunking_config

class RecursiveTextSplitter:
    def __init__(self, **overrides):
        config = get_chunking_config(**overrides)
        self.target_tokens = config.target_tokens
        self.max_tokens = config.max_tokens
        self.overlap = config.chunk_overlap
        self.separators = config.separators
```

### Example: Retrieval Service

```python
# services/retrieval/search/hybrid.py
from shared.config.defaults import get_retrieval_config

class HybridSearcher:
    def __init__(self, **overrides):
        config = get_retrieval_config(**overrides)
        self.semantic_top_k = config.semantic_top_k
        self.keyword_top_k = config.keyword_top_k
        self.rrf_k = config.rrf_k
        self.semantic_weight = config.semantic_weight
```

## Startup Validation

The `validate_all_configs()` function checks configuration consistency at service startup:

```python
from shared.config.defaults import validate_all_configs

errors = validate_all_configs()
if errors:
    for error in errors:
        logger.warning(f"Configuration issue: {error}")
```

### Validation Rules

1. **Chunking**:
   - `chunk_overlap` must be less than `target_tokens`
   - `target_tokens` must not exceed `max_tokens`

2. **Embedding**:
   - `dimensions` should be 384, 768, or 1024 (common model sizes)

3. **Retrieval**:
   - `semantic_weight + keyword_weight` must equal 1.0
   - `rerank_top_k` must not exceed `semantic_top_k`

## Environment Variable Reference

### Chunking

```bash
CHUNKING_TARGET_TOKENS=300
CHUNKING_MAX_TOKENS=512
CHUNKING_CHUNK_OVERLAP=50
```

### Embedding

```bash
EMBEDDING_MODEL=BAAI/bge-large-en-v1.5
EMBEDDING_DIMENSIONS=1024
EMBEDDING_BATCH_SIZE=32
EMBEDDING_NORMALIZE=true
EMBEDDING_QUERY_PREFIX="Represent this sentence for searching relevant passages: "
```

### Retrieval

```bash
RETRIEVAL_SEMANTIC_TOP_K=50
RETRIEVAL_KEYWORD_TOP_K=50
RETRIEVAL_RRF_K=60
RETRIEVAL_SEMANTIC_WEIGHT=0.7
RETRIEVAL_KEYWORD_WEIGHT=0.3
RETRIEVAL_RERANK_TOP_K=10
RETRIEVAL_RERANKER_MODEL=BAAI/bge-reranker-v2-m3
```

## Configuration Hierarchy

```
┌─────────────────────────────────────────────────────────────┐
│                    Service Code                              │
│  get_chunking_config(target_tokens=500)  ← Explicit Override│
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│               Environment Variables                          │
│  CHUNKING_TARGET_TOKENS=400              ← Env Override     │
└─────────────────────────┬───────────────────────────────────┘
                          │
┌─────────────────────────▼───────────────────────────────────┐
│              defaults.py Defaults                            │
│  target_tokens = 300                     ← Code Default     │
└─────────────────────────────────────────────────────────────┘

Result: target_tokens = 500 (explicit override wins)
```

## Best Practices

### 1. Always Use Factory Functions

```python
# Good
config = get_chunking_config()

# Avoid - bypasses environment variable handling
config = ChunkingConfig()
```

### 2. Pass Overrides Explicitly

```python
# Good - clear intent
config = get_chunking_config(target_tokens=500)

# Avoid - modifying after creation
config = get_chunking_config()
config.target_tokens = 500  # This works but is less clear
```

### 3. Validate at Startup

```python
# In service main.py
from shared.config.defaults import validate_all_configs

def startup():
    errors = validate_all_configs()
    for error in errors:
        logger.warning(f"Config validation: {error}")
```

### 4. Document Non-Standard Values

If a service uses non-default values, document why:

```python
# We use larger chunks for legal documents
# because they have longer paragraphs
config = get_chunking_config(
    target_tokens=500,  # Increased for legal docs
    max_tokens=1024,
)
```

## File Structure

```
services/shared/config/
├── __init__.py
├── defaults.py      # Configuration classes and factories
├── timeouts.py      # Timeout configuration
└── validation.py    # Configuration validation utilities
```

## See Also

- [CLAUDE.md](../CLAUDE.md) - Configuration reference in developer guide
- [Architecture](architecture.md) - System architecture overview
- [Retrieval Service](retrieval-service/README.md) - Retrieval configuration in context
