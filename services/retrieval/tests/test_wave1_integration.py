"""Wave 1 Integration Tests.

Tests that ACL and Query Preprocessor modules work together correctly.
"""

import pytest
from uuid import uuid4

from acl.models import UserContext
from acl.filter import ACLFilter
from query.models import ProcessedQuery, QueryPreprocessorConfig
from query.preprocessor import QueryPreprocessor


class TestWave1Integration:
    """Integration tests for Wave 1 components."""

    @pytest.fixture
    def user_context(self):
        """Create a user context for testing."""
        return UserContext(
            user_id=uuid4(),
            tenant_id=uuid4(),
            groups=["engineering", "ml-team"],
            roles=["user"],
            permissions=["read:documents"],
        )

    @pytest.fixture
    def acl_filter(self):
        """Create an ACL filter."""
        return ACLFilter()

    @pytest.fixture
    def preprocessor_config(self):
        """Create preprocessor config."""
        return QueryPreprocessorConfig(
            enable_expansion=True,
            enable_hyde=False,
            cache_enabled=False,
        )

    def test_imports_work(self):
        """Test that all imports work correctly without circular dependencies."""
        # ACL imports
        from acl.models import UserContext, DocumentACL, Visibility, ACLFilterConfig
        from acl.filter import ACLFilter, AnonymousAccessFilter
        from acl.context import UserContextExtractor
        from acl.middleware import ACLMiddleware, create_acl_dependencies

        # Query imports
        from query.models import ProcessedQuery, QueryType, QueryPreprocessorConfig
        from query.preprocessor import QueryPreprocessor
        from query.expander import QueryExpander, SynonymDatabase
        from query.hyde import HyDEGenerator, MultiQueryGenerator
        from query.cache import QueryCache

        # All imports should succeed
        assert UserContext is not None
        assert ACLFilter is not None
        assert ProcessedQuery is not None
        assert QueryPreprocessor is not None

    def test_acl_filter_builds_valid_filter(self, acl_filter, user_context):
        """Test ACL filter produces valid filter dict."""
        filters = acl_filter.build_filter(user_context)

        # Should have required keys
        assert "must" in filters
        assert "should" in filters

        # Tenant isolation should be present
        must_clauses = filters["must"]
        tenant_clause = next(
            (c for c in must_clauses if c["key"] == "tenant_id"),
            None,
        )
        assert tenant_clause is not None

    def test_acl_qdrant_filter_is_valid(self, acl_filter, user_context):
        """Test Qdrant filter is valid."""
        from qdrant_client.models import Filter

        qdrant_filter = acl_filter.build_qdrant_filter(user_context)

        assert qdrant_filter is not None
        assert isinstance(qdrant_filter, Filter)

    def test_acl_opensearch_filter_is_valid(self, acl_filter, user_context):
        """Test OpenSearch filter is valid list."""
        os_filter = acl_filter.build_opensearch_filter(user_context)

        assert isinstance(os_filter, list)
        assert len(os_filter) > 0

    def test_preprocessor_normalizes_query(self, preprocessor_config):
        """Test preprocessor normalizes queries correctly."""
        preprocessor = QueryPreprocessor(preprocessor_config)

        normalized = preprocessor._normalize("  What is Machine LEARNING?  ")

        assert normalized == "what is machine learning?"

    def test_preprocessor_classifies_query(self, preprocessor_config):
        """Test preprocessor classifies queries correctly."""
        from query.models import QueryType

        preprocessor = QueryPreprocessor(preprocessor_config)

        # Questions
        assert preprocessor._classify_query("what is machine learning") == QueryType.QUESTION
        assert preprocessor._classify_query("how does it work?") == QueryType.QUESTION

        # Simple queries
        assert preprocessor._classify_query("python tutorial") == QueryType.SIMPLE

        # Semantic queries
        assert preprocessor._classify_query("compare python and javascript") == QueryType.SEMANTIC

    def test_combined_filter_with_metadata(self, acl_filter, user_context):
        """Test ACL filter combined with metadata filters."""
        # Additional metadata filter
        additional = {"source_type": "pdf", "language": "en"}

        filters = acl_filter.build_filter(user_context, additional)

        must_clauses = filters.get("must", [])

        # Should have source_type filter
        source_clause = next(
            (c for c in must_clauses if c["key"] == "source_type"),
            None,
        )
        assert source_clause is not None
        assert source_clause["match"]["value"] == "pdf"

        # Should have language filter
        lang_clause = next(
            (c for c in must_clauses if c["key"] == "language"),
            None,
        )
        assert lang_clause is not None
        assert lang_clause["match"]["value"] == "en"

    def test_user_context_permissions(self):
        """Test UserContext permission methods."""
        user = UserContext(
            user_id=uuid4(),
            tenant_id=uuid4(),
            groups=["engineering"],
            roles=["user", "reviewer"],
            permissions=["read:documents", "review:documents"],
        )

        # Permission checks
        assert user.has_permission("read:documents") is True
        assert user.has_permission("delete:documents") is False

        # Role checks
        assert user.has_role("user") is True
        assert user.has_role("admin") is False

        # Group checks
        assert user.is_member_of("engineering") is True
        assert user.is_member_of("finance") is False

        # Admin check
        assert user.is_admin() is False

    def test_admin_context_bypasses_acl(self, acl_filter):
        """Test admin context bypasses ACL filtering."""
        admin = UserContext(
            user_id=uuid4(),
            tenant_id=uuid4(),
            groups=["admins"],
            roles=["admin"],
            permissions=["*"],
        )

        filters = acl_filter.build_filter(admin)

        # Admin should bypass, returning empty filter
        assert filters == {}

    def test_anonymous_context_restricts_access(self):
        """Test anonymous context only allows public documents."""
        from acl.context import UserContextExtractor
        from acl.filter import AnonymousAccessFilter

        extractor = UserContextExtractor("secret")
        tenant_id = uuid4()
        anon = extractor.create_anonymous_context(tenant_id)

        anon_filter = AnonymousAccessFilter()
        filters = anon_filter.build_filter(anon)

        must_clauses = filters.get("must", [])

        # Should require public visibility
        visibility_clause = next(
            (c for c in must_clauses if c["key"] == "visibility"),
            None,
        )
        assert visibility_clause is not None
        assert visibility_clause["match"]["value"] == "public"

    def test_processed_query_serialization(self):
        """Test ProcessedQuery can be serialized and deserialized."""
        from query.models import QueryType

        query = ProcessedQuery(
            original_query="What is machine learning?",
            normalized_query="what is machine learning?",
            embedding=[0.1] * 1024,
            query_type=QueryType.QUESTION,
            expanded_queries=["machine learning definition", "ml explained"],
            tokens=10,
            processing_time_ms=50.5,
        )

        # Serialize
        json_str = query.model_dump_json()

        # Deserialize
        restored = ProcessedQuery.model_validate_json(json_str)

        assert restored.original_query == query.original_query
        assert restored.query_type == QueryType.QUESTION
        assert len(restored.embedding) == 1024
        assert len(restored.expanded_queries) == 2


class TestWave1UsagePatterns:
    """Test common usage patterns for Wave 1 components."""

    @pytest.fixture
    def user_context(self):
        """Create a user context."""
        return UserContext(
            user_id=uuid4(),
            tenant_id=uuid4(),
            groups=["engineering"],
        )

    def test_typical_retrieval_flow(self, user_context):
        """Test the typical flow: preprocess query, build filter, search."""
        # 1. Build ACL filter for user
        acl = ACLFilter()
        acl_filters = acl.build_filter(user_context)

        # 2. Preprocess query (mocked embedding)
        preprocessor = QueryPreprocessor(
            QueryPreprocessorConfig(enable_expansion=True, cache_enabled=False)
        )
        normalized = preprocessor._normalize("What is machine learning?")
        query_type = preprocessor._classify_query(normalized)

        # 3. Get expanded queries
        # (would normally call preprocessor.process() with real embedding)

        # Verify flow works
        assert "must" in acl_filters
        assert normalized == "what is machine learning?"
        assert query_type.value == "question"

    def test_multi_tenant_isolation(self):
        """Test that different tenants get different filters."""
        tenant1 = uuid4()
        tenant2 = uuid4()

        user1 = UserContext(user_id=uuid4(), tenant_id=tenant1, groups=["team-a"])
        user2 = UserContext(user_id=uuid4(), tenant_id=tenant2, groups=["team-a"])

        acl = ACLFilter()

        filter1 = acl.build_filter(user1)
        filter2 = acl.build_filter(user2)

        # Extract tenant IDs from filters
        def get_tenant_filter(f):
            return next(
                (c for c in f.get("must", []) if c["key"] == "tenant_id"),
                None,
            )

        tenant1_clause = get_tenant_filter(filter1)
        tenant2_clause = get_tenant_filter(filter2)

        # Different tenants should have different filter values
        assert tenant1_clause["match"]["value"] != tenant2_clause["match"]["value"]
        assert tenant1_clause["match"]["value"] == str(tenant1)
        assert tenant2_clause["match"]["value"] == str(tenant2)
