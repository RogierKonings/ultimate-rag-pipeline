"""Query expansion for the Retrieval Service.

This module provides query expansion through synonym substitution
and LLM-based alternatives.
"""


import httpx

from .models import QueryPreprocessorConfig


class SynonymDatabase:
    """Simple synonym lookup for query expansion.

    In production, consider using WordNet, a domain-specific
    thesaurus, or LLM-based expansion.
    """

    def __init__(self):
        """Initialize synonym database with domain-specific synonyms."""
        # Domain-specific synonyms - extend for your use case
        self._synonyms: dict[str, list[str]] = {
            # Technical errors
            "error": ["bug", "issue", "problem", "fault", "exception", "failure"],
            "bug": ["error", "defect", "issue", "glitch"],
            "issue": ["problem", "error", "bug", "concern"],
            # CRUD operations
            "create": ["make", "build", "generate", "construct", "add", "new"],
            "delete": ["remove", "drop", "destroy", "erase", "clear"],
            "update": ["modify", "change", "edit", "alter", "revise"],
            "read": ["get", "fetch", "retrieve", "load", "query"],
            "find": ["search", "locate", "discover", "lookup", "query"],
            # Performance
            "fast": ["quick", "rapid", "speedy", "high-performance", "efficient"],
            "slow": ["sluggish", "delayed", "latent", "laggy"],
            "optimize": ["improve", "enhance", "speed up", "accelerate"],
            # Users and auth
            "user": ["customer", "client", "member", "account", "person"],
            "authentication": ["auth", "login", "sign-in", "credential", "identity"],
            "authorization": ["permission", "access control", "acl"],
            "password": ["credential", "secret", "passphrase"],
            # Data
            "database": ["db", "datastore", "storage", "data store"],
            "api": ["endpoint", "interface", "service", "rest"],
            "configuration": ["config", "settings", "options", "parameters"],
            "document": ["doc", "file", "record", "article"],
            # Actions
            "install": ["setup", "deploy", "configure"],
            "run": ["execute", "start", "launch", "invoke"],
            "test": ["check", "verify", "validate", "assert"],
            "debug": ["troubleshoot", "diagnose", "investigate"],
            # Machine Learning
            "model": ["algorithm", "neural network", "classifier"],
            "train": ["fit", "learn", "optimize"],
            "predict": ["infer", "classify", "estimate"],
            "embedding": ["vector", "representation", "encoding"],
        }

    def get_synonyms(self, word: str) -> list[str]:
        """Get synonyms for a word.

        Args:
            word: Word to look up.

        Returns:
            List of synonyms, empty if not found.
        """
        return self._synonyms.get(word.lower(), [])

    def add_synonym(self, word: str, synonyms: list[str]) -> None:
        """Add or extend synonyms for a word.

        Args:
            word: Base word.
            synonyms: List of synonyms to add.
        """
        word_lower = word.lower()
        if word_lower in self._synonyms:
            existing = set(self._synonyms[word_lower])
            existing.update(synonyms)
            self._synonyms[word_lower] = list(existing)
        else:
            self._synonyms[word_lower] = synonyms


class QueryExpander:
    """Expands queries with synonyms and related terms."""

    def __init__(self, config: QueryPreprocessorConfig):
        """Initialize query expander.

        Args:
            config: Preprocessor configuration.
        """
        self.config = config
        self._synonym_db = SynonymDatabase()
        self._http_client: httpx.AsyncClient | None = None

    async def expand(self, query: str) -> list[str]:
        """Generate expanded versions of the query.

        Args:
            query: Normalized query string.

        Returns:
            List of up to max_expansions alternative queries.
        """
        if self.config.expansion_model == "synonym":
            return self._expand_with_synonyms(query)
        if self.config.expansion_model == "llm":
            return await self._expand_with_llm(query)

        return []

    def _expand_with_synonyms(self, query: str) -> list[str]:
        """Expand query using synonym substitution.

        Strategy:
        1. Tokenize query
        2. Find words with synonyms
        3. Generate variations by substituting one word at a time

        Args:
            query: Normalized query string.

        Returns:
            List of expanded query variations.
        """
        words = query.lower().split()
        expansions: list[str] = []

        for i, word in enumerate(words):
            synonyms = self._synonym_db.get_synonyms(word)

            for synonym in synonyms[: self.config.max_expansions]:
                # Create variation with this synonym
                new_words = words.copy()
                new_words[i] = synonym
                expansion = " ".join(new_words)

                if expansion != query.lower() and expansion not in expansions:
                    expansions.append(expansion)

                if len(expansions) >= self.config.max_expansions:
                    return expansions

        return expansions

    async def _expand_with_llm(self, query: str) -> list[str]:
        """Expand query using LLM to generate semantically similar queries.

        Args:
            query: Normalized query string.

        Returns:
            List of LLM-generated query variations.
        """
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                base_url=self.config.llm_gateway_url,
                timeout=self.config.request_timeout,
            )

        prompt = f"""Generate {self.config.max_expansions} alternative search queries
that are semantically similar to the following query. Each alternative should
capture the same intent but use different words or phrasing.

Original query: {query}

Return only the alternative queries, one per line, without numbering or explanations."""

        response = await self._http_client.post(
            self.config.completion_endpoint,
            json={
                "model": self.config.hyde_model,
                "prompt": prompt,
                "max_tokens": 200,
                "temperature": 0.7,
            },
        )
        response.raise_for_status()

        data = response.json()
        text = data["choices"][0]["text"].strip()

        # Parse response into list of queries
        expansions = [
            line.strip()
            for line in text.split("\n")
            if line.strip() and line.strip() != query
        ]

        return expansions[: self.config.max_expansions]

    async def close(self):
        """Close HTTP client."""
        if self._http_client:
            await self._http_client.aclose()
            self._http_client = None
