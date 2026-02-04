//! Filter building utilities for Qdrant queries.

use qdrant_client::qdrant::{Condition, Filter};
use qdrant_client::qdrant::condition::ConditionOneOf;
use qdrant_client::qdrant::r#match::MatchValue;
use qdrant_client::qdrant::{FieldCondition, Match, Range, RepeatedStrings};

/// Builder for Qdrant filter conditions.
#[derive(Debug, Clone, Default)]
pub struct FilterBuilder {
    must: Vec<Condition>,
    should: Vec<Condition>,
    must_not: Vec<Condition>,
}

impl FilterBuilder {
    /// Create a new filter builder.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Add a must condition (AND).
    #[must_use]
    pub fn must(mut self, condition: Condition) -> Self {
        self.must.push(condition);
        self
    }

    /// Add a should condition (OR).
    #[must_use]
    pub fn should(mut self, condition: Condition) -> Self {
        self.should.push(condition);
        self
    }

    /// Add a must_not condition (NOT).
    #[must_use]
    pub fn must_not(mut self, condition: Condition) -> Self {
        self.must_not.push(condition);
        self
    }

    /// Create a field condition for string match.
    fn field_match_string(field: impl Into<String>, value: impl Into<String>) -> Condition {
        Condition {
            condition_one_of: Some(ConditionOneOf::Field(FieldCondition {
                key: field.into(),
                r#match: Some(Match {
                    match_value: Some(MatchValue::Keyword(value.into())),
                }),
                ..Default::default()
            })),
        }
    }

    /// Add a string match condition.
    #[must_use]
    pub fn match_string(self, field: impl Into<String>, value: impl Into<String>) -> Self {
        let condition = Self::field_match_string(field, value);
        self.must(condition)
    }

    /// Add a tenant filter.
    #[must_use]
    pub fn tenant(self, tenant_id: impl Into<String>) -> Self {
        self.match_string("tenant_id", tenant_id)
    }

    /// Add a document filter.
    #[must_use]
    pub fn document(self, document_id: impl Into<String>) -> Self {
        self.match_string("document_id", document_id)
    }

    /// Add an integer match condition.
    #[must_use]
    pub fn match_int(self, field: impl Into<String>, value: i64) -> Self {
        let condition = Condition {
            condition_one_of: Some(ConditionOneOf::Field(FieldCondition {
                key: field.into(),
                r#match: Some(Match {
                    match_value: Some(MatchValue::Integer(value)),
                }),
                ..Default::default()
            })),
        };
        self.must(condition)
    }

    /// Add a range condition.
    #[must_use]
    pub fn range(
        self,
        field: impl Into<String>,
        gte: Option<f64>,
        lte: Option<f64>,
    ) -> Self {
        let condition = Condition {
            condition_one_of: Some(ConditionOneOf::Field(FieldCondition {
                key: field.into(),
                range: Some(Range {
                    gte,
                    lte,
                    gt: None,
                    lt: None,
                }),
                ..Default::default()
            })),
        };
        self.must(condition)
    }

    /// Add an "any of" condition (value in list).
    #[must_use]
    pub fn any_of_strings(self, field: impl Into<String>, values: Vec<String>) -> Self {
        if values.is_empty() {
            return self;
        }

        let condition = Condition {
            condition_one_of: Some(ConditionOneOf::Field(FieldCondition {
                key: field.into(),
                r#match: Some(Match {
                    match_value: Some(MatchValue::Keywords(RepeatedStrings { strings: values })),
                }),
                ..Default::default()
            })),
        };
        self.must(condition)
    }

    /// Exclude a specific value.
    #[must_use]
    pub fn exclude_string(self, field: impl Into<String>, value: impl Into<String>) -> Self {
        let condition = Self::field_match_string(field, value);
        self.must_not(condition)
    }

    /// Build the filter.
    #[must_use]
    pub fn build(self) -> Filter {
        Filter {
            must: self.must,
            should: self.should,
            must_not: self.must_not,
        }
    }

    /// Check if the filter is empty.
    #[must_use]
    pub fn is_empty(&self) -> bool {
        self.must.is_empty() && self.should.is_empty() && self.must_not.is_empty()
    }
}

/// Create a filter for multi-tenant ACL checks.
///
/// This creates a filter that matches documents where:
/// - `tenant_id` matches the specified tenant AND
/// - `visibility` is "public" OR `allowed_groups` contains any of the user's groups
#[must_use]
#[allow(dead_code)] // Used by consuming crates
pub fn acl_filter(
    tenant_id: impl Into<String>,
    user_groups: &[String],
    include_public: bool,
) -> Filter {
    let mut builder = FilterBuilder::new().tenant(tenant_id);

    if include_public && !user_groups.is_empty() {
        // Visibility is public OR user is in allowed_groups
        let public_condition = FilterBuilder::field_match_string("visibility", "public");

        let groups_condition = Condition {
            condition_one_of: Some(ConditionOneOf::Field(FieldCondition {
                key: "allowed_groups".into(),
                r#match: Some(Match {
                    match_value: Some(MatchValue::Keywords(RepeatedStrings {
                        strings: user_groups.to_vec(),
                    })),
                }),
                ..Default::default()
            })),
        };

        let visibility_filter = Condition {
            condition_one_of: Some(ConditionOneOf::Filter(Filter {
                should: vec![public_condition, groups_condition],
                ..Default::default()
            })),
        };

        builder = builder.must(visibility_filter);
    } else if include_public {
        builder = builder.match_string("visibility", "public");
    } else if !user_groups.is_empty() {
        builder = builder.any_of_strings("allowed_groups", user_groups.to_vec());
    }

    builder.build()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_filter_builder() {
        let filter = FilterBuilder::new()
            .tenant("tenant-123")
            .match_string("source_type", "pdf")
            .build();

        assert_eq!(filter.must.len(), 2);
    }

    #[test]
    fn test_empty_filter() {
        let builder = FilterBuilder::new();
        assert!(builder.is_empty());
    }

    #[test]
    fn test_acl_filter() {
        let filter = acl_filter(
            "tenant-123",
            &["engineering".into(), "product".into()],
            true,
        );

        // Should have tenant filter and visibility/groups filter
        assert_eq!(filter.must.len(), 2);
    }
}
