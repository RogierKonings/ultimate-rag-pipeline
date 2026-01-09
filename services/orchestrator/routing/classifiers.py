"""Classification utilities for query routing."""

import re
from typing import Optional


class KeywordClassifier:
    """Fast pattern-based classifier for query intent detection."""

    # Greeting patterns (case-insensitive)
    GREETING_PATTERNS = [
        r"^(hi|hello|hey|howdy|greetings|yo|hiya)[\s!.,?]*$",
        r"^(good\s+(morning|afternoon|evening|day))[\s!.,?]*$",
        r"^(what'?s\s+up|sup|wassup)[\s!.,?]*$",
        r"^hi\s+there[\s!.,?]*$",
    ]

    # Gratitude/closing patterns
    GRATITUDE_PATTERNS = [
        r"^(thanks|thank\s+you|thx|ty|cheers)[\s!.,?]*$",
        r"^(bye|goodbye|see\s+you|later|take\s+care)[\s!.,?]*$",
        r"^(ok|okay|got\s+it|understood|perfect|great)[\s!.,?]*$",
    ]

    # Question word patterns
    QUESTION_PATTERNS = {
        "factual": [
            r"\b(what\s+is|what\s+are|what's|whats)\b",
            r"\b(who\s+is|who\s+are|who's|whos)\b",
            r"\b(where\s+is|where\s+are|where's|wheres)\b",
            r"\b(when\s+is|when\s+are|when\s+was|when\s+did)\b",
            r"\b(define|definition\s+of)\b",
            r"\b(name|list)\b",
        ],
        "analytical": [
            r"\b(why\s+is|why\s+are|why\s+did|why\s+do)\b",
            r"\b(compare|comparison|versus|vs\.?|differ|difference)\b",
            r"\b(analyze|analysis|evaluate|evaluation)\b",
            r"\b(better|worse|best|worst|pros?\s+and\s+cons?)\b",
            r"\b(advantages?|disadvantages?|benefits?|drawbacks?)\b",
            r"\b(trade-?offs?|implications?)\b",
        ],
        "procedural": [
            r"\b(how\s+to|how\s+do\s+i|how\s+can\s+i|how\s+should)\b",
            r"\b(steps?\s+to|guide\s+to|tutorial)\b",
            r"\b(implement|install|setup|configure|create)\b",
            r"\b(fix|solve|resolve|troubleshoot)\b",
            r"\b(build|make|write|develop)\b",
        ],
        "clarification": [
            r"\b(what\s+do\s+you\s+mean|can\s+you\s+explain)\b",
            r"\b(clarify|elaborate|more\s+detail)\b",
            r"\b(i\s+don'?t\s+understand|confused)\b",
            r"\b(could\s+you\s+expand|tell\s+me\s+more)\b",
            r"\b(what\s+about|how\s+about)\b",
        ],
    }

    # Multi-part query indicators
    MULTI_PART_PATTERNS = [
        r"\band\s+also\b",
        r"\badditionally\b",
        r"\bfurthermore\b",
        r"\bmoreover\b",
        r",\s*and\s+",
        r"\?\s+and\s+",
        r"\balso\b.*\?",
        r"\b(first|second|third|finally)\b",
    ]

    def __init__(self):
        """Initialize the classifier with compiled regex patterns."""
        self._greeting_regex = [
            re.compile(p, re.IGNORECASE) for p in self.GREETING_PATTERNS
        ]
        self._gratitude_regex = [
            re.compile(p, re.IGNORECASE) for p in self.GRATITUDE_PATTERNS
        ]
        self._question_regex = {
            intent: [re.compile(p, re.IGNORECASE) for p in patterns]
            for intent, patterns in self.QUESTION_PATTERNS.items()
        }
        self._multi_part_regex = [
            re.compile(p, re.IGNORECASE) for p in self.MULTI_PART_PATTERNS
        ]

    def is_greeting(self, query: str) -> tuple[bool, float]:
        """
        Check if the query is a greeting or chitchat.

        Returns:
            Tuple of (is_greeting, confidence)
        """
        query = query.strip()

        # Check greeting patterns
        for pattern in self._greeting_regex:
            if pattern.match(query):
                return (True, 0.95)

        # Check gratitude/closing patterns
        for pattern in self._gratitude_regex:
            if pattern.match(query):
                return (True, 0.90)

        # Check for very short non-question queries
        if len(query) < 15 and "?" not in query:
            words = query.lower().split()
            if len(words) <= 3:
                greeting_words = {
                    "hi",
                    "hello",
                    "hey",
                    "thanks",
                    "bye",
                    "ok",
                    "okay",
                    "cool",
                    "nice",
                    "great",
                    "awesome",
                    "sure",
                    "yes",
                    "no",
                    "yep",
                    "nope",
                }
                if any(w in greeting_words for w in words):
                    return (True, 0.80)

        return (False, 0.0)

    def classify_question_type(self, query: str) -> tuple[str, float]:
        """
        Classify the type of question based on keywords.

        Returns:
            Tuple of (question_type, confidence)
            question_type is one of: factual, analytical, procedural, clarification, unknown
        """
        query_lower = query.lower().strip()
        scores = {}

        for intent, patterns in self._question_regex.items():
            match_count = sum(1 for p in patterns if p.search(query_lower))
            if match_count > 0:
                # Base confidence based on match count
                confidence = min(0.6 + (match_count * 0.15), 0.95)
                scores[intent] = confidence

        if not scores:
            return ("unknown", 0.3)

        # Return the highest scoring intent
        best_intent = max(scores, key=scores.get)
        return (best_intent, scores[best_intent])

    def is_multi_part(self, query: str) -> tuple[bool, int]:
        """
        Detect if the query contains multiple parts/questions.

        Returns:
            Tuple of (is_multi_part, estimated_part_count)
        """
        query_lower = query.lower()

        # Count question marks
        question_count = query.count("?")

        # Check for multi-part patterns
        pattern_matches = sum(
            1 for p in self._multi_part_regex if p.search(query_lower)
        )

        # Check for explicit conjunctions joining queries
        conjunction_count = len(re.findall(r",\s*(and|or)\s+", query_lower))

        # Estimate parts
        estimated_parts = max(
            question_count,
            pattern_matches,
            conjunction_count + 1 if conjunction_count > 0 else 1,
        )

        is_multi = estimated_parts > 1 or pattern_matches > 0
        return (is_multi, max(estimated_parts, 2 if is_multi else 1))


class ComplexityScorer:
    """Scores query complexity on a 0-1 scale."""

    # Temporal/comparison modifier patterns
    MODIFIER_PATTERNS = [
        r"\b(before|after|during|while|since|until)\b",
        r"\b(compare|comparison|versus|vs\.?)\b",
        r"\b(better|worse|best|worst)\b",
        r"\b(more|less|most|least|rather)\b",
        r"\b(different|similar|same|unlike|like)\b",
        r"\b(if|when|assuming|given\s+that|suppose)\b",
        r"\b(however|although|despite|whereas|while)\b",
        r"\b(first|second|third|then|finally|lastly)\b",
    ]

    # Clause boundary patterns
    CLAUSE_PATTERNS = [
        r"[,;]",  # Punctuation-based clauses
        r"\b(and|or|but|because|since|although|while|whereas|if|when|that|which)\b",
    ]

    def __init__(self, max_query_length: int = 500):
        """
        Initialize the complexity scorer.

        Args:
            max_query_length: Query length at which length complexity is maximum
        """
        self._modifier_regex = [
            re.compile(p, re.IGNORECASE) for p in self.MODIFIER_PATTERNS
        ]
        self._clause_regex = [
            re.compile(p, re.IGNORECASE) for p in self.CLAUSE_PATTERNS
        ]
        self._max_query_length = max_query_length

    def score(
        self,
        query: str,
        history: Optional[list[dict]] = None,
        weights: Optional[dict] = None,
    ) -> float:
        """
        Calculate overall complexity score for a query.

        Args:
            query: The query string
            history: Optional conversation history
            weights: Optional custom weights for components

        Returns:
            Complexity score between 0.0 and 1.0
        """
        default_weights = {
            "clause": 0.3,
            "length": 0.2,
            "modifier": 0.3,
            "history": 0.2,
        }
        w = weights or default_weights

        clause_score = self._score_clauses(query)
        length_score = self._score_length(query)
        modifier_score = self._score_modifiers(query)
        history_score = self._score_history(history)

        total_score = (
            w.get("clause", 0.3) * clause_score
            + w.get("length", 0.2) * length_score
            + w.get("modifier", 0.3) * modifier_score
            + w.get("history", 0.2) * history_score
        )

        return min(max(total_score, 0.0), 1.0)

    def _score_clauses(self, query: str) -> float:
        """
        Score based on number of clauses in the query.

        Returns a score where:
        - 1 clause = 0.0
        - 2 clauses = 0.3
        - 3 clauses = 0.5
        - 4+ clauses = 0.7-1.0
        """
        clause_count = 1  # Start with at least one clause

        for pattern in self._clause_regex:
            matches = len(pattern.findall(query))
            clause_count += matches

        # Normalize: 1 clause = 0, 5+ clauses = 1.0
        if clause_count <= 1:
            return 0.0
        elif clause_count == 2:
            return 0.3
        elif clause_count == 3:
            return 0.5
        elif clause_count == 4:
            return 0.7
        else:
            return min(0.7 + (clause_count - 4) * 0.1, 1.0)

    def _score_length(self, query: str) -> float:
        """
        Score based on query length.

        Returns a score normalized by max_query_length.
        """
        length = len(query.strip())
        return min(length / self._max_query_length, 1.0)

    def _score_modifiers(self, query: str) -> float:
        """
        Score based on presence of temporal/comparison modifiers.

        Returns a score where:
        - 0 modifiers = 0.0
        - 1 modifier = 0.3
        - 2 modifiers = 0.5
        - 3+ modifiers = 0.7-1.0
        """
        modifier_count = 0

        for pattern in self._modifier_regex:
            if pattern.search(query):
                modifier_count += 1

        if modifier_count == 0:
            return 0.0
        elif modifier_count == 1:
            return 0.3
        elif modifier_count == 2:
            return 0.5
        elif modifier_count == 3:
            return 0.7
        else:
            return min(0.7 + (modifier_count - 3) * 0.1, 1.0)

    def _score_history(self, history: Optional[list[dict]]) -> float:
        """
        Score based on conversation history complexity.

        Considers:
        - Number of messages in history
        - Whether this appears to be a follow-up question
        """
        if not history:
            return 0.0

        # More history generally means more context to consider
        history_length = len(history)

        if history_length == 0:
            return 0.0
        elif history_length <= 2:
            return 0.2
        elif history_length <= 4:
            return 0.4
        elif history_length <= 6:
            return 0.6
        else:
            return min(0.6 + (history_length - 6) * 0.05, 1.0)
