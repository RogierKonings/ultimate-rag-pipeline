//! Embedding types and operations.
//!
//! This module provides types for working with vector embeddings
//! in the RAG pipeline.

use serde::{Deserialize, Serialize};
use std::fmt;

/// A vector embedding.
///
/// Embeddings are dense vector representations of text, used for
/// semantic similarity search.
#[derive(Clone, PartialEq, Serialize, Deserialize)]
pub struct Embedding {
    /// The embedding vector
    values: Vec<f32>,
}

impl Embedding {
    /// Create a new embedding from a vector of values.
    ///
    /// # Panics
    ///
    /// Panics if the vector is empty.
    #[must_use]
    pub fn new(values: Vec<f32>) -> Self {
        assert!(!values.is_empty(), "Embedding cannot be empty");
        Self { values }
    }

    /// Create an embedding from a slice.
    ///
    /// # Panics
    ///
    /// Panics if the slice is empty.
    #[must_use]
    pub fn from_slice(values: &[f32]) -> Self {
        Self::new(values.to_vec())
    }

    /// Get the embedding values as a slice.
    #[must_use]
    pub fn as_slice(&self) -> &[f32] {
        &self.values
    }

    /// Get the embedding values as a mutable slice.
    pub fn as_mut_slice(&mut self) -> &mut [f32] {
        &mut self.values
    }

    /// Consume the embedding and return the underlying vector.
    #[must_use]
    pub fn into_vec(self) -> Vec<f32> {
        self.values
    }

    /// Get the dimensionality of the embedding.
    #[must_use]
    pub fn dimension(&self) -> usize {
        self.values.len()
    }

    /// Calculate the L2 (Euclidean) norm of the embedding.
    #[must_use]
    pub fn l2_norm(&self) -> f32 {
        self.values.iter().map(|x| x * x).sum::<f32>().sqrt()
    }

    /// Normalize the embedding to unit length (L2 normalization).
    ///
    /// This is required for cosine similarity search in Qdrant.
    #[must_use]
    pub fn normalize(mut self) -> Self {
        let norm = self.l2_norm();
        if norm > f32::EPSILON {
            for v in &mut self.values {
                *v /= norm;
            }
        }
        self
    }

    /// Check if the embedding is normalized (unit length).
    #[must_use]
    pub fn is_normalized(&self) -> bool {
        let norm = self.l2_norm();
        (norm - 1.0).abs() < 1e-5
    }

    /// Calculate cosine similarity with another embedding.
    ///
    /// Both embeddings should be normalized for accurate results.
    ///
    /// # Panics
    ///
    /// Panics if the embeddings have different dimensions.
    #[must_use]
    pub fn cosine_similarity(&self, other: &Self) -> f32 {
        assert_eq!(
            self.dimension(),
            other.dimension(),
            "Embeddings must have the same dimension"
        );

        self.values
            .iter()
            .zip(other.values.iter())
            .map(|(a, b)| a * b)
            .sum()
    }

    /// Calculate dot product with another embedding.
    ///
    /// # Panics
    ///
    /// Panics if the embeddings have different dimensions.
    #[must_use]
    pub fn dot_product(&self, other: &Self) -> f32 {
        assert_eq!(
            self.dimension(),
            other.dimension(),
            "Embeddings must have the same dimension"
        );

        self.values
            .iter()
            .zip(other.values.iter())
            .map(|(a, b)| a * b)
            .sum()
    }

    /// Calculate Euclidean distance to another embedding.
    ///
    /// # Panics
    ///
    /// Panics if the embeddings have different dimensions.
    #[must_use]
    pub fn euclidean_distance(&self, other: &Self) -> f32 {
        assert_eq!(
            self.dimension(),
            other.dimension(),
            "Embeddings must have the same dimension"
        );

        self.values
            .iter()
            .zip(other.values.iter())
            .map(|(a, b)| (a - b).powi(2))
            .sum::<f32>()
            .sqrt()
    }
}

impl fmt::Debug for Embedding {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "Embedding(dim={})", self.dimension())
    }
}

impl From<Vec<f32>> for Embedding {
    fn from(values: Vec<f32>) -> Self {
        Self::new(values)
    }
}

impl From<Embedding> for Vec<f32> {
    fn from(embedding: Embedding) -> Self {
        embedding.values
    }
}

impl AsRef<[f32]> for Embedding {
    fn as_ref(&self) -> &[f32] {
        &self.values
    }
}

/// Standard embedding dimensions used in the pipeline.
pub mod dimensions {
    /// Dimension for `all-MiniLM-L6-v2` model (default for retrieval)
    pub const MINILM_L6_V2: usize = 384;

    /// Dimension for `BAAI/bge-large-en-v1.5` model
    pub const BGE_LARGE_EN: usize = 1024;

    /// Dimension for `BAAI/bge-small-en-v1.5` model
    pub const BGE_SMALL_EN: usize = 384;

    /// Dimension for OpenAI `text-embedding-3-small`
    pub const OPENAI_SMALL: usize = 1536;

    /// Dimension for OpenAI `text-embedding-3-large`
    pub const OPENAI_LARGE: usize = 3072;
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_embedding_creation() {
        let values = vec![0.1, 0.2, 0.3, 0.4];
        let embedding = Embedding::new(values.clone());
        assert_eq!(embedding.dimension(), 4);
        assert_eq!(embedding.as_slice(), &values);
    }

    #[test]
    fn test_embedding_normalization() {
        let embedding = Embedding::new(vec![3.0, 4.0]);
        assert!(!embedding.is_normalized());

        let normalized = embedding.normalize();
        assert!(normalized.is_normalized());

        // 3-4-5 triangle: normalized should be [0.6, 0.8]
        let values = normalized.as_slice();
        assert!((values[0] - 0.6).abs() < 1e-6);
        assert!((values[1] - 0.8).abs() < 1e-6);
    }

    #[test]
    fn test_cosine_similarity() {
        let a = Embedding::new(vec![1.0, 0.0]).normalize();
        let b = Embedding::new(vec![1.0, 0.0]).normalize();
        assert!((a.cosine_similarity(&b) - 1.0).abs() < 1e-6);

        let c = Embedding::new(vec![0.0, 1.0]).normalize();
        assert!(a.cosine_similarity(&c).abs() < 1e-6); // Orthogonal

        let d = Embedding::new(vec![-1.0, 0.0]).normalize();
        assert!((a.cosine_similarity(&d) + 1.0).abs() < 1e-6); // Opposite
    }

    #[test]
    fn test_euclidean_distance() {
        let a = Embedding::new(vec![0.0, 0.0]);
        let b = Embedding::new(vec![3.0, 4.0]);
        assert!((a.euclidean_distance(&b) - 5.0).abs() < 1e-6); // 3-4-5 triangle
    }

    #[test]
    fn test_serialization() {
        let embedding = Embedding::new(vec![0.1, 0.2, 0.3]);
        let json = serde_json::to_string(&embedding).unwrap();
        let deserialized: Embedding = serde_json::from_str(&json).unwrap();
        assert_eq!(embedding, deserialized);
    }

    #[test]
    #[should_panic(expected = "Embedding cannot be empty")]
    fn test_empty_embedding_panics() {
        let _embedding = Embedding::new(vec![]);
    }

    #[test]
    #[should_panic(expected = "must have the same dimension")]
    fn test_dimension_mismatch_panics() {
        let a = Embedding::new(vec![1.0, 2.0]);
        let b = Embedding::new(vec![1.0, 2.0, 3.0]);
        let _ = a.cosine_similarity(&b);
    }
}
