"""ACL Safety Net - Defense-in-depth filter for post-reranking results.

This module provides a backup ACL filter that runs AFTER reranking.
If query-level ACL filtering is working correctly, this safety net
should NEVER filter anything out. Any filtering by this module
indicates a bug in the query-level ACL implementation.

All filtering events are logged as warnings to enable bug detection
and security auditing.
"""

import logging
from typing import Any

from search.fusion import FusedResult

from .models import UserContext, Visibility

# Try to import structlog, fallback to basic logging if not available
try:
    import structlog

    _logger = structlog.get_logger(__name__)
    _HAS_STRUCTLOG = True
except ImportError:
    _logger = logging.getLogger(__name__)
    _HAS_STRUCTLOG = False


def _log_warning(message: str, **kwargs: Any) -> None:
    """Log a warning message, handling both structlog and standard logging."""
    if _HAS_STRUCTLOG:
        _logger.warning(message, **kwargs)
    else:
        # Format kwargs into the message for standard logging
        if kwargs:
            formatted_kwargs = ", ".join(f"{k}={v}" for k, v in kwargs.items())
            _logger.warning(f"{message}: {formatted_kwargs}")
        else:
            _logger.warning(message)


class ACLSafetyNet:
    """Defense-in-depth ACL filter applied after reranking.

    This safety net validates that all results passing through the
    retrieval pipeline are accessible to the requesting user. It serves
    as a backup to query-level ACL filtering.

    WARNING: Any filtering by this class indicates a bug in query-level
    ACL enforcement. All filter events are logged as warnings.

    Access Rules:
    1. Tenant must match (MANDATORY - no cross-tenant access ever)
    2. Status must be "active" (soft-deleted docs are excluded)
    3. Visibility rules:
       - "public": accessible to all users in tenant
       - "tenant": accessible to all users in tenant
       - "group": accessible only if user is in one of allowed_groups
       - "private": accessible only to owner OR users in allowed_users
    """

    def filter(
        self,
        results: list[FusedResult],
        user_context: UserContext,
    ) -> list[FusedResult]:
        """Filter results based on ACL rules.

        This is a BACKUP filter - if query-level ACL is correct,
        this should never filter anything.

        Args:
            results: List of fused results from reranking.
            user_context: Authenticated user's context.

        Returns:
            Filtered list containing only accessible results.
        """
        if not results:
            return []

        accessible_results = []
        filtered_count = 0

        for result in results:
            if self._is_accessible(result, user_context):
                accessible_results.append(result)
            else:
                filtered_count += 1
                self._log_filtered_result(result, user_context)

        if filtered_count > 0:
            # This warning indicates a potential bug in query-level ACL
            _log_warning(
                "acl_safety_net_filtered_results",
                filtered_count=filtered_count,
                total_count=len(results),
                user_id=str(user_context.user_id),
                tenant_id=str(user_context.tenant_id),
                detail="Safety net filtered results - this may indicate a query-level ACL bug",
            )

        return accessible_results

    def _is_accessible(
        self,
        result: FusedResult,
        user_context: UserContext,
    ) -> bool:
        """Check if a result is accessible to the user.

        Args:
            result: Single fused result with metadata.
            user_context: User's authentication context.

        Returns:
            True if user can access the result, False otherwise.
        """
        metadata = result.metadata

        # Extract ACL fields from metadata
        doc_tenant_id = metadata.get("tenant_id")
        doc_visibility = metadata.get("visibility")
        doc_status = metadata.get("status", "active")  # Default to active if missing
        doc_owner_id = metadata.get("owner_id")
        doc_allowed_groups = metadata.get("allowed_groups", [])
        doc_allowed_users = metadata.get("allowed_users", [])

        # 1. Tenant isolation (MANDATORY)
        if doc_tenant_id is None or doc_tenant_id != str(user_context.tenant_id):
            return False

        # 2. Status check - must be active
        if doc_status != "active":
            return False

        # 3. Visibility check
        if doc_visibility is None:
            # Missing visibility - block for safety
            return False

        return self._check_visibility_access(
            visibility=doc_visibility,
            owner_id=doc_owner_id,
            allowed_groups=doc_allowed_groups,
            allowed_users=doc_allowed_users,
            user_context=user_context,
        )

    def _check_visibility_access(
        self,
        visibility: str,
        owner_id: str | None,
        allowed_groups: list[str],
        allowed_users: list[str],
        user_context: UserContext,
    ) -> bool:
        """Check access based on visibility level.

        Args:
            visibility: Document visibility level.
            owner_id: Document owner's user ID.
            allowed_groups: Groups with access.
            allowed_users: Users with explicit access.
            user_context: User's authentication context.

        Returns:
            True if visibility rules allow access.
        """
        user_id_str = str(user_context.user_id)

        if visibility == Visibility.PUBLIC.value:
            # Public: accessible to all in tenant (tenant already checked)
            return True

        if visibility == Visibility.TENANT.value:
            # Tenant: accessible to all in tenant (tenant already checked)
            return True

        if visibility == Visibility.GROUP.value:
            # Group: user must be in at least one allowed group
            if not allowed_groups:
                return False
            user_groups = set(user_context.groups)
            allowed_set = set(allowed_groups)
            return bool(user_groups & allowed_set)

        if visibility == Visibility.PRIVATE.value:
            # Private: owner OR explicit allowed_user
            if owner_id is not None and owner_id == user_id_str:
                return True
            if user_id_str in allowed_users:
                return True
            return False

        # Unknown visibility level - block for safety
        return False

    def _log_filtered_result(
        self,
        result: FusedResult,
        user_context: UserContext,
    ) -> None:
        """Log details about a filtered result for debugging.

        Args:
            result: The result that was filtered out.
            user_context: User's authentication context.
        """
        metadata = result.metadata

        _log_warning(
            "safety_net_filtered_individual_result",
            chunk_id=str(result.chunk_id),
            document_id=str(result.document_id),
            doc_tenant_id=metadata.get("tenant_id"),
            doc_visibility=metadata.get("visibility"),
            doc_status=metadata.get("status"),
            doc_owner_id=metadata.get("owner_id"),
            doc_allowed_groups=metadata.get("allowed_groups", []),
            user_tenant_id=str(user_context.tenant_id),
            user_id=str(user_context.user_id),
            user_groups=user_context.groups,
            reason="Result blocked by safety net - investigate query-level ACL",
        )
