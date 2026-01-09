"""Tests for context formatting utilities."""

import pytest

from prompts.context import (
    count_tokens,
    get_tokenizer,
    format_context,
    format_citations,
    truncate_context,
    truncate_documents,
    format_history_summary,
    extract_document_metadata,
)


class TestGetTokenizer:
    """Tests for the get_tokenizer function."""

    def test_get_tokenizer_for_gpt4(self):
        """Should return encoding for GPT-4."""
        encoding = get_tokenizer("gpt-4")
        assert encoding is not None

    def test_get_tokenizer_for_unknown_model(self):
        """Should fall back to cl100k_base for unknown models."""
        encoding = get_tokenizer("unknown-model-xyz")
        assert encoding is not None

    def test_get_tokenizer_encodes_text(self):
        """Tokenizer should be able to encode text."""
        encoding = get_tokenizer("gpt-4")
        tokens = encoding.encode("Hello, world!")
        assert isinstance(tokens, list)
        assert len(tokens) > 0


class TestCountTokens:
    """Tests for the count_tokens function."""

    def test_count_tokens_empty_string(self):
        """Empty string should return 0 tokens."""
        assert count_tokens("") == 0

    def test_count_tokens_simple_text(self):
        """Simple text should return positive token count."""
        tokens = count_tokens("Hello, world!")
        assert tokens > 0
        assert tokens < 10  # Simple greeting should be few tokens

    def test_count_tokens_longer_text(self):
        """Longer text should have more tokens."""
        short_text = "Hello"
        long_text = "This is a much longer piece of text that should have more tokens."

        short_tokens = count_tokens(short_text)
        long_tokens = count_tokens(long_text)

        assert long_tokens > short_tokens

    def test_count_tokens_with_model_name(self):
        """Should work with different model names."""
        text = "Test text"
        tokens_gpt4 = count_tokens(text, "gpt-4")
        tokens_default = count_tokens(text)

        # Both should return the same for same encoding
        assert tokens_gpt4 == tokens_default


class TestFormatContext:
    """Tests for the format_context function."""

    @pytest.fixture
    def sample_documents(self):
        """Create sample documents for testing."""
        return [
            {
                "content": "Python is a versatile programming language.",
                "title": "Python Introduction",
                "source": "docs/python-intro.md",
                "metadata": {"title": "Python Introduction"},
            },
            {
                "content": "Python supports multiple paradigms.",
                "source": "docs/python-features.md",
                "metadata": {"title": "Python Features"},
            },
        ]

    def test_format_context_empty_list(self):
        """Empty document list should return empty string."""
        assert format_context([]) == ""

    def test_format_context_single_document(self):
        """Single document should be formatted correctly."""
        docs = [{"content": "Test content", "title": "Test Doc"}]
        context = format_context(docs)

        assert "[1]" in context
        assert "Test Doc" in context
        assert "Test content" in context

    def test_format_context_multiple_documents(self, sample_documents):
        """Multiple documents should be numbered and separated."""
        context = format_context(sample_documents)

        assert "[1]" in context
        assert "[2]" in context
        assert "Python Introduction" in context
        assert "Python Features" in context
        assert "---" in context  # Separator

    def test_format_context_with_source(self, sample_documents):
        """Documents with source should include source in output."""
        context = format_context(sample_documents)

        assert "Source:" in context
        assert "docs/python-intro.md" in context

    def test_format_context_uses_metadata_title(self):
        """Should prefer metadata title over direct title."""
        docs = [
            {
                "content": "Content here",
                "title": "Direct Title",
                "metadata": {"title": "Metadata Title"},
            }
        ]
        context = format_context(docs)

        assert "Metadata Title" in context

    def test_format_context_skips_empty_content(self):
        """Documents with empty content should be skipped."""
        docs = [
            {"content": "", "title": "Empty Doc"},
            {"content": "Valid content", "title": "Valid Doc"},
        ]
        context = format_context(docs)

        assert "Valid content" in context
        # Empty doc should not appear
        assert context.count("[") == 1


class TestFormatCitations:
    """Tests for the format_citations function."""

    @pytest.fixture
    def sample_documents(self):
        """Create sample documents for testing."""
        return [
            {
                "content": "Content 1",
                "title": "Doc One",
                "source": "path/to/doc1.md",
                "metadata": {"title": "Document One"},
            },
            {
                "content": "Content 2",
                "source": "path/to/doc2.md",
                "metadata": {"title": "Document Two"},
            },
        ]

    def test_format_citations_empty_list(self):
        """Empty list should return empty string."""
        assert format_citations([]) == ""

    def test_format_citations_single_document(self):
        """Single document should produce single citation."""
        docs = [{"title": "Test Doc", "source": "test.md", "metadata": {}}]
        citations = format_citations(docs)

        assert "[1]" in citations
        assert "Test Doc" in citations

    def test_format_citations_includes_source(self, sample_documents):
        """Citations should include source paths."""
        citations = format_citations(sample_documents)

        assert "path/to/doc1.md" in citations

    def test_format_citations_respects_max_limit(self):
        """Should respect max_citations parameter."""
        docs = [{"content": f"Content {i}", "title": f"Doc {i}", "metadata": {}} for i in range(10)]

        citations = format_citations(docs, max_citations=3)

        assert "[1]" in citations
        assert "[2]" in citations
        assert "[3]" in citations
        assert "[4]" not in citations

    def test_format_citations_newline_separated(self, sample_documents):
        """Citations should be newline separated."""
        citations = format_citations(sample_documents)

        lines = citations.strip().split("\n")
        assert len(lines) == 2


class TestTruncateContext:
    """Tests for the truncate_context function."""

    def test_truncate_context_empty_string(self):
        """Empty string should return empty tuple."""
        result, truncated = truncate_context("", 100)
        assert result == ""
        assert truncated is False

    def test_truncate_context_short_text(self):
        """Short text within limit should not be truncated."""
        text = "Hello world"
        result, truncated = truncate_context(text, 100)

        assert result == text
        assert truncated is False

    def test_truncate_context_long_text(self):
        """Long text should be truncated."""
        text = "This is a test. " * 100  # Long text
        result, truncated = truncate_context(text, 50)

        assert truncated is True
        assert len(result) < len(text)

    def test_truncate_context_adds_ellipsis(self):
        """Truncated text should end with ellipsis."""
        text = "This is a very long piece of text that will need to be truncated. " * 20
        result, truncated = truncate_context(text, 50)

        assert truncated is True
        assert "..." in result

    def test_truncate_context_preserve_end(self):
        """preserve_end=True should keep the end of text."""
        text = "Beginning content. " * 20 + "End content."
        result, truncated = truncate_context(text, 50, preserve_end=True)

        assert truncated is True
        # Should contain end, may start with ellipsis
        assert "End content" in result


class TestTruncateDocuments:
    """Tests for the truncate_documents function."""

    @pytest.fixture
    def sample_documents(self):
        """Create sample documents for testing."""
        return [
            {"content": "Short content", "title": "Doc 1"},
            {"content": "Another short document", "title": "Doc 2"},
            {"content": "Third document here", "title": "Doc 3"},
        ]

    def test_truncate_documents_empty_list(self):
        """Empty list should return empty list."""
        result, truncated = truncate_documents([], 100)
        assert result == []
        assert truncated is False

    def test_truncate_documents_within_limit(self, sample_documents):
        """Documents within limit should all be included."""
        result, truncated = truncate_documents(sample_documents, 10000)

        assert len(result) == len(sample_documents)
        assert truncated is False

    def test_truncate_documents_exceeds_limit(self):
        """Documents exceeding limit should be truncated."""
        docs = [
            {"content": "Word " * 200, "title": f"Doc {i}"}
            for i in range(5)
        ]
        result, truncated = truncate_documents(docs, 100)

        assert truncated is True
        assert len(result) < len(docs)

    def test_truncate_documents_marks_truncated(self):
        """Last included document may be marked as truncated."""
        docs = [
            {"content": "Word " * 100, "title": "Doc 1"},
            {"content": "Word " * 100, "title": "Doc 2"},
        ]
        result, truncated = truncate_documents(docs, 150)

        # Either fewer docs or some marked truncated
        assert truncated or any(d.get("truncated") for d in result)


class TestFormatHistorySummary:
    """Tests for the format_history_summary function."""

    @pytest.fixture
    def sample_history(self):
        """Create sample conversation history."""
        return [
            {"role": "user", "content": "What is Python?"},
            {"role": "assistant", "content": "Python is a programming language."},
            {"role": "user", "content": "Tell me more."},
        ]

    def test_format_history_empty_list(self):
        """Empty history should return empty string."""
        assert format_history_summary([]) == ""

    def test_format_history_single_message(self):
        """Single message should be formatted."""
        history = [{"role": "user", "content": "Hello"}]
        result = format_history_summary(history)

        assert "User:" in result
        assert "Hello" in result

    def test_format_history_multiple_messages(self, sample_history):
        """Multiple messages should all be included."""
        result = format_history_summary(sample_history)

        assert "User:" in result
        assert "Assistant:" in result
        assert "What is Python?" in result

    def test_format_history_respects_max_messages(self, sample_history):
        """Should respect max_messages parameter."""
        result = format_history_summary(sample_history, max_messages=2)

        # Only last 2 messages
        assert "Tell me more" in result

    def test_format_history_truncates_long_content(self):
        """Very long messages should be truncated in summary."""
        history = [{"role": "user", "content": "x" * 1000}]
        result = format_history_summary(history)

        assert len(result) < 1000
        assert "..." in result


class TestExtractDocumentMetadata:
    """Tests for the extract_document_metadata function."""

    @pytest.fixture
    def sample_documents(self):
        """Create sample documents for testing."""
        return [
            {
                "id": "doc-abc",
                "content": "Content",
                "source": "path/to/doc.md",
                "score": 0.95,
                "metadata": {"title": "Test Document"},
            },
            {
                "content": "More content",
                "title": "Direct Title",
                "source": "another/path.md",
                "score": 0.88,
                "metadata": {},
            },
        ]

    def test_extract_metadata_empty_list(self):
        """Empty list should return empty list."""
        assert extract_document_metadata([]) == []

    def test_extract_metadata_includes_index(self, sample_documents):
        """Metadata should include 1-based index."""
        metadata = extract_document_metadata(sample_documents)

        assert metadata[0]["index"] == 1
        assert metadata[1]["index"] == 2

    def test_extract_metadata_includes_id(self, sample_documents):
        """Metadata should include document ID."""
        metadata = extract_document_metadata(sample_documents)

        assert metadata[0]["id"] == "doc-abc"

    def test_extract_metadata_includes_title(self, sample_documents):
        """Metadata should include title from metadata or direct."""
        metadata = extract_document_metadata(sample_documents)

        assert metadata[0]["title"] == "Test Document"  # From metadata
        assert metadata[1]["title"] == "Direct Title"  # From direct title

    def test_extract_metadata_includes_source(self, sample_documents):
        """Metadata should include source path."""
        metadata = extract_document_metadata(sample_documents)

        assert metadata[0]["source"] == "path/to/doc.md"

    def test_extract_metadata_includes_score(self, sample_documents):
        """Metadata should include relevance score."""
        metadata = extract_document_metadata(sample_documents)

        assert metadata[0]["score"] == 0.95
        assert metadata[1]["score"] == 0.88

    def test_extract_metadata_default_values(self):
        """Missing fields should have sensible defaults."""
        docs = [{"content": "Just content"}]
        metadata = extract_document_metadata(docs)

        assert metadata[0]["index"] == 1
        assert "Document 1" in metadata[0]["title"]
        assert metadata[0]["source"] == ""
        assert metadata[0]["score"] is None
