//! Audio extraction from video files using `FFmpeg`.

use crate::error::VideoError;
use crate::extraction::AudioConfig;
use crate::extraction::AudioMetadata;
use crate::Result;
use serde::Deserialize;
use std::path::Path;
use std::process::Stdio;
use tokio::process::Command;
use tracing::{debug, instrument};

/// Audio extractor using `FFmpeg` CLI.
pub struct AudioExtractor {
    pub(crate) config: AudioConfig,
}

/// ffprobe format information for audio files.
#[derive(Debug, Deserialize)]
struct FfprobeAudioFormat {
    #[serde(default)]
    duration: Option<String>,
}

/// ffprobe output structure for audio probing.
#[derive(Debug, Deserialize)]
struct FfprobeAudioOutput {
    format: FfprobeAudioFormat,
}

impl AudioExtractor {
    /// Create a new audio extractor with the given configuration.
    pub fn new(config: AudioConfig) -> Self {
        Self { config }
    }

    /// Extract audio track from video to a separate file.
    ///
    /// # Arguments
    ///
    /// * `video_path` - Path to the video file
    /// * `output_path` - Path where the extracted audio will be saved
    ///
    /// # Returns
    ///
    /// `AudioMetadata` containing information about the extracted audio.
    ///
    /// # Errors
    ///
    /// Returns an error if:
    /// - The video file does not exist
    /// - The video has no audio track
    /// - `FFmpeg` fails to extract the audio
    #[instrument(skip_all, fields(path = %video_path.as_ref().display(), output = %output_path.as_ref().display()))]
    pub async fn extract(
        &self,
        video_path: impl AsRef<Path>,
        output_path: impl AsRef<Path>,
    ) -> Result<AudioMetadata> {
        let video_path = video_path.as_ref();
        let output_path = output_path.as_ref();

        // Check if video file exists
        if !video_path.exists() {
            return Err(VideoError::FileNotFound(video_path.display().to_string()));
        }

        // Ensure output directory exists
        if let Some(parent) = output_path.parent() {
            tokio::fs::create_dir_all(parent).await?;
        }

        debug!("Extracting audio from video");

        let mut cmd = self.build_extract_command(video_path, output_path);

        let output = cmd
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()
            .await
            .map_err(|e| VideoError::Ffmpeg(format!("Failed to execute ffmpeg: {e}")))?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);

            // Check for "no audio stream" error
            if stderr.contains("does not contain any stream")
                || stderr.contains("Output file #0 does not contain any stream")
            {
                return Err(VideoError::InvalidFormat(
                    "Video does not contain any audio track".to_string(),
                ));
            }

            return Err(VideoError::Ffmpeg(format!(
                "FFmpeg audio extraction failed: {stderr}"
            )));
        }

        debug!("Audio extraction complete, probing output file");

        // Probe the extracted audio file to get duration
        let duration_ms = self.probe_audio_duration(output_path).await?;

        // Get file size
        let file_metadata = tokio::fs::metadata(output_path).await?;
        let file_size_bytes = file_metadata.len();

        Ok(AudioMetadata {
            duration_ms,
            sample_rate: self.config.sample_rate,
            channels: self.config.channels,
            file_size_bytes,
        })
    }

    /// Build `FFmpeg` command for audio extraction.
    ///
    /// Command format:
    /// ```text
    /// ffmpeg -i <video> -vn -acodec pcm_s16le -ar <sample_rate> -ac <channels> -y <output>
    /// ```
    pub(crate) fn build_extract_command(&self, video_path: &Path, output_path: &Path) -> Command {
        let mut cmd = Command::new("ffmpeg");

        // Input file
        cmd.arg("-i").arg(video_path);

        // No video output
        cmd.arg("-vn");

        // Audio codec: 16-bit PCM for WAV
        cmd.arg("-acodec").arg("pcm_s16le");

        // Sample rate
        cmd.arg("-ar").arg(self.config.sample_rate.to_string());

        // Number of channels
        cmd.arg("-ac").arg(self.config.channels.to_string());

        // Overwrite output
        cmd.arg("-y");

        // Output file
        cmd.arg(output_path);

        cmd
    }

    /// Probe audio file duration using ffprobe.
    #[allow(clippy::cast_possible_truncation)]
    async fn probe_audio_duration(&self, audio_path: &Path) -> Result<u64> {
        let output = Command::new("ffprobe")
            .args(["-v", "quiet", "-print_format", "json", "-show_format"])
            .arg(audio_path)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()
            .await
            .map_err(|e| VideoError::Ffmpeg(format!("Failed to execute ffprobe: {e}")))?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(VideoError::Ffmpeg(format!(
                "ffprobe failed on audio file: {stderr}"
            )));
        }

        let stdout = String::from_utf8_lossy(&output.stdout);
        let ffprobe: FfprobeAudioOutput = serde_json::from_str(&stdout)
            .map_err(|e| VideoError::Ffmpeg(format!("Failed to parse ffprobe output: {e}")))?;

        let duration_ms = ffprobe
            .format
            .duration
            .as_ref()
            .and_then(|d| d.parse::<f64>().ok())
            .map_or(0, |d| (d * 1000.0) as u64);

        Ok(duration_ms)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::OsStr;

    #[test]
    fn test_audio_extractor_new() {
        let config = AudioConfig::default();
        let extractor = AudioExtractor::new(config.clone());

        assert_eq!(extractor.config.sample_rate, config.sample_rate);
        assert_eq!(extractor.config.channels, config.channels);
        assert_eq!(extractor.config.format, config.format);
    }

    #[test]
    fn test_audio_extractor_new_custom_config() {
        let config = AudioConfig {
            sample_rate: 48000,
            channels: 2,
            format: "mp3".to_string(),
        };
        let extractor = AudioExtractor::new(config);

        assert_eq!(extractor.config.sample_rate, 48000);
        assert_eq!(extractor.config.channels, 2);
        assert_eq!(extractor.config.format, "mp3");
    }

    #[test]
    fn test_audio_config_default_values() {
        let config = AudioConfig::default();

        // Verify defaults from types.rs
        assert_eq!(config.sample_rate, 16000);
        assert_eq!(config.channels, 1);
        assert_eq!(config.format, "wav");
    }

    #[test]
    fn test_build_extract_command_contains_vn() {
        let config = AudioConfig::default();
        let extractor = AudioExtractor::new(config);

        let video_path = Path::new("/tmp/video.mp4");
        let output_path = Path::new("/tmp/audio.wav");

        let cmd = extractor.build_extract_command(video_path, output_path);
        let args: Vec<&OsStr> = cmd.as_std().get_args().collect();

        // Check for -vn flag (no video)
        let has_vn = args.iter().any(|a| *a == "-vn");
        assert!(has_vn, "Command should contain -vn flag");
    }

    #[test]
    fn test_build_extract_command_contains_acodec() {
        let config = AudioConfig::default();
        let extractor = AudioExtractor::new(config);

        let video_path = Path::new("/tmp/video.mp4");
        let output_path = Path::new("/tmp/audio.wav");

        let cmd = extractor.build_extract_command(video_path, output_path);
        let args: Vec<&OsStr> = cmd.as_std().get_args().collect();

        // Check for -acodec pcm_s16le
        let has_acodec = args
            .windows(2)
            .any(|w| w[0] == "-acodec" && w[1] == "pcm_s16le");
        assert!(has_acodec, "Command should contain -acodec pcm_s16le");
    }

    #[test]
    fn test_build_extract_command_contains_ar() {
        let config = AudioConfig {
            sample_rate: 16000,
            ..Default::default()
        };
        let extractor = AudioExtractor::new(config);

        let video_path = Path::new("/tmp/video.mp4");
        let output_path = Path::new("/tmp/audio.wav");

        let cmd = extractor.build_extract_command(video_path, output_path);
        let args: Vec<&OsStr> = cmd.as_std().get_args().collect();

        // Check for -ar 16000
        let has_ar = args.windows(2).any(|w| w[0] == "-ar" && w[1] == "16000");
        assert!(has_ar, "Command should contain -ar 16000");
    }

    #[test]
    fn test_build_extract_command_contains_ar_custom() {
        let config = AudioConfig {
            sample_rate: 44100,
            ..Default::default()
        };
        let extractor = AudioExtractor::new(config);

        let video_path = Path::new("/tmp/video.mp4");
        let output_path = Path::new("/tmp/audio.wav");

        let cmd = extractor.build_extract_command(video_path, output_path);
        let args: Vec<&OsStr> = cmd.as_std().get_args().collect();

        // Check for -ar 44100
        let has_ar = args.windows(2).any(|w| w[0] == "-ar" && w[1] == "44100");
        assert!(has_ar, "Command should contain -ar 44100");
    }

    #[test]
    fn test_build_extract_command_contains_ac() {
        let config = AudioConfig {
            channels: 1,
            ..Default::default()
        };
        let extractor = AudioExtractor::new(config);

        let video_path = Path::new("/tmp/video.mp4");
        let output_path = Path::new("/tmp/audio.wav");

        let cmd = extractor.build_extract_command(video_path, output_path);
        let args: Vec<&OsStr> = cmd.as_std().get_args().collect();

        // Check for -ac 1
        let has_ac = args.windows(2).any(|w| w[0] == "-ac" && w[1] == "1");
        assert!(has_ac, "Command should contain -ac 1");
    }

    #[test]
    fn test_build_extract_command_contains_ac_stereo() {
        let config = AudioConfig {
            channels: 2,
            ..Default::default()
        };
        let extractor = AudioExtractor::new(config);

        let video_path = Path::new("/tmp/video.mp4");
        let output_path = Path::new("/tmp/audio.wav");

        let cmd = extractor.build_extract_command(video_path, output_path);
        let args: Vec<&OsStr> = cmd.as_std().get_args().collect();

        // Check for -ac 2
        let has_ac = args.windows(2).any(|w| w[0] == "-ac" && w[1] == "2");
        assert!(has_ac, "Command should contain -ac 2");
    }

    #[test]
    fn test_build_extract_command_contains_overwrite() {
        let config = AudioConfig::default();
        let extractor = AudioExtractor::new(config);

        let video_path = Path::new("/tmp/video.mp4");
        let output_path = Path::new("/tmp/audio.wav");

        let cmd = extractor.build_extract_command(video_path, output_path);
        let args: Vec<&OsStr> = cmd.as_std().get_args().collect();

        // Check for -y flag
        let has_overwrite = args.iter().any(|a| *a == "-y");
        assert!(has_overwrite, "Command should contain -y flag");
    }

    #[test]
    fn test_build_extract_command_contains_input() {
        let config = AudioConfig::default();
        let extractor = AudioExtractor::new(config);

        let video_path = Path::new("/tmp/test_video.mp4");
        let output_path = Path::new("/tmp/audio.wav");

        let cmd = extractor.build_extract_command(video_path, output_path);
        let args: Vec<&OsStr> = cmd.as_std().get_args().collect();

        // Check for -i flag
        let has_input = args
            .windows(2)
            .any(|w| w[0] == "-i" && w[1] == "/tmp/test_video.mp4");
        assert!(has_input, "Command should contain -i <video_path>");
    }

    #[test]
    fn test_build_extract_command_contains_output() {
        let config = AudioConfig::default();
        let extractor = AudioExtractor::new(config);

        let video_path = Path::new("/tmp/video.mp4");
        let output_path = Path::new("/tmp/extracted_audio.wav");

        let cmd = extractor.build_extract_command(video_path, output_path);
        let args: Vec<&OsStr> = cmd.as_std().get_args().collect();

        // Output should be the last argument
        let last_arg = args.last().unwrap();
        assert_eq!(*last_arg, "/tmp/extracted_audio.wav");
    }

    #[test]
    fn test_build_extract_command_arg_order() {
        let config = AudioConfig::default();
        let extractor = AudioExtractor::new(config);

        let video_path = Path::new("/tmp/video.mp4");
        let output_path = Path::new("/tmp/audio.wav");

        let cmd = extractor.build_extract_command(video_path, output_path);
        let args: Vec<&OsStr> = cmd.as_std().get_args().collect();

        // Find positions of key arguments
        let i_pos = args.iter().position(|a| *a == "-i");
        let vn_pos = args.iter().position(|a| *a == "-vn");
        let y_pos = args.iter().position(|a| *a == "-y");

        // -i should come first (before -vn)
        assert!(i_pos.is_some());
        assert!(vn_pos.is_some());
        assert!(y_pos.is_some());

        // -i should come before -vn
        assert!(
            i_pos.unwrap() < vn_pos.unwrap(),
            "-i should come before -vn"
        );

        // -y should come before output (last)
        assert!(
            y_pos.unwrap() < args.len() - 1,
            "-y should come before output"
        );
    }

    #[test]
    #[allow(clippy::similar_names)]
    fn test_build_extract_command_all_required_args() {
        let config = AudioConfig {
            sample_rate: 22_050,
            channels: 2,
            format: "wav".to_string(),
        };
        let extractor = AudioExtractor::new(config);

        let video_path = Path::new("/tmp/video.mp4");
        let output_path = Path::new("/tmp/audio.wav");

        let cmd = extractor.build_extract_command(video_path, output_path);
        let args: Vec<&OsStr> = cmd.as_std().get_args().collect();

        // Verify all required args are present
        let has_i = args.iter().any(|a| *a == "-i");
        let has_vn = args.iter().any(|a| *a == "-vn");
        let has_acodec = args.iter().any(|a| *a == "-acodec");
        let has_ar = args.iter().any(|a| *a == "-ar");
        let has_ac = args.iter().any(|a| *a == "-ac");
        let has_y = args.iter().any(|a| *a == "-y");

        assert!(has_i, "Missing -i flag");
        assert!(has_vn, "Missing -vn flag");
        assert!(has_acodec, "Missing -acodec flag");
        assert!(has_ar, "Missing -ar flag");
        assert!(has_ac, "Missing -ac flag");
        assert!(has_y, "Missing -y flag");
    }

    #[tokio::test]
    async fn test_extract_nonexistent_video() {
        let config = AudioConfig::default();
        let extractor = AudioExtractor::new(config);

        let result = extractor
            .extract("/nonexistent/video.mp4", "/tmp/audio.wav")
            .await;

        assert!(result.is_err());
        assert!(matches!(result.unwrap_err(), VideoError::FileNotFound(_)));
    }

    #[test]
    fn test_audio_metadata_from_extraction() {
        // Test that AudioMetadata fields can be populated correctly
        let metadata = AudioMetadata {
            duration_ms: 120_000,
            sample_rate: 16_000,
            channels: 1,
            file_size_bytes: 3_840_000, // 120s * 16000 Hz * 2 bytes
        };

        assert_eq!(metadata.duration_ms, 120_000);
        assert_eq!(metadata.sample_rate, 16_000);
        assert_eq!(metadata.channels, 1);
        assert_eq!(metadata.file_size_bytes, 3_840_000);
    }

    #[test]
    fn test_build_extract_command_ffmpeg_binary() {
        let config = AudioConfig::default();
        let extractor = AudioExtractor::new(config);

        let video_path = Path::new("/tmp/video.mp4");
        let output_path = Path::new("/tmp/audio.wav");

        let cmd = extractor.build_extract_command(video_path, output_path);

        // Verify the program is ffmpeg
        assert_eq!(cmd.as_std().get_program(), "ffmpeg");
    }
}
