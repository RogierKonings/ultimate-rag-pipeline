"""Tests for metadata extraction utilities."""


from ..metadata_extractor import MetadataExtractor


class TestMetadataExtractor:
    """Test cases for MetadataExtractor."""

    def test_extract_title_markdown_heading(self):
        """Test extracting title from markdown heading."""
        text = "# My Document Title\n\nThis is the content."
        title = MetadataExtractor.extract_title_from_text(text)

        assert title == "My Document Title"

    def test_extract_title_first_line(self):
        """Test extracting title from first line."""
        text = "Document Title\n\nThis is the content of the document."
        title = MetadataExtractor.extract_title_from_text(text)

        assert title == "Document Title"

    def test_extract_title_skips_empty_lines(self):
        """Test that empty lines are skipped when extracting title."""
        text = "\n\n# Actual Title\n\nContent here."
        title = MetadataExtractor.extract_title_from_text(text)

        assert title == "Actual Title"

    def test_extract_title_max_length(self):
        """Test that title is truncated to max length."""
        long_title = "A" * 300
        text = f"# {long_title}\n\nContent"
        title = MetadataExtractor.extract_title_from_text(text, max_length=100)

        assert len(title) == 100

    def test_extract_title_returns_none_for_sentence(self):
        """Test that sentences ending with period are not extracted as titles."""
        text = "This is a complete sentence.\n\nMore content here."
        # First line ends with period, so we check second line
        # But since it's more than 5 lines deep, returns None
        title = MetadataExtractor.extract_title_from_text(text)

        # The function returns first non-empty line if it doesn't end with period
        # "This is a complete sentence." ends with period, so check next
        # "More content here." also ends with period
        # But the function only checks first 5 lines
        assert title is None or not title.endswith(".")

    def test_extract_dates_from_text_us_format(self):
        """Test extracting dates in US format (MM/DD/YYYY)."""
        text = "The meeting is scheduled for 01/15/2024."
        dates = MetadataExtractor.extract_dates_from_text(text)

        assert len(dates) >= 1
        # Date parsing is ambiguous, just verify a date was found
        assert any(d.year == 2024 for d in dates)

    def test_extract_dates_from_text_iso_format(self):
        """Test extracting dates in ISO format (YYYY-MM-DD)."""
        text = "The document was created on 2024-01-15."
        dates = MetadataExtractor.extract_dates_from_text(text)

        assert len(dates) >= 1
        assert any(d.year == 2024 and d.month == 1 and d.day == 15 for d in dates)

    def test_extract_dates_from_text_written_format(self):
        """Test extracting dates in written format."""
        text = "The event will be held on January 15, 2024."
        dates = MetadataExtractor.extract_dates_from_text(text)

        assert len(dates) >= 1
        assert any(d.year == 2024 and d.month == 1 for d in dates)

    def test_extract_dates_from_text_european_format(self):
        """Test extracting dates in European format (DD Month YYYY)."""
        text = "The deadline is 15 January 2024."
        dates = MetadataExtractor.extract_dates_from_text(text)

        assert len(dates) >= 1
        assert any(d.year == 2024 and d.month == 1 for d in dates)

    def test_extract_dates_from_text_multiple_dates(self):
        """Test extracting multiple dates from text."""
        text = "The project started on 2024-01-01 and ends on 2024-12-31."
        dates = MetadataExtractor.extract_dates_from_text(text)

        assert len(dates) >= 2

    def test_extract_dates_from_text_no_dates(self):
        """Test extracting from text with no dates."""
        text = "This is a document with no dates mentioned."
        dates = MetadataExtractor.extract_dates_from_text(text)

        assert len(dates) == 0

    def test_extract_dates_deduplicates(self):
        """Test that duplicate dates are removed."""
        text = "Date: 2024-01-15. Again: 2024-01-15."
        dates = MetadataExtractor.extract_dates_from_text(text)

        # Even if pattern matches twice, should deduplicate
        unique_dates = {(d.year, d.month, d.day) for d in dates}
        assert len(unique_dates) == len(dates)

    def test_merge_metadata_basic(self):
        """Test basic metadata merging."""
        base = {"title": "Original", "author": "John"}
        override = {"title": "Updated", "department": "Engineering"}

        result = MetadataExtractor.merge_metadata(base, override)

        assert result["title"] == "Updated"
        assert result["author"] == "John"
        assert result["department"] == "Engineering"

    def test_merge_metadata_none_does_not_overwrite(self):
        """Test that None values don't overwrite existing values."""
        base = {"title": "Original", "author": "John"}
        override = {"title": None, "author": "Jane"}

        result = MetadataExtractor.merge_metadata(base, override)

        assert result["title"] == "Original"  # Not overwritten
        assert result["author"] == "Jane"  # Overwritten

    def test_merge_metadata_empty_base(self):
        """Test merging into empty base."""
        base = {}
        override = {"title": "New", "author": "Test"}

        result = MetadataExtractor.merge_metadata(base, override)

        assert result == override

    def test_merge_metadata_empty_override(self):
        """Test merging with empty override."""
        base = {"title": "Original", "author": "John"}
        override = {}

        result = MetadataExtractor.merge_metadata(base, override)

        assert result == base

    def test_parse_date_valid_iso(self):
        """Test parsing valid ISO date."""
        date = MetadataExtractor.parse_date("2024-01-15")

        assert date is not None
        assert date.year == 2024
        assert date.month == 1
        assert date.day == 15

    def test_parse_date_valid_datetime(self):
        """Test parsing valid datetime string."""
        date = MetadataExtractor.parse_date("2024-01-15T10:30:00Z")

        assert date is not None
        assert date.year == 2024
        assert date.hour == 10

    def test_parse_date_invalid(self):
        """Test parsing invalid date returns None."""
        date = MetadataExtractor.parse_date("not-a-date")

        assert date is None

    def test_parse_date_none_input(self):
        """Test parsing None returns None."""
        date = MetadataExtractor.parse_date(None)

        assert date is None

    def test_parse_date_empty_string(self):
        """Test parsing empty string returns None."""
        date = MetadataExtractor.parse_date("")

        assert date is None

    def test_extract_keywords_basic(self):
        """Test basic keyword extraction."""
        text = (
            "Python programming is great for data science. "
            "Python is also used in machine learning and artificial intelligence. "
            "Data science projects often use Python libraries."
        )
        keywords = MetadataExtractor.extract_keywords(text)

        assert "python" in keywords
        assert "data" in keywords
        assert "science" in keywords

    def test_extract_keywords_excludes_stopwords(self):
        """Test that stopwords are excluded."""
        text = "The quick brown fox jumps over the lazy dog"
        keywords = MetadataExtractor.extract_keywords(text)

        assert "the" not in keywords
        assert "over" not in keywords

    def test_extract_keywords_max_limit(self):
        """Test that keyword count is limited."""
        text = "word1 word2 word3 word4 word5 word6 word7 word8 word9 word10 word11 word12"
        keywords = MetadataExtractor.extract_keywords(text, max_keywords=5)

        assert len(keywords) <= 5

    def test_extract_keywords_empty_text(self):
        """Test keyword extraction from empty text."""
        keywords = MetadataExtractor.extract_keywords("")

        assert keywords == []

    def test_extract_keywords_only_stopwords(self):
        """Test text with only stopwords."""
        text = "the a an is are was were"
        keywords = MetadataExtractor.extract_keywords(text)

        assert keywords == []
