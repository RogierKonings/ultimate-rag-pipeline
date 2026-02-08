//! Qdrant vector store client.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::Instant;

use qdrant_client::Qdrant;
use qdrant_client::qdrant::{
    CreateCollectionBuilder, DeletePointsBuilder, Distance, GetPointsBuilder,
    PointId, PointStruct, SearchPointsBuilder, UpsertPointsBuilder,
    VectorParamsBuilder,
    point_id::PointIdOptions,
    vector_output,
};
use serde_json::Value;
use tracing::instrument;

use crate::{Result, SearchRequest, SearchResult, ScoredPoint, VectorStoreConfig, VectorStoreError};

/// Qdrant vector store client.
#[derive(Clone)]
pub struct VectorStoreClient {
    client: Arc<Qdrant>,
    config: VectorStoreConfig,
}

impl VectorStoreClient {
    /// Connect to Qdrant.
    ///
    /// # Errors
    ///
    /// Returns an error if connection fails.
    pub async fn connect(config: &VectorStoreConfig) -> Result<Self> {
        let mut builder = Qdrant::from_url(&config.url)
            .timeout(config.timeout)
            .connect_timeout(config.connect_timeout);

        if let Some(api_key) = &config.api_key {
            builder = builder.api_key(api_key.clone());
        }

        let client = builder
            .build()
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
        let vectors_config = VectorParamsBuilder::new(vector_size, Distance::Cosine)
            .hnsw_config(qdrant_client::qdrant::HnswConfigDiff {
                m: Some(self.config.hnsw_config.m),
                ef_construct: Some(self.config.hnsw_config.ef_construct),
                ..Default::default()
            });

        self.client
            .create_collection(
                CreateCollectionBuilder::new(name)
                    .vectors_config(vectors_config),
            )
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
        self.client
            .collection_exists(name)
            .await
            .map_err(|e| VectorStoreError::Qdrant(e.to_string()))
    }

    /// Get collection info.
    ///
    /// # Errors
    ///
    /// Returns an error if the collection doesn't exist.
    #[instrument(skip(self))]
    pub async fn collection_info(&self, name: &str) -> Result<CollectionInfo> {
        let response = self
            .client
            .collection_info(name)
            .await
            .map_err(|_| VectorStoreError::CollectionNotFound(name.into()))?;

        let info = response
            .result
            .ok_or_else(|| VectorStoreError::CollectionNotFound(name.into()))?;

        Ok(CollectionInfo {
            name: name.into(),
            points_count: info.points_count.unwrap_or(0),
            vectors_count: info.indexed_vectors_count.unwrap_or(0),
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
            .upsert_points(UpsertPointsBuilder::new(collection, points).wait(true))
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

        let mut search_builder = SearchPointsBuilder::new(collection, request.vector, request.limit)
            .with_payload(request.with_payload);

        if request.with_vector {
            search_builder = search_builder.with_vectors(true);
        }

        if let Some(filter) = request.filter {
            search_builder = search_builder.filter(filter);
        }

        if let Some(threshold) = request.score_threshold {
            search_builder = search_builder.score_threshold(threshold);
        }

        if let Some(p) = request.params {
            let mut params = qdrant_client::qdrant::SearchParams::default();
            if let Some(ef) = p.ef {
                params.hnsw_ef = Some(ef);
            }
            params.exact = Some(p.exact);
            search_builder = search_builder.params(params);
        }

        let response = self.client.search_points(search_builder)
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
                    v.vectors_options.and_then(|opts| match opts {
                        qdrant_client::qdrant::vectors_output::VectorsOptions::Vector(vec) => {
                            match vec.into_vector() {
                                vector_output::Vector::Dense(dense) => Some(dense.data),
                                _ => None,
                            }
                        }
                        _ => None,
                    })
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
            .delete_points(
                DeletePointsBuilder::new(collection)
                    .points(point_ids)
                    .wait(true),
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
            .delete_points(
                DeletePointsBuilder::new(collection)
                    .points(filter)
                    .wait(true),
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
                GetPointsBuilder::new(collection, point_ids)
                    .with_payload(true)
                    .with_vectors(true),
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
                    v.vectors_options.and_then(|opts| match opts {
                        qdrant_client::qdrant::vectors_output::VectorsOptions::Vector(vec) => {
                            match vec.into_vector() {
                                vector_output::Vector::Dense(dense) => Some(dense.data),
                                _ => None,
                            }
                        }
                        _ => None,
                    })
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
            } else {
                n.as_f64().map(|f| qdrant_client::qdrant::Value {
                    kind: Some(Kind::DoubleValue(f)),
                })
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
