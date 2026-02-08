//! Post-search ACL evaluation and result filtering.
//!
//! This module provides runtime ACL checks for individual results and
//! batch filtering as a safety net after database-level filtering.

use uuid::Uuid;

use super::config::ACLFilterConfig;
use super::types::HasACLFields;
use crate::types::{UserContext, Visibility};

/// Check if a user can access a document based on ACL rules.
///
/// This is a post-search safety net for checking individual results.
/// The primary ACL filtering should happen at the database level via
/// filter building.
///
/// # Arguments
///
/// * `config` - ACL filter configuration
/// * `user_context` - The authenticated user's context
/// * `visibility` - The document's visibility level
/// * `owner_id` - The document owner's user ID
/// * `allowed_groups` - Groups allowed to access the document
/// * `allowed_users` - Users explicitly allowed access
/// * `denied_groups` - Groups denied access
/// * `denied_users` - Users denied access
/// * `document_tenant_id` - The tenant ID of the document
///
/// # Returns
///
/// `true` if the user can access the document, `false` otherwise.
#[must_use]
#[allow(clippy::too_many_arguments)]
pub fn can_access(
    config: &ACLFilterConfig,
    user_context: &UserContext,
    visibility: Visibility,
    owner_id: Option<Uuid>,
    allowed_groups: &[String],
    allowed_users: &[Uuid],
    denied_groups: &[String],
    denied_users: &[Uuid],
    document_tenant_id: Uuid,
) -> bool {
    // If ACL is disabled, allow all
    if !config.enabled {
        return true;
    }

    // Admin bypass
    if config.admin_bypass && user_context.is_admin {
        return true;
    }

    // Check tenant isolation first
    if !config.is_super_tenant(user_context.tenant_id)
        && user_context.tenant_id != document_tenant_id
    {
        return false;
    }

    // Check denied lists (takes precedence)
    if denied_users.contains(&user_context.user_id) {
        return false;
    }

    if !denied_groups.is_empty()
        && user_context
            .groups
            .iter()
            .any(|g| denied_groups.contains(g))
    {
        return false;
    }

    // Check visibility and access rules
    match visibility {
        Visibility::Public => true,
        Visibility::Tenant => true, // Already passed tenant check
        Visibility::Private => {
            // Owner check
            owner_id.map_or(false, |owner| owner == user_context.user_id)
                // Or explicitly allowed
                || allowed_users.contains(&user_context.user_id)
        }
        Visibility::Group => {
            // Check group membership
            user_context
                .groups
                .iter()
                .any(|g| allowed_groups.contains(g))
                // Or explicitly allowed
                || allowed_users.contains(&user_context.user_id)
                // Or is owner
                || owner_id.map_or(false, |owner| owner == user_context.user_id)
        }
    }
}

/// Filter a list of results based on ACL rules.
///
/// This is a post-search safety net. The primary ACL filtering should
/// happen at the database level, but this provides an additional layer
/// of protection.
///
/// # Type Parameters
///
/// * `T` - A type implementing [`HasACLFields`]
///
/// # Arguments
///
/// * `config` - ACL filter configuration
/// * `user_context` - The authenticated user's context
/// * `results` - The results to filter
///
/// # Returns
///
/// A filtered list containing only accessible results.
pub fn filter_results<T: HasACLFields>(
    config: &ACLFilterConfig,
    user_context: &UserContext,
    results: Vec<T>,
) -> Vec<T> {
    // If ACL is disabled, return all results
    if !config.enabled {
        return results;
    }

    // Admin bypass
    if config.admin_bypass && user_context.is_admin {
        return results;
    }

    results
        .into_iter()
        .filter(|result| {
            can_access(
                config,
                user_context,
                result.visibility(),
                result.owner_id(),
                result.allowed_groups(),
                result.allowed_users(),
                result.denied_groups(),
                result.denied_users(),
                result.tenant_id(),
            )
        })
        .collect()
}

/// Convert visibility enum to string for filter conditions.
#[must_use]
pub fn visibility_to_string(visibility: Visibility) -> String {
    match visibility {
        Visibility::Public => "public".to_string(),
        Visibility::Private => "private".to_string(),
        Visibility::Group => "group".to_string(),
        Visibility::Tenant => "tenant".to_string(),
    }
}
