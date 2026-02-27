//! ACL filter builders for Qdrant and `OpenSearch`.
//!
//! This module provides builders that convert [`UnifiedFilter`] to backend-specific
//! filter formats for Qdrant and `OpenSearch`.
//!
//! # Example
//!
//! ```
//! use rag_retrieval::acl::{
//!     UnifiedFilter, FilterCondition, QdrantFilterBuilder, OpenSearchFilterBuilder
//! };
//!
//! let filter = UnifiedFilter::new()
//!     .must(FilterCondition::value("tenant_id", "tenant-123"))
//!     .should(FilterCondition::value("visibility", "public"))
//!     .must_not(FilterCondition::any_of("denied_users", vec!["user-1".into()]));
//!
//! // Convert to Qdrant filter
//! let qdrant_filter = QdrantFilterBuilder::build(&filter);
//! assert!(qdrant_filter.is_some());
//!
//! // Convert to OpenSearch filter clauses
//! let opensearch_clauses = OpenSearchFilterBuilder::build(&filter);
//! assert!(!opensearch_clauses.is_empty());
//! ```

use rag_vectorstore::qdrant_client::qdrant::condition::ConditionOneOf;
use rag_vectorstore::qdrant_client::qdrant::r#match::MatchValue;
use rag_vectorstore::qdrant_client::qdrant::{
    Condition, FieldCondition, Filter, Match, RepeatedStrings,
};
use serde_json::{json, Value};

use super::types::{FilterCondition, MatchType, UnifiedFilter};

/// Builder for converting [`UnifiedFilter`] to Qdrant [`Filter`].
///
/// This builder creates Qdrant-native filter structures that can be used
/// directly with the Qdrant client for vector search queries.
///
/// # Example
///
/// ```
/// use rag_retrieval::acl::{UnifiedFilter, FilterCondition, QdrantFilterBuilder};
///
/// let filter = UnifiedFilter::new()
///     .must(FilterCondition::value("tenant_id", "tenant-123"))
///     .should(FilterCondition::value("visibility", "public"));
///
/// let qdrant_filter = QdrantFilterBuilder::build(&filter);
/// assert!(qdrant_filter.is_some());
/// ```
pub struct QdrantFilterBuilder;

impl QdrantFilterBuilder {
    /// Convert a [`UnifiedFilter`] to a Qdrant [`Filter`].
    ///
    /// Returns `None` if the filter is empty (no must, should, or `must_not` conditions).
    ///
    /// # Arguments
    ///
    /// * `filter` - The unified filter to convert
    ///
    /// # Returns
    ///
    /// An `Option<Filter>` - `Some(Filter)` if there are conditions, `None` if empty.
    #[must_use]
    pub fn build(filter: &UnifiedFilter) -> Option<Filter> {
        if filter.is_empty() {
            return None;
        }

        let must = filter
            .must
            .iter()
            .map(Self::build_condition)
            .collect::<Vec<_>>();

        let should = filter
            .should
            .iter()
            .map(Self::build_condition)
            .collect::<Vec<_>>();

        let must_not = filter
            .must_not
            .iter()
            .map(Self::build_condition)
            .collect::<Vec<_>>();

        #[allow(clippy::needless_update)]
        Some(Filter {
            must,
            should,
            must_not,
            ..Default::default()
        })
    }

    /// Convert a single [`FilterCondition`] to a Qdrant [`Condition`].
    fn build_condition(condition: &FilterCondition) -> Condition {
        let match_value = match &condition.match_type {
            MatchType::Value(value) => MatchValue::Keyword(value.clone()),
            MatchType::Any(values) => MatchValue::Keywords(RepeatedStrings {
                strings: values.clone(),
            }),
        };

        Condition {
            condition_one_of: Some(ConditionOneOf::Field(FieldCondition {
                key: condition.key.clone(),
                r#match: Some(Match {
                    match_value: Some(match_value),
                }),
                ..Default::default()
            })),
        }
    }
}

/// Builder for converting [`UnifiedFilter`] to `OpenSearch` filter clauses.
///
/// This builder creates JSON structures suitable for use in `OpenSearch`
/// bool queries. The output is a list of filter clauses that should be
/// added to the `filter` array of a bool query.
///
/// # Example
///
/// ```
/// use rag_retrieval::acl::{UnifiedFilter, FilterCondition, OpenSearchFilterBuilder};
///
/// let filter = UnifiedFilter::new()
///     .must(FilterCondition::value("tenant_id", "tenant-123"))
///     .should(FilterCondition::value("visibility", "public"));
///
/// let clauses = OpenSearchFilterBuilder::build(&filter);
/// // Clauses can be used in: { "bool": { "filter": clauses } }
/// ```
pub struct OpenSearchFilterBuilder;

impl OpenSearchFilterBuilder {
    /// Convert a [`UnifiedFilter`] to `OpenSearch` filter clauses.
    ///
    /// Returns a list of JSON values that can be used in the `filter` array
    /// of an `OpenSearch` bool query.
    ///
    /// The output structure:
    /// - `must` conditions become `term` or `terms` clauses
    /// - `should` conditions are wrapped in a `bool` with `minimum_should_match: 1`
    /// - `must_not` conditions are wrapped in a `bool` with `must_not`
    ///
    /// # Arguments
    ///
    /// * `filter` - The unified filter to convert
    ///
    /// # Returns
    ///
    /// A `Vec<Value>` containing the filter clauses.
    #[must_use]
    pub fn build(filter: &UnifiedFilter) -> Vec<Value> {
        let mut clauses = Vec::new();

        // Must clauses become term/terms directly
        for condition in &filter.must {
            clauses.push(Self::build_clause(condition));
        }

        // Should clauses wrapped in bool with minimum_should_match
        if !filter.should.is_empty() {
            let should_clauses: Vec<Value> = filter.should.iter().map(Self::build_clause).collect();

            clauses.push(json!({
                "bool": {
                    "should": should_clauses,
                    "minimum_should_match": 1
                }
            }));
        }

        // Must not clauses wrapped in bool
        if !filter.must_not.is_empty() {
            let must_not_clauses: Vec<Value> =
                filter.must_not.iter().map(Self::build_clause).collect();

            clauses.push(json!({
                "bool": {
                    "must_not": must_not_clauses
                }
            }));
        }

        clauses
    }

    /// Convert a single [`FilterCondition`] to an `OpenSearch` clause.
    fn build_clause(condition: &FilterCondition) -> Value {
        match &condition.match_type {
            MatchType::Value(value) => {
                json!({
                    "term": {
                        &condition.key: value
                    }
                })
            }
            MatchType::Any(values) => {
                json!({
                    "terms": {
                        &condition.key: values
                    }
                })
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_qdrant_builder_empty() {
        let filter = UnifiedFilter::new();
        let result = QdrantFilterBuilder::build(&filter);
        assert!(result.is_none());
    }

    #[test]
    fn test_qdrant_builder_must_only() {
        let filter = UnifiedFilter::new()
            .must(FilterCondition::value("tenant_id", "tenant-123"))
            .must(FilterCondition::value("status", "active"));

        let result = QdrantFilterBuilder::build(&filter);
        assert!(result.is_some());

        let qdrant_filter = result.unwrap();
        assert_eq!(qdrant_filter.must.len(), 2);
        assert!(qdrant_filter.should.is_empty());
        assert!(qdrant_filter.must_not.is_empty());
    }

    #[test]
    fn test_qdrant_builder_full() {
        let filter = UnifiedFilter::new()
            .must(FilterCondition::value("tenant_id", "tenant-123"))
            .should(FilterCondition::value("visibility", "public"))
            .should(FilterCondition::value("visibility", "tenant"))
            .must_not(FilterCondition::any_of(
                "denied_users",
                vec!["user-1".into(), "user-2".into()],
            ));

        let result = QdrantFilterBuilder::build(&filter);
        assert!(result.is_some());

        let qdrant_filter = result.unwrap();
        assert_eq!(qdrant_filter.must.len(), 1);
        assert_eq!(qdrant_filter.should.len(), 2);
        assert_eq!(qdrant_filter.must_not.len(), 1);
    }

    #[test]
    fn test_qdrant_builder_any_of_values() {
        let filter = UnifiedFilter::new().must(FilterCondition::any_of(
            "allowed_groups",
            vec!["engineering".into(), "product".into()],
        ));

        let result = QdrantFilterBuilder::build(&filter);
        assert!(result.is_some());

        let qdrant_filter = result.unwrap();
        assert_eq!(qdrant_filter.must.len(), 1);

        // Verify the condition contains Keywords match
        let condition = &qdrant_filter.must[0];
        let Some(ConditionOneOf::Field(field_condition)) = &condition.condition_one_of else {
            panic!(
                "Expected Field condition, got: {:?}",
                condition.condition_one_of
            );
        };
        assert_eq!(field_condition.key, "allowed_groups");
        let Some(Match {
            match_value: Some(MatchValue::Keywords(keywords)),
        }) = &field_condition.r#match
        else {
            panic!(
                "Expected Keywords match value, got: {:?}",
                field_condition.r#match
            );
        };
        assert_eq!(keywords.strings.len(), 2);
        assert!(keywords.strings.contains(&"engineering".to_string()));
        assert!(keywords.strings.contains(&"product".to_string()));
    }

    #[test]
    fn test_opensearch_builder_empty() {
        let filter = UnifiedFilter::new();
        let clauses = OpenSearchFilterBuilder::build(&filter);
        assert!(clauses.is_empty());
    }

    #[test]
    fn test_opensearch_builder_must_only() {
        let filter = UnifiedFilter::new()
            .must(FilterCondition::value("tenant_id", "tenant-123"))
            .must(FilterCondition::value("status", "active"));

        let clauses = OpenSearchFilterBuilder::build(&filter);
        assert_eq!(clauses.len(), 2);

        // First clause should be term for tenant_id
        assert_eq!(
            clauses[0],
            json!({
                "term": {
                    "tenant_id": "tenant-123"
                }
            })
        );

        // Second clause should be term for status
        assert_eq!(
            clauses[1],
            json!({
                "term": {
                    "status": "active"
                }
            })
        );
    }

    #[test]
    fn test_opensearch_builder_should_clause() {
        let filter = UnifiedFilter::new()
            .should(FilterCondition::value("visibility", "public"))
            .should(FilterCondition::value("visibility", "tenant"));

        let clauses = OpenSearchFilterBuilder::build(&filter);
        assert_eq!(clauses.len(), 1);

        // Should be wrapped in bool with minimum_should_match
        let expected = json!({
            "bool": {
                "should": [
                    { "term": { "visibility": "public" } },
                    { "term": { "visibility": "tenant" } }
                ],
                "minimum_should_match": 1
            }
        });

        assert_eq!(clauses[0], expected);
    }

    #[test]
    fn test_opensearch_builder_must_not() {
        let filter = UnifiedFilter::new()
            .must_not(FilterCondition::value("status", "deleted"))
            .must_not(FilterCondition::any_of(
                "denied_users",
                vec!["user-1".into()],
            ));

        let clauses = OpenSearchFilterBuilder::build(&filter);
        assert_eq!(clauses.len(), 1);

        // Must not should be wrapped in bool
        let expected = json!({
            "bool": {
                "must_not": [
                    { "term": { "status": "deleted" } },
                    { "terms": { "denied_users": ["user-1"] } }
                ]
            }
        });

        assert_eq!(clauses[0], expected);
    }

    #[test]
    fn test_opensearch_builder_full() {
        let filter = UnifiedFilter::new()
            .must(FilterCondition::value("tenant_id", "tenant-123"))
            .must(FilterCondition::value("status", "active"))
            .should(FilterCondition::value("visibility", "public"))
            .should(FilterCondition::value("visibility", "tenant"))
            .must_not(FilterCondition::any_of(
                "denied_users",
                vec!["user-1".into()],
            ));

        let clauses = OpenSearchFilterBuilder::build(&filter);

        // 2 must clauses + 1 should wrapper + 1 must_not wrapper = 4
        assert_eq!(clauses.len(), 4);

        // First two are must clauses (term)
        assert!(clauses[0].get("term").is_some());
        assert!(clauses[1].get("term").is_some());

        // Third is should wrapper
        assert!(clauses[2].get("bool").is_some());
        let should_bool = clauses[2].get("bool").unwrap();
        assert!(should_bool.get("should").is_some());
        assert!(should_bool.get("minimum_should_match").is_some());

        // Fourth is must_not wrapper
        assert!(clauses[3].get("bool").is_some());
        let must_not_bool = clauses[3].get("bool").unwrap();
        assert!(must_not_bool.get("must_not").is_some());
    }

    #[test]
    fn test_opensearch_builder_terms_for_any() {
        let filter = UnifiedFilter::new().must(FilterCondition::any_of(
            "allowed_groups",
            vec!["engineering".into(), "product".into()],
        ));

        let clauses = OpenSearchFilterBuilder::build(&filter);
        assert_eq!(clauses.len(), 1);

        assert_eq!(
            clauses[0],
            json!({
                "terms": {
                    "allowed_groups": ["engineering", "product"]
                }
            })
        );
    }
}
