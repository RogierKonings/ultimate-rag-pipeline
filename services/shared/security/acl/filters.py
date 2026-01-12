"""
ACL filter builders for vector stores.

This module provides filter builders for Qdrant and OpenSearch
that enforce document-level access control in search queries.
"""

from abc import ABC, abstractmethod
from typing import Any, Optional
from uuid import UUID


class ACLFilterBuilder(ABC):
    """
    Abstract base class for ACL filter builders.

    Subclasses implement filter building for specific backends.
    """

    @abstractmethod
    def build_access_filter(
        self,
        user_id: UUID,
        tenant_id: UUID,
        groups: list[str],
        is_admin: bool = False,
        additional_filters: Optional[dict[str, Any]] = None,
    ) -> Any:
        """
        Build an access filter for the backend.

        Args:
            user_id: User requesting access.
            tenant_id: User's tenant.
            groups: User's groups.
            is_admin: Whether user is admin.
            additional_filters: Extra filters to merge.

        Returns:
            Backend-specific filter object.
        """
        pass

    def _build_base_filter(
        self,
        user_id: UUID,
        tenant_id: UUID,
        groups: list[str],
        is_admin: bool = False,
    ) -> dict[str, Any]:
        """
        Build base filter in unified format.

        Returns a dict with must, should, and must_not clauses
        that can be converted to backend-specific formats.
        """
        if is_admin:
            # Admin sees everything in tenant
            return {
                "must": [
                    {"key": "tenant_id", "match": {"value": str(tenant_id)}}
                ]
            }

        must = [{"key": "tenant_id", "match": {"value": str(tenant_id)}}]

        # Document must match at least one visibility criterion
        should = [
            # Public documents
            {"key": "visibility", "match": {"value": "public"}},
            # Tenant-wide documents
            {"key": "visibility", "match": {"value": "tenant"}},
            # User is owner
            {"key": "owner_id", "match": {"value": str(user_id)}},
            # User explicitly allowed
            {"key": "allowed_users", "match": {"any": [str(user_id)]}},
        ]

        # Group access
        if groups:
            should.append({"key": "allowed_groups", "match": {"any": groups}})

        # Explicit denials
        must_not = [
            {"key": "denied_users", "match": {"any": [str(user_id)]}},
        ]

        if groups:
            must_not.append({"key": "denied_groups", "match": {"any": groups}})

        return {
            "must": must,
            "should": should,
            "must_not": must_not,
        }


class QdrantACLFilter(ACLFilterBuilder):
    """
    ACL filter builder for Qdrant vector database.

    Generates Qdrant Filter objects for access control.

    Example:
        ```python
        from qdrant_client import QdrantClient
        from services.shared.security.acl import QdrantACLFilter

        filter_builder = QdrantACLFilter()
        acl_filter = filter_builder.build_access_filter(
            user_id=user_id,
            tenant_id=tenant_id,
            groups=user_groups,
        )

        results = client.search(
            collection_name="documents",
            query_vector=embedding,
            query_filter=acl_filter,
        )
        ```
    """

    def build_access_filter(
        self,
        user_id: UUID,
        tenant_id: UUID,
        groups: list[str],
        is_admin: bool = False,
        additional_filters: Optional[dict[str, Any]] = None,
    ):
        """
        Build Qdrant Filter object for access control.

        Args:
            user_id: User requesting access.
            tenant_id: User's tenant.
            groups: User's groups.
            is_admin: Whether user is admin.
            additional_filters: Extra unified filter clauses.

        Returns:
            Qdrant Filter object.
        """
        from qdrant_client.models import (
            FieldCondition,
            Filter,
            MatchAny,
            MatchValue,
        )

        base = self._build_base_filter(user_id, tenant_id, groups, is_admin)

        # Merge additional filters
        if additional_filters:
            for key, clauses in additional_filters.items():
                if key in base:
                    base[key].extend(clauses)
                else:
                    base[key] = clauses

        def to_condition(clause: dict[str, Any]) -> FieldCondition:
            """Convert unified clause to Qdrant FieldCondition."""
            key = clause["key"]
            match = clause["match"]

            if "value" in match:
                return FieldCondition(key=key, match=MatchValue(value=match["value"]))
            elif "any" in match:
                return FieldCondition(key=key, match=MatchAny(any=match["any"]))
            else:
                raise ValueError(f"Unknown match type: {clause}")

        must = [to_condition(c) for c in base.get("must", [])]
        should = [to_condition(c) for c in base.get("should", [])]
        must_not = [to_condition(c) for c in base.get("must_not", [])]

        return Filter(
            must=must if must else None,
            should=should if should else None,
            must_not=must_not if must_not else None,
        )

    def build_tenant_filter(self, tenant_id: UUID):
        """Build simple tenant-only filter."""
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        return Filter(
            must=[
                FieldCondition(
                    key="tenant_id",
                    match=MatchValue(value=str(tenant_id)),
                )
            ]
        )


class OpenSearchACLFilter(ACLFilterBuilder):
    """
    ACL filter builder for OpenSearch.

    Generates OpenSearch query DSL for access control.

    Example:
        ```python
        from opensearchpy import OpenSearch
        from services.shared.security.acl import OpenSearchACLFilter

        filter_builder = OpenSearchACLFilter()
        acl_filters = filter_builder.build_access_filter(
            user_id=user_id,
            tenant_id=tenant_id,
            groups=user_groups,
        )

        query = {
            "query": {
                "bool": {
                    "must": [{"match": {"content": search_query}}],
                    "filter": acl_filters,
                }
            }
        }
        ```
    """

    def build_access_filter(
        self,
        user_id: UUID,
        tenant_id: UUID,
        groups: list[str],
        is_admin: bool = False,
        additional_filters: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """
        Build OpenSearch filter clauses for access control.

        Args:
            user_id: User requesting access.
            tenant_id: User's tenant.
            groups: User's groups.
            is_admin: Whether user is admin.
            additional_filters: Extra unified filter clauses.

        Returns:
            List of OpenSearch filter clauses for use in bool query.
        """
        base = self._build_base_filter(user_id, tenant_id, groups, is_admin)

        # Merge additional filters
        if additional_filters:
            for key, clauses in additional_filters.items():
                if key in base:
                    base[key].extend(clauses)
                else:
                    base[key] = clauses

        def to_clause(condition: dict[str, Any]) -> dict[str, Any]:
            """Convert unified condition to OpenSearch clause."""
            key = condition["key"]
            match = condition["match"]

            if "value" in match:
                return {"term": {key: match["value"]}}
            elif "any" in match:
                return {"terms": {key: match["any"]}}
            else:
                raise ValueError(f"Unknown match type: {condition}")

        filters: list[dict[str, Any]] = []

        # Must clauses (all required)
        for condition in base.get("must", []):
            filters.append(to_clause(condition))

        # Should clauses (at least one required)
        if base.get("should"):
            should_clauses = [to_clause(c) for c in base["should"]]
            filters.append({
                "bool": {
                    "should": should_clauses,
                    "minimum_should_match": 1,
                }
            })

        # Must not clauses (none can match)
        if base.get("must_not"):
            must_not_clauses = [to_clause(c) for c in base["must_not"]]
            filters.append({
                "bool": {
                    "must_not": must_not_clauses,
                }
            })

        return filters

    def build_tenant_filter(self, tenant_id: UUID) -> list[dict[str, Any]]:
        """Build simple tenant-only filter."""
        return [{"term": {"tenant_id": str(tenant_id)}}]


def build_chunk_acl_payload(
    tenant_id: UUID,
    owner_id: UUID,
    visibility: str = "private",
    allowed_users: Optional[list[UUID]] = None,
    allowed_groups: Optional[list[str]] = None,
    denied_users: Optional[list[UUID]] = None,
    denied_groups: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Build ACL payload for chunk indexing.

    Creates a payload dict with ACL fields for storing
    alongside chunk vectors in Qdrant/OpenSearch.

    Args:
        tenant_id: Document's tenant ID.
        owner_id: Document owner's user ID.
        visibility: Visibility level string.
        allowed_users: Explicitly allowed user IDs.
        allowed_groups: Explicitly allowed group names.
        denied_users: Explicitly denied user IDs.
        denied_groups: Explicitly denied group names.

    Returns:
        Dict with ACL fields ready for indexing.

    Example:
        ```python
        payload = build_chunk_acl_payload(
            tenant_id=tenant_id,
            owner_id=user_id,
            visibility="group",
            allowed_groups=["engineering", "ml-team"],
        )

        # Add to Qdrant payload
        client.upsert(
            collection_name="documents",
            points=[{
                "id": chunk_id,
                "vector": embedding,
                "payload": {
                    **chunk_payload,
                    **payload,
                },
            }]
        )
        ```
    """
    return {
        "tenant_id": str(tenant_id),
        "owner_id": str(owner_id),
        "visibility": visibility,
        "allowed_users": [str(u) for u in (allowed_users or [])],
        "allowed_groups": allowed_groups or [],
        "denied_users": [str(u) for u in (denied_users or [])],
        "denied_groups": denied_groups or [],
    }


def merge_acl_payload(
    existing_payload: dict[str, Any],
    acl_payload: dict[str, Any],
) -> dict[str, Any]:
    """
    Merge ACL payload into existing chunk payload.

    Args:
        existing_payload: Existing chunk payload.
        acl_payload: ACL fields to merge.

    Returns:
        Merged payload dict.
    """
    result = existing_payload.copy()
    result.update(acl_payload)
    return result
