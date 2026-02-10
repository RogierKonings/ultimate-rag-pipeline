//! Types for video extraction operations.

use std::path::PathBuf;

/// Video file metadata.
#[derive(Debug, Clone, Default)]
pub struct VideoMetadata {
    /// Duration of the video in milliseconds.
    pub duration_ms: u64,
    /// Width of the video in pixels.
    pub width: u32,
    /// Height of the video in pixels.
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
    /// Index of the frame in the video sequence.
    pub frame_index: u32,
    /// Timestamp of the frame in milliseconds.
    pub timestamp_ms: u64,
    /// Path to the extracted image file.
    pub image_path: PathBuf,
    /// Path to the thumbnail image, if generated.
    pub thumbnail_path: Option<PathBuf>,
    /// Width of the extracted image in pixels.
    pub width: u32,
    /// Height of the extracted image in pixels.
    pub height: u32,
    /// Size of the image file in bytes.
    pub file_size_bytes: u64,
    /// Whether this frame is at a scene boundary.
    pub is_scene_boundary: bool,
}

/// Audio track metadata.
#[derive(Debug, Clone)]
pub struct AudioMetadata {
    /// Duration of the audio in milliseconds.
    pub duration_ms: u64,
    /// Sample rate in Hz.
    pub sample_rate: u32,
    /// Number of audio channels.
    pub channels: u8,
    /// Size of the audio file in bytes.
    pub file_size_bytes: u64,
}

/// Configuration for keyframe extraction.
#[derive(Debug, Clone)]
pub struct KeyframeConfig {
    /// Output width for extracted frames.
    pub output_width: u32,
    /// Output height for extracted frames.
    pub output_height: u32,
    /// JPEG quality (1-100).
    pub quality: u8,
    /// Whether to generate thumbnail images.
    pub generate_thumbnails: bool,
    /// Width for thumbnail images.
    pub thumbnail_width: u32,
    /// Height for thumbnail images.
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
    /// Sample rate in Hz (16000 is optimal for Whisper).
    pub sample_rate: u32,
    /// Number of audio channels (1 for mono).
    pub channels: u8,
    /// Output audio format.
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
        assert!(metadata.fps.abs() < f32::EPSILON);
        assert_eq!(metadata.codec, "");
        assert!(!metadata.has_audio);
    }

    #[test]
    fn test_video_metadata_with_values() {
        let metadata = VideoMetadata {
            duration_ms: 120_000,
            width: 1920,
            height: 1080,
            fps: 29.97,
            codec: "h264".to_string(),
            has_audio: true,
        };
        assert_eq!(metadata.duration_ms, 120_000);
        assert_eq!(metadata.width, 1920);
        assert_eq!(metadata.height, 1080);
        assert!((metadata.fps - 29.97).abs() < 0.01);
        assert_eq!(metadata.codec, "h264");
        assert!(metadata.has_audio);
    }

    #[test]
    fn test_extracted_keyframe_fields() {
        let keyframe = ExtractedKeyframe {
            frame_index: 42,
            timestamp_ms: 1400,
            image_path: PathBuf::from("/tmp/frame_042.jpg"),
            thumbnail_path: Some(PathBuf::from("/tmp/thumb_042.jpg")),
            width: 1280,
            height: 720,
            file_size_bytes: 45_678,
            is_scene_boundary: true,
        };
        assert_eq!(keyframe.frame_index, 42);
        assert_eq!(keyframe.timestamp_ms, 1400);
        assert_eq!(keyframe.image_path, PathBuf::from("/tmp/frame_042.jpg"));
        assert_eq!(
            keyframe.thumbnail_path,
            Some(PathBuf::from("/tmp/thumb_042.jpg"))
        );
        assert_eq!(keyframe.width, 1280);
        assert_eq!(keyframe.height, 720);
        assert_eq!(keyframe.file_size_bytes, 45_678);
        assert!(keyframe.is_scene_boundary);
    }

    #[test]
    fn test_extracted_keyframe_without_thumbnail() {
        let keyframe = ExtractedKeyframe {
            frame_index: 0,
            timestamp_ms: 0,
            image_path: PathBuf::from("/tmp/frame_000.jpg"),
            thumbnail_path: None,
            width: 1920,
            height: 1080,
            file_size_bytes: 123_456,
            is_scene_boundary: false,
        };
        assert!(keyframe.thumbnail_path.is_none());
        assert!(!keyframe.is_scene_boundary);
    }

    #[test]
    fn test_audio_metadata_fields() {
        let metadata = AudioMetadata {
            duration_ms: 60_000,
            sample_rate: 44_100,
            channels: 2,
            file_size_bytes: 5_292_000,
        };
        assert_eq!(metadata.duration_ms, 60_000);
        assert_eq!(metadata.sample_rate, 44_100);
        assert_eq!(metadata.channels, 2);
        assert_eq!(metadata.file_size_bytes, 5_292_000);
    }

    #[test]
    fn test_keyframe_config_default() {
        let config = KeyframeConfig::default();
        assert_eq!(config.output_width, 1280);
        assert_eq!(config.output_height, 720);
        assert_eq!(config.quality, 85);
        assert!(config.generate_thumbnails);
        assert_eq!(config.thumbnail_width, 320);
        assert_eq!(config.thumbnail_height, 180);
    }

    #[test]
    fn test_keyframe_config_custom() {
        let config = KeyframeConfig {
            output_width: 1920,
            output_height: 1080,
            quality: 95,
            generate_thumbnails: false,
            thumbnail_width: 160,
            thumbnail_height: 90,
        };
        assert_eq!(config.output_width, 1920);
        assert_eq!(config.output_height, 1080);
        assert_eq!(config.quality, 95);
        assert!(!config.generate_thumbnails);
        assert_eq!(config.thumbnail_width, 160);
        assert_eq!(config.thumbnail_height, 90);
    }

    #[test]
    fn test_audio_config_default() {
        let config = AudioConfig::default();
        assert_eq!(config.sample_rate, 16000);
        assert_eq!(config.channels, 1);
        assert_eq!(config.format, "wav");
    }

    #[test]
    fn test_audio_config_custom() {
        let config = AudioConfig {
            sample_rate: 48000,
            channels: 2,
            format: "mp3".to_string(),
        };
        assert_eq!(config.sample_rate, 48000);
        assert_eq!(config.channels, 2);
        assert_eq!(config.format, "mp3");
    }

    #[test]
    fn test_video_metadata_clone() {
        let metadata = VideoMetadata {
            duration_ms: 1000,
            width: 640,
            height: 480,
            fps: 30.0,
            codec: "vp9".to_string(),
            has_audio: false,
        };
        let cloned = metadata.clone();
        assert_eq!(cloned.duration_ms, metadata.duration_ms);
        assert_eq!(cloned.codec, metadata.codec);
    }

    #[test]
    fn test_extracted_keyframe_clone() {
        let keyframe = ExtractedKeyframe {
            frame_index: 10,
            timestamp_ms: 333,
            image_path: PathBuf::from("/tmp/test.jpg"),
            thumbnail_path: None,
            width: 800,
            height: 600,
            file_size_bytes: 10000,
            is_scene_boundary: false,
        };
        let cloned = keyframe.clone();
        assert_eq!(cloned.frame_index, keyframe.frame_index);
        assert_eq!(cloned.image_path, keyframe.image_path);
    }

    #[test]
    fn test_audio_metadata_clone() {
        let metadata = AudioMetadata {
            duration_ms: 5000,
            sample_rate: 22_050,
            channels: 1,
            file_size_bytes: 110_250,
        };
        let cloned = metadata.clone();
        assert_eq!(cloned.sample_rate, metadata.sample_rate);
    }

    #[test]
    fn test_keyframe_config_clone() {
        let config = KeyframeConfig::default();
        let cloned = config.clone();
        assert_eq!(cloned.output_width, config.output_width);
        assert_eq!(cloned.quality, config.quality);
    }

    #[test]
    fn test_audio_config_clone() {
        let config = AudioConfig::default();
        let cloned = config.clone();
        assert_eq!(cloned.sample_rate, config.sample_rate);
        assert_eq!(cloned.format, config.format);
    }

    #[test]
    fn test_video_metadata_debug() {
        let metadata = VideoMetadata::default();
        let debug_str = format!("{metadata:?}");
        assert!(debug_str.contains("VideoMetadata"));
        assert!(debug_str.contains("duration_ms"));
    }

    #[test]
    fn test_extracted_keyframe_debug() {
        let keyframe = ExtractedKeyframe {
            frame_index: 0,
            timestamp_ms: 0,
            image_path: PathBuf::from("/tmp/test.jpg"),
            thumbnail_path: None,
            width: 100,
            height: 100,
            file_size_bytes: 1000,
            is_scene_boundary: false,
        };
        let debug_str = format!("{keyframe:?}");
        assert!(debug_str.contains("ExtractedKeyframe"));
        assert!(debug_str.contains("frame_index"));
    }

    #[test]
    fn test_audio_metadata_debug() {
        let metadata = AudioMetadata {
            duration_ms: 1000,
            sample_rate: 16000,
            channels: 1,
            file_size_bytes: 32000,
        };
        let debug_str = format!("{metadata:?}");
        assert!(debug_str.contains("AudioMetadata"));
    }

    #[test]
    fn test_keyframe_config_debug() {
        let config = KeyframeConfig::default();
        let debug_str = format!("{config:?}");
        assert!(debug_str.contains("KeyframeConfig"));
    }

    #[test]
    fn test_audio_config_debug() {
        let config = AudioConfig::default();
        let debug_str = format!("{config:?}");
        assert!(debug_str.contains("AudioConfig"));
    }
}
