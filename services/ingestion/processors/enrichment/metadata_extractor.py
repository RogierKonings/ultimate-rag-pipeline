"""Metadata extraction utilities."""

import re
from datetime import datetime
from typing import Any

from dateutil import parser as date_parser
from dateutil.parser import ParserError


class MetadataExtractor:
    """Extract structured metadata from document content."""

    @staticmethod
    def extract_title_from_text(
        text: str, max_length: int = 200,
    ) -> str | None:
        """
        Extract title from text if not provided by parser.

        Heuristics:
        - First non-empty line if it looks like a title
        - First heading marker (# in markdown)

        Args:
            text: Document text
            max_length: Maximum title length

        Returns:
            Extracted title or None if not found
        """
        lines = text.strip().split("\n")

        for line in lines[:5]:  # Check first 5 lines
            line = line.strip()
            if not line:
                continue

            # Markdown heading
            if line.startswith("# "):
                return line[2:].strip()[:max_length]

            # Short line that looks like a title (no period at end)
            if len(line) < max_length and not line.endswith("."):
                return line

        return None

    @staticmethod
    def extract_dates_from_text(text: str) -> list[datetime]:
        """
        Extract dates mentioned in text.

        Useful for documents without proper metadata.

        Args:
            text: Document text

        Returns:
            List of unique datetime objects found in text
        """
        # Common date patterns
        date_patterns = [
            r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
            r"\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b",
            r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}\b",
            r"\b\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4}\b",
        ]

        dates: list[datetime] = []
        seen: set[str] = set()

        for pattern in date_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                if match in seen:
                    continue
                seen.add(match)
                try:
                    parsed = date_parser.parse(match, fuzzy=False)
                    dates.append(parsed)
                except (ParserError, ValueError, OverflowError):
                    continue

        return dates

    @staticmethod
    def merge_metadata(
        base: dict[str, Any],
        override: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Merge metadata dictionaries.

        Override values take precedence, but None values don't overwrite
        existing values.

        Args:
            base: Base metadata dictionary
            override: Override values (takes precedence if not None)

        Returns:
            Merged metadata dictionary
        """
        result = base.copy()
        for key, value in override.items():
            if value is not None:
                result[key] = value
        return result

    @staticmethod
    def parse_date(date_str: str | None) -> datetime | None:
        """
        Parse date string to datetime.

        Args:
            date_str: Date string in various formats

        Returns:
            Parsed datetime or None if parsing fails
        """
        if not date_str:
            return None

        try:
            return date_parser.parse(date_str)
        except (ParserError, ValueError, OverflowError):
            return None

    @staticmethod
    def extract_keywords(text: str, max_keywords: int = 10) -> list[str]:
        """
        Extract potential keywords from text using simple heuristics.

        This is a basic implementation. For production use,
        consider using NLP-based keyword extraction.

        Args:
            text: Document text
            max_keywords: Maximum number of keywords to return

        Returns:
            List of potential keywords
        """
        # Simple word frequency approach (excluding common words)
        stopwords = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "must", "shall",
            "can", "need", "dare", "ought", "used", "to", "of", "in",
            "for", "on", "with", "at", "by", "from", "as", "into",
            "through", "during", "before", "after", "above", "below",
            "between", "under", "again", "further", "then", "once",
            "here", "there", "when", "where", "why", "how", "all",
            "each", "few", "more", "most", "other", "some", "such",
            "no", "nor", "not", "only", "own", "same", "so", "than",
            "too", "very", "just", "and", "but", "if", "or", "because",
            "until", "while", "this", "that", "these", "those", "it",
            "its", "i", "me", "my", "we", "our", "you", "your", "he",
            "him", "his", "she", "her", "they", "them", "their", "what",
            "which", "who", "whom",
        }

        # Extract words (alphanumeric only)
        words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())

        # Count frequency excluding stopwords
        word_counts: dict[str, int] = {}
        for word in words:
            if word not in stopwords:
                word_counts[word] = word_counts.get(word, 0) + 1

        # Sort by frequency and return top keywords
        sorted_words = sorted(
            word_counts.items(), key=lambda x: x[1], reverse=True,
        )
        return [word for word, _ in sorted_words[:max_keywords]]
