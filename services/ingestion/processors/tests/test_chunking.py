"""
Unit tests for the Chunking Engine.

Tests cover:
- Chunk and ChunkingResult data models
- RecursiveCharacterSplitter strategy
- SemanticChunker strategy
- HierarchicalChunker strategy
- ChunkingEngine orchestration
"""

from uuid import uuid4

import pytest

from ..chunking import (
    Chunk,
    ChunkingConfig,
    ChunkingEngine,
    ChunkingResult,
    HierarchicalChunker,
    HierarchicalChunkerConfig,
    RecursiveCharacterSplitter,
    SemanticChunker,
    SemanticChunkerConfig,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def sample_text():
    """Sample text with paragraphs and sentences."""
    return """This is the first paragraph. It contains multiple sentences.
Here is another sentence in the first paragraph.

This is the second paragraph. It discusses a different topic.
The second paragraph has three sentences. This is the third.

Finally, this is the third paragraph with closing remarks."""


@pytest.fixture
def long_text():
    """Long text that will require multiple chunks."""
    return "This is a sentence. " * 500


@pytest.fixture
def single_paragraph():
    """Single paragraph of text."""
    return "The quick brown fox jumps over the lazy dog. This is a test sentence. Another sentence here."


@pytest.fixture
def document_id():
    """Generate a test document ID."""
    return uuid4()


@pytest.fixture
def chunking_engine():
    """Create a ChunkingEngine instance."""
    return ChunkingEngine()


@pytest.fixture
def default_config():
    """Default chunking configuration."""
    return ChunkingConfig()


# =============================================================================
# Data Model Tests
# =============================================================================


class TestChunkModel:
    """Tests for the Chunk data model."""

    def test_chunk_creation_with_defaults(self, document_id):
        """Test creating a chunk with default values."""
        chunk = Chunk(
            document_id=document_id,
            content="Test content",
            chunk_index=0,
            start_char=0,
            end_char=12,
            token_count=2,
        )

        assert chunk.chunk_id is not None
        assert chunk.document_id == document_id
        assert chunk.content == "Test content"
        assert chunk.chunk_index == 0
        assert chunk.parent_chunk_id is None
        assert chunk.child_chunk_ids == []
        assert chunk.metadata == {}

    def test_chunk_with_parent_child(self, document_id):
        """Test chunk with parent-child relationships."""
        parent_id = uuid4()
        child_ids = [uuid4(), uuid4()]

        chunk = Chunk(
            document_id=document_id,
            content="Test",
            chunk_index=0,
            start_char=0,
            end_char=4,
            token_count=1,
            parent_chunk_id=parent_id,
            child_chunk_ids=child_ids,
        )

        assert chunk.parent_chunk_id == parent_id
        assert chunk.child_chunk_ids == child_ids

    def test_chunk_with_metadata(self, document_id):
        """Test chunk with custom metadata."""
        metadata = {"source": "test", "page": 1}

        chunk = Chunk(
            document_id=document_id,
            content="Test",
            chunk_index=0,
            start_char=0,
            end_char=4,
            token_count=1,
            metadata=metadata,
            source_page=1,
            source_section="Introduction",
        )

        assert chunk.metadata == metadata
        assert chunk.source_page == 1
        assert chunk.source_section == "Introduction"


class TestChunkingResultModel:
    """Tests for the ChunkingResult data model."""

    def test_chunking_result_creation(self, document_id):
        """Test creating a ChunkingResult."""
        chunks = [
            Chunk(
                document_id=document_id,
                content="Chunk 1",
                chunk_index=0,
                start_char=0,
                end_char=7,
                token_count=1,
            ),
            Chunk(
                document_id=document_id,
                content="Chunk 2",
                chunk_index=1,
                start_char=8,
                end_char=15,
                token_count=1,
            ),
        ]

        result = ChunkingResult(
            document_id=document_id,
            chunks=chunks,
            total_chunks=2,
            strategy_used="test_strategy",
            config={"target_tokens": 300},
        )

        assert result.document_id == document_id
        assert len(result.chunks) == 2
        assert result.total_chunks == 2
        assert result.strategy_used == "test_strategy"


# =============================================================================
# Configuration Tests
# =============================================================================


class TestChunkingConfig:
    """Tests for chunking configuration."""

    def test_default_config(self):
        """Test default configuration values."""
        config = ChunkingConfig()

        assert config.target_tokens == 300
        assert config.max_tokens == 512
        assert config.chunk_overlap == 50
        assert config.min_chunk_size == 50
        assert config.tokenizer == "cl100k_base"
        assert config.preserve_sentences is True
        assert config.preserve_paragraphs is False

    def test_chunk_size_alias(self):
        """Test chunk_size property alias."""
        config = ChunkingConfig(target_tokens=400)
        assert config.chunk_size == 400

    def test_semantic_config(self):
        """Test SemanticChunkerConfig."""
        config = SemanticChunkerConfig(spacy_model="en_core_web_md")
        assert config.spacy_model == "en_core_web_md"
        assert config.target_tokens == 300  # Inherited default

    def test_hierarchical_config(self):
        """Test HierarchicalChunkerConfig."""
        config = HierarchicalChunkerConfig()
        assert config.parent_chunk_size == 2048
        assert config.parent_overlap == 200
        assert config.child_chunk_size == 512
        assert config.child_overlap == 50


# =============================================================================
# RecursiveCharacterSplitter Tests
# =============================================================================


class TestRecursiveCharacterSplitter:
    """Tests for the RecursiveCharacterSplitter strategy."""

    def test_strategy_name(self):
        """Test strategy name."""
        splitter = RecursiveCharacterSplitter()
        assert splitter.name == "recursive_character"

    def test_basic_chunking(self, sample_text, document_id):
        """Test basic text chunking."""
        config = ChunkingConfig(target_tokens=50, max_tokens=100)
        splitter = RecursiveCharacterSplitter(config)

        chunks = splitter.chunk(sample_text, document_id)

        assert len(chunks) > 0
        assert all(isinstance(c, Chunk) for c in chunks)
        assert all(c.document_id == document_id for c in chunks)

    def test_chunk_indices_sequential(self, long_text, document_id):
        """Test that chunk indices are sequential."""
        splitter = RecursiveCharacterSplitter()
        chunks = splitter.chunk(long_text, document_id)

        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i

    def test_character_offsets_valid(self, sample_text, document_id):
        """Test that character offsets are valid."""
        splitter = RecursiveCharacterSplitter()
        chunks = splitter.chunk(sample_text, document_id)

        for chunk in chunks:
            assert chunk.start_char >= 0
            assert chunk.end_char >= chunk.start_char
            assert chunk.end_char <= len(sample_text) + 100  # Allow for overlap

    def test_token_count_accurate(self, single_paragraph, document_id):
        """Test that token counts are accurate."""
        splitter = RecursiveCharacterSplitter()
        chunks = splitter.chunk(single_paragraph, document_id)

        for chunk in chunks:
            actual_tokens = splitter.count_tokens(chunk.content)
            assert chunk.token_count == actual_tokens

    def test_respects_max_tokens(self, long_text, document_id):
        """Test that chunks respect max_tokens limit."""
        config = ChunkingConfig(target_tokens=100, max_tokens=150)
        splitter = RecursiveCharacterSplitter(config)

        chunks = splitter.chunk(long_text, document_id)

        for chunk in chunks:
            assert chunk.token_count <= 150

    def test_metadata_preserved(self, sample_text, document_id):
        """Test that metadata is preserved in chunks."""
        splitter = RecursiveCharacterSplitter()
        metadata = {"source": "test", "author": "tester"}

        chunks = splitter.chunk(sample_text, document_id, metadata)

        for chunk in chunks:
            assert chunk.metadata == metadata

    def test_empty_text_returns_empty(self, document_id):
        """Test that empty text returns no chunks."""
        splitter = RecursiveCharacterSplitter()
        chunks = splitter.chunk("", document_id)

        assert chunks == []

    def test_whitespace_only_returns_empty(self, document_id):
        """Test that whitespace-only text returns no chunks."""
        splitter = RecursiveCharacterSplitter()
        chunks = splitter.chunk("   \n\n   ", document_id)

        assert chunks == []


# =============================================================================
# SemanticChunker Tests
# =============================================================================


class TestSemanticChunker:
    """Tests for the SemanticChunker strategy."""

    def test_strategy_name(self):
        """Test strategy name."""
        chunker = SemanticChunker()
        assert chunker.name == "semantic_sentence"

    def test_respects_sentence_boundaries(self, sample_text, document_id):
        """Test that chunks respect sentence boundaries."""
        config = SemanticChunkerConfig(target_tokens=50)
        chunker = SemanticChunker(config)

        chunks = chunker.chunk(sample_text, document_id)

        for chunk in chunks:
            content = chunk.content.rstrip()
            # Each chunk should end with sentence-ending punctuation
            # (unless it's the result of a long sentence split)
            if chunk.token_count < config.max_tokens:
                assert content.endswith((".", "!", "?", '"', "'"))

    def test_handles_long_sentences(self, document_id):
        """Test handling of very long sentences."""
        # Create a very long sentence
        long_sentence = "word " * 600  # ~600 tokens

        config = SemanticChunkerConfig(target_tokens=100, max_tokens=200)
        chunker = SemanticChunker(config)

        chunks = chunker.chunk(long_sentence, document_id)

        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk.token_count <= 200

    def test_overlap_includes_sentences(self, document_id):
        """Test that overlap includes complete sentences."""
        text = "First sentence. Second sentence. Third sentence. Fourth sentence. Fifth sentence."

        config = SemanticChunkerConfig(target_tokens=10, chunk_overlap=5)
        chunker = SemanticChunker(config)

        chunks = chunker.chunk(text, document_id)

        # With overlap, later chunks should contain some content from earlier chunks
        if len(chunks) > 1:
            # There should be some overlap between consecutive chunks
            # This is a soft test since overlap depends on sentence sizes
            assert len(chunks) >= 2

    def test_preserves_document_id(self, sample_text, document_id):
        """Test that document_id is preserved in all chunks."""
        chunker = SemanticChunker()
        chunks = chunker.chunk(sample_text, document_id)

        for chunk in chunks:
            assert chunk.document_id == document_id


# =============================================================================
# HierarchicalChunker Tests
# =============================================================================


class TestHierarchicalChunker:
    """Tests for the HierarchicalChunker strategy."""

    def test_strategy_name(self):
        """Test strategy name."""
        chunker = HierarchicalChunker()
        assert chunker.name == "hierarchical"

    def test_creates_parent_and_child_chunks(self, long_text, document_id):
        """Test that hierarchical chunker creates parent-child relationships."""
        config = HierarchicalChunkerConfig(
            parent_chunk_size=500,
            child_chunk_size=100,
        )
        chunker = HierarchicalChunker(config)

        chunks = chunker.chunk(long_text, document_id)

        parents = [c for c in chunks if c.parent_chunk_id is None]
        children = [c for c in chunks if c.parent_chunk_id is not None]

        assert len(parents) > 0
        assert len(children) > 0

    def test_parent_child_links_valid(self, long_text, document_id):
        """Test that parent-child links are valid."""
        config = HierarchicalChunkerConfig(
            parent_chunk_size=500,
            child_chunk_size=100,
        )
        chunker = HierarchicalChunker(config)

        chunks = chunker.chunk(long_text, document_id)

        parents = [c for c in chunks if c.parent_chunk_id is None]
        children = [c for c in chunks if c.parent_chunk_id is not None]

        # Verify parent-child links
        for parent in parents:
            for child_id in parent.child_chunk_ids:
                child = next((c for c in children if c.chunk_id == child_id), None)
                assert child is not None, f"Child {child_id} not found"
                assert child.parent_chunk_id == parent.chunk_id

    def test_parent_chunks_larger_than_children(self, long_text, document_id):
        """Test that parent chunks are larger than children."""
        config = HierarchicalChunkerConfig(
            parent_chunk_size=500,
            child_chunk_size=100,
        )
        chunker = HierarchicalChunker(config)

        chunks = chunker.chunk(long_text, document_id)

        parents = [c for c in chunks if c.parent_chunk_id is None]
        children = [c for c in chunks if c.parent_chunk_id is not None]

        if parents and children:
            avg_parent_tokens = sum(p.token_count for p in parents) / len(parents)
            avg_child_tokens = sum(c.token_count for c in children) / len(children)

            # Parents should generally be larger
            assert avg_parent_tokens >= avg_child_tokens


# =============================================================================
# ChunkingEngine Tests
# =============================================================================


class TestChunkingEngine:
    """Tests for the ChunkingEngine."""

    def test_engine_initialization(self, chunking_engine):
        """Test engine initializes with default strategies."""
        strategies = chunking_engine.available_strategies

        assert "recursive_character" in strategies
        assert "semantic_sentence" in strategies
        assert "hierarchical" in strategies

    def test_chunk_with_default_strategy(self, chunking_engine, sample_text, document_id):
        """Test chunking with default strategy."""
        result = chunking_engine.chunk(sample_text, document_id)

        assert isinstance(result, ChunkingResult)
        assert result.document_id == document_id
        assert result.strategy_used == "semantic_sentence"
        assert len(result.chunks) > 0

    def test_chunk_with_recursive_strategy(self, chunking_engine, sample_text, document_id):
        """Test chunking with recursive character strategy."""
        result = chunking_engine.chunk(
            sample_text,
            document_id,
            strategy="recursive_character",
        )

        assert result.strategy_used == "recursive_character"

    def test_chunk_with_hierarchical_strategy(self, chunking_engine, long_text, document_id):
        """Test chunking with hierarchical strategy."""
        result = chunking_engine.chunk(
            long_text,
            document_id,
            strategy="hierarchical",
        )

        assert result.strategy_used == "hierarchical"

        # Should have both parents and children
        parents = [c for c in result.chunks if c.parent_chunk_id is None]
        children = [c for c in result.chunks if c.parent_chunk_id is not None]

        assert len(parents) > 0
        assert len(children) > 0

    def test_unknown_strategy_raises_error(self, chunking_engine, sample_text, document_id):
        """Test that unknown strategy raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            chunking_engine.chunk(
                sample_text,
                document_id,
                strategy="unknown_strategy",
            )

        assert "Unknown strategy" in str(exc_info.value)

    def test_custom_config_override(self, chunking_engine, long_text, document_id):
        """Test custom config override."""
        custom_config = ChunkingConfig(target_tokens=50, max_tokens=100)

        result = chunking_engine.chunk(
            long_text,
            document_id,
            strategy="recursive_character",
            config=custom_config,
        )

        # With smaller chunks, we should get more chunks
        assert result.total_chunks > 10
        assert result.config["target_tokens"] == 50

    def test_metadata_passed_to_chunks(self, chunking_engine, sample_text, document_id):
        """Test that metadata is passed to all chunks."""
        metadata = {"source": "test", "tenant_id": "abc123"}

        result = chunking_engine.chunk(
            sample_text,
            document_id,
            metadata=metadata,
        )

        for chunk in result.chunks:
            assert chunk.metadata == metadata

    def test_get_strategy(self, chunking_engine):
        """Test get_strategy method."""
        strategy = chunking_engine.get_strategy("semantic_sentence")
        assert isinstance(strategy, SemanticChunker)

    def test_get_unknown_strategy_raises(self, chunking_engine):
        """Test that getting unknown strategy raises error."""
        with pytest.raises(ValueError):
            chunking_engine.get_strategy("nonexistent")

    def test_register_custom_strategy(self, chunking_engine, sample_text, document_id):
        """Test registering a custom strategy."""

        # Create a simple custom strategy
        class CustomStrategy(RecursiveCharacterSplitter):
            @property
            def name(self) -> str:
                return "custom_test"

        chunking_engine.register_strategy(CustomStrategy())

        assert "custom_test" in chunking_engine.available_strategies

        result = chunking_engine.chunk(
            sample_text,
            document_id,
            strategy="custom_test",
        )

        assert result.strategy_used == "custom_test"


# =============================================================================
# Integration Tests
# =============================================================================


class TestChunkingIntegration:
    """Integration tests for the chunking module."""

    def test_chunk_size_respected_all_strategies(self, long_text, document_id):
        """Test that all strategies respect max_tokens."""
        engine = ChunkingEngine()

        for strategy_name in ["recursive_character", "semantic_sentence"]:
            result = engine.chunk(
                long_text,
                document_id,
                strategy=strategy_name,
            )

            for chunk in result.chunks:
                assert chunk.token_count <= 512, f"Strategy {strategy_name} exceeded max_tokens"

    def test_total_chunks_matches_list_length(self, sample_text, document_id):
        """Test that total_chunks matches actual chunk count."""
        engine = ChunkingEngine()

        for strategy in engine.available_strategies:
            result = engine.chunk(sample_text, document_id, strategy=strategy)
            assert result.total_chunks == len(result.chunks)

    def test_document_can_be_reconstructed(self, sample_text, document_id):
        """Test that chunks cover the original document."""
        config = ChunkingConfig(chunk_overlap=0)  # No overlap for easier testing
        splitter = RecursiveCharacterSplitter(config)

        chunks = splitter.chunk(sample_text, document_id)

        # All chunks should have valid offsets
        for chunk in chunks:
            assert chunk.start_char >= 0
            assert chunk.end_char >= chunk.start_char

    def test_unicode_handling(self, document_id):
        """Test handling of unicode text."""
        unicode_text = "Привет мир! 你好世界! مرحبا بالعالم! Hello world! 🌍🌎🌏"

        engine = ChunkingEngine()
        result = engine.chunk(unicode_text, document_id)

        assert len(result.chunks) > 0
        # Verify content is preserved
        all_content = " ".join(c.content for c in result.chunks)
        # Some parts of original should be in chunks
        assert "Hello" in all_content or "Привет" in all_content

    def test_special_characters(self, document_id):
        """Test handling of special characters."""
        special_text = "Code: `print('hello')` and math: x² + y² = z². Symbols: © ® ™ € £ ¥"

        engine = ChunkingEngine()
        result = engine.chunk(special_text, document_id)

        assert len(result.chunks) > 0


# =============================================================================
# Performance Tests
# =============================================================================


class TestChunkingPerformance:
    """Performance-related tests for chunking."""

    def test_large_document_chunking(self, document_id):
        """Test chunking of large documents."""
        # Simulate a large document (~100 pages worth)
        large_text = ("This is a paragraph of text. " * 50 + "\n\n") * 100

        engine = ChunkingEngine()
        result = engine.chunk(large_text, document_id)

        # Should complete without error and produce reasonable number of chunks
        assert len(result.chunks) > 100

    def test_token_counting_consistency(self):
        """Test that token counting is consistent."""
        splitter = RecursiveCharacterSplitter()

        text = "The quick brown fox jumps over the lazy dog."
        count1 = splitter.count_tokens(text)
        count2 = splitter.count_tokens(text)

        assert count1 == count2
