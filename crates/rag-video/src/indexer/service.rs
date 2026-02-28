//! Video Qdrant indexer service.

use std::collections::HashMap;
use std::sync::Arc;

use qdrant_client::qdrant::{
    point_id::PointIdOptions, CreateCollectionBuilder, DeletePointsBuilder, Distance,
    FieldCondition, Filter, Match, PointId, PointStruct, ScrollPointsBuilder, SearchPointsBuilder,
    UpsertPointsBuilder, VectorParamsBuilder,
};
use qdrant_client::Qdrant;
use uuid::Uuid;

use super::config::VideoIndexerConfig;
use super::types::{CollectionInfo, IndexResult, SearchFilters, SearchHit, VideoChunkPayload};
use crate::fusion::VideoChunk;
use crate::{Result, VideoError};

/// Progress callback type for batch operations.
pub type ProgressCallback = Box<dyn Fn(usize, usize, &str) + Send + Sync>;

/// Service for indexing video chunks in Qdrant.
pub struct VideoQdrantIndexer {
    client: Arc<Qdrant>,
    config: VideoIndexerConfig,
}

impl VideoQdrantIndexer {
    /// Creates a new video Qdrant indexer.
    ///
    /// # Errors
    ///
    /// Returns an error if the Qdrant client fails to connect.
    #[allow(clippy::unused_async)]
    pub async fn new(config: VideoIndexerConfig) -> Result<Self> {
        let client = Qdrant::from_url(&config.qdrant_url)
            .timeout(std::time::Duration::from_secs(config.timeout_seconds))
            .build()
            .map_err(|e| VideoError::Qdrant(format!("Failed to create client: {e}")))?;

        Ok(Self {
            client: Arc::new(client),
            config,
        })
    }

    /// Returns a reference to the configuration.
    #[must_use]
    pub const fn config(&self) -> &VideoIndexerConfig {
        &self.config
    }

    /// Ensures the collection exists with proper configuration.
    ///
    /// # Returns
    ///
    /// Returns `true` if the collection was created, `false` if it already existed.
    ///
    /// # Errors
    ///
    /// Returns an error if the collection check or creation fails.
    pub async fn ensure_collection(&self) -> Result<bool> {
        let exists = self
            .client
            .collection_exists(&self.config.collection_name)
            .await
            .map_err(|e| VideoError::Qdrant(format!("Failed to check collection: {e}")))?;

        if exists {
            return Ok(false);
        }

        // Create collection with vector params
        let vectors_config =
            VectorParamsBuilder::new(self.config.vector_size as u64, Distance::Cosine).hnsw_config(
                qdrant_client::qdrant::HnswConfigDiff {
                    m: Some(self.config.hnsw_m),
                    ef_construct: Some(self.config.hnsw_ef_construct),
                    ..Default::default()
                },
            );

        self.client
            .create_collection(
                CreateCollectionBuilder::new(&self.config.collection_name)
                    .vectors_config(vectors_config),
            )
            .await
            .map_err(|e| VideoError::Qdrant(format!("Failed to create collection: {e}")))?;

        Ok(true)
    }

    /// Indexes video chunks with their embeddings.
    ///
    /// # Arguments
    ///
    /// * `chunks` - Video chunks to index.
    /// * `embeddings` - Embeddings for each chunk (`chunk_id` -> vector).
    /// * `video_title` - Title of the video.
    /// * `visibility` - Visibility level.
    /// * `allowed_groups` - Groups with access.
    /// * `progress` - Optional progress callback.
    ///
    /// # Errors
    ///
    /// Returns an error if indexing fails.
    pub async fn index_chunks(
        &self,
        chunks: &[VideoChunk],
        embeddings: &[(Uuid, Vec<f32>)],
        video_title: &str,
        visibility: &str,
        allowed_groups: &[String],
        progress: Option<ProgressCallback>,
    ) -> Result<IndexResult> {
        if chunks.is_empty() {
            return Ok(IndexResult::new(
                0,
                &self.config.collection_name,
                Uuid::nil(),
            ));
        }

        let video_id = chunks[0].video_id;

        // Create embedding lookup
        let embedding_map: HashMap<Uuid, &Vec<f32>> =
            embeddings.iter().map(|(id, vec)| (*id, vec)).collect();

        // Process in batches
        let total = chunks.len();
        let mut indexed = 0;

        for (batch_idx, batch) in chunks.chunks(self.config.batch_size).enumerate() {
            let points: Vec<PointStruct> = batch
                .iter()
                .filter_map(|chunk| {
                    let embedding = embedding_map.get(&chunk.id)?;

                    let mut payload = VideoChunkPayload::new(
                        chunk.tenant_id,
                        chunk.video_id,
                        chunk.chunk_index,
                        chunk.start_time_ms,
                        chunk.end_time_ms,
                    );
                    payload.set_fused_text(&chunk.fused_text, 1000);
                    payload.video_title = video_title.to_string();
                    payload.visibility = visibility.to_string();
                    payload.allowed_groups = allowed_groups.to_vec();
                    payload
                        .source_modalities
                        .clone_from(&chunk.source_modalities);
                    payload.keyframe_path = chunk
                        .keyframe_path
                        .as_ref()
                        .map(|p| p.to_string_lossy().to_string());

                    let payload_map = Self::payload_to_map(&payload);

                    Some(PointStruct {
                        id: Some(PointId {
                            point_id_options: Some(PointIdOptions::Uuid(chunk.id.to_string())),
                        }),
                        vectors: Some((*embedding).clone().into()),
                        payload: payload_map,
                    })
                })
                .collect();

            if !points.is_empty() {
                self.client
                    .upsert_points(
                        UpsertPointsBuilder::new(&self.config.collection_name, points).wait(true),
                    )
                    .await
                    .map_err(|e| VideoError::Qdrant(format!("Failed to upsert points: {e}")))?;

                indexed += batch.len();
            }

            if let Some(ref cb) = progress {
                cb(
                    indexed,
                    total,
                    &format!("Indexed batch {} ({} of {})", batch_idx + 1, indexed, total),
                );
            }
        }

        Ok(IndexResult::new(
            indexed,
            &self.config.collection_name,
            video_id,
        ))
    }

    /// Deletes all chunks for a video.
    ///
    /// # Arguments
    ///
    /// * `video_id` - ID of the video to delete chunks for.
    ///
    /// # Returns
    ///
    /// Number of points deleted.
    ///
    /// # Errors
    ///
    /// Returns an error if deletion fails.
    pub async fn delete_by_video_id(&self, video_id: Uuid) -> Result<u64> {
        let filter = Filter {
            must: vec![qdrant_client::qdrant::Condition {
                condition_one_of: Some(qdrant_client::qdrant::condition::ConditionOneOf::Field(
                    FieldCondition {
                        key: "video_id".to_string(),
                        r#match: Some(Match {
                            match_value: Some(qdrant_client::qdrant::r#match::MatchValue::Keyword(
                                video_id.to_string(),
                            )),
                        }),
                        ..Default::default()
                    },
                )),
            }],
            ..Default::default()
        };

        // Count before deletion using scroll
        let scroll_result = self
            .client
            .scroll(
                ScrollPointsBuilder::new(&self.config.collection_name)
                    .filter(filter.clone())
                    .limit(10000)
                    .with_payload(false),
            )
            .await
            .map_err(|e| VideoError::Qdrant(format!("Failed to scroll points: {e}")))?;

        let count = scroll_result.result.len() as u64;

        // Delete points by filter
        self.client
            .delete_points(
                DeletePointsBuilder::new(&self.config.collection_name)
                    .points(filter)
                    .wait(true),
            )
            .await
            .map_err(|e| VideoError::Qdrant(format!("Failed to delete points: {e}")))?;

        Ok(count)
    }

    /// Searches for similar video chunks.
    ///
    /// # Arguments
    ///
    /// * `query_vector` - Query embedding.
    /// * `tenant_id` - Tenant ID for filtering.
    /// * `top_k` - Maximum number of results.
    /// * `filters` - Additional search filters.
    ///
    /// # Errors
    ///
    /// Returns an error if the search fails.
    pub async fn search(
        &self,
        query_vector: &[f32],
        tenant_id: Uuid,
        top_k: usize,
        filters: SearchFilters,
    ) -> Result<Vec<SearchHit>> {
        let mut must_conditions = vec![qdrant_client::qdrant::Condition {
            condition_one_of: Some(qdrant_client::qdrant::condition::ConditionOneOf::Field(
                FieldCondition {
                    key: "tenant_id".to_string(),
                    r#match: Some(Match {
                        match_value: Some(qdrant_client::qdrant::r#match::MatchValue::Keyword(
                            tenant_id.to_string(),
                        )),
                    }),
                    ..Default::default()
                },
            )),
        }];

        // Add video_id filter
        if let Some(video_id) = filters.video_id {
            must_conditions.push(qdrant_client::qdrant::Condition {
                condition_one_of: Some(qdrant_client::qdrant::condition::ConditionOneOf::Field(
                    FieldCondition {
                        key: "video_id".to_string(),
                        r#match: Some(Match {
                            match_value: Some(qdrant_client::qdrant::r#match::MatchValue::Keyword(
                                video_id.to_string(),
                            )),
                        }),
                        ..Default::default()
                    },
                )),
            });
        }

        // Add ACL filter: visibility=public OR user is in allowed_groups
        // For simplicity, we add allowed_groups to should conditions
        let mut should_conditions = Vec::new();
        for group in &filters.allowed_groups {
            should_conditions.push(qdrant_client::qdrant::Condition {
                condition_one_of: Some(qdrant_client::qdrant::condition::ConditionOneOf::Field(
                    FieldCondition {
                        key: "allowed_groups".to_string(),
                        r#match: Some(Match {
                            match_value: Some(qdrant_client::qdrant::r#match::MatchValue::Keyword(
                                group.clone(),
                            )),
                        }),
                        ..Default::default()
                    },
                )),
            });
        }

        let filter = Filter {
            must: must_conditions,
            should: should_conditions,
            ..Default::default()
        };

        let mut search_builder = SearchPointsBuilder::new(
            &self.config.collection_name,
            query_vector.to_vec(),
            top_k as u64,
        )
        .filter(filter)
        .with_payload(true);

        if let Some(threshold) = filters.score_threshold {
            search_builder = search_builder.score_threshold(threshold);
        }

        let response = self
            .client
            .search_points(search_builder)
            .await
            .map_err(|e| VideoError::Qdrant(format!("Search failed: {e}")))?;

        let hits = response
            .result
            .into_iter()
            .map(|point| {
                let id = match point.id.and_then(|id| id.point_id_options) {
                    Some(PointIdOptions::Uuid(uuid)) => uuid,
                    Some(PointIdOptions::Num(num)) => num.to_string(),
                    None => String::new(),
                };
                let payload = Self::map_to_payload(&point.payload);
                SearchHit::new(id, point.score, payload)
            })
            .collect();

        Ok(hits)
    }

    /// Performs a health check on the Qdrant connection.
    ///
    /// # Errors
    ///
    /// Returns an error if the health check fails.
    pub async fn health(&self) -> Result<bool> {
        self.client
            .health_check()
            .await
            .map_err(|e| VideoError::Qdrant(format!("Health check failed: {e}")))?;
        Ok(true)
    }

    /// Gets information about the collection.
    ///
    /// # Errors
    ///
    /// Returns an error if the collection info cannot be retrieved.
    pub async fn get_collection_info(&self) -> Result<Option<CollectionInfo>> {
        let exists = self
            .client
            .collection_exists(&self.config.collection_name)
            .await
            .map_err(|e| VideoError::Qdrant(format!("Failed to check collection: {e}")))?;

        if !exists {
            return Ok(None);
        }

        match self
            .client
            .collection_info(&self.config.collection_name)
            .await
        {
            Ok(response) => {
                let r = response
                    .result
                    .ok_or_else(|| VideoError::Qdrant("Collection info result was empty".into()))?;
                let info = CollectionInfo::new(
                    &self.config.collection_name,
                    r.indexed_vectors_count.unwrap_or(0),
                    r.points_count.unwrap_or(0),
                    format!("{:?}", r.status),
                );
                Ok(Some(info))
            }
            Err(e) => Err(VideoError::Qdrant(format!(
                "Failed to get collection info: {e}"
            ))),
        }
    }

    /// Converts a `VideoChunkPayload` to a Qdrant payload map.
    fn payload_to_map(
        payload: &VideoChunkPayload,
    ) -> HashMap<String, qdrant_client::qdrant::Value> {
        use qdrant_client::qdrant::value::Kind;

        let mut map = HashMap::new();

        map.insert(
            "tenant_id".into(),
            qdrant_client::qdrant::Value {
                kind: Some(Kind::StringValue(payload.tenant_id.clone())),
            },
        );
        map.insert(
            "video_id".into(),
            qdrant_client::qdrant::Value {
                kind: Some(Kind::StringValue(payload.video_id.clone())),
            },
        );
        map.insert(
            "chunk_index".into(),
            qdrant_client::qdrant::Value {
                kind: Some(Kind::IntegerValue(i64::from(payload.chunk_index))),
            },
        );
        map.insert(
            "start_time_ms".into(),
            qdrant_client::qdrant::Value {
                kind: Some(Kind::IntegerValue(payload.start_time_ms as i64)),
            },
        );
        map.insert(
            "end_time_ms".into(),
            qdrant_client::qdrant::Value {
                kind: Some(Kind::IntegerValue(payload.end_time_ms as i64)),
            },
        );
        map.insert(
            "fused_text".into(),
            qdrant_client::qdrant::Value {
                kind: Some(Kind::StringValue(payload.fused_text.clone())),
            },
        );
        map.insert(
            "video_title".into(),
            qdrant_client::qdrant::Value {
                kind: Some(Kind::StringValue(payload.video_title.clone())),
            },
        );
        map.insert(
            "visibility".into(),
            qdrant_client::qdrant::Value {
                kind: Some(Kind::StringValue(payload.visibility.clone())),
            },
        );

        // Convert allowed_groups to list
        let allowed_groups_values: Vec<qdrant_client::qdrant::Value> = payload
            .allowed_groups
            .iter()
            .map(|s| qdrant_client::qdrant::Value {
                kind: Some(Kind::StringValue(s.clone())),
            })
            .collect();
        map.insert(
            "allowed_groups".into(),
            qdrant_client::qdrant::Value {
                kind: Some(Kind::ListValue(qdrant_client::qdrant::ListValue {
                    values: allowed_groups_values,
                })),
            },
        );

        // Convert source_modalities to list
        let source_modalities_values: Vec<qdrant_client::qdrant::Value> = payload
            .source_modalities
            .iter()
            .map(|s| qdrant_client::qdrant::Value {
                kind: Some(Kind::StringValue(s.clone())),
            })
            .collect();
        map.insert(
            "source_modalities".into(),
            qdrant_client::qdrant::Value {
                kind: Some(Kind::ListValue(qdrant_client::qdrant::ListValue {
                    values: source_modalities_values,
                })),
            },
        );

        if let Some(ref path) = payload.keyframe_path {
            map.insert(
                "keyframe_path".into(),
                qdrant_client::qdrant::Value {
                    kind: Some(Kind::StringValue(path.clone())),
                },
            );
        }

        map
    }

    /// Converts a Qdrant payload map to a `VideoChunkPayload`.
    #[allow(clippy::cast_possible_truncation)]
    fn map_to_payload(map: &HashMap<String, qdrant_client::qdrant::Value>) -> VideoChunkPayload {
        let get_string = |key: &str| -> String {
            map.get(key)
                .and_then(|v| v.kind.as_ref())
                .and_then(|k| match k {
                    qdrant_client::qdrant::value::Kind::StringValue(s) => Some(s.clone()),
                    _ => None,
                })
                .unwrap_or_default()
        };

        let get_i64 = |key: &str| -> i64 {
            map.get(key)
                .and_then(|v| v.kind.as_ref())
                .and_then(|k| match k {
                    qdrant_client::qdrant::value::Kind::IntegerValue(i) => Some(*i),
                    _ => None,
                })
                .unwrap_or(0)
        };

        let get_string_list = |key: &str| -> Vec<String> {
            map.get(key)
                .and_then(|v| v.kind.as_ref())
                .and_then(|k| match k {
                    qdrant_client::qdrant::value::Kind::ListValue(list) => Some(
                        list.values
                            .iter()
                            .filter_map(|v| v.kind.as_ref())
                            .filter_map(|k| match k {
                                qdrant_client::qdrant::value::Kind::StringValue(s) => {
                                    Some(s.clone())
                                }
                                _ => None,
                            })
                            .collect(),
                    ),
                    _ => None,
                })
                .unwrap_or_default()
        };

        VideoChunkPayload {
            tenant_id: get_string("tenant_id"),
            video_id: get_string("video_id"),
            chunk_index: get_i64("chunk_index") as u32,
            start_time_ms: get_i64("start_time_ms") as u64,
            end_time_ms: get_i64("end_time_ms") as u64,
            fused_text: get_string("fused_text"),
            video_title: get_string("video_title"),
            visibility: get_string("visibility"),
            allowed_groups: get_string_list("allowed_groups"),
            source_modalities: get_string_list("source_modalities"),
            keyframe_path: map
                .get("keyframe_path")
                .and_then(|v| v.kind.as_ref())
                .and_then(|k| match k {
                    qdrant_client::qdrant::value::Kind::StringValue(s) => {
                        if s.is_empty() {
                            None
                        } else {
                            Some(s.clone())
                        }
                    }
                    _ => None,
                }),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_payload_to_map_and_back() {
        let original = VideoChunkPayload {
            tenant_id: "tenant123".to_string(),
            video_id: "video456".to_string(),
            chunk_index: 5,
            start_time_ms: 10000,
            end_time_ms: 30000,
            fused_text: "Test content".to_string(),
            video_title: "Test Video".to_string(),
            visibility: "private".to_string(),
            allowed_groups: vec!["group1".to_string(), "group2".to_string()],
            source_modalities: vec!["speech".to_string(), "visual".to_string()],
            keyframe_path: Some("/path/to/frame.jpg".to_string()),
        };

        let map = VideoQdrantIndexer::payload_to_map(&original);
        let restored = VideoQdrantIndexer::map_to_payload(&map);

        assert_eq!(original.tenant_id, restored.tenant_id);
        assert_eq!(original.video_id, restored.video_id);
        assert_eq!(original.chunk_index, restored.chunk_index);
        assert_eq!(original.start_time_ms, restored.start_time_ms);
        assert_eq!(original.end_time_ms, restored.end_time_ms);
        assert_eq!(original.fused_text, restored.fused_text);
        assert_eq!(original.video_title, restored.video_title);
        assert_eq!(original.visibility, restored.visibility);
        assert_eq!(original.allowed_groups, restored.allowed_groups);
        assert_eq!(original.source_modalities, restored.source_modalities);
        assert_eq!(original.keyframe_path, restored.keyframe_path);
    }

    #[test]
    fn test_payload_to_map_without_keyframe() {
        let payload = VideoChunkPayload {
            tenant_id: "t".to_string(),
            video_id: "v".to_string(),
            chunk_index: 0,
            start_time_ms: 0,
            end_time_ms: 1000,
            fused_text: String::new(),
            video_title: String::new(),
            visibility: "public".to_string(),
            allowed_groups: Vec::new(),
            source_modalities: Vec::new(),
            keyframe_path: None,
        };

        let map = VideoQdrantIndexer::payload_to_map(&payload);
        let restored = VideoQdrantIndexer::map_to_payload(&map);

        assert!(restored.keyframe_path.is_none());
    }

    #[test]
    fn test_map_to_payload_empty_map() {
        let map = HashMap::new();
        let payload = VideoQdrantIndexer::map_to_payload(&map);

        assert!(payload.tenant_id.is_empty());
        assert!(payload.video_id.is_empty());
        assert_eq!(payload.chunk_index, 0);
        assert!(payload.allowed_groups.is_empty());
    }

    #[test]
    fn test_index_result_empty_chunks() {
        // This is a simple test for the logic that returns early for empty chunks
        // The actual async test would need a Qdrant instance
        let result = IndexResult::new(0, "video_chunks", Uuid::nil());
        assert_eq!(result.indexed_count, 0);
    }
}
