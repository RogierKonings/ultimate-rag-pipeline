"""
Role definitions and hierarchy for RBAC.

This module defines roles, their hierarchy, and inheritance rules.
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    """
    System-defined roles with hierarchical structure.

    Roles are ordered from least to most privileged.
    Higher roles inherit permissions from lower roles.
    """

    # Public/unauthenticated access
    ANONYMOUS = "anonymous"

    # Standard authenticated user
    USER = "user"

    # Data analyst with enhanced search capabilities
    ANALYST = "analyst"

    # Data engineer with ingestion capabilities
    ENGINEER = "engineer"

    # Tenant administrator
    TENANT_ADMIN = "tenant_admin"

    # System administrator
    ADMIN = "admin"

    # Super administrator (cross-tenant)
    SUPER_ADMIN = "super_admin"

    # Service account (for internal services)
    SERVICE = "service"

    @classmethod
    def from_string(cls, role_str: str) -> Role | None:
        """
        Convert a role string to Role enum.

        Args:
            role_str: Role string like "user" or "admin".

        Returns:
            Role enum value or None if not found.
        """
        try:
            return cls(role_str.lower())
        except ValueError:
            return None

    def is_admin_level(self) -> bool:
        """Check if this role has admin-level privileges."""
        return self in (Role.ADMIN, Role.SUPER_ADMIN, Role.TENANT_ADMIN)


# Role hierarchy - defines inheritance
# Each role inherits permissions from roles listed as its parents
ROLE_HIERARCHY: dict[Role, list[Role]] = {
    Role.ANONYMOUS: [],
    Role.USER: [Role.ANONYMOUS],
    Role.ANALYST: [Role.USER],
    Role.ENGINEER: [Role.ANALYST],
    Role.TENANT_ADMIN: [Role.ENGINEER],
    Role.ADMIN: [Role.TENANT_ADMIN],
    Role.SUPER_ADMIN: [Role.ADMIN],
    Role.SERVICE: [Role.USER],  # Service accounts have base user permissions
}


class RoleHierarchy:
    """
    Manages role hierarchy and inheritance.

    Provides methods to determine effective roles based on hierarchy.
    """

    def __init__(self, hierarchy: dict[Role, list[Role]] | None = None):
        """
        Initialize role hierarchy.

        Args:
            hierarchy: Custom hierarchy dict, or use default if None.
        """
        self._hierarchy = hierarchy or ROLE_HIERARCHY
        self._cache: dict[Role, set[Role]] = {}

    def get_inherited_roles(self, role: Role) -> set[Role]:
        """
        Get all roles inherited by a given role.

        Args:
            role: The role to get inherited roles for.

        Returns:
            Set of all inherited roles (including the role itself).
        """
        if role in self._cache:
            return self._cache[role]

        inherited = {role}
        parents = self._hierarchy.get(role, [])

        for parent in parents:
            inherited |= self.get_inherited_roles(parent)

        self._cache[role] = inherited
        return inherited

    def role_inherits_from(self, role: Role, parent: Role) -> bool:
        """
        Check if a role inherits from another role.

        Args:
            role: The role to check.
            parent: The potential parent role.

        Returns:
            True if role inherits from parent.
        """
        inherited = self.get_inherited_roles(role)
        return parent in inherited

    def get_highest_role(self, roles: list[Role]) -> Role | None:
        """
        Get the highest role from a list of roles.

        The highest role is the one that inherits from all others.

        Args:
            roles: List of roles to compare.

        Returns:
            The highest role, or None if list is empty.
        """
        if not roles:
            return None

        # Find the role that inherits from all others
        for candidate in roles:
            candidate_inherited = self.get_inherited_roles(candidate)
            if all(r in candidate_inherited for r in roles):
                return candidate

        # No single highest role, return the first one
        return roles[0]

    def compare_roles(self, role1: Role, role2: Role) -> int:
        """
        Compare two roles by privilege level.

        Args:
            role1: First role.
            role2: Second role.

        Returns:
            -1 if role1 < role2, 0 if equal, 1 if role1 > role2
        """
        if role1 == role2:
            return 0

        role1_inherited = self.get_inherited_roles(role1)
        role2_inherited = self.get_inherited_roles(role2)

        if role2 in role1_inherited:
            return 1  # role1 inherits from role2, so role1 > role2
        if role1 in role2_inherited:
            return -1  # role2 inherits from role1, so role1 < role2

        return 0  # Not comparable (different branches)


# Default hierarchy instance
_default_hierarchy = RoleHierarchy()


def get_effective_roles(role_strings: list[str]) -> set[str]:
    """
    Get effective roles including inherited roles.

    Args:
        role_strings: List of role strings.

    Returns:
        Set of all effective role strings (including inherited).
    """
    effective: set[str] = set()

    for role_str in role_strings:
        role = Role.from_string(role_str)
        if role:
            inherited = _default_hierarchy.get_inherited_roles(role)
            effective |= {r.value for r in inherited}
        else:
            # Custom role, just include as-is
            effective.add(role_str)

    return effective


def is_admin_role(role_str: str) -> bool:
    """
    Check if a role string represents an admin-level role.

    Args:
        role_str: Role string to check.

    Returns:
        True if the role is admin-level.
    """
    role = Role.from_string(role_str)
    return role.is_admin_level() if role else False


def has_role_or_higher(user_roles: list[str], required_role: str) -> bool:
    """
    Check if user has the required role or a higher one.

    Args:
        user_roles: List of user's role strings.
        required_role: Required role string.

    Returns:
        True if user has the required role or higher.
    """
    required = Role.from_string(required_role)
    if not required:
        # Custom role - check exact match
        return required_role in user_roles

    for role_str in user_roles:
        user_role = Role.from_string(role_str)
        if user_role:
            inherited = _default_hierarchy.get_inherited_roles(user_role)
            if required in inherited:
                return True

    return False
