//! OpenSearch client implementation.

use opensearch::{
    http::transport::{SingleNodeConnectionPool, TransportBuilder},
    indices::{IndicesCreateParts, IndicesDeleteParts, IndicesExistsParts},
    BulkOperation, BulkParts, DeleteByQueryParts, DeleteParts, GetParts, IndexParts, OpenSearch,
    SearchParts,
};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::time::Instant;
use url::Url;

use crate::{
    BM25Request, HighlightBuilder, QueryBuilder, Result, SearchConfig, SearchError, SearchHit,
    SearchResponse,
};

/// OpenSearch client for keyword search operations.
#[derive(Clone)]
pub struct SearchClient {
    client: OpenSearch,
    config: SearchConfig,
}

impl SearchClient {
    /// Create a new search client.
    ///
    /// # Errors
    ///
    /// Returns an error if the connection cannot be established.
    pub fn new(config: SearchConfig) -> Result<Self> {
        let url = Url::parse(&config.url)
            .map_err(|e| SearchError::Connection(format!("Invalid URL: {e}")))?;

        let pool = SingleNodeConnectionPool::new(url);
        let mut transport_builder = TransportBuilder::new(pool);

        // Set credentials if provided
        if let (Some(user), Some(pass)) = (&config.username, &config.password) {
            transport_builder = transport_builder.auth(opensearch::auth::Credentials::Basic(
                user.clone(),
                pass.clone(),
            ));
        }

        // Disable certificate verification only when explicitly requested
        if config.danger_accept_invalid_certs {
            transport_builder =
                transport_builder.cert_validation(opensearch::cert::CertificateValidation::None);
        }

        let transport = transport_builder
            .build()
            .map_err(|e| SearchError::Connection(format!("Transport error: {e}")))?;

        let client = OpenSearch::new(transport);

        Ok(Self { client, config })
    }

    /// Get the default index name.
    #[must_use]
    pub fn default_index(&self) -> &str {
        &self.config.default_index
    }

    /// Check if an index exists.
    ///
    /// # Errors
    ///
    /// Returns an error if the request fails.
    pub async fn index_exists(&self, index: &str) -> Result<bool> {
        let response = self
            .client
            .indices()
            .exists(IndicesExistsParts::Index(&[index]))
            .send()
            .await
            .map_err(|e| SearchError::Query(format!("Index exists check failed: {e}")))?;

        Ok(response.status_code().is_success())
    }

    /// Create an index with the given settings and mappings.
    ///
    /// # Errors
    ///
    /// Returns an error if index creation fails.
    pub async fn create_index(&self, index: &str, body: Value) -> Result<()> {
        let response = self
            .client
            .indices()
            .create(IndicesCreateParts::Index(index))
            .body(body)
            .send()
            .await
            .map_err(|e| SearchError::Index(format!("Index creation failed: {e}")))?;

        if !response.status_code().is_success() {
            let body = response
                .text()
                .await
                .unwrap_or_else(|_| "Unknown error".to_string());
            return Err(SearchError::Index(format!("Index creation failed: {body}")));
        }

        Ok(())
    }

    /// Create the default documents index with standard mappings.
    ///
    /// # Errors
    ///
    /// Returns an error if index creation fails.
    pub async fn create_documents_index(&self, index: &str) -> Result<()> {
        let body = json!({
            "settings": {
                "number_of_shards": self.config.number_of_shards,
                "number_of_replicas": self.config.number_of_replicas,
                "analysis": {
                    "analyzer": {
                        "default": {
                            "type": "standard",
                            "stopwords": "_english_"
                        }
                    }
                }
            },
            "mappings": {
                "properties": {
                    "chunk_id": { "type": "keyword" },
                    "document_id": { "type": "keyword" },
                    "tenant_id": { "type": "keyword" },
                    "content": {
                        "type": "text",
                        "analyzer": "default"
                    },
                    "title": {
                        "type": "text",
                        "analyzer": "default"
                    },
                    "source_uri": { "type": "keyword" },
                    "source_type": { "type": "keyword" },
                    "allowed_groups": { "type": "keyword" },
                    "visibility": { "type": "keyword" },
                    "chunk_index": { "type": "integer" },
                    "created_at": { "type": "date" },
                    "updated_at": { "type": "date" }
                }
            }
        });

        self.create_index(index, body).await
    }

    /// Delete an index.
    ///
    /// # Errors
    ///
    /// Returns an error if deletion fails.
    pub async fn delete_index(&self, index: &str) -> Result<()> {
        let response = self
            .client
            .indices()
            .delete(IndicesDeleteParts::Index(&[index]))
            .send()
            .await
            .map_err(|e| SearchError::Index(format!("Index deletion failed: {e}")))?;

        if !response.status_code().is_success() {
            let body = response
                .text()
                .await
                .unwrap_or_else(|_| "Unknown error".to_string());
            return Err(SearchError::Index(format!("Index deletion failed: {body}")));
        }

        Ok(())
    }

    /// Index a document.
    ///
    /// # Errors
    ///
    /// Returns an error if indexing fails.
    pub async fn index_document(&self, index: &str, id: &str, document: Value) -> Result<()> {
        let response = self
            .client
            .index(IndexParts::IndexId(index, id))
            .body(document)
            .send()
            .await
            .map_err(|e| SearchError::Index(format!("Document indexing failed: {e}")))?;

        if !response.status_code().is_success() {
            let body = response
                .text()
                .await
                .unwrap_or_else(|_| "Unknown error".to_string());
            return Err(SearchError::Index(format!(
                "Document indexing failed: {body}"
            )));
        }

        Ok(())
    }

    /// Bulk index documents using the OpenSearch `_bulk` API.
    ///
    /// Sends all documents in a single bulk request instead of individual
    /// index calls, significantly reducing network overhead and latency.
    ///
    /// # Errors
    ///
    /// Returns an error if the bulk request fails or if any individual
    /// document within the bulk response reports an error.
    pub async fn bulk_index(&self, index: &str, documents: Vec<(String, Value)>) -> Result<usize> {
        if documents.is_empty() {
            return Ok(0);
        }

        let count = documents.len();

        // Build bulk operations using the opensearch crate's native BulkOperation API
        let mut ops: Vec<BulkOperation<Value>> = Vec::with_capacity(count);
        for (id, doc) in documents {
            ops.push(BulkOperation::index(doc).id(&id).into());
        }

        // Send a single bulk request for all documents
        let response = self
            .client
            .bulk(BulkParts::Index(index))
            .body(ops)
            .send()
            .await
            .map_err(|e| SearchError::Index(format!("Bulk indexing failed: {e}")))?;

        if !response.status_code().is_success() {
            let body = response
                .text()
                .await
                .unwrap_or_else(|_| "Unknown error".to_string());
            return Err(SearchError::Index(format!("Bulk indexing failed: {body}")));
        }

        // Parse the bulk response and check for per-item errors
        let body: Value = response
            .json()
            .await
            .map_err(|e| SearchError::Serialization(e.to_string()))?;

        if body["errors"].as_bool().unwrap_or(false) {
            let mut error_details: Vec<String> = Vec::new();
            if let Some(items) = body["items"].as_array() {
                for item in items {
                    if let Some(action) = item.get("index").or_else(|| item.get("create")) {
                        if let Some(error) = action.get("error") {
                            let reason = error["reason"].as_str().unwrap_or("unknown reason");
                            let doc_id = action["_id"].as_str().unwrap_or("unknown");
                            error_details.push(format!("doc {doc_id}: {reason}"));
                        }
                    }
                }
            }
            return Err(SearchError::Index(format!(
                "Bulk indexing had {} error(s): {}",
                error_details.len(),
                error_details.join("; ")
            )));
        }

        Ok(count)
    }

    /// Get a document by ID.
    ///
    /// # Errors
    ///
    /// Returns an error if the request fails.
    pub async fn get_document(&self, index: &str, id: &str) -> Result<Option<Value>> {
        let response = self
            .client
            .get(GetParts::IndexId(index, id))
            .send()
            .await
            .map_err(|e| SearchError::Query(format!("Get document failed: {e}")))?;

        if response.status_code().as_u16() == 404 {
            return Ok(None);
        }

        if !response.status_code().is_success() {
            let body = response
                .text()
                .await
                .unwrap_or_else(|_| "Unknown error".to_string());
            return Err(SearchError::Query(format!("Get document failed: {body}")));
        }

        let body: Value = response
            .json()
            .await
            .map_err(|e| SearchError::Serialization(e.to_string()))?;

        Ok(body.get("_source").cloned())
    }

    /// Delete a document by ID.
    ///
    /// # Errors
    ///
    /// Returns an error if deletion fails.
    pub async fn delete_document(&self, index: &str, id: &str) -> Result<bool> {
        let response = self
            .client
            .delete(DeleteParts::IndexId(index, id))
            .send()
            .await
            .map_err(|e| SearchError::Index(format!("Document deletion failed: {e}")))?;

        if response.status_code().as_u16() == 404 {
            return Ok(false);
        }

        if !response.status_code().is_success() {
            let body = response
                .text()
                .await
                .unwrap_or_else(|_| "Unknown error".to_string());
            return Err(SearchError::Index(format!(
                "Document deletion failed: {body}"
            )));
        }

        Ok(true)
    }

    /// Delete documents by query.
    ///
    /// # Errors
    ///
    /// Returns an error if deletion fails.
    pub async fn delete_by_query(&self, index: &str, query: Value) -> Result<u64> {
        let response = self
            .client
            .delete_by_query(DeleteByQueryParts::Index(&[index]))
            .body(json!({ "query": query }))
            .send()
            .await
            .map_err(|e| SearchError::Index(format!("Delete by query failed: {e}")))?;

        if !response.status_code().is_success() {
            let body = response
                .text()
                .await
                .unwrap_or_else(|_| "Unknown error".to_string());
            return Err(SearchError::Index(format!(
                "Delete by query failed: {body}"
            )));
        }

        let body: Value = response
            .json()
            .await
            .map_err(|e| SearchError::Serialization(e.to_string()))?;

        Ok(body["deleted"].as_u64().unwrap_or(0))
    }

    /// Perform a BM25 search.
    ///
    /// # Errors
    ///
    /// Returns an error if the search fails.
    pub async fn search(&self, index: &str, request: &BM25Request) -> Result<SearchResponse> {
        let start = Instant::now();

        // Build the query
        let query = QueryBuilder::new()
            .multi_match(&request.query, &request.fields)
            .with_filters(&request.filters)
            .build();

        // Build the search body
        let mut body = json!({
            "query": query,
            "from": request.offset,
            "size": request.limit,
            "track_total_hits": true
        });

        // Add highlighting if requested
        if request.highlight {
            let highlight_fields = if request.highlight_fields.is_empty() {
                request.fields.clone()
            } else {
                request.highlight_fields.clone()
            };

            let highlight = HighlightBuilder::new()
                .fields(highlight_fields)
                .fragment_size(150)
                .number_of_fragments(3)
                .build();

            body["highlight"] = highlight;
        }

        // Execute search
        let response = self
            .client
            .search(SearchParts::Index(&[index]))
            .body(body)
            .send()
            .await
            .map_err(|e| SearchError::Query(format!("Search failed: {e}")))?;

        if !response.status_code().is_success() {
            let body = response
                .text()
                .await
                .unwrap_or_else(|_| "Unknown error".to_string());
            return Err(SearchError::Query(format!("Search failed: {body}")));
        }

        let body: Value = response
            .json()
            .await
            .map_err(|e| SearchError::Serialization(e.to_string()))?;

        // Parse response
        let took_ms = start.elapsed().as_millis() as u64;
        let total = body["hits"]["total"]["value"].as_u64().unwrap_or(0);

        let hits: Vec<SearchHit> = body["hits"]["hits"]
            .as_array()
            .map(|arr| {
                arr.iter()
                    .map(|hit| {
                        let id = hit["_id"].as_str().unwrap_or("").to_string();
                        let score = hit["_score"].as_f64().unwrap_or(0.0);
                        let source = hit["_source"].clone();

                        let mut search_hit = SearchHit::new(&id, index, score, source);

                        // Parse highlights
                        if let Some(highlights) = hit.get("highlight") {
                            if let Some(obj) = highlights.as_object() {
                                let mut highlight_map: HashMap<String, Vec<String>> =
                                    HashMap::new();
                                for (field, fragments) in obj {
                                    if let Some(arr) = fragments.as_array() {
                                        let frags: Vec<String> = arr
                                            .iter()
                                            .filter_map(|v| v.as_str().map(String::from))
                                            .collect();
                                        highlight_map.insert(field.clone(), frags);
                                    }
                                }
                                search_hit = search_hit.with_highlights(highlight_map);
                            }
                        }

                        search_hit
                    })
                    .collect()
            })
            .unwrap_or_default();

        Ok(SearchResponse::new(hits, total, took_ms))
    }

    /// Check if OpenSearch is healthy and reachable.
    ///
    /// # Errors
    ///
    /// Returns an error if the health check fails.
    pub async fn health_check(&self) -> Result<()> {
        // Use cluster health endpoint to verify connectivity
        let response = self
            .client
            .cluster()
            .health(opensearch::cluster::ClusterHealthParts::None)
            .send()
            .await
            .map_err(|e| SearchError::Connection(format!("Health check failed: {e}")))?;

        if !response.status_code().is_success() {
            let body = response
                .text()
                .await
                .unwrap_or_else(|_| "Unknown error".to_string());
            return Err(SearchError::Connection(format!(
                "Health check failed: {body}"
            )));
        }

        Ok(())
    }

    /// Search using a raw query body.
    ///
    /// # Errors
    ///
    /// Returns an error if the search fails.
    pub async fn search_raw(&self, index: &str, body: Value) -> Result<Value> {
        let response = self
            .client
            .search(SearchParts::Index(&[index]))
            .body(body)
            .send()
            .await
            .map_err(|e| SearchError::Query(format!("Search failed: {e}")))?;

        if !response.status_code().is_success() {
            let body = response
                .text()
                .await
                .unwrap_or_else(|_| "Unknown error".to_string());
            return Err(SearchError::Query(format!("Search failed: {body}")));
        }

        response
            .json()
            .await
            .map_err(|e| SearchError::Serialization(e.to_string()))
    }
}

impl std::fmt::Debug for SearchClient {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("SearchClient")
            .field("url", &self.config.url)
            .field("default_index", &self.config.default_index)
            .finish_non_exhaustive()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_search_config_default() {
        let config = SearchConfig::default();
        assert_eq!(config.url, "http://localhost:9200");
        assert_eq!(config.default_index, "documents");
    }

    #[test]
    fn test_bm25_request() {
        let request = BM25Request::new("test query")
            .with_fields(vec!["title".into(), "content".into()])
            .with_limit(20)
            .with_tenant("t-123")
            .with_highlight();

        assert_eq!(request.query, "test query");
        assert_eq!(request.limit, 20);
        assert!(request.highlight);
        assert!(request.filters.contains_key("tenant_id.keyword"));
    }
}
