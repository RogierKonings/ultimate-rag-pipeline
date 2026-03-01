//! Document ingestion for the RAG pipeline.
//!
//! This crate provides components for the ingestion phase of the RAG pipeline:
//!
//! - **Parsers** ([`parsers`]): Extract structured content from documents
//!   - [`parsers::HtmlParser`]: Parse HTML documents using `scraper`
//!   - [`parsers::MarkdownParser`]: Parse Markdown with YAML frontmatter
//!
//! - **Chunking** ([`chunking`]): Split text into chunks for embedding
//!   - [`chunking::RecursiveCharacterSplitter`]: Split by paragraphs, sentences, words (default)
//!   - [`chunking::SemanticChunker`]: Split by sentence boundaries for prose-heavy text
//!   - [`chunking::HierarchicalChunker`]: Split by detected document sections/headings
//!   - **Auto** (default): analyzes the document (heading density, sentence length,
//!     file type, parser blocks) and picks the best strategy automatically
//!
//! - **Embedding** ([`embedding`]): Generate vector embeddings
//!   - [`embedding::EmbeddingClient`]: HTTP client for embedding service
//!   - [`embedding::EmbeddingClientConfig`]: Configuration for the embedding client
//!
//! - **Indexing** ([`indexing`]): Coordinate writes to multiple stores
//!   - [`indexing::IndexCoordinator`]: Parallel writes to Qdrant, `OpenSearch`, `PostgreSQL`
//!   - [`indexing::IndexStatus`]: Document indexing status tracking
//!
//! - **Connectors** ([`connectors`]): Load documents from various sources
//!   - [`connectors::FilesystemConnector`]: Local filesystem
//!   - [`connectors::S3Connector`]: S3/MinIO object storage
//!
//! # Example
//!
//! ```rust,ignore
//! use rag_ingestion::{
//!     parsers::{HtmlParser, Parser},
//!     chunking::{RecursiveCharacterSplitter, ChunkingConfig},
//!     embedding::{EmbeddingClient, EmbeddingClientConfig},
//!     connectors::{FilesystemConnector, FilesystemConfig, Connector},
//! };
//! use rag_types::DocumentId;
//!
//! // Load documents from filesystem
//! let config = FilesystemConfig::new("/path/to/docs");
//! let mut connector = FilesystemConnector::new(config);
//! connector.connect().await?;
//! let docs = connector.list_documents(None).await?;
//!
//! // Parse a document
//! let parser = HtmlParser::default();
//! let doc = parser.parse(&content, None)?;
//!
//! // Chunk the text
//! let chunker = RecursiveCharacterSplitter::new(ChunkingConfig::default())?;
//! let chunks = chunker.chunk(&doc.text, DocumentId::new(), None)?;
//!
//! // Embed the chunks
//! let client = EmbeddingClient::new(EmbeddingClientConfig::default())?;
//! let texts: Vec<&str> = chunks.iter().map(|c| c.text.as_str()).collect();
//! let (embeddings, tokens) = client.embed_batch(&texts).await?;
//! ```
//!
//! # Feature Roadmap
//!
//! Future additions (Phase 4):
//! - PDF parser
//! - DOCX parser

pub mod api;
pub mod cache_invalidation;
pub mod chunking;
pub mod connectors;
pub mod embedding;
pub mod error;
pub mod indexing;
pub mod parsers;
pub mod pii;
pub mod worker;

pub use error::{Error, Result};

// Re-export commonly used types at crate root for convenience

// Connectors
pub use connectors::{
    Connector, DocumentMetadata, FilesystemConfig, FilesystemConnector, RawDocument, S3Config,
    S3Connector, StorageBackend,
};

// Embedding
pub use embedding::{EmbeddingClient, EmbeddingClientConfig};

// Indexing
pub use indexing::{
    DocumentRecord, IndexCoordinator, IndexCoordinatorConfig, IndexStatus, IndexedChunk,
    WriteResult,
};

// Parsers (commonly used)
pub use parsers::{HtmlParser, MarkdownParser, ParsedDocument, Parser};

// Chunking (commonly used)
pub use chunking::{
    Chunk, ChunkingConfig, ChunkingStrategy, HierarchicalChunker, RecursiveCharacterSplitter,
    SemanticChunker,
};

// Cache invalidation
pub use cache_invalidation::{CacheInvalidationPublisher, InvalidationEvent, INVALIDATION_CHANNEL};
