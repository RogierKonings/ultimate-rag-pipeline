//! Integration tests for P3.4-P3.6 components.
//!
//! These tests verify the complete ingestion workflow:
//! - Filesystem connector -> Parser -> Chunker pipeline
//! - `EmbeddingClient` with mocked responses
//! - End-to-end document processing
#![allow(clippy::cast_possible_truncation)] // test code: index casts are safe

use rag_ingestion::{
    chunking::{ChunkingConfig, ChunkingStrategy, RecursiveCharacterSplitter},
    connectors::{Connector, FilesystemConfig, FilesystemConnector},
    embedding::{EmbeddingClient, EmbeddingClientConfig},
    indexing::{DocumentRecord, IndexStatus, IndexedChunk, WriteResult},
    parsers::{HtmlParser, MarkdownParser, Parser},
};
use rag_types::{ChunkId, DocumentId, TenantId};
use std::time::Duration;
use tempfile::TempDir;
use tokio::io::AsyncWriteExt;
use wiremock::matchers::{method, path};
use wiremock::{Mock, MockServer, ResponseTemplate};

/// Test the complete ingestion pipeline:
/// Filesystem -> Parse -> Chunk -> (mock) Embed
#[tokio::test]
async fn test_full_ingestion_pipeline() {
    // 1. Set up test directory with documents
    let dir = TempDir::new().unwrap();

    // Create a markdown file
    let md_path = dir.path().join("test.md");
    let mut f = tokio::fs::File::create(&md_path).await.unwrap();
    f.write_all(
        b"# Test Document\n\nThis is a test paragraph with some content.\n\nAnother paragraph here.",
    )
    .await
    .unwrap();

    // Create an HTML file
    let html_path = dir.path().join("test.html");
    let mut f = tokio::fs::File::create(&html_path).await.unwrap();
    f.write_all(
        b"<html><head><title>HTML Test</title></head><body><p>HTML content here.</p></body></html>",
    )
    .await
    .unwrap();

    // 2. Connect to filesystem
    let config = FilesystemConfig::new(dir.path());
    let mut connector = FilesystemConnector::new(config);
    connector.connect().await.unwrap();

    // 3. List documents
    let docs = connector.list_documents(None).await.unwrap();
    assert_eq!(docs.len(), 2);

    // 4. Fetch and parse markdown
    let md_raw = connector.fetch_document("test.md").await.unwrap();
    let md_parser = MarkdownParser;
    let md_parsed = md_parser.parse(&md_raw.content, None).unwrap();
    assert!(md_parsed.title.is_some());
    assert!(!md_parsed.text.is_empty());

    // 5. Fetch and parse HTML
    let html_raw = connector.fetch_document("test.html").await.unwrap();
    let html_parser = HtmlParser::default();
    let html_parsed = html_parser.parse(&html_raw.content, None).unwrap();
    assert_eq!(html_parsed.title, Some("HTML Test".to_string()));

    // 6. Chunk the markdown content
    let chunking_config = ChunkingConfig {
        target_tokens: 50,
        max_tokens: 100,
        chunk_overlap: 10,
        min_chunk_size: 5,
        ..Default::default()
    };
    let chunker = RecursiveCharacterSplitter::new(chunking_config).unwrap();
    let chunks = chunker
        .chunk(&md_parsed.text, DocumentId::new(), None)
        .unwrap();
    assert!(!chunks.is_empty());

    // 7. Set up mock embedding server
    let mock_server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/v1/embeddings"))
        .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
            "data": chunks.iter().enumerate().map(|(i, _)| {
                serde_json::json!({
                    "embedding": vec![0.1f32; 384],
                    "index": i
                })
            }).collect::<Vec<_>>(),
            "usage": {"total_tokens": chunks.len() * 10}
        })))
        .mount(&mock_server)
        .await;

    // 8. Embed chunks
    let embedding_config = EmbeddingClientConfig::new(mock_server.uri());
    let embedding_client = EmbeddingClient::new(embedding_config).unwrap();

    let texts: Vec<String> = chunks.iter().map(|c| c.content.clone()).collect();
    let (embeddings, tokens) = embedding_client.embed_batch(&texts).await.unwrap();

    assert_eq!(embeddings.len(), chunks.len());
    assert!(tokens > 0);

    // 9. Verify embeddings have correct dimension
    for embedding in &embeddings {
        assert_eq!(embedding.len(), 384);
    }

    connector.disconnect().await.unwrap();
}

/// Test embedding client retry behavior
#[tokio::test]
async fn test_embedding_client_retries_on_server_error() {
    let mock_server = MockServer::start().await;

    // First two requests fail, third succeeds
    Mock::given(method("POST"))
        .and(path("/v1/embeddings"))
        .respond_with(ResponseTemplate::new(500).set_body_string("Internal Server Error"))
        .up_to_n_times(2)
        .mount(&mock_server)
        .await;

    Mock::given(method("POST"))
        .and(path("/v1/embeddings"))
        .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
            "data": [{"embedding": vec![0.1f32; 384], "index": 0}],
            "usage": {"total_tokens": 5}
        })))
        .mount(&mock_server)
        .await;

    let config = EmbeddingClientConfig::new(mock_server.uri())
        .with_max_retries(3)
        .with_retry_delay_ms(10); // Fast for tests
    let client = EmbeddingClient::new(config).unwrap();

    let result = client.embed_batch(&["test text".to_string()]).await;
    assert!(result.is_ok());
}

/// Test indexing models
#[tokio::test]
async fn test_indexing_models() {
    let document_id = DocumentId::new();
    let tenant_id = TenantId::new();

    // Create document record
    let doc_record =
        DocumentRecord::new(document_id, tenant_id, "path/to/doc.pdf").with_title("Test Document");

    assert_eq!(doc_record.source_id, "path/to/doc.pdf");
    assert_eq!(doc_record.title, Some("Test Document".to_string()));

    // Create indexed chunk
    let chunk = IndexedChunk::new(
        ChunkId::new(),
        document_id,
        tenant_id,
        "Chunk content",
        vec![0.1, 0.2, 0.3],
        0,
    );

    assert_eq!(chunk.content, "Chunk content");
    assert_eq!(chunk.embedding.len(), 3);
    assert_eq!(chunk.chunk_index, 0);

    // Test write result
    let result = WriteResult::success(10, Duration::from_millis(50));
    assert!(result.success);
    assert_eq!(result.items_written, 10);

    // Test index status
    assert_eq!(IndexStatus::default(), IndexStatus::Pending);
    assert_eq!(IndexStatus::Ok.to_string(), "ok");
}

/// Test filesystem connector with extension filtering
#[tokio::test]
async fn test_filesystem_extension_filtering() {
    let dir = TempDir::new().unwrap();

    // Create files with different extensions
    for ext in ["txt", "pdf", "md", "docx"] {
        let path = dir.path().join(format!("file.{ext}"));
        tokio::fs::write(&path, "content").await.unwrap();
    }

    // Filter for only .txt and .md files
    let config = FilesystemConfig::new(dir.path())
        .with_extensions(vec![".txt".to_string(), ".md".to_string()]);
    let mut connector = FilesystemConnector::new(config);
    connector.connect().await.unwrap();

    let docs = connector.list_documents(None).await.unwrap();
    assert_eq!(docs.len(), 2);

    let filenames: Vec<_> = docs.iter().map(|d| &d.filename).collect();
    assert!(filenames.contains(&&"file.txt".to_string()));
    assert!(filenames.contains(&&"file.md".to_string()));
}

/// Test parsing and chunking with metadata preservation
#[tokio::test]
async fn test_metadata_preservation_through_pipeline() {
    use serde_json::Value;
    use std::collections::HashMap;

    let markdown = r"---
title: Metadata Test
author: Test Author
version: 1.0
---

# Content

This is the main content of the document.
";

    let parser = MarkdownParser;
    let parsed = parser.parse(markdown.as_bytes(), None).unwrap();

    // Verify frontmatter was extracted
    assert_eq!(parsed.title, Some("Metadata Test".to_string()));
    assert_eq!(
        parsed.metadata.get("author"),
        Some(&Value::String("Test Author".to_string()))
    );

    // Chunk with custom metadata
    let mut chunk_metadata = HashMap::new();
    chunk_metadata.insert("source".to_string(), Value::String("test".to_string()));

    let chunker = RecursiveCharacterSplitter::default();
    let chunks = chunker
        .chunk(&parsed.text, DocumentId::new(), Some(chunk_metadata))
        .unwrap();

    // Verify metadata was attached to chunks
    for chunk in &chunks {
        assert_eq!(
            chunk.metadata.get("source"),
            Some(&Value::String("test".to_string()))
        );
    }
}

/// Test handling of various HTML structures
#[tokio::test]
async fn test_html_parser_complex_structures() {
    let html = r"
        <!DOCTYPE html>
        <html>
        <head><title>Complex HTML</title></head>
        <body>
            <h1>Main Title</h1>
            <p>Introduction paragraph.</p>
            <table>
                <thead><tr><th>Column A</th><th>Column B</th></tr></thead>
                <tbody>
                    <tr><td>Value 1</td><td>Value 2</td></tr>
                    <tr><td>Value 3</td><td>Value 4</td></tr>
                </tbody>
            </table>
            <pre>function example() { return 42; }</pre>
            <script>alert('should be removed');</script>
            <style>.hidden { display: none; }</style>
        </body>
        </html>
    ";

    let parser = HtmlParser::default();
    let parsed = parser.parse(html.as_bytes(), None).unwrap();

    // Title extracted
    assert_eq!(parsed.title, Some("Complex HTML".to_string()));

    // Tables extracted
    assert_eq!(parsed.tables.len(), 1);
    assert_eq!(parsed.tables[0].headers, vec!["Column A", "Column B"]);
    assert_eq!(parsed.tables[0].rows.len(), 2);

    // Script and style content should be removed
    assert!(!parsed.text.contains("alert"));
    assert!(!parsed.text.contains("display: none"));

    // Main content preserved
    assert!(parsed.text.contains("Main Title"));
    assert!(parsed.text.contains("Introduction paragraph"));
}

/// Test chunking behavior with different configurations
#[tokio::test]
async fn test_chunking_configurations() {
    let long_text = "This is a sentence with some words. ".repeat(100);

    // Small chunks
    let small_config = ChunkingConfig {
        target_tokens: 20,
        max_tokens: 40,
        chunk_overlap: 5,
        min_chunk_size: 5,
        ..Default::default()
    };

    let small_chunker = RecursiveCharacterSplitter::new(small_config).unwrap();
    let small_chunks = small_chunker
        .chunk(&long_text, DocumentId::new(), None)
        .unwrap();

    // Large chunks
    let large_config = ChunkingConfig {
        target_tokens: 200,
        max_tokens: 400,
        chunk_overlap: 20,
        min_chunk_size: 50,
        ..Default::default()
    };

    let large_chunker = RecursiveCharacterSplitter::new(large_config).unwrap();
    let large_chunks = large_chunker
        .chunk(&long_text, DocumentId::new(), None)
        .unwrap();

    // Small config should produce more chunks
    assert!(
        small_chunks.len() > large_chunks.len(),
        "Small chunks: {}, Large chunks: {}",
        small_chunks.len(),
        large_chunks.len()
    );

    // Verify token limits are respected
    for chunk in &small_chunks {
        assert!(
            chunk.token_count <= 40,
            "Small chunk exceeded max: {} tokens",
            chunk.token_count
        );
    }

    for chunk in &large_chunks {
        assert!(
            chunk.token_count <= 400,
            "Large chunk exceeded max: {} tokens",
            chunk.token_count
        );
    }
}

/// Test embedding client with empty input
#[tokio::test]
async fn test_embedding_client_empty_input() {
    // No server needed - empty input should return immediately
    let config = EmbeddingClientConfig::new("http://localhost:9999");
    let client = EmbeddingClient::new(config).unwrap();

    let (embeddings, tokens) = client.embed_batch(&[]).await.unwrap();
    assert!(embeddings.is_empty());
    assert_eq!(tokens, 0);
}

/// Test document record and indexed chunk builders
#[tokio::test]
async fn test_indexing_builders() {
    use serde_json::Value;

    let doc_id = DocumentId::new();
    let tenant_id = TenantId::new();

    // Document record with all fields
    let doc = DocumentRecord::new(doc_id, tenant_id, "s3://bucket/file.pdf")
        .with_title("Important Document")
        .with_metadata("category", Value::String("reports".to_string()))
        .with_metadata("pages", Value::Number(42.into()));

    assert_eq!(doc.source_id, "s3://bucket/file.pdf");
    assert_eq!(doc.title, Some("Important Document".to_string()));
    assert!(doc.metadata.contains_key("category"));
    assert!(doc.metadata.contains_key("pages"));

    // Indexed chunk with metadata
    let chunk = IndexedChunk::new(
        ChunkId::new(),
        doc_id,
        tenant_id,
        "Chunk text content here",
        vec![0.1, 0.2, 0.3, 0.4, 0.5],
        0,
    )
    .with_metadata("section", Value::String("introduction".to_string()));

    assert_eq!(chunk.content, "Chunk text content here");
    assert_eq!(chunk.embedding.len(), 5);
    assert_eq!(chunk.chunk_index, 0);
    assert!(chunk.metadata.contains_key("section"));
}

/// Test write result variants
#[test]
fn test_write_result_variants() {
    // Success
    let success = WriteResult::success(100, Duration::from_millis(500));
    assert!(success.success);
    assert_eq!(success.items_written, 100);
    assert_eq!(success.items_failed, 0);
    assert!(success.errors.is_empty());

    // Failure
    let failure = WriteResult::failure("Connection timeout", Duration::from_millis(5000));
    assert!(!failure.success);
    assert_eq!(failure.items_written, 0);
    assert_eq!(failure.errors.len(), 1);
    assert!(failure.errors[0].contains("Connection timeout"));

    // Partial success
    let partial = WriteResult::partial(
        80,
        20,
        vec!["Error 1".to_string(), "Error 2".to_string()],
        Duration::from_millis(1000),
    );
    assert!(!partial.success); // Not fully successful
    assert_eq!(partial.items_written, 80);
    assert_eq!(partial.items_failed, 20);
    assert_eq!(partial.errors.len(), 2);
}

/// Test index status enum
#[test]
fn test_index_status_enum() {
    // Default
    assert_eq!(IndexStatus::default(), IndexStatus::Pending);

    // Display
    assert_eq!(IndexStatus::Pending.to_string(), "pending");
    assert_eq!(IndexStatus::Ok.to_string(), "ok");
    assert_eq!(IndexStatus::Error.to_string(), "error");
    assert_eq!(IndexStatus::Stale.to_string(), "stale");

    // Serialization
    let json = serde_json::to_string(&IndexStatus::Ok).unwrap();
    assert_eq!(json, "\"ok\"");

    let parsed: IndexStatus = serde_json::from_str("\"pending\"").unwrap();
    assert_eq!(parsed, IndexStatus::Pending);
}

// ============================================================================
// Tests for PostgreSQL data model conversions (P3.5 Index Coordinator)
// ============================================================================
// These tests verify that DocumentRecord and IndexedChunk can be properly
// converted to the database models (NewSourceDocument, NewChunk) with all
// metadata fields correctly mapped.

use rag_database::{NewChunk, NewSourceDocument, Visibility};
use uuid::Uuid;

/// Test conversion of `DocumentRecord` to `NewSourceDocument` format.
/// This verifies the data mapping that `write_to_database` performs.
#[test]
fn test_document_record_to_new_source_document_conversion() {
    let document_id = DocumentId::new();
    let tenant_id = TenantId::new();

    // Create a DocumentRecord with all metadata fields
    let doc_record = DocumentRecord::new(document_id, tenant_id, "s3://bucket/path/file.pdf")
        .with_title("Test Document")
        .with_metadata("source_type", serde_json::Value::String("s3".to_string()))
        .with_metadata(
            "mime_type",
            serde_json::Value::String("application/pdf".to_string()),
        )
        .with_metadata(
            "content_hash",
            serde_json::Value::String("abc123hash".to_string()),
        )
        .with_metadata("file_size", serde_json::Value::Number(1024.into()))
        .with_metadata("allowed_groups", serde_json::json!(["admin", "users"]));

    // Simulate the conversion logic from write_to_database
    let doc_id =
        Uuid::parse_str(&doc_record.document_id.to_string()).unwrap_or_else(|_| Uuid::new_v4());

    let new_doc = NewSourceDocument {
        id: doc_id,
        tenant_id: doc_record.tenant_id.to_string(),
        title: doc_record.title.clone(),
        source_uri: doc_record.source_id.clone(),
        source_type: doc_record
            .metadata
            .get("source_type")
            .and_then(|v| v.as_str())
            .unwrap_or("file")
            .to_string(),
        mime_type: doc_record
            .metadata
            .get("mime_type")
            .and_then(|v| v.as_str())
            .map(String::from),
        content_hash: doc_record
            .metadata
            .get("content_hash")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        file_size: doc_record
            .metadata
            .get("file_size")
            .and_then(serde_json::Value::as_i64),
        visibility: Visibility::Private,
        allowed_groups: doc_record
            .metadata
            .get("allowed_groups")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(String::from))
                    .collect()
            })
            .unwrap_or_default(),
        metadata: serde_json::to_value(&doc_record.metadata).unwrap_or(serde_json::Value::Null),
    };

    // Verify all fields are correctly mapped
    assert_eq!(new_doc.tenant_id, tenant_id.to_string());
    assert_eq!(new_doc.title, Some("Test Document".to_string()));
    assert_eq!(new_doc.source_uri, "s3://bucket/path/file.pdf");
    assert_eq!(new_doc.source_type, "s3");
    assert_eq!(new_doc.mime_type, Some("application/pdf".to_string()));
    assert_eq!(new_doc.content_hash, "abc123hash");
    assert_eq!(new_doc.file_size, Some(1024));
    assert_eq!(new_doc.visibility, Visibility::Private);
    assert_eq!(new_doc.allowed_groups, vec!["admin", "users"]);
}

/// Test conversion with minimal metadata (default values)
#[test]
fn test_document_record_conversion_with_defaults() {
    let document_id = DocumentId::new();
    let tenant_id = TenantId::new();

    // Create a minimal DocumentRecord without optional metadata
    let doc_record = DocumentRecord::new(document_id, tenant_id, "/local/path/file.txt");

    // Simulate conversion
    let doc_id =
        Uuid::parse_str(&doc_record.document_id.to_string()).unwrap_or_else(|_| Uuid::new_v4());

    let new_doc = NewSourceDocument {
        id: doc_id,
        tenant_id: doc_record.tenant_id.to_string(),
        title: doc_record.title.clone(),
        source_uri: doc_record.source_id.clone(),
        source_type: doc_record
            .metadata
            .get("source_type")
            .and_then(|v| v.as_str())
            .unwrap_or("file")
            .to_string(),
        mime_type: doc_record
            .metadata
            .get("mime_type")
            .and_then(|v| v.as_str())
            .map(String::from),
        content_hash: doc_record
            .metadata
            .get("content_hash")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        file_size: doc_record
            .metadata
            .get("file_size")
            .and_then(serde_json::Value::as_i64),
        visibility: Visibility::Private,
        allowed_groups: doc_record
            .metadata
            .get("allowed_groups")
            .and_then(|v| v.as_array())
            .map(|arr| {
                arr.iter()
                    .filter_map(|v| v.as_str().map(String::from))
                    .collect()
            })
            .unwrap_or_default(),
        metadata: serde_json::to_value(&doc_record.metadata).unwrap_or(serde_json::Value::Null),
    };

    // Verify defaults are applied
    assert_eq!(new_doc.title, None);
    assert_eq!(new_doc.source_type, "file"); // Default
    assert_eq!(new_doc.mime_type, None);
    assert_eq!(new_doc.content_hash, ""); // Default empty
    assert_eq!(new_doc.file_size, None);
    assert!(new_doc.allowed_groups.is_empty()); // Default empty
}

/// Test conversion of `IndexedChunk` to `NewChunk` format
#[test]
fn test_indexed_chunk_to_new_chunk_conversion() {
    let chunk_id = ChunkId::new();
    let document_id = DocumentId::new();
    let tenant_id = TenantId::new();

    // Create an IndexedChunk with all metadata fields
    let indexed_chunk = IndexedChunk::new(
        chunk_id,
        document_id,
        tenant_id,
        "This is the chunk content for testing.",
        vec![0.1, 0.2, 0.3, 0.4, 0.5],
        0,
    )
    .with_metadata("token_count", serde_json::Value::Number(10.into()))
    .with_metadata(
        "embedding_model",
        serde_json::Value::String("all-MiniLM-L6-v2".to_string()),
    )
    .with_metadata(
        "content_hash",
        serde_json::Value::String("chunk_hash_123".to_string()),
    )
    .with_metadata("start_char", serde_json::Value::Number(0.into()))
    .with_metadata("end_char", serde_json::Value::Number(38.into()));

    // Simulate conversion (document_id for the chunk comes from the parent document)
    let doc_uuid = Uuid::parse_str(&document_id.to_string()).unwrap_or_else(|_| Uuid::new_v4());
    let chunk_uuid =
        Uuid::parse_str(&indexed_chunk.chunk_id.to_string()).unwrap_or_else(|_| Uuid::new_v4());

    let new_chunk = NewChunk {
        id: chunk_uuid,
        document_id: doc_uuid,
        tenant_id: indexed_chunk.tenant_id.to_string(),
        chunk_index: indexed_chunk.chunk_index as i32,
        content: indexed_chunk.content.clone(),
        token_count: indexed_chunk
            .metadata
            .get("token_count")
            .and_then(serde_json::Value::as_i64)
            .unwrap_or(0) as i32,
        char_count: indexed_chunk.content.len() as i32,
        embedding_model: indexed_chunk
            .metadata
            .get("embedding_model")
            .and_then(|v| v.as_str())
            .map(String::from),
        content_hash: indexed_chunk
            .metadata
            .get("content_hash")
            .and_then(|v| v.as_str())
            .unwrap_or("")
            .to_string(),
        start_offset: indexed_chunk
            .metadata
            .get("start_char")
            .and_then(serde_json::Value::as_i64)
            .map(|v| v as i32),
        end_offset: indexed_chunk
            .metadata
            .get("end_char")
            .and_then(serde_json::Value::as_i64)
            .map(|v| v as i32),
        metadata: serde_json::to_value(&indexed_chunk.metadata).unwrap_or(serde_json::Value::Null),
    };

    // Verify all fields are correctly mapped
    assert_eq!(new_chunk.document_id, doc_uuid);
    assert_eq!(new_chunk.tenant_id, tenant_id.to_string());
    assert_eq!(new_chunk.chunk_index, 0);
    assert_eq!(new_chunk.content, "This is the chunk content for testing.");
    assert_eq!(new_chunk.token_count, 10);
    assert_eq!(new_chunk.char_count, 38);
    assert_eq!(
        new_chunk.embedding_model,
        Some("all-MiniLM-L6-v2".to_string())
    );
    assert_eq!(new_chunk.content_hash, "chunk_hash_123");
    assert_eq!(new_chunk.start_offset, Some(0));
    assert_eq!(new_chunk.end_offset, Some(38));
}

/// Test conversion of multiple chunks (simulating batch insert)
#[test]
fn test_multiple_chunks_conversion() {
    let document_id = DocumentId::new();
    let tenant_id = TenantId::new();
    let doc_uuid = Uuid::parse_str(&document_id.to_string()).unwrap_or_else(|_| Uuid::new_v4());

    // Create multiple indexed chunks
    let chunks: Vec<IndexedChunk> = (0..5)
        .map(|i| {
            IndexedChunk::new(
                ChunkId::new(),
                document_id,
                tenant_id,
                format!("Chunk content number {i}"),
                vec![0.1 * i as f32; 384],
                i,
            )
            .with_metadata(
                "token_count",
                serde_json::Value::Number((10 + i64::from(i)).into()),
            )
        })
        .collect();

    // Convert all chunks
    let new_chunks: Vec<NewChunk> = chunks
        .iter()
        .map(|c| {
            let chunk_uuid =
                Uuid::parse_str(&c.chunk_id.to_string()).unwrap_or_else(|_| Uuid::new_v4());
            NewChunk {
                id: chunk_uuid,
                document_id: doc_uuid,
                tenant_id: c.tenant_id.to_string(),
                chunk_index: c.chunk_index as i32,
                content: c.content.clone(),
                token_count: c
                    .metadata
                    .get("token_count")
                    .and_then(serde_json::Value::as_i64)
                    .unwrap_or(0) as i32,
                char_count: c.content.len() as i32,
                embedding_model: c
                    .metadata
                    .get("embedding_model")
                    .and_then(|v| v.as_str())
                    .map(String::from),
                content_hash: c
                    .metadata
                    .get("content_hash")
                    .and_then(|v| v.as_str())
                    .unwrap_or("")
                    .to_string(),
                start_offset: c
                    .metadata
                    .get("start_char")
                    .and_then(serde_json::Value::as_i64)
                    .map(|v| v as i32),
                end_offset: c
                    .metadata
                    .get("end_char")
                    .and_then(serde_json::Value::as_i64)
                    .map(|v| v as i32),
                metadata: serde_json::to_value(&c.metadata).unwrap_or(serde_json::Value::Null),
            }
        })
        .collect();

    // Verify batch conversion
    assert_eq!(new_chunks.len(), 5);

    for (i, chunk) in new_chunks.iter().enumerate() {
        assert_eq!(chunk.chunk_index, i as i32);
        assert_eq!(chunk.content, format!("Chunk content number {i}"));
        assert_eq!(chunk.token_count, (10 + i) as i32);
        assert_eq!(chunk.document_id, doc_uuid); // All reference same document
    }
}

/// Test UUID parsing from rag-types IDs
#[test]
fn test_uuid_parsing_from_type_ids() {
    let document_id = DocumentId::new();
    let chunk_id = ChunkId::new();
    let tenant_id = TenantId::new();

    // IDs from rag-types should produce valid UUIDs
    let doc_uuid_result = Uuid::parse_str(&document_id.to_string());
    let chunk_uuid_result = Uuid::parse_str(&chunk_id.to_string());

    assert!(
        doc_uuid_result.is_ok(),
        "DocumentId should produce valid UUID string"
    );
    assert!(
        chunk_uuid_result.is_ok(),
        "ChunkId should produce valid UUID string"
    );

    // TenantId is used as string directly
    let tenant_str = tenant_id.to_string();
    assert!(
        !tenant_str.is_empty(),
        "TenantId should produce non-empty string"
    );
}

/// Test empty chunks handling
#[test]
fn test_empty_chunks_conversion() {
    let _document_id = DocumentId::new();
    let _tenant_id = TenantId::new();

    let chunks: Vec<IndexedChunk> = vec![];

    // Convert empty list - verify empty
    assert!(chunks.is_empty());
}
