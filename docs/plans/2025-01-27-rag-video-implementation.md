# rag-video Crate Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a new `rag-video` crate that implements the video processing pipeline with FFmpeg bindings, Tesseract OCR, HTTP clients for Python microservices, content fusion, and Qdrant indexing.

**Architecture:** New workspace member `rag-video` with modules for extraction (FFmpeg), OCR (Tesseract), HTTP clients (scene detection, transcription), content fusion, video indexing (Qdrant), and pipeline orchestration. Uses rayon for CPU-parallel batch processing and tokio for async I/O.

**Tech Stack:** Rust, ffmpeg-next, tesseract, reqwest, qdrant-client, rayon, tokio, serde, thiserror, uuid, tracing

**Design Reference:** `docs/plans/2025-01-27-rust-video-processing-design.md`

---

## Task 1: Crate Setup and Error Types

**Files:**
- Create: `crates/rag-video/Cargo.toml`
- Create: `crates/rag-video/src/lib.rs`
- Create: `crates/rag-video/src/error.rs`
- Modify: `crates/Cargo.toml` (add to workspace members)

**Step 1: Write the failing test**

Create the test file first:

```rust
// crates/rag-video/src/error.rs

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_video_error_display_file_not_found() {
        let err = VideoError::FileNotFound("/path/to/video.mp4".to_string());
        assert_eq!(err.to_string(), "Video file not found: /path/to/video.mp4");
    }

    #[test]
    fn test_video_error_display_ffmpeg() {
        let err = VideoError::Ffmpeg("decoder error".to_string());
        assert_eq!(err.to_string(), "FFmpeg error: decoder error");
    }

    #[test]
    fn test_video_error_from_io() {
        let io_err = std::io::Error::new(std::io::ErrorKind::NotFound, "file not found");
        let err: VideoError = io_err.into();
        assert!(matches!(err, VideoError::Io(_)));
    }

    #[test]
    fn test_result_type_alias() {
        fn returns_result() -> Result<()> {
            Ok(())
        }
        assert!(returns_result().is_ok());
    }
}
```

**Step 2: Run test to verify it fails**

Run: `cd crates && cargo test -p rag-video`
Expected: FAIL with "can't find crate for `rag_video`"

**Step 3: Add workspace member**

Edit `crates/Cargo.toml`:

```toml
[workspace]
resolver = "2"
members = [
    "rag-types",
    "rag-config",
    "rag-cache",
    "rag-retrieval",
    "rag-auth",
    "rag-telemetry",
    "rag-storage",
    "rag-vectorstore",
    "rag-search",
    "rag-database",
    "rag-ingestion",
    "rag-video",
]
```

**Step 4: Create Cargo.toml**

Create `crates/rag-video/Cargo.toml`:

```toml
[package]
name = "rag-video"
version.workspace = true
edition.workspace = true
rust-version.workspace = true
license.workspace = true
description = "Video processing pipeline for RAG: extraction, OCR, fusion, and indexing"

[dependencies]
# Internal crates
rag-types = { path = "../rag-types" }
rag-vectorstore = { path = "../rag-vectorstore" }
rag-ingestion = { path = "../rag-ingestion" }

# Async runtime
tokio = { workspace = true, features = ["fs", "process"] }

# HTTP client
reqwest = { version = "0.11", default-features = false, features = ["json", "rustls-tls"] }

# Qdrant
qdrant-client = "1.12"

# Parallelism
rayon = "1.10"

# Serialization
serde = { workspace = true }
serde_json = { workspace = true }

# Error handling
thiserror = { workspace = true }

# Utilities
uuid = { workspace = true }
chrono = { workspace = true }
tracing = { workspace = true }
tempfile = "3.14"

[dev-dependencies]
wiremock = "0.5"
tokio-test = { workspace = true }
pretty_assertions = "1.4"

[lints]
workspace = true
```

**Step 5: Create lib.rs**

Create `crates/rag-video/src/lib.rs`:

```rust
//! Video processing pipeline for RAG.
//!
//! This crate provides video processing capabilities including:
//! - Keyframe and audio extraction (FFmpeg)
//! - OCR text extraction (Tesseract)
//! - Scene detection and transcription (HTTP clients to Python services)
//! - Content fusion (combining transcript, scene descriptions, OCR)
//! - Video chunk indexing (Qdrant)
//! - Pipeline orchestration

pub mod error;

pub use error::{Result, VideoError};
```

**Step 6: Create error.rs with implementation**

Create `crates/rag-video/src/error.rs`:

```rust
//! Error types for video processing.

use thiserror::Error;

/// Video processing errors.
#[derive(Error, Debug)]
pub enum VideoError {
    /// Video file not found.
    #[error("Video file not found: {0}")]
    FileNotFound(String),

    /// Invalid video format.
    #[error("Invalid video format: {0}")]
    InvalidFormat(String),

    /// FFmpeg operation failed.
    #[error("FFmpeg error: {0}")]
    Ffmpeg(String),

    /// OCR operation failed.
    #[error("OCR error: {0}")]
    Ocr(String),

    /// Scene detection service error.
    #[error("Scene detection service error: {0}")]
    SceneDetection(String),

    /// Transcription service error.
    #[error("Transcription service error: {0}")]
    Transcription(String),

    /// Indexing operation failed.
    #[error("Indexing error: {0}")]
    Indexing(String),

    /// HTTP request failed.
    #[error("HTTP request failed: {0}")]
    Http(#[from] reqwest::Error),

    /// IO error.
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    /// Operation timed out.
    #[error("Timeout after {0}ms")]
    Timeout(u64),

    /// Qdrant client error.
    #[error("Qdrant error: {0}")]
    Qdrant(String),
}

/// Result type alias for video operations.
pub type Result<T> = std::result::Result<T, VideoError>;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_video_error_display_file_not_found() {
        let err = VideoError::FileNotFound("/path/to/video.mp4".to_string());
        assert_eq!(err.to_string(), "Video file not found: /path/to/video.mp4");
    }

    #[test]
    fn test_video_error_display_ffmpeg() {
        let err = VideoError::Ffmpeg("decoder error".to_string());
        assert_eq!(err.to_string(), "FFmpeg error: decoder error");
    }

    #[test]
    fn test_video_error_from_io() {
        let io_err = std::io::Error::new(std::io::ErrorKind::NotFound, "file not found");
        let err: VideoError = io_err.into();
        assert!(matches!(err, VideoError::Io(_)));
    }

    #[test]
    fn test_result_type_alias() {
        fn returns_result() -> Result<()> {
            Ok(())
        }
        assert!(returns_result().is_ok());
    }
}
```

**Step 7: Run tests to verify they pass**

Run: `cd crates && cargo test -p rag-video`
Expected: PASS (4 tests)

**Step 8: Commit**

```bash
git add crates/Cargo.toml crates/rag-video/
git commit -m "feat(rag-video): add crate with error types

- Create rag-video crate in workspace
- Add VideoError enum with thiserror
- Define Result type alias
- Add tests for error display and conversions"
```

---

## Task 2: Extraction Types

**Files:**
- Create: `crates/rag-video/src/extraction/mod.rs`
- Create: `crates/rag-video/src/extraction/types.rs`
- Modify: `crates/rag-video/src/lib.rs`

**Step 1: Write the failing test**

```rust
// crates/rag-video/src/extraction/types.rs

#[cfg(test)]
mod tests {
    use super::*;
    use std::path::PathBuf;

    #[test]
    fn test_video_metadata_default() {
        let metadata = VideoMetadata::default();
        assert_eq!(metadata.duration_ms, 0);
        assert_eq!(metadata.width, 0);
        assert_eq!(metadata.height, 0);
        assert!(!metadata.has_audio);
    }

    #[test]
    fn test_extracted_keyframe_timestamp_ms() {
        let keyframe = ExtractedKeyframe {
            frame_index: 0,
            timestamp_ms: 5500,
            image_path: PathBuf::from("/tmp/frame.jpg"),
            thumbnail_path: None,
            width: 1280,
            height: 720,
            file_size_bytes: 50000,
            is_scene_boundary: true,
        };
        assert_eq!(keyframe.timestamp_ms, 5500);
    }

    #[test]
    fn test_audio_metadata_fields() {
        let meta = AudioMetadata {
            duration_ms: 60000,
            sample_rate: 16000,
            channels: 1,
            file_size_bytes: 1920000,
        };
        assert_eq!(meta.duration_ms, 60000);
        assert_eq!(meta.sample_rate, 16000);
    }

    #[test]
    fn test_keyframe_config_default() {
        let config = KeyframeConfig::default();
        assert_eq!(config.output_width, 1280);
        assert_eq!(config.output_height, 720);
        assert_eq!(config.quality, 85);
        assert!(config.generate_thumbnails);
    }

    #[test]
    fn test_audio_config_default() {
        let config = AudioConfig::default();
        assert_eq!(config.sample_rate, 16000);
        assert_eq!(config.channels, 1);
        assert_eq!(config.format, "wav");
    }
}
```

**Step 2: Run test to verify it fails**

Run: `cd crates && cargo test -p rag-video extraction`
Expected: FAIL with "failed to resolve: use of undeclared crate or module `extraction`"

**Step 3: Create extraction module**

Create `crates/rag-video/src/extraction/mod.rs`:

```rust
//! Video extraction module.
//!
//! Provides keyframe extraction, audio extraction, and video metadata probing.

pub mod types;

pub use types::{
    AudioConfig, AudioMetadata, ExtractedKeyframe, KeyframeConfig, VideoMetadata,
};
```

**Step 4: Create types.rs with implementation**

Create `crates/rag-video/src/extraction/types.rs`:

```rust
//! Types for video extraction operations.

use std::path::PathBuf;

/// Video file metadata.
#[derive(Debug, Clone, Default)]
pub struct VideoMetadata {
    /// Duration in milliseconds.
    pub duration_ms: u64,
    /// Video width in pixels.
    pub width: u32,
    /// Video height in pixels.
    pub height: u32,
    /// Frames per second.
    pub fps: f32,
    /// Video codec name.
    pub codec: String,
    /// Whether the video has an audio track.
    pub has_audio: bool,
}

/// An extracted keyframe from a video.
#[derive(Debug, Clone)]
pub struct ExtractedKeyframe {
    /// Frame index in extraction order.
    pub frame_index: u32,
    /// Timestamp in milliseconds.
    pub timestamp_ms: u64,
    /// Path to the extracted image file.
    pub image_path: PathBuf,
    /// Path to the thumbnail image (if generated).
    pub thumbnail_path: Option<PathBuf>,
    /// Image width in pixels.
    pub width: u32,
    /// Image height in pixels.
    pub height: u32,
    /// Image file size in bytes.
    pub file_size_bytes: u64,
    /// Whether this keyframe is at a scene boundary.
    pub is_scene_boundary: bool,
}

/// Audio track metadata.
#[derive(Debug, Clone)]
pub struct AudioMetadata {
    /// Duration in milliseconds.
    pub duration_ms: u64,
    /// Sample rate in Hz.
    pub sample_rate: u32,
    /// Number of audio channels.
    pub channels: u8,
    /// File size in bytes.
    pub file_size_bytes: u64,
}

/// Configuration for keyframe extraction.
#[derive(Debug, Clone)]
pub struct KeyframeConfig {
    /// Maximum output width (preserves aspect ratio).
    pub output_width: u32,
    /// Maximum output height (preserves aspect ratio).
    pub output_height: u32,
    /// JPEG quality (1-100).
    pub quality: u8,
    /// Whether to generate thumbnails.
    pub generate_thumbnails: bool,
    /// Thumbnail width.
    pub thumbnail_width: u32,
    /// Thumbnail height.
    pub thumbnail_height: u32,
}

impl Default for KeyframeConfig {
    fn default() -> Self {
        Self {
            output_width: 1280,
            output_height: 720,
            quality: 85,
            generate_thumbnails: true,
            thumbnail_width: 320,
            thumbnail_height: 180,
        }
    }
}

/// Configuration for audio extraction.
#[derive(Debug, Clone)]
pub struct AudioConfig {
    /// Sample rate in Hz (default: 16000 for Whisper).
    pub sample_rate: u32,
    /// Number of channels (default: 1 for mono).
    pub channels: u8,
    /// Output format (default: "wav").
    pub format: String,
}

impl Default for AudioConfig {
    fn default() -> Self {
        Self {
            sample_rate: 16000,
            channels: 1,
            format: "wav".to_string(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_video_metadata_default() {
        let metadata = VideoMetadata::default();
        assert_eq!(metadata.duration_ms, 0);
        assert_eq!(metadata.width, 0);
        assert_eq!(metadata.height, 0);
        assert!(!metadata.has_audio);
    }

    #[test]
    fn test_extracted_keyframe_timestamp_ms() {
        let keyframe = ExtractedKeyframe {
            frame_index: 0,
            timestamp_ms: 5500,
            image_path: PathBuf::from("/tmp/frame.jpg"),
            thumbnail_path: None,
            width: 1280,
            height: 720,
            file_size_bytes: 50000,
            is_scene_boundary: true,
        };
        assert_eq!(keyframe.timestamp_ms, 5500);
    }

    #[test]
    fn test_audio_metadata_fields() {
        let meta = AudioMetadata {
            duration_ms: 60000,
            sample_rate: 16000,
            channels: 1,
            file_size_bytes: 1920000,
        };
        assert_eq!(meta.duration_ms, 60000);
        assert_eq!(meta.sample_rate, 16000);
    }

    #[test]
    fn test_keyframe_config_default() {
        let config = KeyframeConfig::default();
        assert_eq!(config.output_width, 1280);
        assert_eq!(config.output_height, 720);
        assert_eq!(config.quality, 85);
        assert!(config.generate_thumbnails);
    }

    #[test]
    fn test_audio_config_default() {
        let config = AudioConfig::default();
        assert_eq!(config.sample_rate, 16000);
        assert_eq!(config.channels, 1);
        assert_eq!(config.format, "wav");
    }
}
```

**Step 5: Update lib.rs**

Update `crates/rag-video/src/lib.rs`:

```rust
//! Video processing pipeline for RAG.
//!
//! This crate provides video processing capabilities including:
//! - Keyframe and audio extraction (FFmpeg)
//! - OCR text extraction (Tesseract)
//! - Scene detection and transcription (HTTP clients to Python services)
//! - Content fusion (combining transcript, scene descriptions, OCR)
//! - Video chunk indexing (Qdrant)
//! - Pipeline orchestration

pub mod error;
pub mod extraction;

pub use error::{Result, VideoError};
```

**Step 6: Run tests to verify they pass**

Run: `cd crates && cargo test -p rag-video`
Expected: PASS (9 tests)

**Step 7: Commit**

```bash
git add crates/rag-video/src/extraction/ crates/rag-video/src/lib.rs
git commit -m "feat(rag-video): add extraction types

- Add VideoMetadata, ExtractedKeyframe, AudioMetadata
- Add KeyframeConfig and AudioConfig with defaults
- Prepare for FFmpeg-based extraction"
```

---

## Task 3: Extraction Module - Metadata Probe (FFmpeg CLI)

**Files:**
- Create: `crates/rag-video/src/extraction/metadata.rs`
- Modify: `crates/rag-video/src/extraction/mod.rs`

**Note:** We use FFmpeg CLI (ffprobe) via tokio::process instead of ffmpeg-next bindings for simplicity and reliability. The bindings can be added later if needed.

**Step 1: Write the failing test**

```rust
// crates/rag-video/src/extraction/metadata.rs

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_ffprobe_output_valid() {
        let output = r#"{
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "30/1",
                    "duration": "120.5"
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac"
                }
            ],
            "format": {
                "duration": "120.500000"
            }
        }"#;

        let metadata = MetadataProbe::parse_ffprobe_output(output).unwrap();
        assert_eq!(metadata.width, 1920);
        assert_eq!(metadata.height, 1080);
        assert_eq!(metadata.codec, "h264");
        assert!(metadata.has_audio);
        assert_eq!(metadata.duration_ms, 120500);
    }

    #[test]
    fn test_parse_ffprobe_output_no_audio() {
        let output = r#"{
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "vp9",
                    "width": 1280,
                    "height": 720,
                    "r_frame_rate": "25/1",
                    "duration": "60.0"
                }
            ],
            "format": {
                "duration": "60.000000"
            }
        }"#;

        let metadata = MetadataProbe::parse_ffprobe_output(output).unwrap();
        assert!(!metadata.has_audio);
        assert_eq!(metadata.codec, "vp9");
    }

    #[test]
    fn test_parse_frame_rate() {
        assert!((MetadataProbe::parse_frame_rate("30/1") - 30.0).abs() < 0.01);
        assert!((MetadataProbe::parse_frame_rate("24000/1001") - 23.976).abs() < 0.01);
        assert!((MetadataProbe::parse_frame_rate("25") - 25.0).abs() < 0.01);
        assert!((MetadataProbe::parse_frame_rate("invalid") - 0.0).abs() < 0.01);
    }
}
```

**Step 2: Run test to verify it fails**

Run: `cd crates && cargo test -p rag-video metadata`
Expected: FAIL with "cannot find value `MetadataProbe`"

**Step 3: Create metadata.rs with implementation**

Create `crates/rag-video/src/extraction/metadata.rs`:

```rust
//! Video metadata probing using ffprobe.

use crate::error::{Result, VideoError};
use crate::extraction::VideoMetadata;
use serde::Deserialize;
use std::path::Path;
use std::process::Stdio;
use tokio::process::Command;
use tracing::{debug, instrument};

/// Video metadata probe using ffprobe.
pub struct MetadataProbe;

#[derive(Debug, Deserialize)]
struct FfprobeOutput {
    streams: Vec<StreamInfo>,
    format: FormatInfo,
}

#[derive(Debug, Deserialize)]
struct StreamInfo {
    codec_type: String,
    codec_name: Option<String>,
    width: Option<u32>,
    height: Option<u32>,
    r_frame_rate: Option<String>,
    #[serde(default)]
    duration: Option<String>,
}

#[derive(Debug, Deserialize)]
struct FormatInfo {
    duration: Option<String>,
}

impl MetadataProbe {
    /// Probe video file for metadata without full decode.
    ///
    /// Uses ffprobe to extract video metadata including duration,
    /// dimensions, codec, frame rate, and audio presence.
    ///
    /// # Errors
    ///
    /// Returns an error if:
    /// - The file does not exist
    /// - ffprobe is not available
    /// - The file is not a valid video
    #[instrument(skip_all, fields(path = %video_path.as_ref().display()))]
    pub async fn probe(video_path: impl AsRef<Path>) -> Result<VideoMetadata> {
        let path = video_path.as_ref();

        if !path.exists() {
            return Err(VideoError::FileNotFound(path.display().to_string()));
        }

        let output = Command::new("ffprobe")
            .args([
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
            ])
            .arg(path)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()
            .await
            .map_err(|e| VideoError::Ffmpeg(format!("Failed to run ffprobe: {e}")))?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(VideoError::Ffmpeg(format!("ffprobe failed: {stderr}")));
        }

        let stdout = String::from_utf8_lossy(&output.stdout);
        Self::parse_ffprobe_output(&stdout)
    }

    /// Validate that a video file is processable.
    ///
    /// # Errors
    ///
    /// Returns an error if the file cannot be processed.
    #[instrument(skip_all, fields(path = %video_path.as_ref().display()))]
    pub async fn validate(video_path: impl AsRef<Path>) -> Result<()> {
        let metadata = Self::probe(&video_path).await?;

        if metadata.duration_ms == 0 {
            return Err(VideoError::InvalidFormat("Video has zero duration".to_string()));
        }

        if metadata.width == 0 || metadata.height == 0 {
            return Err(VideoError::InvalidFormat("Video has invalid dimensions".to_string()));
        }

        debug!(
            duration_ms = metadata.duration_ms,
            width = metadata.width,
            height = metadata.height,
            "Video validated"
        );

        Ok(())
    }

    /// Parse ffprobe JSON output into VideoMetadata.
    pub(crate) fn parse_ffprobe_output(output: &str) -> Result<VideoMetadata> {
        let probe: FfprobeOutput = serde_json::from_str(output)
            .map_err(|e| VideoError::Ffmpeg(format!("Failed to parse ffprobe output: {e}")))?;

        // Find video stream
        let video_stream = probe
            .streams
            .iter()
            .find(|s| s.codec_type == "video")
            .ok_or_else(|| VideoError::InvalidFormat("No video stream found".to_string()))?;

        // Check for audio stream
        let has_audio = probe.streams.iter().any(|s| s.codec_type == "audio");

        // Parse duration from format or stream
        let duration_str = probe
            .format
            .duration
            .as_deref()
            .or(video_stream.duration.as_deref())
            .unwrap_or("0");

        let duration_secs: f64 = duration_str.parse().unwrap_or(0.0);
        #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
        let duration_ms = (duration_secs * 1000.0) as u64;

        // Parse frame rate
        let fps = video_stream
            .r_frame_rate
            .as_deref()
            .map(Self::parse_frame_rate)
            .unwrap_or(0.0);

        Ok(VideoMetadata {
            duration_ms,
            width: video_stream.width.unwrap_or(0),
            height: video_stream.height.unwrap_or(0),
            fps,
            codec: video_stream.codec_name.clone().unwrap_or_default(),
            has_audio,
        })
    }

    /// Parse frame rate string (e.g., "30/1" or "24000/1001").
    #[allow(clippy::cast_precision_loss)]
    pub(crate) fn parse_frame_rate(rate: &str) -> f32 {
        if let Some((num, den)) = rate.split_once('/') {
            let num: f64 = num.parse().unwrap_or(0.0);
            let den: f64 = den.parse().unwrap_or(1.0);
            if den > 0.0 {
                return (num / den) as f32;
            }
        }
        rate.parse().unwrap_or(0.0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_ffprobe_output_valid() {
        let output = r#"{
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "30/1",
                    "duration": "120.5"
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac"
                }
            ],
            "format": {
                "duration": "120.500000"
            }
        }"#;

        let metadata = MetadataProbe::parse_ffprobe_output(output).unwrap();
        assert_eq!(metadata.width, 1920);
        assert_eq!(metadata.height, 1080);
        assert_eq!(metadata.codec, "h264");
        assert!(metadata.has_audio);
        assert_eq!(metadata.duration_ms, 120500);
    }

    #[test]
    fn test_parse_ffprobe_output_no_audio() {
        let output = r#"{
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "vp9",
                    "width": 1280,
                    "height": 720,
                    "r_frame_rate": "25/1",
                    "duration": "60.0"
                }
            ],
            "format": {
                "duration": "60.000000"
            }
        }"#;

        let metadata = MetadataProbe::parse_ffprobe_output(output).unwrap();
        assert!(!metadata.has_audio);
        assert_eq!(metadata.codec, "vp9");
    }

    #[test]
    fn test_parse_frame_rate() {
        assert!((MetadataProbe::parse_frame_rate("30/1") - 30.0).abs() < 0.01);
        assert!((MetadataProbe::parse_frame_rate("24000/1001") - 23.976).abs() < 0.01);
        assert!((MetadataProbe::parse_frame_rate("25") - 25.0).abs() < 0.01);
        assert!((MetadataProbe::parse_frame_rate("invalid") - 0.0).abs() < 0.01);
    }
}
```

**Step 4: Update extraction/mod.rs**

```rust
//! Video extraction module.
//!
//! Provides keyframe extraction, audio extraction, and video metadata probing.

pub mod metadata;
pub mod types;

pub use metadata::MetadataProbe;
pub use types::{
    AudioConfig, AudioMetadata, ExtractedKeyframe, KeyframeConfig, VideoMetadata,
};
```

**Step 5: Run tests to verify they pass**

Run: `cd crates && cargo test -p rag-video`
Expected: PASS (12 tests)

**Step 6: Commit**

```bash
git add crates/rag-video/src/extraction/
git commit -m "feat(rag-video): add metadata probe with ffprobe

- Add MetadataProbe for video file inspection
- Parse ffprobe JSON output for metadata
- Support frame rate parsing (e.g., 30/1, 24000/1001)
- Validate video files before processing"
```

---

## Task 4: Extraction Module - Keyframe Extractor

**Files:**
- Create: `crates/rag-video/src/extraction/keyframe.rs`
- Modify: `crates/rag-video/src/extraction/mod.rs`

**Step 1: Write the failing test**

```rust
// crates/rag-video/src/extraction/keyframe.rs

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::tempdir;

    #[test]
    fn test_keyframe_extractor_new() {
        let config = KeyframeConfig::default();
        let extractor = KeyframeExtractor::new(config);
        assert_eq!(extractor.config.output_width, 1280);
    }

    #[test]
    fn test_build_ffmpeg_command() {
        let config = KeyframeConfig {
            output_width: 1280,
            output_height: 720,
            quality: 85,
            ..Default::default()
        };
        let extractor = KeyframeExtractor::new(config);

        let cmd = extractor.build_extract_command(
            Path::new("/tmp/video.mp4"),
            5.5,
            Path::new("/tmp/output/frame.jpg"),
        );

        let args: Vec<_> = cmd.as_std().get_args().collect();
        assert!(args.contains(&std::ffi::OsStr::new("-ss")));
        assert!(args.contains(&std::ffi::OsStr::new("5.5")));
        assert!(args.contains(&std::ffi::OsStr::new("-vframes")));
        assert!(args.contains(&std::ffi::OsStr::new("1")));
    }

    #[test]
    fn test_timestamp_to_filename() {
        assert_eq!(KeyframeExtractor::timestamp_to_filename(0, 0), "00000_0000.jpg");
        assert_eq!(KeyframeExtractor::timestamp_to_filename(5, 5500), "00005_5500.jpg");
        assert_eq!(KeyframeExtractor::timestamp_to_filename(100, 120000), "00100_120000.jpg");
    }
}
```

**Step 2: Run test to verify it fails**

Run: `cd crates && cargo test -p rag-video keyframe`
Expected: FAIL with "cannot find value `KeyframeExtractor`"

**Step 3: Create keyframe.rs with implementation**

Create `crates/rag-video/src/extraction/keyframe.rs`:

```rust
//! Keyframe extraction using FFmpeg.

use crate::error::{Result, VideoError};
use crate::extraction::{ExtractedKeyframe, KeyframeConfig};
use std::path::{Path, PathBuf};
use std::process::Stdio;
use tokio::process::Command;
use tracing::{debug, instrument, warn};

/// Keyframe extractor using FFmpeg.
pub struct KeyframeExtractor {
    pub(crate) config: KeyframeConfig,
}

impl KeyframeExtractor {
    /// Create a new keyframe extractor.
    #[must_use]
    pub fn new(config: KeyframeConfig) -> Self {
        Self { config }
    }

    /// Extract keyframes at specified timestamps.
    ///
    /// # Arguments
    ///
    /// * `video_path` - Path to the video file
    /// * `timestamps_ms` - List of timestamps in milliseconds
    /// * `output_dir` - Directory to store extracted frames
    ///
    /// # Errors
    ///
    /// Returns an error if extraction fails.
    #[instrument(skip(self, timestamps_ms), fields(count = timestamps_ms.len()))]
    pub async fn extract(
        &self,
        video_path: &Path,
        timestamps_ms: &[u64],
        output_dir: &Path,
    ) -> Result<Vec<ExtractedKeyframe>> {
        if !video_path.exists() {
            return Err(VideoError::FileNotFound(video_path.display().to_string()));
        }

        if !output_dir.exists() {
            tokio::fs::create_dir_all(output_dir).await?;
        }

        let mut keyframes = Vec::with_capacity(timestamps_ms.len());

        for (index, &timestamp_ms) in timestamps_ms.iter().enumerate() {
            let filename = Self::timestamp_to_filename(index as u32, timestamp_ms);
            let output_path = output_dir.join(&filename);

            match self.extract_single(video_path, timestamp_ms, &output_path, index as u32).await {
                Ok(keyframe) => keyframes.push(keyframe),
                Err(e) => {
                    warn!(
                        timestamp_ms,
                        error = %e,
                        "Failed to extract keyframe, skipping"
                    );
                }
            }
        }

        debug!(extracted = keyframes.len(), "Keyframe extraction complete");
        Ok(keyframes)
    }

    /// Extract a single keyframe at a timestamp.
    async fn extract_single(
        &self,
        video_path: &Path,
        timestamp_ms: u64,
        output_path: &Path,
        frame_index: u32,
    ) -> Result<ExtractedKeyframe> {
        let timestamp_secs = timestamp_ms as f64 / 1000.0;

        let mut cmd = self.build_extract_command(video_path, timestamp_secs, output_path);

        let output = cmd
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .output()
            .await
            .map_err(|e| VideoError::Ffmpeg(format!("Failed to run ffmpeg: {e}")))?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(VideoError::Ffmpeg(format!(
                "ffmpeg extraction failed at {timestamp_ms}ms: {stderr}"
            )));
        }

        if !output_path.exists() {
            return Err(VideoError::Ffmpeg(format!(
                "Output file not created at {timestamp_ms}ms"
            )));
        }

        // Get file metadata
        let file_meta = tokio::fs::metadata(output_path).await?;

        // Extract thumbnail if configured
        let thumbnail_path = if self.config.generate_thumbnails {
            let thumb_path = Self::thumbnail_path(output_path);
            match self.generate_thumbnail(output_path, &thumb_path).await {
                Ok(()) => Some(thumb_path),
                Err(e) => {
                    warn!(error = %e, "Failed to generate thumbnail");
                    None
                }
            }
        } else {
            None
        };

        Ok(ExtractedKeyframe {
            frame_index,
            timestamp_ms,
            image_path: output_path.to_path_buf(),
            thumbnail_path,
            width: self.config.output_width,
            height: self.config.output_height,
            file_size_bytes: file_meta.len(),
            is_scene_boundary: true, // Caller can override
        })
    }

    /// Build the FFmpeg command for extraction.
    pub(crate) fn build_extract_command(
        &self,
        video_path: &Path,
        timestamp_secs: f64,
        output_path: &Path,
    ) -> Command {
        let scale_filter = format!(
            "scale='min({},iw)':'min({},ih)':force_original_aspect_ratio=decrease",
            self.config.output_width, self.config.output_height
        );

        // Convert quality (1-100) to FFmpeg qscale (1-31, lower is better)
        let qscale = 31 - (self.config.quality as u32 * 30 / 100);

        let mut cmd = Command::new("ffmpeg");
        cmd.args([
            "-ss", &format!("{timestamp_secs}"),
            "-i", video_path.to_str().unwrap_or(""),
            "-vframes", "1",
            "-vf", &scale_filter,
            "-q:v", &qscale.to_string(),
            "-y",
        ])
        .arg(output_path);

        cmd
    }

    /// Generate a thumbnail from an image.
    async fn generate_thumbnail(&self, image_path: &Path, thumb_path: &Path) -> Result<()> {
        let scale_filter = format!(
            "scale={}:{}:force_original_aspect_ratio=decrease",
            self.config.thumbnail_width, self.config.thumbnail_height
        );

        let output = Command::new("ffmpeg")
            .args([
                "-i", image_path.to_str().unwrap_or(""),
                "-vf", &scale_filter,
                "-q:v", "5",
                "-y",
            ])
            .arg(thumb_path)
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .output()
            .await
            .map_err(|e| VideoError::Ffmpeg(format!("Failed to generate thumbnail: {e}")))?;

        if !output.status.success() {
            return Err(VideoError::Ffmpeg("Thumbnail generation failed".to_string()));
        }

        Ok(())
    }

    /// Generate filename from frame index and timestamp.
    #[must_use]
    pub fn timestamp_to_filename(index: u32, timestamp_ms: u64) -> String {
        format!("{index:05}_{timestamp_ms}.jpg")
    }

    /// Get thumbnail path from image path.
    fn thumbnail_path(image_path: &Path) -> PathBuf {
        let stem = image_path.file_stem().unwrap_or_default().to_str().unwrap_or("");
        image_path.with_file_name(format!("{stem}_thumb.jpg"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_keyframe_extractor_new() {
        let config = KeyframeConfig::default();
        let extractor = KeyframeExtractor::new(config);
        assert_eq!(extractor.config.output_width, 1280);
    }

    #[test]
    fn test_build_ffmpeg_command() {
        let config = KeyframeConfig {
            output_width: 1280,
            output_height: 720,
            quality: 85,
            ..Default::default()
        };
        let extractor = KeyframeExtractor::new(config);

        let cmd = extractor.build_extract_command(
            Path::new("/tmp/video.mp4"),
            5.5,
            Path::new("/tmp/output/frame.jpg"),
        );

        let args: Vec<_> = cmd.as_std().get_args().collect();
        assert!(args.contains(&std::ffi::OsStr::new("-ss")));
        assert!(args.contains(&std::ffi::OsStr::new("5.5")));
        assert!(args.contains(&std::ffi::OsStr::new("-vframes")));
        assert!(args.contains(&std::ffi::OsStr::new("1")));
    }

    #[test]
    fn test_timestamp_to_filename() {
        assert_eq!(KeyframeExtractor::timestamp_to_filename(0, 0), "00000_0.jpg");
        assert_eq!(KeyframeExtractor::timestamp_to_filename(5, 5500), "00005_5500.jpg");
        assert_eq!(KeyframeExtractor::timestamp_to_filename(100, 120000), "00100_120000.jpg");
    }

    #[test]
    fn test_thumbnail_path() {
        let image = Path::new("/tmp/frames/00001_5000.jpg");
        let thumb = KeyframeExtractor::thumbnail_path(image);
        assert_eq!(thumb, PathBuf::from("/tmp/frames/00001_5000_thumb.jpg"));
    }
}
```

**Step 4: Update extraction/mod.rs**

```rust
//! Video extraction module.
//!
//! Provides keyframe extraction, audio extraction, and video metadata probing.

pub mod keyframe;
pub mod metadata;
pub mod types;

pub use keyframe::KeyframeExtractor;
pub use metadata::MetadataProbe;
pub use types::{
    AudioConfig, AudioMetadata, ExtractedKeyframe, KeyframeConfig, VideoMetadata,
};
```

**Step 5: Run tests to verify they pass**

Run: `cd crates && cargo test -p rag-video`
Expected: PASS (16 tests)

**Step 6: Commit**

```bash
git add crates/rag-video/src/extraction/
git commit -m "feat(rag-video): add keyframe extractor

- Add KeyframeExtractor using FFmpeg CLI
- Support batch extraction at timestamps
- Generate thumbnails optionally
- Convert quality to FFmpeg qscale"
```

---

## Task 5: Extraction Module - Audio Extractor

**Files:**
- Create: `crates/rag-video/src/extraction/audio.rs`
- Modify: `crates/rag-video/src/extraction/mod.rs`

**Step 1: Write the failing test**

```rust
// crates/rag-video/src/extraction/audio.rs

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_audio_extractor_new() {
        let config = AudioConfig::default();
        let extractor = AudioExtractor::new(config);
        assert_eq!(extractor.config.sample_rate, 16000);
        assert_eq!(extractor.config.channels, 1);
    }

    #[test]
    fn test_build_ffmpeg_command() {
        let config = AudioConfig {
            sample_rate: 16000,
            channels: 1,
            format: "wav".to_string(),
        };
        let extractor = AudioExtractor::new(config);

        let cmd = extractor.build_extract_command(
            Path::new("/tmp/video.mp4"),
            Path::new("/tmp/audio.wav"),
        );

        let args: Vec<_> = cmd.as_std().get_args().collect();
        assert!(args.contains(&std::ffi::OsStr::new("-ar")));
        assert!(args.contains(&std::ffi::OsStr::new("16000")));
        assert!(args.contains(&std::ffi::OsStr::new("-ac")));
        assert!(args.contains(&std::ffi::OsStr::new("1")));
        assert!(args.contains(&std::ffi::OsStr::new("-vn")));
    }

    #[test]
    fn test_audio_config_with_custom_values() {
        let config = AudioConfig {
            sample_rate: 44100,
            channels: 2,
            format: "mp3".to_string(),
        };
        assert_eq!(config.sample_rate, 44100);
        assert_eq!(config.channels, 2);
    }
}
```

**Step 2: Run test to verify it fails**

Run: `cd crates && cargo test -p rag-video audio`
Expected: FAIL with "cannot find value `AudioExtractor`"

**Step 3: Create audio.rs with implementation**

Create `crates/rag-video/src/extraction/audio.rs`:

```rust
//! Audio extraction using FFmpeg.

use crate::error::{Result, VideoError};
use crate::extraction::{AudioConfig, AudioMetadata};
use std::path::Path;
use std::process::Stdio;
use tokio::process::Command;
use tracing::{debug, instrument};

/// Audio extractor using FFmpeg.
pub struct AudioExtractor {
    pub(crate) config: AudioConfig,
}

impl AudioExtractor {
    /// Create a new audio extractor.
    #[must_use]
    pub fn new(config: AudioConfig) -> Self {
        Self { config }
    }

    /// Extract audio track from video to a separate file.
    ///
    /// # Arguments
    ///
    /// * `video_path` - Path to the video file
    /// * `output_path` - Path for the output audio file
    ///
    /// # Errors
    ///
    /// Returns an error if extraction fails or video has no audio.
    #[instrument(skip(self), fields(
        video = %video_path.as_ref().display(),
        output = %output_path.as_ref().display()
    ))]
    pub async fn extract(
        &self,
        video_path: impl AsRef<Path>,
        output_path: impl AsRef<Path>,
    ) -> Result<AudioMetadata> {
        let video_path = video_path.as_ref();
        let output_path = output_path.as_ref();

        if !video_path.exists() {
            return Err(VideoError::FileNotFound(video_path.display().to_string()));
        }

        // Create parent directory if needed
        if let Some(parent) = output_path.parent() {
            if !parent.exists() {
                tokio::fs::create_dir_all(parent).await?;
            }
        }

        let mut cmd = self.build_extract_command(video_path, output_path);

        let output = cmd
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .output()
            .await
            .map_err(|e| VideoError::Ffmpeg(format!("Failed to run ffmpeg: {e}")))?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            // Check for common "no audio" errors
            if stderr.contains("does not contain any stream")
                || stderr.contains("Output file #0 does not contain any stream")
            {
                return Err(VideoError::InvalidFormat("Video has no audio track".to_string()));
            }
            return Err(VideoError::Ffmpeg(format!("Audio extraction failed: {stderr}")));
        }

        if !output_path.exists() {
            return Err(VideoError::Ffmpeg("Output audio file not created".to_string()));
        }

        // Get file metadata
        let file_meta = tokio::fs::metadata(output_path).await?;

        // Probe the output file to get duration
        let duration_ms = self.probe_audio_duration(output_path).await.unwrap_or(0);

        let metadata = AudioMetadata {
            duration_ms,
            sample_rate: self.config.sample_rate,
            channels: self.config.channels,
            file_size_bytes: file_meta.len(),
        };

        debug!(
            duration_ms = metadata.duration_ms,
            file_size = metadata.file_size_bytes,
            "Audio extraction complete"
        );

        Ok(metadata)
    }

    /// Build the FFmpeg command for audio extraction.
    pub(crate) fn build_extract_command(&self, video_path: &Path, output_path: &Path) -> Command {
        let mut cmd = Command::new("ffmpeg");
        cmd.args([
            "-i", video_path.to_str().unwrap_or(""),
            "-vn", // No video
            "-acodec", "pcm_s16le", // 16-bit PCM for WAV
            "-ar", &self.config.sample_rate.to_string(),
            "-ac", &self.config.channels.to_string(),
            "-y", // Overwrite
        ])
        .arg(output_path);

        cmd
    }

    /// Probe audio file duration using ffprobe.
    async fn probe_audio_duration(&self, audio_path: &Path) -> Result<u64> {
        let output = Command::new("ffprobe")
            .args([
                "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
            ])
            .arg(audio_path)
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .output()
            .await
            .map_err(|e| VideoError::Ffmpeg(format!("Failed to probe audio: {e}")))?;

        if !output.status.success() {
            return Err(VideoError::Ffmpeg("Failed to probe audio duration".to_string()));
        }

        let stdout = String::from_utf8_lossy(&output.stdout);
        let duration_secs: f64 = stdout.trim().parse().unwrap_or(0.0);

        #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
        Ok((duration_secs * 1000.0) as u64)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_audio_extractor_new() {
        let config = AudioConfig::default();
        let extractor = AudioExtractor::new(config);
        assert_eq!(extractor.config.sample_rate, 16000);
        assert_eq!(extractor.config.channels, 1);
    }

    #[test]
    fn test_build_ffmpeg_command() {
        let config = AudioConfig {
            sample_rate: 16000,
            channels: 1,
            format: "wav".to_string(),
        };
        let extractor = AudioExtractor::new(config);

        let cmd = extractor.build_extract_command(
            Path::new("/tmp/video.mp4"),
            Path::new("/tmp/audio.wav"),
        );

        let args: Vec<_> = cmd.as_std().get_args().collect();
        assert!(args.contains(&std::ffi::OsStr::new("-ar")));
        assert!(args.contains(&std::ffi::OsStr::new("16000")));
        assert!(args.contains(&std::ffi::OsStr::new("-ac")));
        assert!(args.contains(&std::ffi::OsStr::new("1")));
        assert!(args.contains(&std::ffi::OsStr::new("-vn")));
    }

    #[test]
    fn test_audio_config_with_custom_values() {
        let config = AudioConfig {
            sample_rate: 44100,
            channels: 2,
            format: "mp3".to_string(),
        };
        assert_eq!(config.sample_rate, 44100);
        assert_eq!(config.channels, 2);
    }
}
```

**Step 4: Update extraction/mod.rs**

```rust
//! Video extraction module.
//!
//! Provides keyframe extraction, audio extraction, and video metadata probing.

pub mod audio;
pub mod keyframe;
pub mod metadata;
pub mod types;

pub use audio::AudioExtractor;
pub use keyframe::KeyframeExtractor;
pub use metadata::MetadataProbe;
pub use types::{
    AudioConfig, AudioMetadata, ExtractedKeyframe, KeyframeConfig, VideoMetadata,
};
```

**Step 5: Run tests to verify they pass**

Run: `cd crates && cargo test -p rag-video`
Expected: PASS (19 tests)

**Step 6: Commit**

```bash
git add crates/rag-video/src/extraction/
git commit -m "feat(rag-video): add audio extractor

- Add AudioExtractor using FFmpeg CLI
- Extract to 16kHz mono WAV (Whisper optimal)
- Probe duration after extraction
- Handle videos without audio track"
```

---

## Task 6: HTTP Clients - Scene Detection Client

**Files:**
- Create: `crates/rag-video/src/clients/mod.rs`
- Create: `crates/rag-video/src/clients/types.rs`
- Create: `crates/rag-video/src/clients/scene_detection.rs`
- Modify: `crates/rag-video/src/lib.rs`

**Step 1: Write the failing test**

```rust
// crates/rag-video/src/clients/scene_detection.rs

#[cfg(test)]
mod tests {
    use super::*;
    use wiremock::matchers::{method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    #[tokio::test]
    async fn test_scene_detection_client_detect() {
        let mock_server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/detect"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "scenes": [
                    {"scene_index": 0, "start_ms": 0, "end_ms": 5000, "is_detected": true},
                    {"scene_index": 1, "start_ms": 5000, "end_ms": 10000, "is_detected": true}
                ],
                "total_frames": 300,
                "fps": 30.0,
                "duration_seconds": 10.0,
                "detection_method": "content"
            })))
            .mount(&mock_server)
            .await;

        let config = SceneDetectionConfig {
            base_url: mock_server.uri(),
            ..Default::default()
        };
        let client = SceneDetectionClient::new(config);

        let result = client.detect(Path::new("/tmp/test.mp4")).await.unwrap();
        assert_eq!(result.scenes.len(), 2);
        assert_eq!(result.detection_method, "content");
        assert_eq!(result.fps, 30.0);
    }

    #[tokio::test]
    async fn test_scene_detection_client_health() {
        let mock_server = MockServer::start().await;

        Mock::given(method("GET"))
            .and(path("/health"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "status": "healthy"
            })))
            .mount(&mock_server)
            .await;

        let config = SceneDetectionConfig {
            base_url: mock_server.uri(),
            ..Default::default()
        };
        let client = SceneDetectionClient::new(config);

        assert!(client.health().await.unwrap());
    }

    #[test]
    fn test_scene_detection_config_default() {
        let config = SceneDetectionConfig::default();
        assert_eq!(config.threshold, 27.0);
        assert_eq!(config.timeout_seconds, 120);
        assert_eq!(config.min_scene_len_frames, 15);
    }
}
```

**Step 2: Run test to verify it fails**

Run: `cd crates && cargo test -p rag-video scene_detection`
Expected: FAIL with "failed to resolve: use of undeclared crate or module `clients`"

**Step 3: Create clients module**

Create `crates/rag-video/src/clients/mod.rs`:

```rust
//! HTTP clients for video processing microservices.
//!
//! Provides clients for:
//! - Scene detection service (PySceneDetect wrapper)
//! - Transcription service (Whisper wrapper)

pub mod scene_detection;
pub mod types;

pub use scene_detection::{SceneDetectionClient, SceneDetectionConfig, SceneDetectionResult};
pub use types::{SceneBoundary, TranscriptSegment};
```

**Step 4: Create types.rs**

Create `crates/rag-video/src/clients/types.rs`:

```rust
//! Shared types for video processing clients.

use serde::{Deserialize, Serialize};

/// A detected scene boundary.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SceneBoundary {
    /// Scene index (0-indexed).
    pub scene_index: u32,
    /// Start time in milliseconds.
    pub start_ms: u64,
    /// End time in milliseconds.
    pub end_ms: u64,
    /// Whether detected by algorithm or fallback.
    pub is_detected: bool,
}

impl SceneBoundary {
    /// Get scene duration in milliseconds.
    #[must_use]
    pub fn duration_ms(&self) -> u64 {
        self.end_ms - self.start_ms
    }

    /// Get midpoint time in milliseconds.
    #[must_use]
    pub fn mid_ms(&self) -> u64 {
        (self.start_ms + self.end_ms) / 2
    }
}

/// A transcript segment with timing.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TranscriptSegment {
    /// Start time in milliseconds.
    pub start_ms: u64,
    /// End time in milliseconds.
    pub end_ms: u64,
    /// Transcribed text.
    pub text: String,
    /// Confidence score (0-1).
    pub confidence: Option<f32>,
}

impl TranscriptSegment {
    /// Get segment duration in milliseconds.
    #[must_use]
    pub fn duration_ms(&self) -> u64 {
        self.end_ms - self.start_ms
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_scene_boundary_duration() {
        let scene = SceneBoundary {
            scene_index: 0,
            start_ms: 1000,
            end_ms: 5000,
            is_detected: true,
        };
        assert_eq!(scene.duration_ms(), 4000);
        assert_eq!(scene.mid_ms(), 3000);
    }

    #[test]
    fn test_transcript_segment_duration() {
        let segment = TranscriptSegment {
            start_ms: 0,
            end_ms: 2500,
            text: "Hello world".to_string(),
            confidence: Some(0.95),
        };
        assert_eq!(segment.duration_ms(), 2500);
    }
}
```

**Step 5: Create scene_detection.rs**

Create `crates/rag-video/src/clients/scene_detection.rs`:

```rust
//! HTTP client for scene detection service.

use crate::clients::SceneBoundary;
use crate::error::{Result, VideoError};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::path::Path;
use std::time::Duration;
use tracing::{debug, instrument};

/// Configuration for scene detection client.
#[derive(Debug, Clone)]
pub struct SceneDetectionConfig {
    /// Base URL of the scene detection service.
    pub base_url: String,
    /// Request timeout in seconds.
    pub timeout_seconds: u64,
    /// Content detector threshold.
    pub threshold: f32,
    /// Minimum scene length in frames.
    pub min_scene_len_frames: u32,
    /// Fallback interval for static videos.
    pub fallback_interval_seconds: f32,
}

impl Default for SceneDetectionConfig {
    fn default() -> Self {
        Self {
            base_url: "http://localhost:8010".to_string(),
            timeout_seconds: 120,
            threshold: 27.0,
            min_scene_len_frames: 15,
            fallback_interval_seconds: 5.0,
        }
    }
}

/// Result of scene detection.
#[derive(Debug, Clone)]
pub struct SceneDetectionResult {
    /// Detected scene boundaries.
    pub scenes: Vec<SceneBoundary>,
    /// Total frames in video.
    pub total_frames: u64,
    /// Video frame rate.
    pub fps: f32,
    /// Video duration in milliseconds.
    pub duration_ms: u64,
    /// Detection method used ("content" or "fallback").
    pub detection_method: String,
}

/// HTTP client for scene detection service.
pub struct SceneDetectionClient {
    client: Client,
    config: SceneDetectionConfig,
}

#[derive(Serialize)]
struct DetectRequest {
    video_path: String,
    threshold: f32,
    min_scene_len_frames: u32,
    fallback_interval_seconds: f32,
}

#[derive(Deserialize)]
struct DetectResponse {
    scenes: Vec<SceneBoundary>,
    total_frames: u64,
    fps: f32,
    duration_seconds: f64,
    detection_method: String,
}

#[derive(Deserialize)]
struct HealthResponse {
    status: String,
}

impl SceneDetectionClient {
    /// Create a new scene detection client.
    #[must_use]
    pub fn new(config: SceneDetectionConfig) -> Self {
        let client = Client::builder()
            .timeout(Duration::from_secs(config.timeout_seconds))
            .build()
            .expect("Failed to build HTTP client");

        Self { client, config }
    }

    /// Detect scene boundaries in a video.
    ///
    /// # Errors
    ///
    /// Returns an error if the request fails or service returns an error.
    #[instrument(skip(self), fields(path = %video_path.as_ref().display()))]
    pub async fn detect(&self, video_path: impl AsRef<Path>) -> Result<SceneDetectionResult> {
        let url = format!("{}/detect", self.config.base_url);

        let request = DetectRequest {
            video_path: video_path.as_ref().display().to_string(),
            threshold: self.config.threshold,
            min_scene_len_frames: self.config.min_scene_len_frames,
            fallback_interval_seconds: self.config.fallback_interval_seconds,
        };

        let response = self
            .client
            .post(&url)
            .json(&request)
            .send()
            .await
            .map_err(|e| VideoError::SceneDetection(format!("Request failed: {e}")))?;

        let status = response.status();
        if !status.is_success() {
            let body = response.text().await.unwrap_or_default();
            return Err(VideoError::SceneDetection(format!(
                "Service returned {status}: {body}"
            )));
        }

        let response: DetectResponse = response
            .json()
            .await
            .map_err(|e| VideoError::SceneDetection(format!("Invalid response: {e}")))?;

        #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
        let duration_ms = (response.duration_seconds * 1000.0) as u64;

        debug!(
            scenes = response.scenes.len(),
            method = %response.detection_method,
            "Scene detection complete"
        );

        Ok(SceneDetectionResult {
            scenes: response.scenes,
            total_frames: response.total_frames,
            fps: response.fps,
            duration_ms,
            detection_method: response.detection_method,
        })
    }

    /// Check service health.
    ///
    /// # Errors
    ///
    /// Returns an error if the health check fails.
    pub async fn health(&self) -> Result<bool> {
        let url = format!("{}/health", self.config.base_url);

        let response = self
            .client
            .get(&url)
            .send()
            .await
            .map_err(|e| VideoError::SceneDetection(format!("Health check failed: {e}")))?;

        if !response.status().is_success() {
            return Ok(false);
        }

        let body: HealthResponse = response
            .json()
            .await
            .map_err(|e| VideoError::SceneDetection(format!("Invalid health response: {e}")))?;

        Ok(body.status == "healthy")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use wiremock::matchers::{method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    #[tokio::test]
    async fn test_scene_detection_client_detect() {
        let mock_server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/detect"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "scenes": [
                    {"scene_index": 0, "start_ms": 0, "end_ms": 5000, "is_detected": true},
                    {"scene_index": 1, "start_ms": 5000, "end_ms": 10000, "is_detected": true}
                ],
                "total_frames": 300,
                "fps": 30.0,
                "duration_seconds": 10.0,
                "detection_method": "content"
            })))
            .mount(&mock_server)
            .await;

        let config = SceneDetectionConfig {
            base_url: mock_server.uri(),
            ..Default::default()
        };
        let client = SceneDetectionClient::new(config);

        let result = client.detect(Path::new("/tmp/test.mp4")).await.unwrap();
        assert_eq!(result.scenes.len(), 2);
        assert_eq!(result.detection_method, "content");
        assert_eq!(result.fps, 30.0);
    }

    #[tokio::test]
    async fn test_scene_detection_client_health() {
        let mock_server = MockServer::start().await;

        Mock::given(method("GET"))
            .and(path("/health"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "status": "healthy"
            })))
            .mount(&mock_server)
            .await;

        let config = SceneDetectionConfig {
            base_url: mock_server.uri(),
            ..Default::default()
        };
        let client = SceneDetectionClient::new(config);

        assert!(client.health().await.unwrap());
    }

    #[test]
    fn test_scene_detection_config_default() {
        let config = SceneDetectionConfig::default();
        assert_eq!(config.threshold, 27.0);
        assert_eq!(config.timeout_seconds, 120);
        assert_eq!(config.min_scene_len_frames, 15);
    }
}
```

**Step 6: Update lib.rs**

```rust
//! Video processing pipeline for RAG.
//!
//! This crate provides video processing capabilities including:
//! - Keyframe and audio extraction (FFmpeg)
//! - OCR text extraction (Tesseract)
//! - Scene detection and transcription (HTTP clients to Python services)
//! - Content fusion (combining transcript, scene descriptions, OCR)
//! - Video chunk indexing (Qdrant)
//! - Pipeline orchestration

pub mod clients;
pub mod error;
pub mod extraction;

pub use error::{Result, VideoError};
```

**Step 7: Run tests to verify they pass**

Run: `cd crates && cargo test -p rag-video`
Expected: PASS (24 tests)

**Step 8: Commit**

```bash
git add crates/rag-video/src/clients/ crates/rag-video/src/lib.rs
git commit -m "feat(rag-video): add scene detection HTTP client

- Add SceneDetectionClient for PySceneDetect service
- Add SceneBoundary and TranscriptSegment types
- Configure threshold, min scene length, fallback interval
- Include health check endpoint"
```

---

## Task 7: HTTP Clients - Transcription Client

**Files:**
- Create: `crates/rag-video/src/clients/transcription.rs`
- Modify: `crates/rag-video/src/clients/mod.rs`

**Step 1: Write the failing test**

```rust
// crates/rag-video/src/clients/transcription.rs

#[cfg(test)]
mod tests {
    use super::*;
    use wiremock::matchers::{method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    #[tokio::test]
    async fn test_transcription_client_transcribe() {
        let mock_server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/transcribe"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "segments": [
                    {"start_ms": 0, "end_ms": 2000, "text": "Hello world", "confidence": 0.95},
                    {"start_ms": 2000, "end_ms": 4000, "text": "How are you", "confidence": 0.92}
                ],
                "language": "en",
                "duration_seconds": 4.0
            })))
            .mount(&mock_server)
            .await;

        let config = TranscriptionConfig {
            base_url: mock_server.uri(),
            ..Default::default()
        };
        let client = TranscriptionClient::new(config);

        let result = client.transcribe(Path::new("/tmp/audio.wav")).await.unwrap();
        assert_eq!(result.segments.len(), 2);
        assert_eq!(result.language, "en");
        assert_eq!(result.segments[0].text, "Hello world");
    }

    #[tokio::test]
    async fn test_transcription_client_health() {
        let mock_server = MockServer::start().await;

        Mock::given(method("GET"))
            .and(path("/health"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "status": "healthy"
            })))
            .mount(&mock_server)
            .await;

        let config = TranscriptionConfig {
            base_url: mock_server.uri(),
            ..Default::default()
        };
        let client = TranscriptionClient::new(config);

        assert!(client.health().await.unwrap());
    }

    #[test]
    fn test_transcription_config_default() {
        let config = TranscriptionConfig::default();
        assert_eq!(config.model, "base");
        assert_eq!(config.timeout_seconds, 300);
        assert!(config.language.is_none());
    }
}
```

**Step 2: Run test to verify it fails**

Run: `cd crates && cargo test -p rag-video transcription`
Expected: FAIL with "cannot find value `TranscriptionClient`"

**Step 3: Create transcription.rs**

Create `crates/rag-video/src/clients/transcription.rs`:

```rust
//! HTTP client for transcription service.

use crate::clients::TranscriptSegment;
use crate::error::{Result, VideoError};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::path::Path;
use std::time::Duration;
use tracing::{debug, instrument};

/// Configuration for transcription client.
#[derive(Debug, Clone)]
pub struct TranscriptionConfig {
    /// Base URL of the transcription service.
    pub base_url: String,
    /// Request timeout in seconds.
    pub timeout_seconds: u64,
    /// Whisper model to use.
    pub model: String,
    /// Language code (None for auto-detect).
    pub language: Option<String>,
}

impl Default for TranscriptionConfig {
    fn default() -> Self {
        Self {
            base_url: "http://localhost:8011".to_string(),
            timeout_seconds: 300, // 5 minutes for long videos
            model: "base".to_string(),
            language: None,
        }
    }
}

/// Result of transcription.
#[derive(Debug, Clone)]
pub struct TranscriptionResult {
    /// Transcript segments with timing.
    pub segments: Vec<TranscriptSegment>,
    /// Detected or specified language.
    pub language: String,
    /// Audio duration in milliseconds.
    pub duration_ms: u64,
}

/// HTTP client for transcription service.
pub struct TranscriptionClient {
    client: Client,
    config: TranscriptionConfig,
}

#[derive(Serialize)]
struct TranscribeRequest {
    audio_path: String,
    model: String,
    language: Option<String>,
}

#[derive(Deserialize)]
struct TranscribeResponse {
    segments: Vec<TranscriptSegment>,
    language: String,
    duration_seconds: f64,
}

#[derive(Deserialize)]
struct HealthResponse {
    status: String,
}

impl TranscriptionClient {
    /// Create a new transcription client.
    #[must_use]
    pub fn new(config: TranscriptionConfig) -> Self {
        let client = Client::builder()
            .timeout(Duration::from_secs(config.timeout_seconds))
            .build()
            .expect("Failed to build HTTP client");

        Self { client, config }
    }

    /// Transcribe an audio file.
    ///
    /// # Errors
    ///
    /// Returns an error if the request fails or service returns an error.
    #[instrument(skip(self), fields(path = %audio_path.as_ref().display()))]
    pub async fn transcribe(&self, audio_path: impl AsRef<Path>) -> Result<TranscriptionResult> {
        let url = format!("{}/transcribe", self.config.base_url);

        let request = TranscribeRequest {
            audio_path: audio_path.as_ref().display().to_string(),
            model: self.config.model.clone(),
            language: self.config.language.clone(),
        };

        let response = self
            .client
            .post(&url)
            .json(&request)
            .send()
            .await
            .map_err(|e| VideoError::Transcription(format!("Request failed: {e}")))?;

        let status = response.status();
        if !status.is_success() {
            let body = response.text().await.unwrap_or_default();
            return Err(VideoError::Transcription(format!(
                "Service returned {status}: {body}"
            )));
        }

        let response: TranscribeResponse = response
            .json()
            .await
            .map_err(|e| VideoError::Transcription(format!("Invalid response: {e}")))?;

        #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
        let duration_ms = (response.duration_seconds * 1000.0) as u64;

        debug!(
            segments = response.segments.len(),
            language = %response.language,
            "Transcription complete"
        );

        Ok(TranscriptionResult {
            segments: response.segments,
            language: response.language,
            duration_ms,
        })
    }

    /// Check service health.
    ///
    /// # Errors
    ///
    /// Returns an error if the health check fails.
    pub async fn health(&self) -> Result<bool> {
        let url = format!("{}/health", self.config.base_url);

        let response = self
            .client
            .get(&url)
            .send()
            .await
            .map_err(|e| VideoError::Transcription(format!("Health check failed: {e}")))?;

        if !response.status().is_success() {
            return Ok(false);
        }

        let body: HealthResponse = response
            .json()
            .await
            .map_err(|e| VideoError::Transcription(format!("Invalid health response: {e}")))?;

        Ok(body.status == "healthy")
    }

    /// Get full transcript text from segments.
    #[must_use]
    pub fn full_text(result: &TranscriptionResult) -> String {
        result
            .segments
            .iter()
            .map(|s| s.text.as_str())
            .collect::<Vec<_>>()
            .join(" ")
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use wiremock::matchers::{method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    #[tokio::test]
    async fn test_transcription_client_transcribe() {
        let mock_server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/transcribe"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "segments": [
                    {"start_ms": 0, "end_ms": 2000, "text": "Hello world", "confidence": 0.95},
                    {"start_ms": 2000, "end_ms": 4000, "text": "How are you", "confidence": 0.92}
                ],
                "language": "en",
                "duration_seconds": 4.0
            })))
            .mount(&mock_server)
            .await;

        let config = TranscriptionConfig {
            base_url: mock_server.uri(),
            ..Default::default()
        };
        let client = TranscriptionClient::new(config);

        let result = client.transcribe(Path::new("/tmp/audio.wav")).await.unwrap();
        assert_eq!(result.segments.len(), 2);
        assert_eq!(result.language, "en");
        assert_eq!(result.segments[0].text, "Hello world");
    }

    #[tokio::test]
    async fn test_transcription_client_health() {
        let mock_server = MockServer::start().await;

        Mock::given(method("GET"))
            .and(path("/health"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "status": "healthy"
            })))
            .mount(&mock_server)
            .await;

        let config = TranscriptionConfig {
            base_url: mock_server.uri(),
            ..Default::default()
        };
        let client = TranscriptionClient::new(config);

        assert!(client.health().await.unwrap());
    }

    #[test]
    fn test_transcription_config_default() {
        let config = TranscriptionConfig::default();
        assert_eq!(config.model, "base");
        assert_eq!(config.timeout_seconds, 300);
        assert!(config.language.is_none());
    }

    #[test]
    fn test_full_text() {
        let result = TranscriptionResult {
            segments: vec![
                TranscriptSegment {
                    start_ms: 0,
                    end_ms: 1000,
                    text: "Hello".to_string(),
                    confidence: None,
                },
                TranscriptSegment {
                    start_ms: 1000,
                    end_ms: 2000,
                    text: "world".to_string(),
                    confidence: None,
                },
            ],
            language: "en".to_string(),
            duration_ms: 2000,
        };

        assert_eq!(TranscriptionClient::full_text(&result), "Hello world");
    }
}
```

**Step 4: Update clients/mod.rs**

```rust
//! HTTP clients for video processing microservices.
//!
//! Provides clients for:
//! - Scene detection service (PySceneDetect wrapper)
//! - Transcription service (Whisper wrapper)

pub mod scene_detection;
pub mod transcription;
pub mod types;

pub use scene_detection::{SceneDetectionClient, SceneDetectionConfig, SceneDetectionResult};
pub use transcription::{TranscriptionClient, TranscriptionConfig, TranscriptionResult};
pub use types::{SceneBoundary, TranscriptSegment};
```

**Step 5: Run tests to verify they pass**

Run: `cd crates && cargo test -p rag-video`
Expected: PASS (28 tests)

**Step 6: Commit**

```bash
git add crates/rag-video/src/clients/
git commit -m "feat(rag-video): add transcription HTTP client

- Add TranscriptionClient for Whisper service
- Support model selection and language specification
- Include health check endpoint
- Add full_text helper for concatenating segments"
```

---

This plan continues with more tasks. Due to length, I'll summarize the remaining tasks:

## Remaining Tasks (8-14)

### Task 8: Content Fusion Types
- Create `crates/rag-video/src/fusion/mod.rs`
- Create `crates/rag-video/src/fusion/types.rs` with `VideoChunk`, `KeyframeWithContent`
- Create `crates/rag-video/src/fusion/config.rs` with `FusionConfig`

### Task 9: Content Fusion Service
- Create `crates/rag-video/src/fusion/service.rs`
- Implement `ContentFusionService::create_chunks()`
- Implement chunk boundary generation with overlap
- Implement modality fusion with labels

### Task 10: Video Indexer Config and Types
- Create `crates/rag-video/src/indexer/mod.rs`
- Create `crates/rag-video/src/indexer/config.rs` with `VideoIndexerConfig`
- Create `crates/rag-video/src/indexer/types.rs` with `VideoChunkPayload`, `IndexResult`, `SearchHit`

### Task 11: Video Qdrant Indexer
- Create `crates/rag-video/src/indexer/service.rs`
- Implement `VideoQdrantIndexer` with collection management
- Implement batch upsert with progress callback
- Implement search with ACL filtering

### Task 12: Pipeline Stages and Config
- Create `crates/rag-video/src/pipeline/mod.rs`
- Create `crates/rag-video/src/pipeline/stages.rs` with `PipelineStage` enum
- Create `crates/rag-video/src/pipeline/config.rs` with `PipelineConfig`

### Task 13: Pipeline Executor Types
- Create `crates/rag-video/src/pipeline/types.rs` with `PipelineResult`, `ProgressCallback`

### Task 14: Pipeline Executor Implementation
- Create `crates/rag-video/src/pipeline/executor.rs`
- Implement `VideoPipeline::process()` with parallel stages
- Wire up all components
- Implement progress tracking

---

**Plan complete and saved to `docs/plans/2025-01-27-rag-video-implementation.md`. Two execution options:**

**1. Subagent-Driven (this session)** - I dispatch fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** - Open new session with executing-plans, batch execution with checkpoints

**Which approach?**