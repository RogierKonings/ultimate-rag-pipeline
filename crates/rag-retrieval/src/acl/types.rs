//! ACL filter primitive types.
//!
//! This module provides the core filter types used to build database-agnostic
//! filters that can be converted to Qdrant or `OpenSearch` format.

use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::types::Visibility;

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

/// Unified filter format that can be converted to Qdrant or `OpenSearch`.
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

    /// Add a `must_not` condition.
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

    /// Add multiple `must_not` conditions.
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
    pub fn merge(mut self, other: Self) -> Self {
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_match_type_value() {
        let m = MatchType::value("test");
        assert_eq!(m, MatchType::Value("test".to_string()));
    }

    #[test]
    fn test_match_type_any() {
        let m = MatchType::any(vec!["a".to_string(), "b".to_string()]);
        assert_eq!(m, MatchType::Any(vec!["a".to_string(), "b".to_string()]));
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
            .must_not(FilterCondition::any_of(
                "denied_users",
                vec!["u1".to_string()],
            ));

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
}
