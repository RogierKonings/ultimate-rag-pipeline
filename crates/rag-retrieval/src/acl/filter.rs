//! ACL filter builder and result filtering.
//!
//! This module provides the core ACL filtering logic that builds database
//! filters and performs post-search safety net filtering.

use serde::{Deserialize, Serialize};
use uuid::Uuid;

use super::config::ACLFilterConfig;
use crate::types::{UserContext, Visibility};

/// Match type for filter conditions.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum MatchType {
    /// Match exact value.
    Value(String),
    /// Match any of the values.
    Any(Vec<String>),
}

impl MatchType {
    /// Create a value match.
    #[must_use]
    pub fn value(v: impl Into<String>) -> Self {
        Self::Value(v.into())
    }

    /// Create an any-of match.
    #[must_use]
    pub fn any(values: Vec<String>) -> Self {
        Self::Any(values)
    }
}

/// A single filter condition.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct FilterCondition {
    /// The field key to match against.
    pub key: String,
    /// The match type and value(s).
    pub match_type: MatchType,
}

impl FilterCondition {
    /// Create a new filter condition.
    #[must_use]
    pub fn new(key: impl Into<String>, match_type: MatchType) -> Self {
        Self {
            key: key.into(),
            match_type,
        }
    }

    /// Create a value match condition.
    #[must_use]
    pub fn value(key: impl Into<String>, value: impl Into<String>) -> Self {
        Self::new(key, MatchType::Value(value.into()))
    }

    /// Create an any-of match condition.
    #[must_use]
    pub fn any_of(key: impl Into<String>, values: Vec<String>) -> Self {
        Self::new(key, MatchType::Any(values))
    }
}

/// Unified filter format that can be converted to Qdrant or OpenSearch.
///
/// This provides a backend-agnostic filter structure that follows the
/// bool query pattern:
/// - `must`: All conditions must match (AND)
/// - `should`: At least one condition must match (OR)
/// - `must_not`: None of the conditions may match (NOT)
///
/// # Example
///
/// ```
/// use rag_retrieval::acl::{UnifiedFilter, FilterCondition, MatchType};
///
/// let filter = UnifiedFilter::new()
///     .must(FilterCondition::value("tenant_id", "tenant-123"))
///     .should(FilterCondition::value("visibility", "public"))
///     .should(FilterCondition::value("visibility", "tenant"))
///     .must_not(FilterCondition::any_of(
///         "denied_users",
///         vec!["user-1".to_string()]
///     ));
/// ```
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct UnifiedFilter {
    /// Conditions that must all match (AND logic).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub must: Vec<FilterCondition>,

    /// Conditions where at least one must match (OR logic).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub should: Vec<FilterCondition>,

    /// Conditions that must not match (NOT logic).
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub must_not: Vec<FilterCondition>,
}

impl UnifiedFilter {
    /// Create a new empty filter.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Add a must condition.
    #[must_use]
    pub fn must(mut self, condition: FilterCondition) -> Self {
        self.must.push(condition);
        self
    }

    /// Add a should condition.
    #[must_use]
    pub fn should(mut self, condition: FilterCondition) -> Self {
        self.should.push(condition);
        self
    }

    /// Add a must_not condition.
    #[must_use]
    pub fn must_not(mut self, condition: FilterCondition) -> Self {
        self.must_not.push(condition);
        self
    }

    /// Add multiple must conditions.
    #[must_use]
    pub fn must_all(mut self, conditions: Vec<FilterCondition>) -> Self {
        self.must.extend(conditions);
        self
    }

    /// Add multiple should conditions.
    #[must_use]
    pub fn should_any(mut self, conditions: Vec<FilterCondition>) -> Self {
        self.should.extend(conditions);
        self
    }

    /// Add multiple must_not conditions.
    #[must_use]
    pub fn must_not_any(mut self, conditions: Vec<FilterCondition>) -> Self {
        self.must_not.extend(conditions);
        self
    }

    /// Check if the filter is empty (no conditions).
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.must.is_empty() && self.should.is_empty() && self.must_not.is_empty()
    }

    /// Merge another filter into this one.
    ///
    /// Conditions from `other` are appended to the corresponding lists.
    #[must_use]
    pub fn merge(mut self, other: UnifiedFilter) -> Self {
        self.must.extend(other.must);
        self.should.extend(other.should);
        self.must_not.extend(other.must_not);
        self
    }
}

/// Trait for types that have ACL fields for filtering.
///
/// Implement this trait on result types to enable post-search
/// ACL filtering with [`ACLFilter::filter_results`].
pub trait HasACLFields {
    /// Get the document's visibility level.
    fn visibility(&self) -> Visibility;

    /// Get the owner's user ID, if any.
    fn owner_id(&self) -> Option<Uuid>;

    /// Get the list of groups allowed to access this document.
    fn allowed_groups(&self) -> &[String];

    /// Get the list of users explicitly allowed to access this document.
    fn allowed_users(&self) -> &[Uuid];

    /// Get the list of groups denied access to this document.
    fn denied_groups(&self) -> &[String];

    /// Get the list of users denied access to this document.
    fn denied_users(&self) -> &[Uuid];

    /// Get the tenant ID this document belongs to.
    fn tenant_id(&self) -> Uuid;
}

/// ACL filter builder and result filter.
///
/// Builds database filters for ACL enforcement and provides post-search
/// filtering as a safety net.
///
/// # ACL Logic
///
/// 1. Document must belong to user's tenant (unless super tenant)
/// 2. Document must be:
///    - PUBLIC visibility, OR
///    - TENANT visibility (same tenant), OR
///    - GROUP visibility with matching groups, OR
///    - Explicitly allowed for user, OR
///    - Owned by user
/// 3. User must not be in denied_groups or denied_users
///
/// # Example
///
/// ```
/// use rag_retrieval::acl::{ACLFilter, ACLFilterConfig};
/// use rag_retrieval::types::UserContext;
/// use uuid::Uuid;
///
/// let config = ACLFilterConfig::default();
/// let acl = ACLFilter::new(config);
///
/// let user = UserContext::new(Uuid::new_v4(), Uuid::new_v4())
///     .with_groups(vec!["engineering".into()]);
///
/// let filter = acl.build_filter(&user, None);
///
/// // Check if filter has the expected structure
/// assert!(!filter.must.is_empty()); // tenant_id, status
/// assert!(!filter.should.is_empty()); // visibility options
/// ```
#[derive(Debug, Clone)]
pub struct ACLFilter {
    config: ACLFilterConfig,
}

impl ACLFilter {
    /// Create a new ACL filter with the given configuration.
    #[must_use]
    pub fn new(config: ACLFilterConfig) -> Self {
        Self { config }
    }

    /// Create an ACL filter with default configuration.
    #[must_use]
    pub fn with_defaults() -> Self {
        Self::new(ACLFilterConfig::default())
    }

    /// Get the filter configuration.
    #[must_use]
    pub const fn config(&self) -> &ACLFilterConfig {
        &self.config
    }

    /// Build unified filter for user context.
    ///
    /// This creates a filter that can be converted to Qdrant or OpenSearch
    /// format. The filter enforces:
    ///
    /// - Tenant isolation
    /// - Visibility-based access control
    /// - Explicit allow/deny lists
    ///
    /// # Arguments
    ///
    /// * `user_context` - The authenticated user's context
    /// * `additional_filters` - Optional extra filters to merge
    ///
    /// # Returns
    ///
    /// A [`UnifiedFilter`] that can be converted to backend-specific formats.
    #[must_use]
    pub fn build_filter(
        &self,
        user_context: &UserContext,
        additional_filters: Option<&UnifiedFilter>,
    ) -> UnifiedFilter {
        // If ACL is disabled, return only additional filters
        if !self.config.enabled {
            return additional_filters.cloned().unwrap_or_default();
        }

        // Admin bypass: return empty ACL filter (still apply additional filters)
        if self.config.admin_bypass && user_context.is_admin {
            return self.merge_filters(UnifiedFilter::new(), additional_filters);
        }

        // Build the ACL filter
        let acl_filter = self.build_acl_clauses(user_context);
        self.merge_filters(acl_filter, additional_filters)
    }

    /// Build the core ACL filter clauses.
    fn build_acl_clauses(&self, user: &UserContext) -> UnifiedFilter {
        let mut filter = UnifiedFilter::new();

        // Always filter deleted documents
        filter = filter.must(FilterCondition::value("status", "active"));

        // Tenant isolation (always required unless super tenant)
        if !self.config.is_super_tenant(user.tenant_id) {
            filter = filter.must(FilterCondition::value("tenant_id", user.tenant_id.to_string()));
        }

        // Visibility options (document must match at least one)

        // 1. Public documents
        filter = filter.should(FilterCondition::value(
            "visibility",
            visibility_to_string(Visibility::Public),
        ));

        // 2. Tenant-wide documents (same tenant)
        filter = filter.should(FilterCondition::value(
            "visibility",
            visibility_to_string(Visibility::Tenant),
        ));

        // 3. Documents allowed for user's groups
        if !user.groups.is_empty() {
            filter = filter.should(FilterCondition::any_of("allowed_groups", user.groups.clone()));
        }

        // 4. Documents explicitly allowed for this user
        filter = filter.should(FilterCondition::any_of(
            "allowed_users",
            vec![user.user_id.to_string()],
        ));

        // 5. Documents owned by this user (owner always has access)
        filter = filter.should(FilterCondition::value("owner_id", user.user_id.to_string()));

        // Denied access (must not match any)
        if !user.groups.is_empty() {
            filter = filter.must_not(FilterCondition::any_of("denied_groups", user.groups.clone()));
        }

        filter = filter.must_not(FilterCondition::any_of(
            "denied_users",
            vec![user.user_id.to_string()],
        ));

        filter
    }

    /// Merge ACL filter with additional filters.
    fn merge_filters(
        &self,
        acl_filter: UnifiedFilter,
        additional_filters: Option<&UnifiedFilter>,
    ) -> UnifiedFilter {
        match additional_filters {
            Some(additional) => acl_filter.merge(additional.clone()),
            None => acl_filter,
        }
    }

    /// Check if a single result passes ACL filter.
    ///
    /// This is a post-search safety net for checking individual results.
    /// The primary ACL filtering should happen at the database level via
    /// [`build_filter`].
    ///
    /// # Arguments
    ///
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
        &self,
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
        if !self.config.enabled {
            return true;
        }

        // Admin bypass
        if self.config.admin_bypass && user_context.is_admin {
            return true;
        }

        // Check tenant isolation first
        if !self.config.is_super_tenant(user_context.tenant_id)
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
    /// * `user_context` - The authenticated user's context
    /// * `results` - The results to filter
    ///
    /// # Returns
    ///
    /// A filtered list containing only accessible results.
    pub fn filter_results<T: HasACLFields>(
        &self,
        user_context: &UserContext,
        results: Vec<T>,
    ) -> Vec<T> {
        // If ACL is disabled, return all results
        if !self.config.enabled {
            return results;
        }

        // Admin bypass
        if self.config.admin_bypass && user_context.is_admin {
            return results;
        }

        results
            .into_iter()
            .filter(|result| {
                self.can_access(
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
}

/// Convert visibility enum to string for filter conditions.
fn visibility_to_string(visibility: Visibility) -> String {
    match visibility {
        Visibility::Public => "public".to_string(),
        Visibility::Private => "private".to_string(),
        Visibility::Group => "group".to_string(),
        Visibility::Tenant => "tenant".to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Helper struct for testing HasACLFields
    #[derive(Debug, Clone)]
    struct TestDocument {
        id: String,
        visibility: Visibility,
        owner_id: Option<Uuid>,
        tenant_id: Uuid,
        allowed_groups: Vec<String>,
        allowed_users: Vec<Uuid>,
        denied_groups: Vec<String>,
        denied_users: Vec<Uuid>,
    }

    impl TestDocument {
        fn new(id: &str, tenant_id: Uuid, visibility: Visibility) -> Self {
            Self {
                id: id.to_string(),
                visibility,
                owner_id: None,
                tenant_id,
                allowed_groups: vec![],
                allowed_users: vec![],
                denied_groups: vec![],
                denied_users: vec![],
            }
        }

        fn with_owner(mut self, owner_id: Uuid) -> Self {
            self.owner_id = Some(owner_id);
            self
        }

        fn with_allowed_groups(mut self, groups: Vec<String>) -> Self {
            self.allowed_groups = groups;
            self
        }

        fn with_allowed_users(mut self, users: Vec<Uuid>) -> Self {
            self.allowed_users = users;
            self
        }

        fn with_denied_groups(mut self, groups: Vec<String>) -> Self {
            self.denied_groups = groups;
            self
        }

        fn with_denied_users(mut self, users: Vec<Uuid>) -> Self {
            self.denied_users = users;
            self
        }
    }

    impl HasACLFields for TestDocument {
        fn visibility(&self) -> Visibility {
            self.visibility
        }

        fn owner_id(&self) -> Option<Uuid> {
            self.owner_id
        }

        fn allowed_groups(&self) -> &[String] {
            &self.allowed_groups
        }

        fn allowed_users(&self) -> &[Uuid] {
            &self.allowed_users
        }

        fn denied_groups(&self) -> &[String] {
            &self.denied_groups
        }

        fn denied_users(&self) -> &[Uuid] {
            &self.denied_users
        }

        fn tenant_id(&self) -> Uuid {
            self.tenant_id
        }
    }

    #[test]
    fn test_match_type_value() {
        let m = MatchType::value("test");
        assert_eq!(m, MatchType::Value("test".to_string()));
    }

    #[test]
    fn test_match_type_any() {
        let m = MatchType::any(vec!["a".to_string(), "b".to_string()]);
        assert_eq!(
            m,
            MatchType::Any(vec!["a".to_string(), "b".to_string()])
        );
    }

    #[test]
    fn test_filter_condition_value() {
        let cond = FilterCondition::value("key", "val");
        assert_eq!(cond.key, "key");
        assert_eq!(cond.match_type, MatchType::Value("val".to_string()));
    }

    #[test]
    fn test_filter_condition_any_of() {
        let cond = FilterCondition::any_of("key", vec!["a".to_string(), "b".to_string()]);
        assert_eq!(cond.key, "key");
        assert_eq!(
            cond.match_type,
            MatchType::Any(vec!["a".to_string(), "b".to_string()])
        );
    }

    #[test]
    fn test_unified_filter_builder() {
        let filter = UnifiedFilter::new()
            .must(FilterCondition::value("tenant_id", "t1"))
            .should(FilterCondition::value("visibility", "public"))
            .should(FilterCondition::value("visibility", "tenant"))
            .must_not(FilterCondition::any_of("denied_users", vec!["u1".to_string()]));

        assert_eq!(filter.must.len(), 1);
        assert_eq!(filter.should.len(), 2);
        assert_eq!(filter.must_not.len(), 1);
    }

    #[test]
    fn test_unified_filter_is_empty() {
        let empty = UnifiedFilter::new();
        assert!(empty.is_empty());

        let not_empty = UnifiedFilter::new().must(FilterCondition::value("k", "v"));
        assert!(!not_empty.is_empty());
    }

    #[test]
    fn test_unified_filter_merge() {
        let f1 = UnifiedFilter::new()
            .must(FilterCondition::value("a", "1"))
            .should(FilterCondition::value("b", "2"));

        let f2 = UnifiedFilter::new()
            .must(FilterCondition::value("c", "3"))
            .must_not(FilterCondition::value("d", "4"));

        let merged = f1.merge(f2);

        assert_eq!(merged.must.len(), 2);
        assert_eq!(merged.should.len(), 1);
        assert_eq!(merged.must_not.len(), 1);
    }

    #[test]
    fn test_build_filter_disabled() {
        let config = ACLFilterConfig::disabled();
        let acl = ACLFilter::new(config);

        let user = UserContext::new(Uuid::new_v4(), Uuid::new_v4());
        let filter = acl.build_filter(&user, None);

        assert!(filter.is_empty());
    }

    #[test]
    fn test_build_filter_admin_bypass() {
        let config = ACLFilterConfig::builder().admin_bypass(true).build();
        let acl = ACLFilter::new(config);

        let user = UserContext::new(Uuid::new_v4(), Uuid::new_v4()).with_admin(true);
        let filter = acl.build_filter(&user, None);

        // Admin bypass: no ACL filters applied
        assert!(filter.is_empty());
    }

    #[test]
    fn test_build_filter_admin_bypass_with_additional() {
        let config = ACLFilterConfig::builder().admin_bypass(true).build();
        let acl = ACLFilter::new(config);

        let user = UserContext::new(Uuid::new_v4(), Uuid::new_v4()).with_admin(true);
        let additional = UnifiedFilter::new().must(FilterCondition::value("source_type", "pdf"));
        let filter = acl.build_filter(&user, Some(&additional));

        // Admin bypass but additional filters still applied
        assert_eq!(filter.must.len(), 1);
        assert_eq!(filter.must[0].key, "source_type");
    }

    #[test]
    fn test_build_filter_tenant_isolation() {
        let config = ACLFilterConfig::default();
        let acl = ACLFilter::new(config);

        let tenant_id = Uuid::new_v4();
        let user = UserContext::new(Uuid::new_v4(), tenant_id);
        let filter = acl.build_filter(&user, None);

        // Should have tenant_id and status in must
        assert!(filter
            .must
            .iter()
            .any(|c| c.key == "tenant_id"
                && c.match_type == MatchType::Value(tenant_id.to_string())));
        assert!(filter
            .must
            .iter()
            .any(|c| c.key == "status" && c.match_type == MatchType::Value("active".to_string())));
    }

    #[test]
    fn test_build_filter_super_tenant_no_tenant_filter() {
        let super_tenant = Uuid::new_v4();
        let config = ACLFilterConfig::builder()
            .super_tenant_id(Some(super_tenant))
            .build();
        let acl = ACLFilter::new(config);

        let user = UserContext::new(Uuid::new_v4(), super_tenant);
        let filter = acl.build_filter(&user, None);

        // Super tenant should not have tenant_id filter
        assert!(!filter.must.iter().any(|c| c.key == "tenant_id"));
        // But should still have status filter
        assert!(filter.must.iter().any(|c| c.key == "status"));
    }

    #[test]
    fn test_build_filter_visibility_options() {
        let config = ACLFilterConfig::default();
        let acl = ACLFilter::new(config);

        let user = UserContext::new(Uuid::new_v4(), Uuid::new_v4())
            .with_groups(vec!["engineering".into()]);
        let filter = acl.build_filter(&user, None);

        // Should have visibility options in should
        assert!(filter.should.iter().any(|c| c.key == "visibility"
            && c.match_type == MatchType::Value("public".to_string())));
        assert!(filter.should.iter().any(|c| c.key == "visibility"
            && c.match_type == MatchType::Value("tenant".to_string())));
        assert!(filter.should.iter().any(|c| c.key == "allowed_groups"));
        assert!(filter.should.iter().any(|c| c.key == "allowed_users"));
        assert!(filter.should.iter().any(|c| c.key == "owner_id"));
    }

    #[test]
    fn test_build_filter_denied_clauses() {
        let config = ACLFilterConfig::default();
        let acl = ACLFilter::new(config);

        let user_id = Uuid::new_v4();
        let user = UserContext::new(user_id, Uuid::new_v4())
            .with_groups(vec!["engineering".into()]);
        let filter = acl.build_filter(&user, None);

        // Should have denied_groups and denied_users in must_not
        assert!(filter.must_not.iter().any(|c| c.key == "denied_groups"));
        assert!(filter.must_not.iter().any(|c| c.key == "denied_users"));
    }

    #[test]
    fn test_can_access_public() {
        let config = ACLFilterConfig::default();
        let acl = ACLFilter::new(config);

        let tenant_id = Uuid::new_v4();
        let user = UserContext::new(Uuid::new_v4(), tenant_id);

        // Public documents should be accessible
        assert!(acl.can_access(
            &user,
            Visibility::Public,
            None,
            &[],
            &[],
            &[],
            &[],
            tenant_id,
        ));
    }

    #[test]
    fn test_can_access_tenant() {
        let config = ACLFilterConfig::default();
        let acl = ACLFilter::new(config);

        let tenant_id = Uuid::new_v4();
        let user = UserContext::new(Uuid::new_v4(), tenant_id);

        // Tenant documents should be accessible to same tenant
        assert!(acl.can_access(
            &user,
            Visibility::Tenant,
            None,
            &[],
            &[],
            &[],
            &[],
            tenant_id,
        ));
    }

    #[test]
    fn test_can_access_different_tenant() {
        let config = ACLFilterConfig::default();
        let acl = ACLFilter::new(config);

        let user_tenant = Uuid::new_v4();
        let doc_tenant = Uuid::new_v4();
        let user = UserContext::new(Uuid::new_v4(), user_tenant);

        // Even public documents from different tenant should NOT be accessible
        // (tenant isolation is enforced first)
        assert!(!acl.can_access(
            &user,
            Visibility::Public,
            None,
            &[],
            &[],
            &[],
            &[],
            doc_tenant,
        ));
    }

    #[test]
    fn test_can_access_private_owner() {
        let config = ACLFilterConfig::default();
        let acl = ACLFilter::new(config);

        let tenant_id = Uuid::new_v4();
        let user_id = Uuid::new_v4();
        let user = UserContext::new(user_id, tenant_id);

        // Owner can access private documents
        assert!(acl.can_access(
            &user,
            Visibility::Private,
            Some(user_id),
            &[],
            &[],
            &[],
            &[],
            tenant_id,
        ));
    }

    #[test]
    fn test_can_access_private_not_owner() {
        let config = ACLFilterConfig::default();
        let acl = ACLFilter::new(config);

        let tenant_id = Uuid::new_v4();
        let user_id = Uuid::new_v4();
        let other_user_id = Uuid::new_v4();
        let user = UserContext::new(user_id, tenant_id);

        // Non-owner cannot access private documents
        assert!(!acl.can_access(
            &user,
            Visibility::Private,
            Some(other_user_id),
            &[],
            &[],
            &[],
            &[],
            tenant_id,
        ));
    }

    #[test]
    fn test_can_access_private_explicitly_allowed() {
        let config = ACLFilterConfig::default();
        let acl = ACLFilter::new(config);

        let tenant_id = Uuid::new_v4();
        let user_id = Uuid::new_v4();
        let owner_id = Uuid::new_v4();
        let user = UserContext::new(user_id, tenant_id);

        // User in allowed_users can access private documents
        assert!(acl.can_access(
            &user,
            Visibility::Private,
            Some(owner_id),
            &[],
            &[user_id],
            &[],
            &[],
            tenant_id,
        ));
    }

    #[test]
    fn test_can_access_group_membership() {
        let config = ACLFilterConfig::default();
        let acl = ACLFilter::new(config);

        let tenant_id = Uuid::new_v4();
        let user = UserContext::new(Uuid::new_v4(), tenant_id)
            .with_groups(vec!["engineering".into(), "product".into()]);

        // User in allowed group can access
        assert!(acl.can_access(
            &user,
            Visibility::Group,
            None,
            &["engineering".into()],
            &[],
            &[],
            &[],
            tenant_id,
        ));
    }

    #[test]
    fn test_can_access_group_no_membership() {
        let config = ACLFilterConfig::default();
        let acl = ACLFilter::new(config);

        let tenant_id = Uuid::new_v4();
        let user = UserContext::new(Uuid::new_v4(), tenant_id)
            .with_groups(vec!["sales".into()]);

        // User not in allowed group cannot access
        assert!(!acl.can_access(
            &user,
            Visibility::Group,
            None,
            &["engineering".into()],
            &[],
            &[],
            &[],
            tenant_id,
        ));
    }

    #[test]
    fn test_can_access_denied_user() {
        let config = ACLFilterConfig::default();
        let acl = ACLFilter::new(config);

        let tenant_id = Uuid::new_v4();
        let user_id = Uuid::new_v4();
        let user = UserContext::new(user_id, tenant_id);

        // Denied user cannot access even public documents
        assert!(!acl.can_access(
            &user,
            Visibility::Public,
            None,
            &[],
            &[],
            &[],
            &[user_id],
            tenant_id,
        ));
    }

    #[test]
    fn test_can_access_denied_group() {
        let config = ACLFilterConfig::default();
        let acl = ACLFilter::new(config);

        let tenant_id = Uuid::new_v4();
        let user = UserContext::new(Uuid::new_v4(), tenant_id)
            .with_groups(vec!["contractors".into()]);

        // User in denied group cannot access
        assert!(!acl.can_access(
            &user,
            Visibility::Public,
            None,
            &[],
            &[],
            &["contractors".into()],
            &[],
            tenant_id,
        ));
    }

    #[test]
    fn test_can_access_admin_bypass() {
        let config = ACLFilterConfig::builder().admin_bypass(true).build();
        let acl = ACLFilter::new(config);

        let user_tenant = Uuid::new_v4();
        let doc_tenant = Uuid::new_v4();
        let user_id = Uuid::new_v4();
        let user = UserContext::new(user_id, user_tenant).with_admin(true);

        // Admin can access anything, even cross-tenant and denied
        assert!(acl.can_access(
            &user,
            Visibility::Private,
            Some(Uuid::new_v4()),
            &[],
            &[],
            &[],
            &[user_id], // Even if in denied list
            doc_tenant,
        ));
    }

    #[test]
    fn test_can_access_acl_disabled() {
        let config = ACLFilterConfig::disabled();
        let acl = ACLFilter::new(config);

        let user_tenant = Uuid::new_v4();
        let doc_tenant = Uuid::new_v4();
        let user_id = Uuid::new_v4();
        let user = UserContext::new(user_id, user_tenant);

        // ACL disabled: everyone can access everything
        assert!(acl.can_access(
            &user,
            Visibility::Private,
            Some(Uuid::new_v4()),
            &[],
            &[],
            &[],
            &[user_id],
            doc_tenant,
        ));
    }

    #[test]
    fn test_filter_results() {
        let config = ACLFilterConfig::default();
        let acl = ACLFilter::new(config);

        let tenant_id = Uuid::new_v4();
        let user_id = Uuid::new_v4();
        let user = UserContext::new(user_id, tenant_id)
            .with_groups(vec!["engineering".into()]);

        let docs = vec![
            TestDocument::new("doc1", tenant_id, Visibility::Public),
            TestDocument::new("doc2", tenant_id, Visibility::Private).with_owner(user_id),
            TestDocument::new("doc3", tenant_id, Visibility::Private).with_owner(Uuid::new_v4()), // Not owner
            TestDocument::new("doc4", tenant_id, Visibility::Group)
                .with_allowed_groups(vec!["engineering".into()]),
            TestDocument::new("doc5", tenant_id, Visibility::Group)
                .with_allowed_groups(vec!["sales".into()]), // Not in group
            TestDocument::new("doc6", tenant_id, Visibility::Public)
                .with_denied_users(vec![user_id]), // Denied
        ];

        let filtered = acl.filter_results(&user, docs);

        assert_eq!(filtered.len(), 3);
        assert_eq!(filtered[0].id, "doc1"); // Public
        assert_eq!(filtered[1].id, "doc2"); // Owner
        assert_eq!(filtered[2].id, "doc4"); // Group member
    }

    #[test]
    fn test_filter_results_admin() {
        let config = ACLFilterConfig::builder().admin_bypass(true).build();
        let acl = ACLFilter::new(config);

        let tenant_id = Uuid::new_v4();
        let admin = UserContext::new(Uuid::new_v4(), tenant_id).with_admin(true);

        let docs = vec![
            TestDocument::new("doc1", tenant_id, Visibility::Private),
            TestDocument::new("doc2", Uuid::new_v4(), Visibility::Private), // Different tenant
        ];

        let filtered = acl.filter_results(&admin, docs);

        // Admin sees everything
        assert_eq!(filtered.len(), 2);
    }

    #[test]
    fn test_filter_results_disabled() {
        let config = ACLFilterConfig::disabled();
        let acl = ACLFilter::new(config);

        let user = UserContext::new(Uuid::new_v4(), Uuid::new_v4());

        let docs = vec![
            TestDocument::new("doc1", Uuid::new_v4(), Visibility::Private),
            TestDocument::new("doc2", Uuid::new_v4(), Visibility::Private),
        ];

        let filtered = acl.filter_results(&user, docs);

        // ACL disabled: all docs pass through
        assert_eq!(filtered.len(), 2);
    }

    #[test]
    fn test_unified_filter_serialization() {
        let filter = UnifiedFilter::new()
            .must(FilterCondition::value("tenant_id", "t1"))
            .should(FilterCondition::value("visibility", "public"))
            .must_not(FilterCondition::any_of("denied_users", vec!["u1".into()]));

        let json = serde_json::to_string(&filter).unwrap();
        let deserialized: UnifiedFilter = serde_json::from_str(&json).unwrap();

        assert_eq!(filter, deserialized);
    }
}
