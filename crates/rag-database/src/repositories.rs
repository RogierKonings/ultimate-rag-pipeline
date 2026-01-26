//! Repository pattern implementations for database access.

pub mod document_repository;
pub mod chunk_repository;

pub use document_repository::DocumentRepository;
pub use chunk_repository::ChunkRepository;
