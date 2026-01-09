"""
Chunking Engine for document processing.

This module provides configurable chunking strategies for splitting documents
into chunks suitable for embedding and retrieval. Strategies include:
- RecursiveCharacterSplitter: Split by paragraphs, sentences, words
- SemanticChunker: Split at sentence boundaries using spaCy
- HierarchicalChunker: Create parent-child chunk relationships

Default configuration:
- Target: 300 tokens
- Max: 512 tokens
- Overlap: 50 tokens
- Tokenizer: cl100k_base (OpenAI, compatible with BGE)
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

import tiktoken
from pydantic import BaseModel, Field

# Lazy load spaCy to avoid import overhead when not using semantic chunking
_nlp = None


def _get_spacy_nlp(model: str = "en_core_web_sm"):
    """Lazily load spaCy model."""
    global _nlp
    if _nlp is None:
        import spacy
        _nlp = spacy.load(model)
        _nlp.max_length = 2_000_000  # Handle large documents
    return _nlp


# =============================================================================
# Data Models
# =============================================================================


class Chunk(BaseModel):
    """Represents a chunk of text from a document."""

    chunk_id: UUID = Field(default_factory=uuid4)
    document_id: UUID
    content: str
    chunk_index: int  # Position in document
    start_char: int  # Character offset in original text
    end_char: int
    token_count: int

    # Parent-child relationships for hierarchical retrieval
    parent_chunk_id: Optional[UUID] = None
    child_chunk_ids: list[UUID] = Field(default_factory=list)

    # Metadata preserved from document
    metadata: dict = Field(default_factory=dict)

    # Source information for citation
    source_page: Optional[int] = None
    source_section: Optional[str] = None


class ChunkingResult(BaseModel):
    """Result of chunking a document."""

    document_id: UUID
    chunks: list[Chunk]
    total_chunks: int
    strategy_used: str
    config: dict


# =============================================================================
# Configuration
# =============================================================================


class ChunkingConfig(BaseModel):
    """Configuration for chunking strategies."""

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


class SemanticChunkerConfig(ChunkingConfig):
    """Configuration specific to semantic chunking."""

    spacy_model: str = "en_core_web_sm"


class HierarchicalChunkerConfig(ChunkingConfig):
    """Configuration for hierarchical chunking with parent-child relationships."""

    parent_chunk_size: int = 2048  # Larger parent chunks
    parent_overlap: int = 200
    child_chunk_size: int = 512   # Smaller child chunks
    child_overlap: int = 50


# =============================================================================
# Strategy Enum
# =============================================================================


class ChunkingStrategyType(str, Enum):
    """Available chunking strategy types."""

    RECURSIVE = "recursive"
    SEMANTIC = "semantic"
    HIERARCHICAL = "hierarchical"


# =============================================================================
# Base Strategy
# =============================================================================


class BaseChunkingStrategy(ABC):
    """Abstract base class for chunking strategies."""

    def __init__(self, config: ChunkingConfig | None = None):
        self.config = config or ChunkingConfig()
        self._tokenizer = tiktoken.get_encoding(self.config.tokenizer)

    def count_tokens(self, text: str) -> int:
        """Count tokens in text using the configured tokenizer."""
        return len(self._tokenizer.encode(text))

    @abstractmethod
    def chunk(
        self,
        text: str,
        document_id: UUID,
        metadata: dict | None = None
    ) -> list[Chunk]:
        """Split text into chunks.

        Args:
            text: The document text to chunk
            document_id: UUID of the source document
            metadata: Optional metadata to attach to each chunk

        Returns:
            List of Chunk objects
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """Return strategy name identifier."""
        pass


# =============================================================================
# Recursive Character Splitter
# =============================================================================


class RecursiveCharacterSplitter(BaseChunkingStrategy):
    """
    Recursively split text by trying different separators.

    Tries to split by paragraphs first, then sentences, then words.
    This maintains semantic coherence by preferring larger natural
    boundaries when possible.
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
        metadata: dict | None = None
    ) -> list[Chunk]:
        """Split text recursively using multiple separators."""
        metadata = metadata or {}
        chunks = []

        # Get raw splits with character offsets
        raw_splits = self._split_recursive(text, self.SEPARATORS, 0)

        # Merge small chunks and handle overlap
        merged = self._merge_and_overlap(raw_splits)

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
        separators: list[str],
        offset: int
    ) -> list[tuple[str, int, int]]:
        """
        Recursively split text, tracking character offsets.

        Args:
            text: Text to split
            separators: List of separators to try in order
            offset: Character offset in original document

        Returns:
            List of (content, start_char, end_char) tuples
        """
        if not text.strip():
            return []

        if not separators:
            return [(text, offset, offset + len(text))]

        sep = separators[0]

        # Character-level split as fallback
        if sep == "":
            return self._split_by_tokens(text, offset)

        # Check if separator exists in text
        if sep not in text:
            return self._split_recursive(text, separators[1:], offset)

        parts = []
        current_offset = offset
        splits = text.split(sep)

        for i, part in enumerate(splits):
            if not part.strip():
                current_offset += len(part) + len(sep)
                continue

            token_count = self.count_tokens(part)

            if token_count > self.config.max_tokens:
                # Too large, split further with next separator
                sub_parts = self._split_recursive(
                    part, separators[1:], current_offset
                )
                parts.extend(sub_parts)
            else:
                parts.append((part, current_offset, current_offset + len(part)))

            current_offset += len(part) + len(sep)

        return parts

    def _split_by_tokens(
        self,
        text: str,
        offset: int
    ) -> list[tuple[str, int, int]]:
        """
        Split text into chunks of target_tokens size when no separators work.

        This is the fallback when text has no good split points.
        """
        parts = []
        tokens = self._tokenizer.encode(text)

        i = 0
        char_offset = offset

        while i < len(tokens):
            # Take target_tokens worth of tokens
            chunk_tokens = tokens[i:i + self.config.target_tokens]
            chunk_text = self._tokenizer.decode(chunk_tokens)

            parts.append((
                chunk_text,
                char_offset,
                char_offset + len(chunk_text)
            ))

            char_offset += len(chunk_text)
            i += self.config.target_tokens

        return parts

    def _merge_and_overlap(
        self,
        splits: list[tuple[str, int, int]]
    ) -> list[tuple[str, int, int]]:
        """
        Merge small chunks and create overlapping chunks.

        - Merges consecutive chunks that are below min_chunk_size
        - Creates overlap between chunks based on chunk_overlap setting
        """
        if not splits:
            return []

        # First pass: merge small chunks
        merged = []
        current_content = ""
        current_start = splits[0][1]
        current_end = splits[0][2]

        for content, start, end in splits:
            potential_content = current_content + " " + content if current_content else content
            potential_tokens = self.count_tokens(potential_content)

            if potential_tokens <= self.config.target_tokens:
                # Can merge
                current_content = potential_content.strip()
                current_end = end
            else:
                # Save current and start new
                if current_content and self.count_tokens(current_content) >= self.config.min_chunk_size:
                    merged.append((current_content, current_start, current_end))
                elif current_content:
                    # Too small, will be merged with next
                    current_content = potential_content.strip()
                    current_end = end
                    continue

                current_content = content
                current_start = start
                current_end = end

        # Don't forget the last chunk
        if current_content:
            merged.append((current_content, current_start, current_end))

        # Second pass: add overlap
        if self.config.chunk_overlap <= 0 or len(merged) <= 1:
            return merged

        overlapped = []
        for i, (content, start, end) in enumerate(merged):
            if i == 0:
                overlapped.append((content, start, end))
                continue

            # Get overlap from previous chunk
            prev_content = merged[i - 1][0]
            overlap_text = self._get_overlap_text(prev_content, self.config.chunk_overlap)

            if overlap_text:
                new_content = overlap_text + " " + content
                # Adjust start to reflect overlap
                overlap_char_len = len(overlap_text)
                new_start = max(0, start - overlap_char_len)
                overlapped.append((new_content, new_start, end))
            else:
                overlapped.append((content, start, end))

        return overlapped

    def _get_overlap_text(self, text: str, overlap_tokens: int) -> str:
        """Get the last N tokens worth of text for overlap."""
        tokens = self._tokenizer.encode(text)
        if len(tokens) <= overlap_tokens:
            return text

        overlap_token_ids = tokens[-overlap_tokens:]
        return self._tokenizer.decode(overlap_token_ids)


# =============================================================================
# Semantic Chunker
# =============================================================================


class SemanticChunker(BaseChunkingStrategy):
    """
    Split text at sentence boundaries for semantic coherence.

    Uses spaCy for accurate sentence boundary detection across languages.
    Respects paragraph structure when possible.
    """

    def __init__(self, config: SemanticChunkerConfig | None = None):
        config = config or SemanticChunkerConfig()
        super().__init__(config)
        self._spacy_model = config.spacy_model
        self._nlp = None  # Lazy load

    @property
    def nlp(self):
        """Lazy-load spaCy model."""
        if self._nlp is None:
            import spacy
            self._nlp = spacy.load(self._spacy_model)
            self._nlp.max_length = 2_000_000
        return self._nlp

    @property
    def name(self) -> str:
        return "semantic_sentence"

    def chunk(
        self,
        text: str,
        document_id: UUID,
        metadata: dict | None = None
    ) -> list[Chunk]:
        """Split text at sentence boundaries."""
        metadata = metadata or {}

        # Process text with spaCy for sentence detection
        doc = self.nlp(text)
        sentences = list(doc.sents)

        chunks = []
        current_sentences: list[str] = []
        current_tokens = 0
        current_start = 0
        chunk_index = 0

        for sent in sentences:
            sent_text = sent.text.strip()
            if not sent_text:
                continue

            sent_tokens = self.count_tokens(sent_text)

            # If single sentence exceeds max size, split it
            if sent_tokens > self.config.max_tokens:
                # Flush current chunk first
                if current_sentences:
                    chunk = self._create_chunk(
                        current_sentences, document_id, chunk_index,
                        current_start, sent.start_char, metadata
                    )
                    chunks.append(chunk)
                    chunk_index += 1
                    current_sentences = []
                    current_tokens = 0

                # Split long sentence using fallback
                sub_chunks = self._split_long_sentence(
                    sent_text, sent.start_char, document_id,
                    chunk_index, metadata
                )
                for sub in sub_chunks:
                    chunks.append(sub)
                    chunk_index += 1

                current_start = sent.end_char
                continue

            # Check if adding this sentence exceeds target size
            if current_tokens + sent_tokens > self.config.target_tokens:
                # Create chunk from current sentences
                if current_sentences:
                    chunk = self._create_chunk(
                        current_sentences, document_id, chunk_index,
                        current_start, sent.start_char, metadata
                    )
                    chunks.append(chunk)
                    chunk_index += 1

                # Handle overlap: include last N tokens from previous chunk
                overlap_sentences = self._get_overlap_sentences(
                    current_sentences, self.config.chunk_overlap
                )
                current_sentences = overlap_sentences + [sent_text]
                current_tokens = sum(self.count_tokens(s) for s in current_sentences)
                current_start = sent.start_char
            else:
                if not current_sentences:
                    current_start = sent.start_char
                current_sentences.append(sent_text)
                current_tokens += sent_tokens

        # Don't forget the last chunk
        if current_sentences:
            chunk = self._create_chunk(
                current_sentences, document_id, chunk_index,
                current_start, len(text), metadata
            )
            chunks.append(chunk)

        return chunks

    def _create_chunk(
        self,
        sentences: list[str],
        document_id: UUID,
        chunk_index: int,
        start_char: int,
        end_char: int,
        metadata: dict
    ) -> Chunk:
        """Create a Chunk from a list of sentences."""
        content = " ".join(sentences)
        return Chunk(
            document_id=document_id,
            content=content,
            chunk_index=chunk_index,
            start_char=start_char,
            end_char=end_char,
            token_count=self.count_tokens(content),
            metadata=metadata.copy()
        )

    def _split_long_sentence(
        self,
        sentence: str,
        start_char: int,
        document_id: UUID,
        base_index: int,
        metadata: dict
    ) -> list[Chunk]:
        """Split a very long sentence that exceeds max_tokens."""
        chunks = []
        tokens = self._tokenizer.encode(sentence)

        i = 0
        char_offset = start_char
        sub_index = 0

        while i < len(tokens):
            # Take max_tokens worth of tokens
            chunk_tokens = tokens[i:i + self.config.max_tokens]
            chunk_text = self._tokenizer.decode(chunk_tokens)

            chunks.append(Chunk(
                document_id=document_id,
                content=chunk_text,
                chunk_index=base_index + sub_index,
                start_char=char_offset,
                end_char=char_offset + len(chunk_text),
                token_count=len(chunk_tokens),
                metadata=metadata.copy()
            ))

            char_offset += len(chunk_text)
            i += self.config.max_tokens
            sub_index += 1

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


# =============================================================================
# Hierarchical Chunker
# =============================================================================


class HierarchicalChunker(BaseChunkingStrategy):
    """
    Create parent and child chunks for hierarchical retrieval.

    Strategy:
    1. Create large parent chunks
    2. Split each parent into smaller child chunks
    3. Link children to parents for context expansion

    This enables "small-to-big" retrieval where you search over
    small chunks but retrieve surrounding context from parents.
    """

    def __init__(self, config: HierarchicalChunkerConfig | None = None):
        config = config or HierarchicalChunkerConfig()
        super().__init__(config)
        self._config: HierarchicalChunkerConfig = config

        # Create child chunker with child-specific settings
        child_config = SemanticChunkerConfig(
            target_tokens=config.child_chunk_size,
            max_tokens=config.child_chunk_size,
            chunk_overlap=config.child_overlap
        )
        self._child_chunker = SemanticChunker(child_config)

    @property
    def name(self) -> str:
        return "hierarchical"

    def chunk(
        self,
        text: str,
        document_id: UUID,
        metadata: dict | None = None
    ) -> list[Chunk]:
        """Create hierarchical parent-child chunks."""
        metadata = metadata or {}
        all_chunks = []

        # Create parent chunks using recursive splitter
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
                # Adjust child offsets relative to document
                child.start_char += parent.start_char
                child.end_char += parent.start_char
                child_ids.append(child.chunk_id)
                all_chunks.append(child)

            # Update parent with child references
            parent.child_chunk_ids = child_ids

        return all_chunks

    def _create_parent_chunks(
        self,
        text: str,
        document_id: UUID,
        metadata: dict
    ) -> list[Chunk]:
        """Create large parent chunks."""
        parent_config = ChunkingConfig(
            target_tokens=self._config.parent_chunk_size,
            max_tokens=self._config.parent_chunk_size,
            chunk_overlap=self._config.parent_overlap,
            min_chunk_size=self._config.child_chunk_size  # At least one child
        )

        parent_splitter = RecursiveCharacterSplitter(parent_config)
        return parent_splitter.chunk(text, document_id, metadata)


# =============================================================================
# Chunking Engine
# =============================================================================


class ChunkingEngine:
    """
    Main chunking engine that manages strategies and produces chunks.

    Usage:
        engine = ChunkingEngine()
        result = engine.chunk(text, document_id, strategy="semantic_sentence")

    Available strategies:
        - "recursive_character": Split by paragraphs, sentences, words
        - "semantic_sentence": Split at sentence boundaries (default)
        - "hierarchical": Create parent-child chunk relationships
    """

    def __init__(self):
        self._strategies: dict[str, BaseChunkingStrategy] = {}
        self._register_default_strategies()

    def _register_default_strategies(self):
        """Register built-in chunking strategies."""
        self.register_strategy(RecursiveCharacterSplitter())
        self.register_strategy(SemanticChunker())
        self.register_strategy(HierarchicalChunker())

    def register_strategy(self, strategy: BaseChunkingStrategy):
        """Register a new chunking strategy.

        Args:
            strategy: A chunking strategy instance
        """
        self._strategies[strategy.name] = strategy

    def chunk(
        self,
        text: str,
        document_id: UUID,
        strategy: str = "semantic_sentence",
        metadata: dict | None = None,
        config: ChunkingConfig | None = None
    ) -> ChunkingResult:
        """
        Chunk text using the specified strategy.

        Args:
            text: Document text to chunk
            document_id: UUID of the source document
            strategy: Name of chunking strategy to use
            metadata: Metadata to attach to each chunk
            config: Optional config override for the strategy

        Returns:
            ChunkingResult with all chunks and metadata

        Raises:
            ValueError: If strategy is unknown
        """
        if strategy not in self._strategies:
            available = ", ".join(self._strategies.keys())
            raise ValueError(
                f"Unknown strategy: {strategy}. Available: {available}"
            )

        chunker = self._strategies[strategy]

        # If config provided, create new instance with that config
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
        """Get list of registered strategy names."""
        return list(self._strategies.keys())

    def get_strategy(self, name: str) -> BaseChunkingStrategy:
        """Get a strategy by name.

        Args:
            name: Strategy name

        Returns:
            The strategy instance

        Raises:
            ValueError: If strategy not found
        """
        if name not in self._strategies:
            raise ValueError(f"Unknown strategy: {name}")
        return self._strategies[name]
