//! Query builder for OpenSearch.

use serde_json::{json, Value};
use std::collections::HashMap;

/// Builder for constructing OpenSearch queries.
#[derive(Debug, Clone, Default)]
pub struct QueryBuilder {
    must: Vec<Value>,
    filter: Vec<Value>,
    should: Vec<Value>,
    must_not: Vec<Value>,
    minimum_should_match: Option<i32>,
}

impl QueryBuilder {
    /// Create a new query builder.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Add a multi-match query (searches across multiple fields).
    #[must_use]
    pub fn multi_match(mut self, query: &str, fields: &[String]) -> Self {
        self.must.push(json!({
            "multi_match": {
                "query": query,
                "fields": fields,
                "type": "best_fields",
                "operator": "or"
            }
        }));
        self
    }

    /// Add a match query for a specific field.
    #[must_use]
    pub fn match_query(mut self, field: &str, query: &str) -> Self {
        self.must.push(json!({
            "match": {
                field: {
                    "query": query
                }
            }
        }));
        self
    }

    /// Add a match phrase query.
    #[must_use]
    pub fn match_phrase(mut self, field: &str, phrase: &str) -> Self {
        self.must.push(json!({
            "match_phrase": {
                field: phrase
            }
        }));
        self
    }

    /// Add a term filter (exact match).
    #[must_use]
    pub fn term_filter(mut self, field: &str, value: impl Into<Value>) -> Self {
        self.filter.push(json!({
            "term": {
                field: value.into()
            }
        }));
        self
    }

    /// Add a terms filter (match any of the values).
    #[must_use]
    pub fn terms_filter(mut self, field: &str, values: Vec<Value>) -> Self {
        self.filter.push(json!({
            "terms": {
                field: values
            }
        }));
        self
    }

    /// Add a range filter.
    #[must_use]
    pub fn range_filter(
        mut self,
        field: &str,
        gte: Option<Value>,
        lte: Option<Value>,
        gt: Option<Value>,
        lt: Option<Value>,
    ) -> Self {
        let mut range = serde_json::Map::new();
        if let Some(v) = gte {
            range.insert("gte".to_string(), v);
        }
        if let Some(v) = lte {
            range.insert("lte".to_string(), v);
        }
        if let Some(v) = gt {
            range.insert("gt".to_string(), v);
        }
        if let Some(v) = lt {
            range.insert("lt".to_string(), v);
        }

        self.filter.push(json!({
            "range": {
                field: range
            }
        }));
        self
    }

    /// Add an exists filter (field must exist).
    #[must_use]
    pub fn exists_filter(mut self, field: &str) -> Self {
        self.filter.push(json!({
            "exists": {
                "field": field
            }
        }));
        self
    }

    /// Add a should clause (optional match, boosts score).
    #[must_use]
    pub fn should_match(mut self, field: &str, query: &str) -> Self {
        self.should.push(json!({
            "match": {
                field: {
                    "query": query
                }
            }
        }));
        self
    }

    /// Add a must_not clause (documents must NOT match).
    #[must_use]
    pub fn must_not_term(mut self, field: &str, value: impl Into<Value>) -> Self {
        self.must_not.push(json!({
            "term": {
                field: value.into()
            }
        }));
        self
    }

    /// Set minimum should match.
    #[must_use]
    pub const fn minimum_should_match(mut self, count: i32) -> Self {
        self.minimum_should_match = Some(count);
        self
    }

    /// Add filters from a HashMap.
    #[must_use]
    pub fn with_filters(mut self, filters: &HashMap<String, Value>) -> Self {
        for (field, value) in filters {
            self.filter.push(json!({
                "term": {
                    field: value
                }
            }));
        }
        self
    }

    /// Add tenant filter.
    /// Uses `.keyword` subfield for exact matching on dynamically-mapped text fields.
    #[must_use]
    pub fn with_tenant(self, tenant_id: &str) -> Self {
        self.term_filter("tenant_id.keyword", tenant_id)
    }

    /// Add ACL filter for allowed groups.
    /// Uses `.keyword` subfield for exact matching on dynamically-mapped text fields.
    #[must_use]
    pub fn with_acl(self, groups: Vec<String>) -> Self {
        if groups.is_empty() {
            self
        } else {
            let values: Vec<Value> = groups.into_iter().map(Value::String).collect();
            self.terms_filter("allowed_groups.keyword", values)
        }
    }

    /// Build the query as JSON.
    #[must_use]
    pub fn build(self) -> Value {
        let mut bool_query = serde_json::Map::new();

        if !self.must.is_empty() {
            bool_query.insert("must".to_string(), Value::Array(self.must));
        }

        if !self.filter.is_empty() {
            bool_query.insert("filter".to_string(), Value::Array(self.filter));
        }

        if !self.should.is_empty() {
            bool_query.insert("should".to_string(), Value::Array(self.should));
        }

        if !self.must_not.is_empty() {
            bool_query.insert("must_not".to_string(), Value::Array(self.must_not));
        }

        if let Some(min) = self.minimum_should_match {
            bool_query.insert("minimum_should_match".to_string(), json!(min));
        }

        // If no clauses, return match_all
        if bool_query.is_empty() {
            json!({
                "match_all": {}
            })
        } else {
            json!({
                "bool": bool_query
            })
        }
    }
}

/// Builder for highlight configuration.
#[derive(Debug, Clone, Default)]
pub struct HighlightBuilder {
    fields: Vec<String>,
    pre_tag: String,
    post_tag: String,
    fragment_size: Option<usize>,
    number_of_fragments: Option<usize>,
}

impl HighlightBuilder {
    /// Create a new highlight builder.
    #[must_use]
    pub fn new() -> Self {
        Self {
            pre_tag: "<em>".to_string(),
            post_tag: "</em>".to_string(),
            ..Default::default()
        }
    }

    /// Add a field to highlight.
    #[must_use]
    pub fn field(mut self, field: impl Into<String>) -> Self {
        self.fields.push(field.into());
        self
    }

    /// Add multiple fields to highlight.
    #[must_use]
    pub fn fields(mut self, fields: Vec<String>) -> Self {
        self.fields.extend(fields);
        self
    }

    /// Set custom highlight tags.
    #[must_use]
    pub fn tags(mut self, pre: impl Into<String>, post: impl Into<String>) -> Self {
        self.pre_tag = pre.into();
        self.post_tag = post.into();
        self
    }

    /// Set fragment size.
    #[must_use]
    pub const fn fragment_size(mut self, size: usize) -> Self {
        self.fragment_size = Some(size);
        self
    }

    /// Set number of fragments.
    #[must_use]
    pub const fn number_of_fragments(mut self, count: usize) -> Self {
        self.number_of_fragments = Some(count);
        self
    }

    /// Build the highlight configuration.
    #[must_use]
    pub fn build(self) -> Value {
        let mut fields_config = serde_json::Map::new();
        for field in &self.fields {
            fields_config.insert(field.clone(), json!({}));
        }

        let mut highlight = json!({
            "pre_tags": [self.pre_tag],
            "post_tags": [self.post_tag],
            "fields": fields_config
        });

        if let Some(size) = self.fragment_size {
            highlight["fragment_size"] = json!(size);
        }

        if let Some(count) = self.number_of_fragments {
            highlight["number_of_fragments"] = json!(count);
        }

        highlight
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_query_builder_empty() {
        let query = QueryBuilder::new().build();
        assert_eq!(query, json!({"match_all": {}}));
    }

    #[test]
    fn test_query_builder_multi_match() {
        let query = QueryBuilder::new()
            .multi_match("search term", &["title".into(), "content".into()])
            .build();

        assert!(query["bool"]["must"][0]["multi_match"].is_object());
    }

    #[test]
    fn test_query_builder_with_filters() {
        let query = QueryBuilder::new()
            .multi_match("test", &["content".into()])
            .with_tenant("t-123")
            .build();

        assert!(query["bool"]["filter"].is_array());
    }

    #[test]
    fn test_highlight_builder() {
        let highlight = HighlightBuilder::new()
            .field("content")
            .field("title")
            .fragment_size(150)
            .build();

        assert_eq!(highlight["pre_tags"][0], "<em>");
        assert!(highlight["fields"]["content"].is_object());
        assert!(highlight["fields"]["title"].is_object());
    }
}
