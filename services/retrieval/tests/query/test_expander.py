"""Tests for query expander."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from query.expander import QueryExpander, SynonymDatabase
from query.models import QueryPreprocessorConfig


class TestSynonymDatabase:
    """Tests for SynonymDatabase."""

    @pytest.fixture
    def db(self):
        """Create synonym database."""
        return SynonymDatabase()

    def test_get_synonyms_found(self, db):
        """Test getting synonyms for a word."""
        synonyms = db.get_synonyms("error")

        assert len(synonyms) > 0
        assert "bug" in synonyms
        assert "issue" in synonyms

    def test_get_synonyms_case_insensitive(self, db):
        """Test case insensitive lookup."""
        synonyms1 = db.get_synonyms("error")
        synonyms2 = db.get_synonyms("ERROR")
        synonyms3 = db.get_synonyms("Error")

        assert synonyms1 == synonyms2 == synonyms3

    def test_get_synonyms_not_found(self, db):
        """Test getting synonyms for unknown word."""
        synonyms = db.get_synonyms("xyznonexistent")

        assert synonyms == []

    def test_add_synonym_new_word(self, db):
        """Test adding synonyms for a new word."""
        db.add_synonym("myword", ["alternative1", "alternative2"])

        synonyms = db.get_synonyms("myword")
        assert "alternative1" in synonyms
        assert "alternative2" in synonyms

    def test_add_synonym_existing_word(self, db):
        """Test extending synonyms for existing word."""
        db.get_synonyms("error")
        db.add_synonym("error", ["newsynonym"])

        updated = db.get_synonyms("error")
        assert "newsynonym" in updated
        # Original synonyms should still be there
        assert "bug" in updated


class TestQueryExpander:
    """Tests for QueryExpander."""

    @pytest.fixture
    def config(self):
        """Create test configuration."""
        return QueryPreprocessorConfig(
            expansion_model="synonym",
            max_expansions=3,
        )

    @pytest.fixture
    def expander(self, config):
        """Create query expander."""
        return QueryExpander(config)

    @pytest.mark.asyncio
    async def test_expand_synonym_mode(self, expander):
        """Test synonym-based expansion."""
        expansions = await expander.expand("fix the error")

        assert len(expansions) <= 3
        # Should have at least one expansion if words have synonyms
        assert any("bug" in e or "issue" in e or "problem" in e for e in expansions)

    def test_expand_with_synonyms_single_word(self, expander):
        """Test synonym expansion for single word."""
        expansions = expander._expand_with_synonyms("error")

        assert len(expansions) > 0
        # Original word should not be in expansions
        assert "error" not in expansions

    def test_expand_with_synonyms_multiple_words(self, expander):
        """Test synonym expansion for multiple words."""
        expansions = expander._expand_with_synonyms("create database")

        assert len(expansions) <= 3
        # Should substitute words one at a time
        for exp in expansions:
            words = exp.split()
            assert len(words) == 2  # Same word count

    def test_expand_with_synonyms_no_match(self, expander):
        """Test expansion when no synonyms found."""
        expansions = expander._expand_with_synonyms("xyznonexistent query")

        assert expansions == []

    def test_expand_with_synonyms_respects_max(self):
        """Test that max_expansions is respected."""
        config = QueryPreprocessorConfig(max_expansions=2)
        expander = QueryExpander(config)

        expansions = expander._expand_with_synonyms("fix the error issue bug")

        assert len(expansions) <= 2

    def test_expand_with_synonyms_no_duplicates(self, expander):
        """Test that expansions don't contain duplicates."""
        expansions = expander._expand_with_synonyms("find the error")

        # No duplicates
        assert len(expansions) == len(set(expansions))

    def test_expand_with_synonyms_not_original(self, expander):
        """Test that original query is not in expansions."""
        query = "fix the error"
        expansions = expander._expand_with_synonyms(query)

        assert query.lower() not in expansions

    @pytest.mark.asyncio
    async def test_expand_llm_mode(self):
        """Test LLM-based expansion."""
        config = QueryPreprocessorConfig(
            expansion_model="llm",
            max_expansions=3,
        )
        expander = QueryExpander(config)

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "choices": [
                {
                    "text": "resolve the bug\nfix the issue\naddress the problem",
                },
            ],
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = mock_response

            expansions = await expander.expand("fix the error")

            assert len(expansions) <= 3

        await expander.close()

    @pytest.mark.asyncio
    async def test_expand_unknown_mode(self):
        """Test expansion with unknown mode returns empty."""
        config = QueryPreprocessorConfig(expansion_model="unknown")
        expander = QueryExpander(config)

        expansions = await expander.expand("test query")

        assert expansions == []


class TestQueryExpanderDomainSynonyms:
    """Tests for domain-specific synonyms."""

    @pytest.fixture
    def db(self):
        """Create synonym database."""
        return SynonymDatabase()

    def test_technical_synonyms(self, db):
        """Test technical/programming synonyms."""
        # CRUD operations
        assert "make" in db.get_synonyms("create")
        assert "remove" in db.get_synonyms("delete")
        assert "change" in db.get_synonyms("update")
        assert "get" in db.get_synonyms("read")

    def test_error_synonyms(self, db):
        """Test error-related synonyms."""
        error_syns = db.get_synonyms("error")
        assert "bug" in error_syns
        assert "exception" in error_syns

    def test_user_synonyms(self, db):
        """Test user-related synonyms."""
        user_syns = db.get_synonyms("user")
        assert "customer" in user_syns
        assert "client" in user_syns

    def test_auth_synonyms(self, db):
        """Test authentication synonyms."""
        auth_syns = db.get_synonyms("authentication")
        assert "login" in auth_syns
        assert "auth" in auth_syns

    def test_database_synonyms(self, db):
        """Test database synonyms."""
        db_syns = db.get_synonyms("database")
        assert "db" in db_syns
        assert "storage" in db_syns

    def test_api_synonyms(self, db):
        """Test API synonyms."""
        api_syns = db.get_synonyms("api")
        assert "endpoint" in api_syns
        assert "service" in api_syns

    def test_ml_synonyms(self, db):
        """Test machine learning synonyms."""
        assert "vector" in db.get_synonyms("embedding")
        assert "fit" in db.get_synonyms("train")
        assert "infer" in db.get_synonyms("predict")
