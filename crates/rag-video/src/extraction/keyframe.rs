//! Keyframe extraction from video files using FFmpeg.

use crate::error::VideoError;
use crate::extraction::{ExtractedKeyframe, KeyframeConfig};
use crate::Result;
use std::path::Path;
use std::process::Stdio;
use tokio::process::Command;
use tracing::{debug, instrument};

/// Keyframe extractor using FFmpeg CLI.
pub struct KeyframeExtractor {
    pub(crate) config: KeyframeConfig,
}

impl KeyframeExtractor {
    /// Create a new keyframe extractor with the given configuration.
    pub fn new(config: KeyframeConfig) -> Self {
        Self { config }
    }

    /// Extract keyframes at specified timestamps.
    ///
    /// # Arguments
    ///
    /// * `video_path` - Path to the video file
    /// * `timestamps_ms` - List of timestamps in milliseconds to extract frames at
    /// * `output_dir` - Directory to save extracted frames
    ///
    /// # Returns
    ///
    /// A vector of `ExtractedKeyframe` structs containing metadata about each extracted frame.
    #[instrument(skip_all, fields(path = %video_path.as_ref().display(), num_timestamps = timestamps_ms.len()))]
    pub async fn extract(
        &self,
        video_path: impl AsRef<Path>,
        timestamps_ms: &[u64],
        output_dir: impl AsRef<Path>,
    ) -> Result<Vec<ExtractedKeyframe>> {
        let video_path = video_path.as_ref();
        let output_dir = output_dir.as_ref();

        // Check if video file exists
        if !video_path.exists() {
            return Err(VideoError::FileNotFound(video_path.display().to_string()));
        }

        // Ensure output directory exists
        tokio::fs::create_dir_all(output_dir).await?;

        let mut keyframes = Vec::with_capacity(timestamps_ms.len());

        for (index, &timestamp_ms) in timestamps_ms.iter().enumerate() {
            let index_u32 = index as u32;
            let filename = Self::timestamp_to_filename(index_u32, timestamp_ms);
            let output_path = output_dir.join(&filename);

            debug!(
                index = index,
                timestamp_ms = timestamp_ms,
                output = %output_path.display(),
                "Extracting keyframe"
            );

            // Extract the main frame
            let timestamp_secs = timestamp_ms as f64 / 1000.0;
            let mut cmd = self.build_extract_command(video_path, timestamp_secs, &output_path);

            let output = cmd
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .output()
                .await
                .map_err(|e| VideoError::Ffmpeg(format!("Failed to execute ffmpeg: {e}")))?;

            if !output.status.success() {
                let stderr = String::from_utf8_lossy(&output.stderr);
                return Err(VideoError::Ffmpeg(format!(
                    "FFmpeg failed for frame {index}: {stderr}"
                )));
            }

            // Get file metadata for the extracted frame
            let file_metadata = tokio::fs::metadata(&output_path).await?;
            let file_size_bytes = file_metadata.len();

            // Extract thumbnail if configured
            let thumbnail_path = if self.config.generate_thumbnails {
                let thumb_filename = format!("thumb_{filename}");
                let thumb_path = output_dir.join(&thumb_filename);

                let mut thumb_cmd =
                    self.build_thumbnail_command(video_path, timestamp_secs, &thumb_path);

                let thumb_output = thumb_cmd
                    .stdout(Stdio::piped())
                    .stderr(Stdio::piped())
                    .output()
                    .await
                    .map_err(|e| {
                        VideoError::Ffmpeg(format!("Failed to execute ffmpeg for thumbnail: {e}"))
                    })?;

                if thumb_output.status.success() {
                    Some(thumb_path)
                } else {
                    debug!(
                        index = index,
                        "Thumbnail generation failed, continuing without thumbnail"
                    );
                    None
                }
            } else {
                None
            };

            keyframes.push(ExtractedKeyframe {
                frame_index: index_u32,
                timestamp_ms,
                image_path: output_path,
                thumbnail_path,
                width: self.config.output_width,
                height: self.config.output_height,
                file_size_bytes,
                is_scene_boundary: false, // Scene detection is handled elsewhere
            });
        }

        debug!(num_keyframes = keyframes.len(), "Keyframe extraction complete");

        Ok(keyframes)
    }

    /// Build FFmpeg command for frame extraction.
    ///
    /// Command format:
    /// ```text
    /// ffmpeg -ss <timestamp> -i <video> -vframes 1 \
    ///   -vf scale='min(WIDTH,iw)':'min(HEIGHT,ih)':force_original_aspect_ratio=decrease \
    ///   -q:v <qscale> -y <output>
    /// ```
    pub(crate) fn build_extract_command(
        &self,
        video_path: &Path,
        timestamp_secs: f64,
        output_path: &Path,
    ) -> Command {
        let mut cmd = Command::new("ffmpeg");

        // Seek to timestamp (before input for faster seeking)
        cmd.arg("-ss").arg(format!("{timestamp_secs:.3}"));

        // Input file
        cmd.arg("-i").arg(video_path);

        // Extract single frame
        cmd.arg("-vframes").arg("1");

        // Scale filter preserving aspect ratio
        let scale_filter = format!(
            "scale='min({},iw)':'min({},ih)':force_original_aspect_ratio=decrease",
            self.config.output_width, self.config.output_height
        );
        cmd.arg("-vf").arg(&scale_filter);

        // Quality setting (convert 1-100 to qscale 1-31)
        let qscale = Self::quality_to_qscale(self.config.quality);
        cmd.arg("-q:v").arg(qscale.to_string());

        // Overwrite output
        cmd.arg("-y");

        // Output file
        cmd.arg(output_path);

        cmd
    }

    /// Build FFmpeg command for thumbnail extraction.
    pub(crate) fn build_thumbnail_command(
        &self,
        video_path: &Path,
        timestamp_secs: f64,
        output_path: &Path,
    ) -> Command {
        let mut cmd = Command::new("ffmpeg");

        // Seek to timestamp
        cmd.arg("-ss").arg(format!("{timestamp_secs:.3}"));

        // Input file
        cmd.arg("-i").arg(video_path);

        // Extract single frame
        cmd.arg("-vframes").arg("1");

        // Scale filter for thumbnail dimensions
        let scale_filter = format!(
            "scale='min({},iw)':'min({},ih)':force_original_aspect_ratio=decrease",
            self.config.thumbnail_width, self.config.thumbnail_height
        );
        cmd.arg("-vf").arg(&scale_filter);

        // Quality setting (use slightly lower quality for thumbnails)
        let qscale = Self::quality_to_qscale(self.config.quality.saturating_sub(10));
        cmd.arg("-q:v").arg(qscale.to_string());

        // Overwrite output
        cmd.arg("-y");

        // Output file
        cmd.arg(output_path);

        cmd
    }

    /// Generate filename from frame index and timestamp.
    ///
    /// Format: `{index:05}_{timestamp_ms}.jpg`
    ///
    /// # Examples
    ///
    /// ```
    /// use rag_video::extraction::KeyframeExtractor;
    ///
    /// assert_eq!(
    ///     KeyframeExtractor::timestamp_to_filename(5, 5500),
    ///     "00005_5500.jpg"
    /// );
    /// assert_eq!(
    ///     KeyframeExtractor::timestamp_to_filename(0, 0),
    ///     "00000_0.jpg"
    /// );
    /// ```
    pub fn timestamp_to_filename(index: u32, timestamp_ms: u64) -> String {
        format!("{index:05}_{timestamp_ms}.jpg")
    }

    /// Convert quality (1-100) to FFmpeg qscale (1-31, lower is better).
    ///
    /// Formula: `qscale = 31 - (quality * 30 / 100)`
    ///
    /// - Quality 100 -> qscale 1 (best)
    /// - Quality 1 -> qscale 31 (worst)
    /// - Quality 85 -> qscale 6 (good default)
    pub(crate) fn quality_to_qscale(quality: u8) -> u8 {
        let quality = quality.clamp(1, 100);
        let qscale = 31 - (u32::from(quality) * 30 / 100);
        qscale.clamp(1, 31) as u8
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::OsStr;

    #[test]
    fn test_keyframe_extractor_new() {
        let config = KeyframeConfig::default();
        let extractor = KeyframeExtractor::new(config.clone());

        assert_eq!(extractor.config.output_width, config.output_width);
        assert_eq!(extractor.config.output_height, config.output_height);
        assert_eq!(extractor.config.quality, config.quality);
        assert_eq!(
            extractor.config.generate_thumbnails,
            config.generate_thumbnails
        );
    }

    #[test]
    fn test_keyframe_extractor_new_custom_config() {
        let config = KeyframeConfig {
            output_width: 1920,
            output_height: 1080,
            quality: 95,
            generate_thumbnails: false,
            thumbnail_width: 160,
            thumbnail_height: 90,
        };
        let extractor = KeyframeExtractor::new(config);

        assert_eq!(extractor.config.output_width, 1920);
        assert_eq!(extractor.config.output_height, 1080);
        assert_eq!(extractor.config.quality, 95);
        assert!(!extractor.config.generate_thumbnails);
    }

    #[test]
    fn test_timestamp_to_filename_basic() {
        assert_eq!(
            KeyframeExtractor::timestamp_to_filename(5, 5500),
            "00005_5500.jpg"
        );
    }

    #[test]
    fn test_timestamp_to_filename_zero() {
        assert_eq!(
            KeyframeExtractor::timestamp_to_filename(0, 0),
            "00000_0.jpg"
        );
    }

    #[test]
    fn test_timestamp_to_filename_large_index() {
        assert_eq!(
            KeyframeExtractor::timestamp_to_filename(99999, 123456789),
            "99999_123456789.jpg"
        );
    }

    #[test]
    fn test_timestamp_to_filename_max_values() {
        assert_eq!(
            KeyframeExtractor::timestamp_to_filename(u32::MAX, u64::MAX),
            format!("{:05}_{}.jpg", u32::MAX, u64::MAX)
        );
    }

    #[test]
    fn test_timestamp_to_filename_padded() {
        // Verify 5-digit padding for index
        assert_eq!(
            KeyframeExtractor::timestamp_to_filename(1, 100),
            "00001_100.jpg"
        );
        assert_eq!(
            KeyframeExtractor::timestamp_to_filename(12, 1000),
            "00012_1000.jpg"
        );
        assert_eq!(
            KeyframeExtractor::timestamp_to_filename(123, 10000),
            "00123_10000.jpg"
        );
        assert_eq!(
            KeyframeExtractor::timestamp_to_filename(1234, 100000),
            "01234_100000.jpg"
        );
        assert_eq!(
            KeyframeExtractor::timestamp_to_filename(12345, 1000000),
            "12345_1000000.jpg"
        );
    }

    #[test]
    fn test_quality_to_qscale_max_quality() {
        // Quality 100 should give qscale 1 (best quality)
        assert_eq!(KeyframeExtractor::quality_to_qscale(100), 1);
    }

    #[test]
    fn test_quality_to_qscale_min_quality() {
        // Quality 1 should give qscale 31 (worst quality)
        assert_eq!(KeyframeExtractor::quality_to_qscale(1), 31);
    }

    #[test]
    fn test_quality_to_qscale_default() {
        // Quality 85 (default) should give qscale ~6
        let qscale = KeyframeExtractor::quality_to_qscale(85);
        assert!(qscale <= 10);
        assert!(qscale >= 1);
    }

    #[test]
    fn test_quality_to_qscale_mid_range() {
        // Quality 50 should give qscale ~16
        let qscale = KeyframeExtractor::quality_to_qscale(50);
        assert_eq!(qscale, 16);
    }

    #[test]
    fn test_quality_to_qscale_clamped_high() {
        // Quality above 100 should be clamped
        assert_eq!(KeyframeExtractor::quality_to_qscale(255), 1);
    }

    #[test]
    fn test_quality_to_qscale_zero_clamped() {
        // Quality 0 should be clamped to 1, giving qscale 31
        assert_eq!(KeyframeExtractor::quality_to_qscale(0), 31);
    }

    #[test]
    fn test_build_extract_command_contains_seek() {
        let config = KeyframeConfig::default();
        let extractor = KeyframeExtractor::new(config);

        let video_path = Path::new("/tmp/video.mp4");
        let output_path = Path::new("/tmp/output.jpg");

        let cmd = extractor.build_extract_command(video_path, 5.5, output_path);
        let args: Vec<&OsStr> = cmd.as_std().get_args().collect();

        // Check for -ss flag
        let has_ss = args.windows(2).any(|w| w[0] == "-ss" && w[1] == "5.500");
        assert!(has_ss, "Command should contain -ss 5.500");
    }

    #[test]
    fn test_build_extract_command_contains_vframes() {
        let config = KeyframeConfig::default();
        let extractor = KeyframeExtractor::new(config);

        let video_path = Path::new("/tmp/video.mp4");
        let output_path = Path::new("/tmp/output.jpg");

        let cmd = extractor.build_extract_command(video_path, 1.0, output_path);
        let args: Vec<&OsStr> = cmd.as_std().get_args().collect();

        // Check for -vframes 1
        let has_vframes = args.windows(2).any(|w| w[0] == "-vframes" && w[1] == "1");
        assert!(has_vframes, "Command should contain -vframes 1");
    }

    #[test]
    fn test_build_extract_command_contains_input() {
        let config = KeyframeConfig::default();
        let extractor = KeyframeExtractor::new(config);

        let video_path = Path::new("/tmp/test_video.mp4");
        let output_path = Path::new("/tmp/output.jpg");

        let cmd = extractor.build_extract_command(video_path, 0.0, output_path);
        let args: Vec<&OsStr> = cmd.as_std().get_args().collect();

        // Check for -i flag
        let has_input = args
            .windows(2)
            .any(|w| w[0] == "-i" && w[1] == "/tmp/test_video.mp4");
        assert!(has_input, "Command should contain -i <video_path>");
    }

    #[test]
    fn test_build_extract_command_contains_scale_filter() {
        let config = KeyframeConfig {
            output_width: 1920,
            output_height: 1080,
            ..Default::default()
        };
        let extractor = KeyframeExtractor::new(config);

        let video_path = Path::new("/tmp/video.mp4");
        let output_path = Path::new("/tmp/output.jpg");

        let cmd = extractor.build_extract_command(video_path, 0.0, output_path);
        let args: Vec<&OsStr> = cmd.as_std().get_args().collect();

        // Check for -vf flag with scale filter
        let has_vf = args
            .windows(2)
            .any(|w| w[0] == "-vf" && w[1].to_string_lossy().contains("scale="));
        assert!(has_vf, "Command should contain -vf scale=...");

        // Verify dimensions in scale filter
        let scale_arg = args
            .windows(2)
            .find(|w| w[0] == "-vf")
            .map(|w| w[1].to_string_lossy().to_string());
        assert!(scale_arg.is_some());
        let scale = scale_arg.unwrap();
        assert!(scale.contains("1920"));
        assert!(scale.contains("1080"));
        assert!(scale.contains("force_original_aspect_ratio=decrease"));
    }

    #[test]
    fn test_build_extract_command_contains_quality() {
        let config = KeyframeConfig {
            quality: 85,
            ..Default::default()
        };
        let extractor = KeyframeExtractor::new(config);

        let video_path = Path::new("/tmp/video.mp4");
        let output_path = Path::new("/tmp/output.jpg");

        let cmd = extractor.build_extract_command(video_path, 0.0, output_path);
        let args: Vec<&OsStr> = cmd.as_std().get_args().collect();

        // Check for -q:v flag
        let has_quality = args.windows(2).any(|w| w[0] == "-q:v");
        assert!(has_quality, "Command should contain -q:v");
    }

    #[test]
    fn test_build_extract_command_contains_overwrite() {
        let config = KeyframeConfig::default();
        let extractor = KeyframeExtractor::new(config);

        let video_path = Path::new("/tmp/video.mp4");
        let output_path = Path::new("/tmp/output.jpg");

        let cmd = extractor.build_extract_command(video_path, 0.0, output_path);
        let args: Vec<&OsStr> = cmd.as_std().get_args().collect();

        // Check for -y flag
        let has_overwrite = args.iter().any(|a| *a == "-y");
        assert!(has_overwrite, "Command should contain -y flag");
    }

    #[test]
    fn test_build_extract_command_contains_output() {
        let config = KeyframeConfig::default();
        let extractor = KeyframeExtractor::new(config);

        let video_path = Path::new("/tmp/video.mp4");
        let output_path = Path::new("/tmp/frame_00001.jpg");

        let cmd = extractor.build_extract_command(video_path, 0.0, output_path);
        let args: Vec<&OsStr> = cmd.as_std().get_args().collect();

        // Output should be the last argument
        let last_arg = args.last().unwrap();
        assert_eq!(*last_arg, "/tmp/frame_00001.jpg");
    }

    #[test]
    fn test_build_extract_command_timestamp_precision() {
        let config = KeyframeConfig::default();
        let extractor = KeyframeExtractor::new(config);

        let video_path = Path::new("/tmp/video.mp4");
        let output_path = Path::new("/tmp/output.jpg");

        // Test with fractional timestamp
        let cmd = extractor.build_extract_command(video_path, 10.123, output_path);
        let args: Vec<&OsStr> = cmd.as_std().get_args().collect();

        let has_precise_ss = args
            .windows(2)
            .any(|w| w[0] == "-ss" && w[1] == "10.123");
        assert!(
            has_precise_ss,
            "Command should have timestamp with 3 decimal places"
        );
    }

    #[test]
    fn test_build_thumbnail_command_smaller_dimensions() {
        let config = KeyframeConfig {
            thumbnail_width: 320,
            thumbnail_height: 180,
            ..Default::default()
        };
        let extractor = KeyframeExtractor::new(config);

        let video_path = Path::new("/tmp/video.mp4");
        let output_path = Path::new("/tmp/thumb.jpg");

        let cmd = extractor.build_thumbnail_command(video_path, 0.0, output_path);
        let args: Vec<&OsStr> = cmd.as_std().get_args().collect();

        // Verify thumbnail dimensions in scale filter
        let scale_arg = args
            .windows(2)
            .find(|w| w[0] == "-vf")
            .map(|w| w[1].to_string_lossy().to_string());
        assert!(scale_arg.is_some());
        let scale = scale_arg.unwrap();
        assert!(scale.contains("320"));
        assert!(scale.contains("180"));
    }

    #[tokio::test]
    async fn test_extract_nonexistent_video() {
        let config = KeyframeConfig::default();
        let extractor = KeyframeExtractor::new(config);

        let result = extractor
            .extract(
                "/nonexistent/video.mp4",
                &[0, 1000, 2000],
                "/tmp/output",
            )
            .await;

        assert!(result.is_err());
        assert!(matches!(result.unwrap_err(), VideoError::FileNotFound(_)));
    }

    #[test]
    fn test_build_extract_command_zero_timestamp() {
        let config = KeyframeConfig::default();
        let extractor = KeyframeExtractor::new(config);

        let video_path = Path::new("/tmp/video.mp4");
        let output_path = Path::new("/tmp/output.jpg");

        let cmd = extractor.build_extract_command(video_path, 0.0, output_path);
        let args: Vec<&OsStr> = cmd.as_std().get_args().collect();

        let has_ss = args
            .windows(2)
            .any(|w| w[0] == "-ss" && w[1] == "0.000");
        assert!(has_ss, "Command should contain -ss 0.000");
    }

    #[test]
    fn test_build_extract_command_arg_order() {
        let config = KeyframeConfig::default();
        let extractor = KeyframeExtractor::new(config);

        let video_path = Path::new("/tmp/video.mp4");
        let output_path = Path::new("/tmp/output.jpg");

        let cmd = extractor.build_extract_command(video_path, 5.0, output_path);
        let args: Vec<&OsStr> = cmd.as_std().get_args().collect();

        // Find positions of key arguments
        let ss_pos = args.iter().position(|a| *a == "-ss");
        let i_pos = args.iter().position(|a| *a == "-i");

        // -ss should come before -i for faster seeking
        assert!(ss_pos.is_some());
        assert!(i_pos.is_some());
        assert!(
            ss_pos.unwrap() < i_pos.unwrap(),
            "-ss should come before -i for input seeking"
        );
    }

    #[test]
    fn test_quality_to_qscale_range() {
        // Test that all quality values produce valid qscale values
        for quality in 1..=100 {
            let qscale = KeyframeExtractor::quality_to_qscale(quality);
            assert!(qscale >= 1 && qscale <= 31, "qscale should be in range 1-31");
        }
    }

    #[test]
    fn test_quality_to_qscale_monotonic() {
        // Higher quality should produce lower (better) qscale
        let mut prev_qscale = KeyframeExtractor::quality_to_qscale(1);
        for quality in 2..=100 {
            let qscale = KeyframeExtractor::quality_to_qscale(quality);
            assert!(
                qscale <= prev_qscale,
                "Higher quality should produce lower or equal qscale"
            );
            prev_qscale = qscale;
        }
    }
}
