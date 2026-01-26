//! Qdrant vector store client.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Instant;

use qdrant_client::prelude::*;
use qdrant_client::qdrant::{
    CreateCollection, Distance, PointId, PointStruct, SearchPoints,
    VectorParams, VectorsConfig, WithPayloadSelector, WithVectorsSelector,
    vectors_config::Config as VectorsConfigEnum,
    with_payload_selector::SelectorOptions,
    point_id::PointIdOptions,
};
use serde_json::Value;
use tracing::instrument;

use crate::{Result, SearchRequest, SearchResult, ScoredPoint, VectorStoreConfig, VectorStoreError};

/// Qdrant vector store client.
#[derive(Clone)]
pub struct VectorStoreClient {
    client: Arc<QdrantClient>,
    config: VectorStoreConfig,
}

impl VectorStoreClient {
    /// Connect to Qdrant.
    ///
    /// # Errors
    ///
    /// Returns an error if connection fails.
    pub async fn connect(config: &VectorStoreConfig) -> Result<Self> {
        let mut client_config = QdrantClientConfig::from_url(&config.url);

        if let Some(api_key) = &config.api_key {
            client_config = client_config.with_api_key(api_key.clone());
        }

        client_config.timeout = config.timeout;
        client_config.connect_timeout = config.connect_timeout;

        let client = QdrantClient::new(Some(client_config))
            .map_err(|e| VectorStoreError::Connection(e.to_string()))?;

        Ok(Self {
            client: Arc::new(client),
            config: config.clone(),
        })
    }

    /// Get the default collection or return an error if not set.
    fn default_collection(&self) -> Result<&str> {
        self.config
            .default_collection
            .as_deref()
            .ok_or_else(|| VectorStoreError::Config("No default collection configured".into()))
    }

    /// Create a collection with cosine similarity.
    ///
    /// # Errors
    ///
    /// Returns an error if collection creation fails.
    #[instrument(skip(self))]
    pub async fn create_collection(&self, name: &str, vector_size: u64) -> Result<()> {
        self.client
            .create_collection(&CreateCollection {
                collection_name: name.into(),
                vectors_config: Some(VectorsConfig {
                    config: Some(VectorsConfigEnum::Params(VectorParams {
                        size: vector_size,
                        distance: Distance::Cosine.into(),
                        hnsw_config: Some(qdrant_client::qdrant::HnswConfigDiff {
                            m: Some(self.config.hnsw_config.m),
                            ef_construct: Some(self.config.hnsw_config.ef_construct),
                            ..Default::default()
                        }),
                        ..Default::default()
                    })),
                }),
                ..Default::default()
            })
            .await
            .map_err(|e| VectorStoreError::Qdrant(e.to_string()))?;

        tracing::info!(collection = name, vector_size, "Created collection");
        Ok(())
    }

    /// Delete a collection.
    ///
    /// # Errors
    ///
    /// Returns an error if deletion fails.
    #[instrument(skip(self))]
    pub async fn delete_collection(&self, name: &str) -> Result<()> {
        self.client
            .delete_collection(name)
            .await
            .map_err(|e| VectorStoreError::Qdrant(e.to_string()))?;
        tracing::info!(collection = name, "Deleted collection");
        Ok(())
    }

    /// Check if a collection exists.
    ///
    /// # Errors
    ///
    /// Returns an error if the check fails (other than collection not found).
    #[instrument(skip(self))]
    pub async fn collection_exists(&self, name: &str) -> Result<bool> {
        // In qdrant-client 1.7.0, we use collection_info and check for errors
        match self.client.collection_info(name).await {
            Ok(_) => Ok(true),
            Err(e) => {
                // Check if the error indicates collection not found
                let err_str = e.to_string().to_lowercase();
                if err_str.contains("not found") || err_str.contains("doesn't exist") {
                    Ok(false)
                } else {
                    Err(VectorStoreError::Qdrant(e.to_string()))
                }
            }
        }
    }

    /// Get collection info.
    ///
    /// # Errors
    ///
    /// Returns an error if the collection doesn't exist.
    #[instrument(skip(self))]
    pub async fn collection_info(&self, name: &str) -> Result<CollectionInfo> {
        let info = self
            .client
            .collection_info(name)
            .await
            .map_err(|_| VectorStoreError::CollectionNotFound(name.into()))?;

        let result = info.result.ok_or_else(|| {
            VectorStoreError::CollectionNotFound(name.into())
        })?;

        Ok(CollectionInfo {
            name: name.into(),
            points_count: result.points_count.unwrap_or(0),
            vectors_count: result.points_count.unwrap_or(0), // Use points_count as fallback
        })
    }

    /// Upsert points into a collection.
    ///
    /// # Errors
    ///
    /// Returns an error if upsert fails.
    #[instrument(skip(self, vectors, payloads), fields(count = ids.len()))]
    pub async fn upsert(
        &self,
        collection: Option<&str>,
        ids: Vec<String>,
        vectors: Vec<Vec<f32>>,
        payloads: Vec<Value>,
    ) -> Result<()> {
        let collection = collection
            .map(Ok)
            .unwrap_or_else(|| self.default_collection())?;

        if ids.len() != vectors.len() || ids.len() != payloads.len() {
            return Err(VectorStoreError::Config(
                "ids, vectors, and payloads must have the same length".into(),
            ));
        }

        let points: Vec<PointStruct> = ids
            .into_iter()
            .zip(vectors)
            .zip(payloads)
            .map(|((id, vector), payload)| {
                let payload_map = payload_to_qdrant(&payload);
                PointStruct {
                    id: Some(PointId {
                        point_id_options: Some(PointIdOptions::Uuid(id)),
                    }),
                    vectors: Some(vector.into()),
                    payload: payload_map,
                }
            })
            .collect();

        let count = points.len();

        self.client
            .upsert_points_blocking(collection, None, points, None)
            .await
            .map_err(|e| VectorStoreError::Qdrant(e.to_string()))?;

        tracing::debug!(collection, count, "Upserted points");
        Ok(())
    }

    /// Search for similar vectors.
    ///
    /// # Errors
    ///
    /// Returns an error if search fails.
    #[instrument(skip(self, request), fields(limit = request.limit))]
    pub async fn search(
        &self,
        collection: Option<&str>,
        request: SearchRequest,
    ) -> Result<SearchResult> {
        let collection = collection
            .map(Ok)
            .unwrap_or_else(|| self.default_collection())?;

        let start = Instant::now();

        let with_payload = if request.with_payload {
            Some(WithPayloadSelector {
                selector_options: Some(SelectorOptions::Enable(true)),
            })
        } else {
            Some(WithPayloadSelector {
                selector_options: Some(SelectorOptions::Enable(false)),
            })
        };

        let with_vectors = if request.with_vector {
            Some(WithVectorsSelector {
                selector_options: Some(
                    qdrant_client::qdrant::with_vectors_selector::SelectorOptions::Enable(true),
                ),
            })
        } else {
            None
        };

        let search_points = SearchPoints {
            collection_name: collection.into(),
            vector: request.vector,
            limit: request.limit,
            filter: request.filter,
            with_payload,
            with_vectors,
            score_threshold: request.score_threshold,
            params: request.params.map(|p| qdrant_client::qdrant::SearchParams {
                hnsw_ef: p.ef.map(|ef| ef as u64),
                exact: Some(p.exact),
                ..Default::default()
            }),
            ..Default::default()
        };

        let response = self.client.search_points(&search_points)
            .await
            .map_err(|e| VectorStoreError::Qdrant(e.to_string()))?;

        let points: Vec<ScoredPoint> = response
            .result
            .into_iter()
            .map(|p| {
                let id = match p.id.and_then(|id| id.point_id_options) {
                    Some(PointIdOptions::Uuid(uuid)) => uuid,
                    Some(PointIdOptions::Num(num)) => num.to_string(),
                    None => String::new(),
                };

                let payload = qdrant_to_payload(&p.payload);
                let vector = p.vectors.and_then(|v| {
                    match v.vectors_options {
                        Some(qdrant_client::qdrant::vectors::VectorsOptions::Vector(vec)) => {
                            Some(vec.data)
                        }
                        _ => None,
                    }
                });

                ScoredPoint {
                    id,
                    score: p.score,
                    payload,
                    vector,
                }
            })
            .collect();

        let duration_ms = start.elapsed().as_millis() as u64;

        tracing::debug!(
            collection,
            results = points.len(),
            duration_ms,
            "Search completed"
        );

        Ok(SearchResult {
            points,
            duration_ms: Some(duration_ms),
        })
    }

    /// Delete points by IDs.
    ///
    /// # Errors
    ///
    /// Returns an error if deletion fails.
    #[instrument(skip(self), fields(count = ids.len()))]
    pub async fn delete_points(&self, collection: Option<&str>, ids: Vec<String>) -> Result<()> {
        let collection = collection
            .map(Ok)
            .unwrap_or_else(|| self.default_collection())?;

        let point_ids: Vec<PointId> = ids
            .into_iter()
            .map(|id| PointId {
                point_id_options: Some(PointIdOptions::Uuid(id)),
            })
            .collect();

        self.client
            .delete_points_blocking(
                collection,
                None,
                &qdrant_client::qdrant::PointsSelector {
                    points_selector_one_of: Some(
                        qdrant_client::qdrant::points_selector::PointsSelectorOneOf::Points(
                            qdrant_client::qdrant::PointsIdsList { ids: point_ids },
                        ),
                    ),
                },
                None,
            )
            .await
            .map_err(|e| VectorStoreError::Qdrant(e.to_string()))?;

        tracing::debug!(collection, "Deleted points");
        Ok(())
    }

    /// Delete points by filter.
    ///
    /// # Errors
    ///
    /// Returns an error if deletion fails.
    #[instrument(skip(self, filter))]
    pub async fn delete_by_filter(
        &self,
        collection: Option<&str>,
        filter: qdrant_client::qdrant::Filter,
    ) -> Result<()> {
        let collection = collection
            .map(Ok)
            .unwrap_or_else(|| self.default_collection())?;

        self.client
            .delete_points_blocking(
                collection,
                None,
                &qdrant_client::qdrant::PointsSelector {
                    points_selector_one_of: Some(
                        qdrant_client::qdrant::points_selector::PointsSelectorOneOf::Filter(filter),
                    ),
                },
                None,
            )
            .await
            .map_err(|e| VectorStoreError::Qdrant(e.to_string()))?;

        tracing::debug!(collection, "Deleted points by filter");
        Ok(())
    }

    /// Get points by IDs.
    ///
    /// # Errors
    ///
    /// Returns an error if retrieval fails.
    #[instrument(skip(self), fields(count = ids.len()))]
    pub async fn get_points(
        &self,
        collection: Option<&str>,
        ids: Vec<String>,
    ) -> Result<Vec<ScoredPoint>> {
        let collection = collection
            .map(Ok)
            .unwrap_or_else(|| self.default_collection())?;

        let point_ids: Vec<PointId> = ids
            .into_iter()
            .map(|id| PointId {
                point_id_options: Some(PointIdOptions::Uuid(id)),
            })
            .collect();

        let response = self
            .client
            .get_points(
                collection,
                None,
                &point_ids,
                Some(true),
                Some(true),
                None,
            )
            .await
            .map_err(|e| VectorStoreError::Qdrant(e.to_string()))?;

        let points: Vec<ScoredPoint> = response
            .result
            .into_iter()
            .map(|p| {
                let id = match p.id.and_then(|id| id.point_id_options) {
                    Some(PointIdOptions::Uuid(uuid)) => uuid,
                    Some(PointIdOptions::Num(num)) => num.to_string(),
                    None => String::new(),
                };

                let payload = qdrant_to_payload(&p.payload);
                let vector = p.vectors.and_then(|v| {
                    match v.vectors_options {
                        Some(qdrant_client::qdrant::vectors::VectorsOptions::Vector(vec)) => {
                            Some(vec.data)
                        }
                        _ => None,
                    }
                });

                ScoredPoint {
                    id,
                    score: 1.0, // No score for direct retrieval
                    payload,
                    vector,
                }
            })
            .collect();

        Ok(points)
    }

    /// Health check.
    ///
    /// # Errors
    ///
    /// Returns an error if the service is unhealthy.
    pub async fn health_check(&self) -> Result<()> {
        self.client
            .health_check()
            .await
            .map_err(|e| VectorStoreError::Connection(e.to_string()))?;
        Ok(())
    }
}

/// Collection information.
#[derive(Debug, Clone)]
pub struct CollectionInfo {
    /// Collection name.
    pub name: String,
    /// Number of points.
    pub points_count: u64,
    /// Number of vectors.
    pub vectors_count: u64,
}

impl std::fmt::Debug for VectorStoreClient {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("VectorStoreClient")
            .field("url", &self.config.url)
            .field("default_collection", &self.config.default_collection)
            .finish_non_exhaustive()
    }
}

/// Convert JSON Value to Qdrant payload.
fn payload_to_qdrant(value: &Value) -> HashMap<String, qdrant_client::qdrant::Value> {
    let mut map = HashMap::new();

    if let Value::Object(obj) = value {
        for (k, v) in obj {
            if let Some(qdrant_value) = json_to_qdrant_value(v) {
                map.insert(k.clone(), qdrant_value);
            }
        }
    }

    map
}

/// Convert JSON value to Qdrant value.
fn json_to_qdrant_value(value: &Value) -> Option<qdrant_client::qdrant::Value> {
    use qdrant_client::qdrant::value::Kind;

    match value {
        Value::Null => Some(qdrant_client::qdrant::Value {
            kind: Some(Kind::NullValue(0)),
        }),
        Value::Bool(b) => Some(qdrant_client::qdrant::Value {
            kind: Some(Kind::BoolValue(*b)),
        }),
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                Some(qdrant_client::qdrant::Value {
                    kind: Some(Kind::IntegerValue(i)),
                })
            } else if let Some(f) = n.as_f64() {
                Some(qdrant_client::qdrant::Value {
                    kind: Some(Kind::DoubleValue(f)),
                })
            } else {
                None
            }
        }
        Value::String(s) => Some(qdrant_client::qdrant::Value {
            kind: Some(Kind::StringValue(s.clone())),
        }),
        Value::Array(arr) => {
            let values: Vec<qdrant_client::qdrant::Value> =
                arr.iter().filter_map(json_to_qdrant_value).collect();
            Some(qdrant_client::qdrant::Value {
                kind: Some(Kind::ListValue(qdrant_client::qdrant::ListValue { values })),
            })
        }
        Value::Object(obj) => {
            let fields: HashMap<String, qdrant_client::qdrant::Value> = obj
                .iter()
                .filter_map(|(k, v)| json_to_qdrant_value(v).map(|val| (k.clone(), val)))
                .collect();
            Some(qdrant_client::qdrant::Value {
                kind: Some(Kind::StructValue(qdrant_client::qdrant::Struct { fields })),
            })
        }
    }
}

/// Convert Qdrant payload to JSON.
fn qdrant_to_payload(
    payload: &HashMap<String, qdrant_client::qdrant::Value>,
) -> HashMap<String, Value> {
    payload
        .iter()
        .filter_map(|(k, v)| qdrant_value_to_json(v).map(|val| (k.clone(), val)))
        .collect()
}

/// Convert Qdrant value to JSON value.
fn qdrant_value_to_json(value: &qdrant_client::qdrant::Value) -> Option<Value> {
    use qdrant_client::qdrant::value::Kind;

    match &value.kind {
        Some(Kind::NullValue(_)) => Some(Value::Null),
        Some(Kind::BoolValue(b)) => Some(Value::Bool(*b)),
        Some(Kind::IntegerValue(i)) => Some(Value::Number((*i).into())),
        Some(Kind::DoubleValue(d)) => {
            serde_json::Number::from_f64(*d).map(Value::Number)
        }
        Some(Kind::StringValue(s)) => Some(Value::String(s.clone())),
        Some(Kind::ListValue(list)) => {
            let values: Vec<Value> = list
                .values
                .iter()
                .filter_map(qdrant_value_to_json)
                .collect();
            Some(Value::Array(values))
        }
        Some(Kind::StructValue(s)) => {
            let map: serde_json::Map<String, Value> = s
                .fields
                .iter()
                .filter_map(|(k, v)| qdrant_value_to_json(v).map(|val| (k.clone(), val)))
                .collect();
            Some(Value::Object(map))
        }
        None => None,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_payload_conversion() {
        let json = serde_json::json!({
            "tenant_id": "t-123",
            "score": 0.95,
            "tags": ["a", "b"],
            "metadata": {"key": "value"}
        });

        let qdrant = payload_to_qdrant(&json);
        let back = qdrant_to_payload(&qdrant);

        assert_eq!(back.get("tenant_id").and_then(Value::as_str), Some("t-123"));
        assert_eq!(back.get("score").and_then(Value::as_f64), Some(0.95));
    }
}
