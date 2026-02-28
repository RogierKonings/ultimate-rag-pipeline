//! Metadata extraction from video files using ffprobe.

use crate::error::VideoError;
use crate::extraction::VideoMetadata;
use crate::Result;
use serde::Deserialize;
use std::path::Path;
use std::process::Stdio;
use tokio::process::Command;
use tracing::{debug, instrument};

/// Video metadata probe using ffprobe.
pub struct MetadataProbe;

/// ffprobe stream information.
#[derive(Debug, Deserialize)]
struct FfprobeStream {
    codec_type: String,
    #[serde(default)]
    codec_name: String,
    #[serde(default)]
    width: Option<u32>,
    #[serde(default)]
    height: Option<u32>,
    #[serde(default)]
    r_frame_rate: Option<String>,
}

/// ffprobe format information.
#[derive(Debug, Deserialize)]
struct FfprobeFormat {
    #[serde(default)]
    duration: Option<String>,
}

/// ffprobe output structure.
#[derive(Debug, Deserialize)]
struct FfprobeOutput {
    streams: Vec<FfprobeStream>,
    format: FfprobeFormat,
}

impl MetadataProbe {
    /// Probe video file for metadata without full decode.
    /// Uses ffprobe to extract video metadata.
    #[allow(clippy::cast_possible_truncation)]
    #[instrument(skip_all, fields(path = %video_path.as_ref().display()))]
    pub async fn probe(video_path: impl AsRef<Path>) -> Result<VideoMetadata> {
        let path = video_path.as_ref();

        // Check if file exists
        if !path.exists() {
            return Err(VideoError::FileNotFound(path.display().to_string()));
        }

        debug!("Probing video metadata with ffprobe");

        // Run ffprobe command
        let output = Command::new("ffprobe")
            .args([
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
            ])
            .arg(path)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()
            .await
            .map_err(|e| VideoError::Ffmpeg(format!("Failed to execute ffprobe: {e}")))?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(VideoError::Ffmpeg(format!("ffprobe failed: {stderr}")));
        }

        let stdout = String::from_utf8_lossy(&output.stdout);
        Self::parse_ffprobe_output(&stdout)
    }

    /// Validate video file is processable.
    #[instrument(skip_all, fields(path = %video_path.as_ref().display()))]
    pub async fn validate(video_path: impl AsRef<Path>) -> Result<()> {
        let path = video_path.as_ref();

        // Check if file exists
        if !path.exists() {
            return Err(VideoError::FileNotFound(path.display().to_string()));
        }

        debug!("Validating video file");

        // Probe the file - if probing succeeds, the file is valid
        let metadata = Self::probe(path).await?;

        // Verify we have a valid video stream
        if metadata.width == 0 || metadata.height == 0 {
            return Err(VideoError::InvalidFormat(
                "No valid video stream found".to_string(),
            ));
        }

        if metadata.duration_ms == 0 {
            return Err(VideoError::InvalidFormat(
                "Video has no duration".to_string(),
            ));
        }

        debug!(
            width = metadata.width,
            height = metadata.height,
            duration_ms = metadata.duration_ms,
            "Video validated successfully"
        );

        Ok(())
    }

    /// Parse ffprobe JSON output into `VideoMetadata`.
    #[allow(clippy::cast_possible_truncation)]
    pub(crate) fn parse_ffprobe_output(output: &str) -> Result<VideoMetadata> {
        let ffprobe: FfprobeOutput = serde_json::from_str(output)
            .map_err(|e| VideoError::Ffmpeg(format!("Failed to parse ffprobe output: {e}")))?;

        // Find video stream
        let video_stream = ffprobe
            .streams
            .iter()
            .find(|s| s.codec_type == "video")
            .ok_or_else(|| VideoError::InvalidFormat("No video stream found".to_string()))?;

        // Check for audio stream
        let has_audio = ffprobe.streams.iter().any(|s| s.codec_type == "audio");

        // Parse duration from format
        let duration_ms = ffprobe
            .format
            .duration
            .as_ref()
            .and_then(|d| d.parse::<f64>().ok())
            .map_or(0, |d| (d * 1000.0) as u64);

        // Parse frame rate
        let fps = video_stream
            .r_frame_rate
            .as_ref()
            .map_or(0.0, |r| Self::parse_frame_rate(r));

        Ok(VideoMetadata {
            duration_ms,
            width: video_stream.width.unwrap_or(0),
            height: video_stream.height.unwrap_or(0),
            fps,
            codec: video_stream.codec_name.clone(),
            has_audio,
        })
    }

    /// Parse frame rate string (e.g., "30/1" or "24000/1001").
    pub(crate) fn parse_frame_rate(rate: &str) -> f32 {
        if let Some((num, den)) = rate.split_once('/') {
            let numerator: f32 = num.parse().unwrap_or(0.0);
            let denominator: f32 = den.parse().unwrap_or(1.0);
            if denominator == 0.0 {
                0.0
            } else {
                numerator / denominator
            }
        } else {
            // Try parsing as a simple float
            rate.parse().unwrap_or(0.0)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_ffprobe_output_with_video_and_audio() {
        let json = r#"{
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "30/1"
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac"
                }
            ],
            "format": {
                "duration": "120.5"
            }
        }"#;

        let metadata = MetadataProbe::parse_ffprobe_output(json).unwrap();

        assert_eq!(metadata.width, 1920);
        assert_eq!(metadata.height, 1080);
        assert_eq!(metadata.codec, "h264");
        assert!((metadata.fps - 30.0).abs() < 0.01);
        assert_eq!(metadata.duration_ms, 120_500);
        assert!(metadata.has_audio);
    }

    #[test]
    fn test_parse_ffprobe_output_without_audio() {
        let json = r#"{
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "vp9",
                    "width": 1280,
                    "height": 720,
                    "r_frame_rate": "24000/1001"
                }
            ],
            "format": {
                "duration": "60.0"
            }
        }"#;

        let metadata = MetadataProbe::parse_ffprobe_output(json).unwrap();

        assert_eq!(metadata.width, 1280);
        assert_eq!(metadata.height, 720);
        assert_eq!(metadata.codec, "vp9");
        // 24000/1001 ≈ 23.976
        assert!((metadata.fps - 23.976).abs() < 0.01);
        assert_eq!(metadata.duration_ms, 60_000);
        assert!(!metadata.has_audio);
    }

    #[test]
    fn test_parse_ffprobe_output_no_video_stream() {
        let json = r#"{
            "streams": [
                {
                    "codec_type": "audio",
                    "codec_name": "mp3"
                }
            ],
            "format": {
                "duration": "180.0"
            }
        }"#;

        let result = MetadataProbe::parse_ffprobe_output(json);
        assert!(result.is_err());
        assert!(matches!(result.unwrap_err(), VideoError::InvalidFormat(_)));
    }

    #[test]
    fn test_parse_ffprobe_output_invalid_json() {
        let json = "not valid json";
        let result = MetadataProbe::parse_ffprobe_output(json);
        assert!(result.is_err());
        assert!(matches!(result.unwrap_err(), VideoError::Ffmpeg(_)));
    }

    #[test]
    fn test_parse_ffprobe_output_missing_duration() {
        let json = r#"{
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 640,
                    "height": 480,
                    "r_frame_rate": "25/1"
                }
            ],
            "format": {}
        }"#;

        let metadata = MetadataProbe::parse_ffprobe_output(json).unwrap();

        assert_eq!(metadata.width, 640);
        assert_eq!(metadata.height, 480);
        assert_eq!(metadata.duration_ms, 0);
    }

    #[test]
    fn test_parse_frame_rate_simple_fraction() {
        assert!((MetadataProbe::parse_frame_rate("30/1") - 30.0).abs() < 0.01);
    }

    #[test]
    fn test_parse_frame_rate_ntsc() {
        // 24000/1001 = 23.976...
        let fps = MetadataProbe::parse_frame_rate("24000/1001");
        assert!((fps - 23.976).abs() < 0.01);
    }

    #[test]
    fn test_parse_frame_rate_30_ntsc() {
        // 30000/1001 = 29.97...
        let fps = MetadataProbe::parse_frame_rate("30000/1001");
        assert!((fps - 29.97).abs() < 0.01);
    }

    #[test]
    fn test_parse_frame_rate_simple_number() {
        assert!((MetadataProbe::parse_frame_rate("25") - 25.0).abs() < 0.01);
    }

    #[test]
    fn test_parse_frame_rate_float_string() {
        assert!((MetadataProbe::parse_frame_rate("29.97") - 29.97).abs() < 0.01);
    }

    #[test]
    fn test_parse_frame_rate_invalid() {
        assert!(MetadataProbe::parse_frame_rate("invalid").abs() < f32::EPSILON);
    }

    #[test]
    fn test_parse_frame_rate_zero_denominator() {
        assert!(MetadataProbe::parse_frame_rate("30/0").abs() < f32::EPSILON);
    }

    #[test]
    fn test_parse_frame_rate_empty_string() {
        assert!(MetadataProbe::parse_frame_rate("").abs() < f32::EPSILON);
    }

    #[test]
    fn test_parse_ffprobe_output_with_multiple_video_streams() {
        // ffprobe returns multiple streams for some files, we take the first video stream
        let json = r#"{
            "streams": [
                {
                    "codec_type": "video",
                    "codec_name": "h264",
                    "width": 1920,
                    "height": 1080,
                    "r_frame_rate": "30/1"
                },
                {
                    "codec_type": "video",
                    "codec_name": "mjpeg",
                    "width": 320,
                    "height": 240,
                    "r_frame_rate": "0/0"
                },
                {
                    "codec_type": "audio",
                    "codec_name": "aac"
                }
            ],
            "format": {
                "duration": "100.0"
            }
        }"#;

        let metadata = MetadataProbe::parse_ffprobe_output(json).unwrap();

        // Should use the first video stream
        assert_eq!(metadata.width, 1920);
        assert_eq!(metadata.height, 1080);
        assert_eq!(metadata.codec, "h264");
    }

    #[tokio::test]
    async fn test_probe_nonexistent_file() {
        let result = MetadataProbe::probe("/nonexistent/path/video.mp4").await;
        assert!(result.is_err());
        assert!(matches!(result.unwrap_err(), VideoError::FileNotFound(_)));
    }

    #[tokio::test]
    async fn test_validate_nonexistent_file() {
        let result = MetadataProbe::validate("/nonexistent/path/video.mp4").await;
        assert!(result.is_err());
        assert!(matches!(result.unwrap_err(), VideoError::FileNotFound(_)));
    }
}
