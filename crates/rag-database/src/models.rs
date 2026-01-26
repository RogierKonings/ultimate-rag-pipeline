//! Database models corresponding to PostgreSQL tables.

mod source_document;
mod chunk;

pub use source_document::{NewSourceDocument, SourceDocument, SourceDocumentBuilder, Visibility};
pub use chunk::{Chunk, ChunkBuilder, NewChunk};
