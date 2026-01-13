"""ACL filter builder for search queries.

This module builds database filters for ACL enforcement, generating
filter clauses for both Qdrant and OpenSearch that restrict results
to documents the user is authorized to see.
"""

from typing import Any

from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
)

from .models import ACLFilterConfig, UserContext, Visibility


class ACLFilter:
    """Builds database filters for ACL enforcement.

    Generates filter clauses for Qdrant and OpenSearch that restrict
    results to documents the user is authorized to see.

    ACL Logic:
    1. Document must belong to user's tenant (unless super tenant)
    2. Document must be:
       - PUBLIC visibility, OR
       - TENANT visibility (same tenant), OR
       - GROUP visibility with matching groups, OR
       - Explicitly allowed for user, OR
       - Owned by user
    3. User must not be in denied_groups or denied_users
    """

    def __init__(self, config: ACLFilterConfig | None = None):
        """Initialize ACL filter.

        Args:
            config: ACL filter configuration. Uses defaults if not provided.
        """
        self.config = config or ACLFilterConfig()

    def build_filter(
        self,
        user_context: UserContext,
        additional_filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build filter dict for Qdrant/OpenSearch.

        Args:
            user_context: Authenticated user's context.
            additional_filters: Extra filters to merge (metadata, etc.).

        Returns:
            Filter dict in unified format for both backends.
        """
        if not self.config.enabled:
            return additional_filters or {}

        # Admin bypass
        if self.config.admin_bypass and user_context.is_admin():
            return self._merge_filters({}, additional_filters)

        # Anonymous bypass - rely on explicit filters (e.g., tenant_id in request)
        if user_context.is_anonymous():
            return self._merge_filters({}, additional_filters)

        # Build ACL filter
        acl_filter = self._build_acl_clauses(user_context)

        return self._merge_filters(acl_filter, additional_filters)

    def _build_acl_clauses(self, user: UserContext) -> dict[str, Any]:
        """Build the core ACL filter clauses.

        Structure:
        {
            "must": [
                {"key": "tenant_id", "match": {"value": <tenant>}}
            ],
            "should": [
                {"key": "visibility", "match": {"value": "public"}},
                {"key": "visibility", "match": {"value": "tenant"}},
                {"key": "allowed_groups", "match": {"any": <groups>}},
                {"key": "allowed_users", "match": {"any": <user_ids>}},
                {"key": "owner_id", "match": {"value": <user_id>}}
            ],
            "must_not": [
                {"key": "denied_groups", "match": {"any": <groups>}},
                {"key": "denied_users", "match": {"any": <user_ids>}}
            ]
        }

        Args:
            user: User context with identity and permissions.

        Returns:
            Dict with must, should, and must_not filter clauses.
        """
        must_clauses: list[dict[str, Any]] = []
        should_clauses: list[dict[str, Any]] = []
        must_not_clauses: list[dict[str, Any]] = []

        # Tenant isolation (always required unless super tenant)
        if self.config.super_tenant_id is None or user.tenant_id != self.config.super_tenant_id:
            must_clauses.append(
                {"key": "tenant_id", "match": {"value": str(user.tenant_id)}},
            )

        # Visibility options (document must match at least one)
        # 1. Public documents
        should_clauses.append(
            {"key": "visibility", "match": {"value": Visibility.PUBLIC.value}},
        )

        # 2. Tenant-wide documents (same tenant)
        should_clauses.append(
            {"key": "visibility", "match": {"value": Visibility.TENANT.value}},
        )

        # 3. Documents allowed for user's groups
        if user.groups:
            should_clauses.append(
                {"key": "allowed_groups", "match": {"any": user.groups}},
            )

        # 4. Documents explicitly allowed for this user
        should_clauses.append(
            {"key": "allowed_users", "match": {"any": [str(user.user_id)]}},
        )

        # 5. Documents owned by this user (owner always has access)
        should_clauses.append(
            {"key": "owner_id", "match": {"value": str(user.user_id)}},
        )

        # Denied access (must not match any)
        if user.groups:
            must_not_clauses.append(
                {"key": "denied_groups", "match": {"any": user.groups}},
            )

        must_not_clauses.append(
            {"key": "denied_users", "match": {"any": [str(user.user_id)]}},
        )

        result: dict[str, Any] = {}
        if must_clauses:
            result["must"] = must_clauses
        if should_clauses:
            result["should"] = should_clauses
        if must_not_clauses:
            result["must_not"] = must_not_clauses

        return result

    def _merge_filters(
        self,
        acl_filter: dict[str, Any],
        additional_filters: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Merge ACL filters with additional filters.

        Additional filters are added to the must clause.

        Args:
            acl_filter: ACL filter clauses.
            additional_filters: Extra filters to merge.

        Returns:
            Merged filter dict.
        """
        if not additional_filters:
            return acl_filter

        result = acl_filter.copy()

        # Merge must clauses
        if "must" not in result:
            result["must"] = []

        for key, value in additional_filters.items():
            if key in ["must", "should", "must_not"]:
                if key not in result:
                    result[key] = []
                result[key].extend(value)
            else:
                # Simple key-value filter
                result["must"].append({"key": key, "match": {"value": value}})

        return result

    def build_qdrant_filter(
        self,
        user_context: UserContext,
        additional_filters: dict[str, Any] | None = None,
    ) -> Filter | None:
        """Build Qdrant-specific Filter object.

        Converts the unified filter format to Qdrant Filter.

        Args:
            user_context: Authenticated user's context.
            additional_filters: Extra filters to merge.

        Returns:
            Qdrant Filter object, or None if no filters.
        """
        unified = self.build_filter(user_context, additional_filters)

        if not unified:
            return None

        must_conditions: list[FieldCondition] = []
        should_conditions: list[FieldCondition] = []
        must_not_conditions: list[FieldCondition] = []

        def build_condition(clause: dict[str, Any]) -> FieldCondition:
            """Convert unified clause to Qdrant FieldCondition."""
            key = clause["key"]
            match = clause["match"]

            if "value" in match:
                return FieldCondition(key=key, match=MatchValue(value=match["value"]))
            if "any" in match:
                return FieldCondition(key=key, match=MatchAny(any=match["any"]))
            raise ValueError(f"Unknown match type in clause: {clause}")

        for clause in unified.get("must", []):
            must_conditions.append(build_condition(clause))

        for clause in unified.get("should", []):
            should_conditions.append(build_condition(clause))

        for clause in unified.get("must_not", []):
            must_not_conditions.append(build_condition(clause))

        return Filter(
            must=must_conditions if must_conditions else None,
            should=should_conditions if should_conditions else None,
            must_not=must_not_conditions if must_not_conditions else None,
        )

    def build_opensearch_filter(
        self,
        user_context: UserContext,
        additional_filters: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Build OpenSearch filter clauses.

        Returns list of filter clauses for bool query.

        Args:
            user_context: Authenticated user's context.
            additional_filters: Extra filters to merge.

        Returns:
            List of OpenSearch filter clauses for use in bool query.
        """
        unified = self.build_filter(user_context, additional_filters)

        if not unified:
            return []

        clauses: list[dict[str, Any]] = []

        def build_clause(condition: dict[str, Any]) -> dict[str, Any]:
            """Convert unified condition to OpenSearch clause."""
            key = condition["key"]
            match = condition["match"]

            if "value" in match:
                return {"term": {key: match["value"]}}
            if "any" in match:
                return {"terms": {key: match["any"]}}
            raise ValueError(f"Unknown match type in condition: {condition}")

        # Must clauses
        for condition in unified.get("must", []):
            clauses.append(build_clause(condition))

        # Should clauses (wrap in bool with minimum_should_match)
        if unified.get("should"):
            should_clauses = [build_clause(c) for c in unified["should"]]
            clauses.append(
                {"bool": {"should": should_clauses, "minimum_should_match": 1}},
            )

        # Must not clauses
        if unified.get("must_not"):
            must_not_clauses = [build_clause(c) for c in unified["must_not"]]
            clauses.append({"bool": {"must_not": must_not_clauses}})

        return clauses


class AnonymousAccessFilter(ACLFilter):
    """ACL filter for anonymous (unauthenticated) access.

    Only allows access to public documents within the specified tenant.
    """

    def build_filter(
        self,
        user_context: UserContext,
        additional_filters: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build filter dict for anonymous access.

        Overrides parent to always apply ACL clauses (no anonymous bypass).

        Args:
            user_context: Anonymous user's context.
            additional_filters: Extra filters to merge (metadata, etc.).

        Returns:
            Filter dict requiring public visibility only.
        """
        if not self.config.enabled:
            return additional_filters or {}

        acl_filter = self._build_acl_clauses(user_context)
        return self._merge_filters(acl_filter, additional_filters)

    def _build_acl_clauses(self, user: UserContext) -> dict[str, Any]:
        """Build filter for public documents only.

        Args:
            user: User context (should be anonymous context).

        Returns:
            Filter dict requiring public visibility.
        """
        return {
            "must": [
                {"key": "tenant_id", "match": {"value": str(user.tenant_id)}},
                {"key": "visibility", "match": {"value": Visibility.PUBLIC.value}},
            ],
        }
