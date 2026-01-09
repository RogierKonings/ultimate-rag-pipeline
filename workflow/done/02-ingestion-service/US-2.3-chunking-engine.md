# US-2.3: Chunking Engine

> **Story ID:** US-2.3  
> **Epic:** Ingestion Service  
> **Priority:** Critical  
> **Estimated Effort:** 2-3 days  
> **Dependencies:** US-2.2 (Document Parsers)

## User Story

**As a** data engineer  
**I want** configurable chunking strategies  
**So that** I can optimize retrieval quality

## Context

After documents are parsed, they need to be split into chunks suitable for embedding and retrieval. The chunking strategy significantly impacts retrieval quality. Different strategies work better for different document types. The architecture specifies a default of 512 tokens with 50 token overlap, using semantic chunking at sentence boundaries.

## Technical Requirements

### Directory Structure

```
ingestion-service/
└── processors/
    ├── chunking.py           # Chunking engine and strategies
    └── __init__.py
```

### Chunk Data Model

```python
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID, uuid4

class Chunk(BaseModel):
    chunk_id: UUID = Field(default_factory=uuid4)
    document_id: UUID
    content: str
    chunk_index: int  # Position in document
    start_char: int  # Character offset in original text
    end_char: int
    token_count: int
    
    # Parent-child relationships for hierarchical retrieval
    parent_chunk_id: Optional[UUID] = None
    child_chunk_ids: list[UUID] = []
    
    # Metadata preserved from document
    metadata: dict = {}
    
    # Source information for citation
    source_page: Optional[int] = None
    source_section: Optional[str] = None

class ChunkingResult(BaseModel):
    document_id: UUID
    chunks: list[Chunk]
    total_chunks: int
    strategy_used: str
    config: dict
```

### Chunking Strategy Interface

```python
from abc import ABC, abstractmethod
from typing import Optional
import tiktoken

class ChunkingConfig(BaseModel):
    target_tokens: int = 300  # Target chunk size (architecture default)
    max_tokens: int = 512  # Maximum chunk size (hard limit)
    chunk_overlap: int = 50  # tokens (architecture default)
    min_chunk_size: int = 50  # Minimum tokens per chunk
    tokenizer: str = "cl100k_base"  # OpenAI tokenizer (compatible with BGE)
    preserve_sentences: bool = True
    preserve_paragraphs: bool = False
    
    @property
    def chunk_size(self) -> int:
        """Alias for target_tokens for backward compatibility."""
        return self.target_tokens

class BaseChunkingStrategy(ABC):
    """Abstract base class for chunking strategies."""
    
    def __init__(self, config: ChunkingConfig = ChunkingConfig()):
        self.config = config
        self._tokenizer = tiktoken.get_encoding(config.tokenizer)
    
    def count_tokens(self, text: str) -> int:
        """Count tokens in text."""
        return len(self._tokenizer.encode(text))
    
    @abstractmethod
    def chunk(
        self,
        text: str,
        document_id: UUID,
        metadata: dict = {}
    ) -> list[Chunk]:
        """Split text into chunks."""
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Return strategy name."""
        pass
```

### 1. Recursive Character Splitter

Split text recursively by different separators:

```python
class RecursiveCharacterSplitter(BaseChunkingStrategy):
    """
    Recursively split text by trying different separators.
    Tries to split by paragraphs first, then sentences, then words.
    """
    
    SEPARATORS = [
        "\n\n",  # Paragraphs
        "\n",    # Lines
        ". ",    # Sentences
        "? ",
        "! ",
        "; ",
        ", ",
        " ",     # Words
        ""       # Characters (fallback)
    ]
    
    @property
    def name(self) -> str:
        return "recursive_character"
    
    def chunk(
        self,
        text: str,
        document_id: UUID,
        metadata: dict = {}
    ) -> list[Chunk]:
        chunks = []
        current_chunks = self._split_recursive(text, self.SEPARATORS)
        
        # Merge small chunks and split large chunks
        merged = self._merge_chunks(current_chunks)
        
        for i, (content, start, end) in enumerate(merged):
            chunks.append(Chunk(
                document_id=document_id,
                content=content,
                chunk_index=i,
                start_char=start,
                end_char=end,
                token_count=self.count_tokens(content),
                metadata=metadata.copy()
            ))
        
        return chunks
    
    def _split_recursive(
        self,
        text: str,
        separators: list[str]
    ) -> list[tuple[str, int, int]]:
        """Recursively split text, tracking character offsets."""
        if not separators:
            return [(text, 0, len(text))]
        
        sep = separators[0]
        if sep == "":
            # Character-level split as fallback
            return self._split_by_tokens(text)
        
        parts = []
        current_offset = 0
        
        if sep in text:
            splits = text.split(sep)
            for i, part in enumerate(splits):
                if part:
                    token_count = self.count_tokens(part)
                    if token_count > self.config.chunk_size:
                        # Too large, split further
                        sub_parts = self._split_recursive(part, separators[1:])
                        for sub, sub_start, sub_end in sub_parts:
                            parts.append((sub, current_offset + sub_start, current_offset + sub_end))
                    else:
                        parts.append((part, current_offset, current_offset + len(part)))
                current_offset += len(part) + len(sep)
        else:
            # Separator not found, try next
            return self._split_recursive(text, separators[1:])
        
        return parts
```

**Requirements:**
- Try splitting by paragraphs first, then sentences, then words
- Track character offsets for each chunk
- Respect `chunk_size` and `chunk_overlap` settings
- Merge small chunks that are below `min_chunk_size`

### 2. Semantic Chunker (Sentence-Boundary)

Split at sentence boundaries for semantic coherence:

```python
import spacy

class SemanticChunkerConfig(ChunkingConfig):
    spacy_model: str = "en_core_web_sm"

class SemanticChunker(BaseChunkingStrategy):
    """
    Split text at sentence boundaries for semantic coherence.
    Respects paragraph structure when possible.
    """
    
    def __init__(self, config: SemanticChunkerConfig = SemanticChunkerConfig()):
        super().__init__(config)
        self.nlp = spacy.load(config.spacy_model)
        self.nlp.max_length = 2_000_000  # Handle large documents
    
    @property
    def name(self) -> str:
        return "semantic_sentence"
    
    def chunk(
        self,
        text: str,
        document_id: UUID,
        metadata: dict = {}
    ) -> list[Chunk]:
        # Process text with spaCy for sentence detection
        doc = self.nlp(text)
        sentences = list(doc.sents)
        
        chunks = []
        current_chunk = []
        current_tokens = 0
        current_start = 0
        chunk_index = 0
        
        for sent in sentences:
            sent_text = sent.text.strip()
            sent_tokens = self.count_tokens(sent_text)
            
            # If single sentence exceeds chunk size, split it
            if sent_tokens > self.config.chunk_size:
                # Flush current chunk
                if current_chunk:
                    chunks.append(self._create_chunk(
                        current_chunk, document_id, chunk_index,
                        current_start, metadata
                    ))
                    chunk_index += 1
                    current_chunk = []
                    current_tokens = 0
                
                # Split long sentence
                sub_chunks = self._split_long_sentence(sent_text, sent.start_char)
                for sub in sub_chunks:
                    chunks.append(Chunk(
                        document_id=document_id,
                        chunk_index=chunk_index,
                        **sub,
                        metadata=metadata.copy()
                    ))
                    chunk_index += 1
                current_start = sent.end_char
                continue
            
            # Check if adding this sentence exceeds chunk size
            if current_tokens + sent_tokens > self.config.chunk_size:
                # Create chunk from current sentences
                if current_chunk:
                    chunks.append(self._create_chunk(
                        current_chunk, document_id, chunk_index,
                        current_start, metadata
                    ))
                    chunk_index += 1
                
                # Handle overlap: include last N tokens from previous chunk
                overlap_sentences = self._get_overlap_sentences(
                    current_chunk, self.config.chunk_overlap
                )
                current_chunk = overlap_sentences + [sent_text]
                current_tokens = sum(self.count_tokens(s) for s in current_chunk)
                current_start = sent.start_char
            else:
                current_chunk.append(sent_text)
                current_tokens += sent_tokens
        
        # Don't forget the last chunk
        if current_chunk:
            chunks.append(self._create_chunk(
                current_chunk, document_id, chunk_index,
                current_start, metadata
            ))
        
        return chunks
    
    def _get_overlap_sentences(
        self,
        sentences: list[str],
        overlap_tokens: int
    ) -> list[str]:
        """Get sentences from end that fit within overlap token budget."""
        result = []
        total = 0
        for sent in reversed(sentences):
            tokens = self.count_tokens(sent)
            if total + tokens > overlap_tokens:
                break
            result.insert(0, sent)
            total += tokens
        return result
```

**Requirements:**
- Use spaCy for sentence boundary detection
- Keep sentences intact (don't split mid-sentence)
- Handle overlap by including trailing sentences from previous chunk
- Split very long sentences using fallback strategy
- Support multiple languages via spaCy models

### 3. Hierarchical Chunker (Parent-Child)

Create hierarchical chunks for context-aware retrieval:

```python
class HierarchicalChunkerConfig(ChunkingConfig):
    parent_chunk_size: int = 2048  # Larger parent chunks
    parent_overlap: int = 200
    child_chunk_size: int = 512   # Smaller child chunks
    child_overlap: int = 50

class HierarchicalChunker(BaseChunkingStrategy):
    """
    Create parent and child chunks for hierarchical retrieval.
    
    Strategy:
    1. Create large parent chunks
    2. Split each parent into smaller child chunks
    3. Link children to parents for context expansion
    """
    
    def __init__(self, config: HierarchicalChunkerConfig = HierarchicalChunkerConfig()):
        super().__init__(config)
        self.config = config
        self._child_chunker = SemanticChunker(ChunkingConfig(
            chunk_size=config.child_chunk_size,
            chunk_overlap=config.child_overlap
        ))
    
    @property
    def name(self) -> str:
        return "hierarchical"
    
    def chunk(
        self,
        text: str,
        document_id: UUID,
        metadata: dict = {}
    ) -> list[Chunk]:
        all_chunks = []
        
        # Create parent chunks
        parent_chunks = self._create_parent_chunks(text, document_id, metadata)
        
        for parent in parent_chunks:
            parent_id = parent.chunk_id
            all_chunks.append(parent)
            
            # Create child chunks from parent content
            children = self._child_chunker.chunk(
                parent.content,
                document_id,
                metadata
            )
            
            child_ids = []
            for child in children:
                child.parent_chunk_id = parent_id
                child_ids.append(child.chunk_id)
                all_chunks.append(child)
            
            # Update parent with child references
            parent.child_chunk_ids = child_ids
        
        return all_chunks
```

**Requirements:**
- Create two levels of chunks (parent and child)
- Link children to parents via `parent_chunk_id`
- Store child IDs in parent's `child_chunk_ids`
- Use different sizes for parent (larger) and child (smaller)
- Enables "small-to-big" retrieval pattern

### Chunking Engine

Main engine that orchestrates chunking with strategy selection:

```python
from enum import Enum

class ChunkingStrategyType(str, Enum):
    RECURSIVE = "recursive"
    SEMANTIC = "semantic"
    HIERARCHICAL = "hierarchical"

class ChunkingEngine:
    """
    Main chunking engine that manages strategies and produces chunks.
    """
    
    def __init__(self):
        self._strategies: dict[str, BaseChunkingStrategy] = {}
        self._register_default_strategies()
    
    def _register_default_strategies(self):
        self.register_strategy(RecursiveCharacterSplitter())
        self.register_strategy(SemanticChunker())
        self.register_strategy(HierarchicalChunker())
    
    def register_strategy(self, strategy: BaseChunkingStrategy):
        self._strategies[strategy.name] = strategy
    
    def chunk(
        self,
        text: str,
        document_id: UUID,
        strategy: str = "semantic_sentence",
        metadata: dict = {},
        config: Optional[ChunkingConfig] = None
    ) -> ChunkingResult:
        """
        Chunk text using the specified strategy.
        
        Args:
            text: Document text to chunk
            document_id: UUID of the source document
            strategy: Name of chunking strategy to use
            metadata: Metadata to attach to each chunk
            config: Optional config override for the strategy
        """
        if strategy not in self._strategies:
            raise ValueError(f"Unknown strategy: {strategy}")
        
        chunker = self._strategies[strategy]
        if config:
            chunker = type(chunker)(config)
        
        chunks = chunker.chunk(text, document_id, metadata)
        
        return ChunkingResult(
            document_id=document_id,
            chunks=chunks,
            total_chunks=len(chunks),
            strategy_used=strategy,
            config=chunker.config.model_dump()
        )
    
    @property
    def available_strategies(self) -> list[str]:
        return list(self._strategies.keys())
```

## Acceptance Criteria

- [ ] `Chunk` and `ChunkingResult` Pydantic models defined
- [ ] `BaseChunkingStrategy` abstract class implemented
- [ ] `RecursiveCharacterSplitter` handles various separators
- [ ] `SemanticChunker` splits at sentence boundaries using spaCy
- [ ] `HierarchicalChunker` creates parent-child relationships
- [ ] All strategies respect `target_tokens` (default 300) with `max_tokens` (512) hard limit
- [ ] All strategies implement `chunk_overlap` (default 50 tokens)
- [ ] Token counting uses `tiktoken` with `cl100k_base` encoding
- [ ] Metadata preserved and attached to all chunks
- [ ] Character offsets tracked for each chunk
- [ ] `ChunkingEngine` manages strategy registration and selection
- [ ] Unit tests for each strategy

## Testing Requirements

```python
import pytest
from uuid import uuid4

@pytest.fixture
def sample_text():
    return """
    This is the first paragraph. It contains multiple sentences.
    Here is another sentence in the first paragraph.
    
    This is the second paragraph. It discusses a different topic.
    The second paragraph has three sentences. This is the third.
    
    Finally, this is the third paragraph with closing remarks.
    """

@pytest.fixture
def chunking_engine():
    return ChunkingEngine()

def test_semantic_chunker_respects_sentence_boundaries(chunking_engine, sample_text):
    result = chunking_engine.chunk(
        sample_text,
        uuid4(),
        strategy="semantic_sentence"
    )
    
    for chunk in result.chunks:
        # Each chunk should end with sentence-ending punctuation
        assert chunk.content.rstrip().endswith((".", "!", "?"))

def test_hierarchical_chunker_creates_parent_child_links(chunking_engine, sample_text):
    result = chunking_engine.chunk(
        sample_text,
        uuid4(),
        strategy="hierarchical"
    )
    
    parents = [c for c in result.chunks if c.parent_chunk_id is None]
    children = [c for c in result.chunks if c.parent_chunk_id is not None]
    
    assert len(parents) > 0
    assert len(children) > 0
    
    # Verify parent-child links
    for parent in parents:
        for child_id in parent.child_chunk_ids:
            child = next(c for c in children if c.chunk_id == child_id)
            assert child.parent_chunk_id == parent.chunk_id

def test_chunk_size_respected(chunking_engine):
    long_text = "This is a sentence. " * 1000
    result = chunking_engine.chunk(long_text, uuid4())
    
    for chunk in result.chunks:
        assert chunk.token_count <= 512  # Must not exceed max_tokens
```

## Dependencies

- `tiktoken>=0.5.0`
- `spacy>=3.7.0`
- `pydantic>=2.0.0`

Also requires spaCy model download:
```bash
python -m spacy download en_core_web_sm
```

## Definition of Done

- [ ] All chunking strategies implemented and tested
- [ ] Default config matches architecture (300 target tokens, 512 max, 50 overlap)
- [ ] Token counting accurate and tested
- [ ] Parent-child relationships work correctly
- [ ] >90% test coverage for chunking module
- [ ] Performance tested with large documents (100+ pages)
- [ ] Docstrings on all public methods
- [ ] Type hints validated with mypy
