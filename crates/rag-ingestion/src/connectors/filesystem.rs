//! Filesystem connector for local documents.

use async_trait::async_trait;
use bytes::Bytes;
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::path::{Path, PathBuf};
use tokio::fs;
use tracing::{debug, instrument};

use super::base::{Connector, DocumentMetadata, RawDocument, StorageBackend};
use crate::error::{Error, Result};

/// Configuration for the filesystem connector.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FilesystemConfig {
    /// Base path to scan for documents.
    pub base_path: PathBuf,
    /// Whether to scan subdirectories recursively.
    #[serde(default = "default_recursive")]
    pub recursive: bool,
    /// File extensions to include (e.g., [".pdf", ".md"]).
    /// If None, all files are included.
    pub file_extensions: Option<Vec<String>>,
}

fn default_recursive() -> bool {
    true
}

impl FilesystemConfig {
    /// Create a new configuration for the given path.
    pub fn new(base_path: impl Into<PathBuf>) -> Self {
        Self {
            base_path: base_path.into(),
            recursive: true,
            file_extensions: None,
        }
    }

    /// Set whether to scan recursively.
    #[must_use]
    pub fn with_recursive(mut self, recursive: bool) -> Self {
        self.recursive = recursive;
        self
    }

    /// Set file extensions to filter.
    #[must_use]
    pub fn with_extensions(mut self, extensions: Vec<String>) -> Self {
        self.file_extensions = Some(extensions);
        self
    }
}

/// Connector for local filesystem documents.
pub struct FilesystemConnector {
    config: FilesystemConfig,
    connected: bool,
}

impl FilesystemConnector {
    /// Create a new filesystem connector.
    pub fn new(config: FilesystemConfig) -> Self {
        Self {
            config,
            connected: false,
        }
    }

    /// Check if a file should be included based on extension filter.
    fn should_include(&self, path: &Path) -> bool {
        match &self.config.file_extensions {
            None => true,
            Some(extensions) => path
                .extension()
                .and_then(|ext| ext.to_str())
                .map(|ext| {
                    let ext_with_dot = format!(".{}", ext.to_lowercase());
                    extensions.iter().any(|e| e.to_lowercase() == ext_with_dot)
                })
                .unwrap_or(false),
        }
    }

    /// Recursively scan a directory for files.
    async fn scan_directory(&self, path: &Path) -> Result<Vec<PathBuf>> {
        let mut files = Vec::new();
        let mut dirs_to_scan = vec![path.to_path_buf()];

        while let Some(dir) = dirs_to_scan.pop() {
            let mut entries = fs::read_dir(&dir).await.map_err(|e| {
                Error::Connector(format!("Failed to read directory {}: {}", dir.display(), e))
            })?;

            while let Some(entry) = entries
                .next_entry()
                .await
                .map_err(|e| Error::Connector(format!("Failed to read directory entry: {e}")))?
            {
                let entry_path = entry.path();
                let file_type = entry
                    .file_type()
                    .await
                    .map_err(|e| Error::Connector(format!("Failed to get file type: {e}")))?;

                if file_type.is_dir() {
                    if self.config.recursive {
                        dirs_to_scan.push(entry_path);
                    }
                } else if file_type.is_file() && self.should_include(&entry_path) {
                    files.push(entry_path);
                }
            }
        }

        Ok(files)
    }

    /// Get metadata for a file.
    async fn get_file_metadata(&self, path: &Path) -> Result<DocumentMetadata> {
        let metadata = fs::metadata(path).await.map_err(|e| {
            Error::Connector(format!(
                "Failed to get metadata for {}: {}",
                path.display(),
                e
            ))
        })?;

        let source_id = path
            .strip_prefix(&self.config.base_path)
            .unwrap_or(path)
            .to_string_lossy()
            .to_string();

        let filename = path
            .file_name()
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_default();

        let mime_type = mime_guess::from_path(path).first().map(|m| m.to_string());

        let size_bytes = metadata.len();

        let modified_at = metadata.modified().ok().map(DateTime::<Utc>::from);

        let created_at = metadata.created().ok().map(DateTime::<Utc>::from);

        Ok(
            DocumentMetadata::new(source_id, StorageBackend::Local, filename)
                .with_size(size_bytes)
                .with_timestamps(created_at, modified_at)
                .with_mime_type(
                    mime_type.unwrap_or_else(|| "application/octet-stream".to_string()),
                ),
        )
    }
}

#[async_trait]
impl Connector for FilesystemConnector {
    #[instrument(skip(self))]
    async fn connect(&mut self) -> Result<()> {
        // Verify the base path exists and is a directory
        let metadata = fs::metadata(&self.config.base_path).await.map_err(|e| {
            Error::Connector(format!(
                "Base path {} does not exist or is not accessible: {}",
                self.config.base_path.display(),
                e
            ))
        })?;

        if !metadata.is_dir() {
            return Err(Error::Connector(format!(
                "Base path {} is not a directory",
                self.config.base_path.display()
            )));
        }

        self.connected = true;
        debug!(base_path = %self.config.base_path.display(), "Connected to filesystem");
        Ok(())
    }

    async fn disconnect(&mut self) -> Result<()> {
        self.connected = false;
        debug!("Disconnected from filesystem");
        Ok(())
    }

    #[instrument(skip(self))]
    async fn list_documents(&self, path: Option<&str>) -> Result<Vec<DocumentMetadata>> {
        if !self.connected {
            return Err(Error::Connector("Not connected".to_string()));
        }

        let scan_path = match path {
            Some(p) => self.config.base_path.join(p),
            None => self.config.base_path.clone(),
        };

        let files = self.scan_directory(&scan_path).await?;
        let mut documents = Vec::with_capacity(files.len());

        for file_path in files {
            match self.get_file_metadata(&file_path).await {
                Ok(meta) => documents.push(meta),
                Err(e) => {
                    debug!(path = %file_path.display(), error = %e, "Skipping file");
                }
            }
        }

        Ok(documents)
    }

    #[instrument(skip(self))]
    async fn fetch_document(&self, source_id: &str) -> Result<RawDocument> {
        if !self.connected {
            return Err(Error::Connector("Not connected".to_string()));
        }

        let file_path = self.config.base_path.join(source_id);

        if !file_path.exists() {
            return Err(Error::NotFound(format!("Document not found: {source_id}")));
        }

        let content = fs::read(&file_path).await.map_err(|e| {
            Error::Connector(format!("Failed to read {}: {}", file_path.display(), e))
        })?;

        let metadata = self.get_file_metadata(&file_path).await?;

        Ok(RawDocument::new(Bytes::from(content), metadata))
    }

    fn is_connected(&self) -> bool {
        self.connected
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;
    use tokio::io::AsyncWriteExt;

    async fn setup_test_dir() -> TempDir {
        let dir = TempDir::new().unwrap();

        // Create test files
        let file1 = dir.path().join("test.txt");
        let mut f = tokio::fs::File::create(&file1).await.unwrap();
        f.write_all(b"Hello, World!").await.unwrap();

        let file2 = dir.path().join("test.md");
        let mut f = tokio::fs::File::create(&file2).await.unwrap();
        f.write_all(b"# Markdown").await.unwrap();

        // Create subdirectory with file
        let subdir = dir.path().join("subdir");
        tokio::fs::create_dir(&subdir).await.unwrap();
        let file3 = subdir.join("nested.txt");
        let mut f = tokio::fs::File::create(&file3).await.unwrap();
        f.write_all(b"Nested content").await.unwrap();

        dir
    }

    #[tokio::test]
    async fn test_connect_success() {
        let dir = setup_test_dir().await;
        let config = FilesystemConfig::new(dir.path());
        let mut connector = FilesystemConnector::new(config);

        assert!(!connector.is_connected());
        connector.connect().await.unwrap();
        assert!(connector.is_connected());
    }

    #[tokio::test]
    async fn test_connect_nonexistent_path() {
        let config = FilesystemConfig::new("/nonexistent/path");
        let mut connector = FilesystemConnector::new(config);

        let result = connector.connect().await;
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn test_list_documents_all() {
        let dir = setup_test_dir().await;
        let config = FilesystemConfig::new(dir.path());
        let mut connector = FilesystemConnector::new(config);
        connector.connect().await.unwrap();

        let docs = connector.list_documents(None).await.unwrap();
        assert_eq!(docs.len(), 3); // test.txt, test.md, subdir/nested.txt
    }

    #[tokio::test]
    async fn test_list_documents_filtered() {
        let dir = setup_test_dir().await;
        let config = FilesystemConfig::new(dir.path()).with_extensions(vec![".txt".to_string()]);
        let mut connector = FilesystemConnector::new(config);
        connector.connect().await.unwrap();

        let docs = connector.list_documents(None).await.unwrap();
        assert_eq!(docs.len(), 2); // test.txt, subdir/nested.txt
        assert!(docs.iter().all(|d| d.filename.ends_with(".txt")));
    }

    #[tokio::test]
    async fn test_list_documents_non_recursive() {
        let dir = setup_test_dir().await;
        let config = FilesystemConfig::new(dir.path()).with_recursive(false);
        let mut connector = FilesystemConnector::new(config);
        connector.connect().await.unwrap();

        let docs = connector.list_documents(None).await.unwrap();
        assert_eq!(docs.len(), 2); // test.txt, test.md (no nested)
    }

    #[tokio::test]
    async fn test_fetch_document() {
        let dir = setup_test_dir().await;
        let config = FilesystemConfig::new(dir.path());
        let mut connector = FilesystemConnector::new(config);
        connector.connect().await.unwrap();

        let doc = connector.fetch_document("test.txt").await.unwrap();
        assert_eq!(doc.content_as_str().unwrap(), "Hello, World!");
        assert_eq!(doc.metadata.filename, "test.txt");
        assert_eq!(doc.metadata.source_type, StorageBackend::Local);
    }

    #[tokio::test]
    async fn test_fetch_document_not_found() {
        let dir = setup_test_dir().await;
        let config = FilesystemConfig::new(dir.path());
        let mut connector = FilesystemConnector::new(config);
        connector.connect().await.unwrap();

        let result = connector.fetch_document("nonexistent.txt").await;
        assert!(matches!(result, Err(Error::NotFound(_))));
    }

    #[tokio::test]
    async fn test_fetch_without_connect() {
        let dir = setup_test_dir().await;
        let config = FilesystemConfig::new(dir.path());
        let connector = FilesystemConnector::new(config);

        let result = connector.fetch_document("test.txt").await;
        assert!(result.is_err());
    }
}
