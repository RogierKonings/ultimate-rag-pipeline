"""Detection utilities for guardrails.

This module provides pattern-based detection for:
- PII (emails, phone numbers, SSNs, credit cards, IP addresses)
- Prompt injection attempts
- Harmful content
"""

import re
from dataclasses import dataclass

from .models import PIIType


@dataclass
class DetectionMatch:
    """A detection match result."""

    matched_text: str
    start: int
    end: int
    pattern_name: str
    details: dict | None = None


# =============================================================================
# PII Detection Patterns
# =============================================================================

# Email pattern - RFC 5322 simplified
EMAIL_PATTERN = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
    re.IGNORECASE,
)

# Phone number patterns (US formats)
PHONE_PATTERNS = [
    # (123) 456-7890
    re.compile(r"\(\d{3}\)\s*\d{3}[-.\s]?\d{4}"),
    # 123-456-7890
    re.compile(r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b"),
    # 1234567890 (10 digits)
    re.compile(r"\b\d{10}\b"),
    # +1 123 456 7890
    re.compile(r"\+1\s*\d{3}[-.\s]?\d{3}[-.\s]?\d{4}"),
]

# SSN pattern - XXX-XX-XXXX
SSN_PATTERN = re.compile(r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b")

# Credit card patterns
CREDIT_CARD_PATTERNS = [
    # Visa: 4XXX-XXXX-XXXX-XXXX
    re.compile(r"\b4\d{3}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"),
    # MasterCard: 5XXX-XXXX-XXXX-XXXX
    re.compile(r"\b5[1-5]\d{2}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"),
    # American Express: 3XXX-XXXXXX-XXXXX
    re.compile(r"\b3[47]\d{2}[-\s]?\d{6}[-\s]?\d{5}\b"),
    # Generic 16-digit card number
    re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"),
]

# IP Address pattern (IPv4)
IP_ADDRESS_PATTERN = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}"
    r"(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b",
)


def detect_pii(text: str) -> list[DetectionMatch]:
    """Detect PII in text.

    Args:
        text: The text to scan for PII.

    Returns:
        List of DetectionMatch objects for each PII found.
    """
    matches: list[DetectionMatch] = []

    # Detect emails
    for match in EMAIL_PATTERN.finditer(text):
        matches.append(
            DetectionMatch(
                matched_text=match.group(),
                start=match.start(),
                end=match.end(),
                pattern_name="email",
                details={"pii_type": PIIType.EMAIL.value},
            ),
        )

    # Detect phone numbers
    for pattern in PHONE_PATTERNS:
        for match in pattern.finditer(text):
            # Avoid duplicate matches
            if not _overlaps_existing(matches, match.start(), match.end()):
                matches.append(
                    DetectionMatch(
                        matched_text=match.group(),
                        start=match.start(),
                        end=match.end(),
                        pattern_name="phone",
                        details={"pii_type": PIIType.PHONE.value},
                    ),
                )

    # Detect SSNs
    for match in SSN_PATTERN.finditer(text):
        # Exclude if it looks like a phone number (already matched)
        if not _overlaps_existing(matches, match.start(), match.end()):
            matches.append(
                DetectionMatch(
                    matched_text=match.group(),
                    start=match.start(),
                    end=match.end(),
                    pattern_name="ssn",
                    details={"pii_type": PIIType.SSN.value},
                ),
            )

    # Detect credit cards
    for pattern in CREDIT_CARD_PATTERNS:
        for match in pattern.finditer(text):
            if not _overlaps_existing(matches, match.start(), match.end()):
                matches.append(
                    DetectionMatch(
                        matched_text=match.group(),
                        start=match.start(),
                        end=match.end(),
                        pattern_name="credit_card",
                        details={"pii_type": PIIType.CREDIT_CARD.value},
                    ),
                )

    # Detect IP addresses
    for match in IP_ADDRESS_PATTERN.finditer(text):
        if not _overlaps_existing(matches, match.start(), match.end()):
            matches.append(
                DetectionMatch(
                    matched_text=match.group(),
                    start=match.start(),
                    end=match.end(),
                    pattern_name="ip_address",
                    details={"pii_type": PIIType.IP_ADDRESS.value},
                ),
            )

    return matches


def _overlaps_existing(matches: list[DetectionMatch], start: int, end: int) -> bool:
    """Check if a range overlaps with existing matches."""
    return any(not (end <= m.start or start >= m.end) for m in matches)


# =============================================================================
# Prompt Injection Detection Patterns
# =============================================================================

# Patterns that indicate prompt injection attempts
INJECTION_PATTERNS = [
    # Direct instruction override attempts
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|above)\s+instructions?", re.IGNORECASE),
    re.compile(r"forget\s+(all\s+)?(previous|prior|above)\s+instructions?", re.IGNORECASE),
    # System prompt extraction
    re.compile(r"(reveal|show|display|print|output)\s+(your\s+)?(system\s+)?prompt", re.IGNORECASE),
    re.compile(r"what\s+(is|are)\s+(your\s+)?(system\s+)?instructions?", re.IGNORECASE),
    re.compile(r"(tell|show)\s+me\s+(your\s+)?(system\s+)?prompt", re.IGNORECASE),
    # Role playing attacks
    re.compile(r"you\s+are\s+now\s+(a\s+)?new\s+ai", re.IGNORECASE),
    re.compile(r"pretend\s+(you\s+are|to\s+be)\s+a\s+different\s+ai", re.IGNORECASE),
    re.compile(r"act\s+as\s+(if\s+you\s+are\s+)?(a\s+)?different\s+ai", re.IGNORECASE),
    # Jailbreak patterns
    re.compile(r"(dan|dude|developer)\s+mode", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"bypass\s+(your\s+)?(safety|security|restrictions?)", re.IGNORECASE),
    # Delimiter injection
    re.compile(r"<\|system\|>", re.IGNORECASE),
    re.compile(r"<\|user\|>", re.IGNORECASE),
    re.compile(r"<\|assistant\|>", re.IGNORECASE),
    re.compile(r"\[INST\]", re.IGNORECASE),
    re.compile(r"\[/INST\]", re.IGNORECASE),
    re.compile(r"<<SYS>>", re.IGNORECASE),
    re.compile(r"<</SYS>>", re.IGNORECASE),
    # Code/command injection attempts
    re.compile(r"execute\s+(the\s+)?following\s+(code|command|script)", re.IGNORECASE),
    re.compile(r"run\s+(the\s+)?following\s+(code|command|script)", re.IGNORECASE),
]


def detect_injection(text: str) -> list[DetectionMatch]:
    """Detect prompt injection attempts in text.

    Args:
        text: The text to scan for injection attempts.

    Returns:
        List of DetectionMatch objects for each injection pattern found.
    """
    matches: list[DetectionMatch] = []

    for pattern in INJECTION_PATTERNS:
        for match in pattern.finditer(text):
            if not _overlaps_existing(matches, match.start(), match.end()):
                matches.append(
                    DetectionMatch(
                        matched_text=match.group(),
                        start=match.start(),
                        end=match.end(),
                        pattern_name="injection",
                        details={"pattern": pattern.pattern},
                    ),
                )

    return matches


# =============================================================================
# Harmful Content Detection
# =============================================================================

# Basic harmful content blocklist - categories with severity
HARMFUL_PATTERNS = [
    # Violence and threats
    (
        re.compile(r"\b(kill|murder|assassinate)\s+(you|yourself|them|him|her)\b", re.IGNORECASE),
        "violence",
        "high",
    ),
    (
        re.compile(r"\b(how\s+to\s+make\s+a?\s*)?(bomb|explosive|weapon)\b", re.IGNORECASE),
        "violence",
        "critical",
    ),
    (re.compile(r"\bterrorist?\s+(attack|plot)\b", re.IGNORECASE), "violence", "critical"),
    # Self-harm
    (re.compile(r"\bhow\s+to\s+(commit\s+)?suicide\b", re.IGNORECASE), "self_harm", "critical"),
    (re.compile(r"\bharm\s+(myself|yourself)\b", re.IGNORECASE), "self_harm", "high"),
    # Illegal activities
    (re.compile(r"\bhow\s+to\s+(hack|crack)\s+(into|a)\b", re.IGNORECASE), "illegal", "high"),
    (
        re.compile(r"\b(buy|sell|obtain)\s+illegal\s+(drugs|weapons)\b", re.IGNORECASE),
        "illegal",
        "high",
    ),
    # Hate speech (basic patterns)
    (
        re.compile(r"\bexterminate\s+(all\s+)?(the\s+)?[a-z]+s?\b", re.IGNORECASE),
        "hate",
        "critical",
    ),
]


def detect_harmful_content(text: str) -> list[DetectionMatch]:
    """Detect harmful content in text.

    Args:
        text: The text to scan for harmful content.

    Returns:
        List of DetectionMatch objects for each harmful pattern found.
    """
    matches: list[DetectionMatch] = []

    for pattern, category, severity in HARMFUL_PATTERNS:
        for match in pattern.finditer(text):
            if not _overlaps_existing(matches, match.start(), match.end()):
                matches.append(
                    DetectionMatch(
                        matched_text=match.group(),
                        start=match.start(),
                        end=match.end(),
                        pattern_name="harmful_content",
                        details={"category": category, "severity": severity},
                    ),
                )

    return matches


# =============================================================================
# Hallucination Detection
# =============================================================================


def detect_hallucination(
    response: str, context: str, threshold: float = 0.5,
) -> list[DetectionMatch]:
    """Detect potential hallucinations in a response.

    This is a basic implementation that checks if key claims in the response
    can be found in the provided context. A more sophisticated implementation
    would use semantic similarity or NLI models.

    Args:
        response: The LLM response to check.
        context: The context/source documents used to generate the response.
        threshold: Similarity threshold (0-1). Lower = more strict.

    Returns:
        List of DetectionMatch objects for potential hallucinations.
    """
    matches: list[DetectionMatch] = []

    if not context or not response:
        return matches

    # Normalize texts for comparison
    context_lower = context.lower()
    response_sentences = _split_sentences(response)

    for sentence in response_sentences:
        sentence_lower = sentence.strip().lower()

        # Skip very short sentences
        if len(sentence_lower) < 20:
            continue

        # Extract key terms from the sentence
        key_terms = _extract_key_terms(sentence_lower)

        if not key_terms:
            continue

        # Count how many key terms appear in context
        terms_found = sum(1 for term in key_terms if term in context_lower)
        coverage = terms_found / len(key_terms) if key_terms else 1.0

        # If coverage is below threshold, flag as potential hallucination
        if coverage < threshold:
            # Find the position in the original response
            start = response.lower().find(sentence_lower)
            if start == -1:
                start = 0
            end = start + len(sentence)

            matches.append(
                DetectionMatch(
                    matched_text=sentence.strip(),
                    start=start,
                    end=end,
                    pattern_name="hallucination",
                    details={
                        "coverage": coverage,
                        "key_terms": key_terms,
                        "terms_found": terms_found,
                    },
                ),
            )

    return matches


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    # Simple sentence splitting - could be improved with NLTK or spaCy
    sentences = re.split(r"[.!?]+", text)
    return [s.strip() for s in sentences if s.strip()]


def _extract_key_terms(text: str) -> list[str]:
    """Extract key terms from text for hallucination detection.

    This is a simple implementation that extracts:
    - Proper nouns (capitalized words)
    - Numbers
    - Technical terms (longer words)
    """
    # Common stopwords to exclude
    stopwords = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "and",
        "or",
        "but",
        "if",
        "then",
        "that",
        "this",
        "these",
        "those",
        "it",
        "its",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "under",
        "again",
        "further",
        "once",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "all",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
    }

    # Extract words
    words = re.findall(r"\b[a-zA-Z0-9]+\b", text)

    key_terms = []
    for word in words:
        word_lower = word.lower()

        # Skip stopwords
        if word_lower in stopwords:
            continue

        # Skip very short words
        if len(word) < 3:
            continue

        # Include numbers
        if word.isdigit():
            key_terms.append(word)
            continue

        # Include longer words (likely meaningful)
        if len(word) >= 5:
            key_terms.append(word_lower)

    return list(set(key_terms))  # Remove duplicates
