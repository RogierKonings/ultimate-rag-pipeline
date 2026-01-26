//! Integration tests for the rag-retrieval crate.
//!
//! This module provides integration test infrastructure including mock
//! implementations of external dependencies (vector stores, search clients, etc.)
//! for testing the retrieval pipeline without requiring actual external services.

pub mod hybrid_search;
pub mod mocks;
pub mod pipeline;

pub use mocks::*;
