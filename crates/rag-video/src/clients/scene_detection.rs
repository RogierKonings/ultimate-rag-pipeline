//! Scene detection HTTP client for communicating with the scene detection service.

use std::path::Path;
use std::time::Duration;

use reqwest::Client;
use serde::{Deserialize, Serialize};

use super::types::SceneBoundary;
use crate::{Result, VideoError};

/// Configuration for the scene detection client.
#[derive(Debug, Clone)]
pub struct SceneDetectionConfig {
    /// Base URL of the scene detection service.
    pub base_url: String,
    /// Request timeout in seconds.
    pub timeout_seconds: u64,
    /// Scene detection threshold (lower = more sensitive).
    pub threshold: f32,
    /// Minimum scene length in frames.
    pub min_scene_len_frames: u32,
    /// Fallback interval in seconds when no scenes are detected.
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

impl SceneDetectionConfig {
    /// Creates a new configuration with the given base URL.
    pub fn with_base_url(base_url: impl Into<String>) -> Self {
        Self {
            base_url: base_url.into(),
            ..Default::default()
        }
    }
}

/// Result from scene detection.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct SceneDetectionResult {
    /// Detected scene boundaries.
    pub scenes: Vec<SceneBoundary>,
    /// Total number of frames in the video.
    pub total_frames: u64,
    /// Frames per second of the video.
    pub fps: f32,
    /// Total duration of the video in milliseconds.
    pub duration_ms: u64,
    /// Method used for detection: "content" or "fallback".
    pub detection_method: String,
}

/// Request body for the scene detection API.
#[derive(Debug, Serialize)]
struct DetectionRequest {
    video_path: String,
    threshold: f32,
    min_scene_len_frames: u32,
    fallback_interval_seconds: f32,
}

/// Response from the scene detection API.
#[derive(Debug, Deserialize)]
struct DetectionResponse {
    scenes: Vec<SceneBoundaryResponse>,
    total_frames: u64,
    fps: f32,
    duration_ms: u64,
    detection_method: String,
}

/// Scene boundary in the API response format.
#[derive(Debug, Deserialize)]
struct SceneBoundaryResponse {
    scene_index: u32,
    start_ms: u64,
    end_ms: u64,
    is_detected: bool,
}

/// Response from the health endpoint.
#[derive(Debug, Deserialize)]
struct HealthResponse {
    status: String,
}

/// HTTP client for the scene detection service.
pub struct SceneDetectionClient {
    client: Client,
    config: SceneDetectionConfig,
}

impl SceneDetectionClient {
    /// Creates a new scene detection client with the given configuration.
    #[allow(clippy::missing_panics_doc)]
    pub fn new(config: SceneDetectionConfig) -> Self {
        let client = Client::builder()
            .timeout(Duration::from_secs(config.timeout_seconds))
            .build()
            .expect("Failed to build HTTP client");

        Self { client, config }
    }

    /// Detects scenes in the given video file.
    ///
    /// # Arguments
    ///
    /// * `video_path` - Path to the video file to analyze.
    ///
    /// # Returns
    ///
    /// Returns `SceneDetectionResult` containing the detected scenes and metadata.
    ///
    /// # Errors
    ///
    /// Returns `VideoError::SceneDetection` if the request fails or the response is invalid.
    pub async fn detect(&self, video_path: impl AsRef<Path>) -> Result<SceneDetectionResult> {
        let video_path_str = video_path
            .as_ref()
            .to_str()
            .ok_or_else(|| VideoError::SceneDetection("Invalid video path encoding".to_string()))?
            .to_string();

        let request = DetectionRequest {
            video_path: video_path_str,
            threshold: self.config.threshold,
            min_scene_len_frames: self.config.min_scene_len_frames,
            fallback_interval_seconds: self.config.fallback_interval_seconds,
        };

        let url = format!("{}/detect", self.config.base_url);

        let response = self
            .client
            .post(&url)
            .json(&request)
            .send()
            .await
            .map_err(|e| VideoError::SceneDetection(format!("HTTP request failed: {e}")))?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response
                .text()
                .await
                .unwrap_or_else(|_| "Failed to read response body".to_string());
            return Err(VideoError::SceneDetection(format!(
                "Scene detection failed with status {status}: {body}"
            )));
        }

        let detection_response: DetectionResponse = response
            .json()
            .await
            .map_err(|e| VideoError::SceneDetection(format!("Failed to parse response: {e}")))?;

        let scenes = detection_response
            .scenes
            .into_iter()
            .map(|s| SceneBoundary {
                scene_index: s.scene_index,
                start_ms: s.start_ms,
                end_ms: s.end_ms,
                is_detected: s.is_detected,
            })
            .collect();

        Ok(SceneDetectionResult {
            scenes,
            total_frames: detection_response.total_frames,
            fps: detection_response.fps,
            duration_ms: detection_response.duration_ms,
            detection_method: detection_response.detection_method,
        })
    }

    /// Checks if the scene detection service is healthy.
    ///
    /// # Returns
    ///
    /// Returns `true` if the service is healthy, `false` otherwise.
    ///
    /// # Errors
    ///
    /// Returns `VideoError::SceneDetection` if the request fails.
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

        let health_response: HealthResponse = response
            .json()
            .await
            .map_err(|e| VideoError::SceneDetection(format!("Failed to parse health response: {e}")))?;

        Ok(health_response.status == "healthy")
    }

    /// Returns a reference to the client configuration.
    pub fn config(&self) -> &SceneDetectionConfig {
        &self.config
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use wiremock::matchers::{body_json, method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    #[test]
    fn test_config_default() {
        let config = SceneDetectionConfig::default();
        assert_eq!(config.base_url, "http://localhost:8010");
        assert_eq!(config.timeout_seconds, 120);
        assert!((config.threshold - 27.0).abs() < f32::EPSILON);
        assert_eq!(config.min_scene_len_frames, 15);
        assert!((config.fallback_interval_seconds - 5.0).abs() < f32::EPSILON);
    }

    #[test]
    fn test_config_with_base_url() {
        let config = SceneDetectionConfig::with_base_url("http://custom:9000");
        assert_eq!(config.base_url, "http://custom:9000");
        // Other values should be default
        assert_eq!(config.timeout_seconds, 120);
    }

    #[test]
    fn test_client_new() {
        let config = SceneDetectionConfig::default();
        let client = SceneDetectionClient::new(config.clone());
        assert_eq!(client.config().base_url, config.base_url);
    }

    #[tokio::test]
    async fn test_detect_success() {
        let mock_server = MockServer::start().await;

        let expected_request = serde_json::json!({
            "video_path": "/path/to/video.mp4",
            "threshold": 27.0,
            "min_scene_len_frames": 15,
            "fallback_interval_seconds": 5.0
        });

        let mock_response = serde_json::json!({
            "scenes": [
                {"scene_index": 0, "start_ms": 0, "end_ms": 5000, "is_detected": true},
                {"scene_index": 1, "start_ms": 5000, "end_ms": 10000, "is_detected": true}
            ],
            "total_frames": 300,
            "fps": 30.0,
            "duration_ms": 10000,
            "detection_method": "content"
        });

        Mock::given(method("POST"))
            .and(path("/detect"))
            .and(body_json(&expected_request))
            .respond_with(ResponseTemplate::new(200).set_body_json(&mock_response))
            .mount(&mock_server)
            .await;

        let config = SceneDetectionConfig::with_base_url(mock_server.uri());
        let client = SceneDetectionClient::new(config);

        let result = client.detect("/path/to/video.mp4").await.unwrap();

        assert_eq!(result.scenes.len(), 2);
        assert_eq!(result.scenes[0].scene_index, 0);
        assert_eq!(result.scenes[0].start_ms, 0);
        assert_eq!(result.scenes[0].end_ms, 5000);
        assert!(result.scenes[0].is_detected);
        assert_eq!(result.scenes[1].scene_index, 1);
        assert_eq!(result.scenes[1].start_ms, 5000);
        assert_eq!(result.scenes[1].end_ms, 10000);
        assert!(result.scenes[1].is_detected);
        assert_eq!(result.total_frames, 300);
        assert!((result.fps - 30.0).abs() < f32::EPSILON);
        assert_eq!(result.duration_ms, 10000);
        assert_eq!(result.detection_method, "content");
    }

    #[tokio::test]
    async fn test_detect_fallback_method() {
        let mock_server = MockServer::start().await;

        let mock_response = serde_json::json!({
            "scenes": [
                {"scene_index": 0, "start_ms": 0, "end_ms": 5000, "is_detected": false},
                {"scene_index": 1, "start_ms": 5000, "end_ms": 10000, "is_detected": false}
            ],
            "total_frames": 300,
            "fps": 30.0,
            "duration_ms": 10000,
            "detection_method": "fallback"
        });

        Mock::given(method("POST"))
            .and(path("/detect"))
            .respond_with(ResponseTemplate::new(200).set_body_json(&mock_response))
            .mount(&mock_server)
            .await;

        let config = SceneDetectionConfig::with_base_url(mock_server.uri());
        let client = SceneDetectionClient::new(config);

        let result = client.detect("/path/to/video.mp4").await.unwrap();

        assert_eq!(result.detection_method, "fallback");
        assert!(!result.scenes[0].is_detected);
        assert!(!result.scenes[1].is_detected);
    }

    #[tokio::test]
    async fn test_detect_empty_scenes() {
        let mock_server = MockServer::start().await;

        let mock_response = serde_json::json!({
            "scenes": [],
            "total_frames": 0,
            "fps": 0.0,
            "duration_ms": 0,
            "detection_method": "content"
        });

        Mock::given(method("POST"))
            .and(path("/detect"))
            .respond_with(ResponseTemplate::new(200).set_body_json(&mock_response))
            .mount(&mock_server)
            .await;

        let config = SceneDetectionConfig::with_base_url(mock_server.uri());
        let client = SceneDetectionClient::new(config);

        let result = client.detect("/path/to/video.mp4").await.unwrap();

        assert!(result.scenes.is_empty());
        assert_eq!(result.total_frames, 0);
    }

    #[tokio::test]
    async fn test_detect_server_error() {
        let mock_server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/detect"))
            .respond_with(ResponseTemplate::new(500).set_body_string("Internal Server Error"))
            .mount(&mock_server)
            .await;

        let config = SceneDetectionConfig::with_base_url(mock_server.uri());
        let client = SceneDetectionClient::new(config);

        let result = client.detect("/path/to/video.mp4").await;

        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(matches!(err, VideoError::SceneDetection(_)));
        assert!(err.to_string().contains("500"));
    }

    #[tokio::test]
    async fn test_detect_invalid_json_response() {
        let mock_server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/detect"))
            .respond_with(ResponseTemplate::new(200).set_body_string("not json"))
            .mount(&mock_server)
            .await;

        let config = SceneDetectionConfig::with_base_url(mock_server.uri());
        let client = SceneDetectionClient::new(config);

        let result = client.detect("/path/to/video.mp4").await;

        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(matches!(err, VideoError::SceneDetection(_)));
        assert!(err.to_string().contains("Failed to parse response"));
    }

    #[tokio::test]
    async fn test_detect_connection_refused() {
        // Use a port that should not be in use
        let config = SceneDetectionConfig::with_base_url("http://localhost:59999");
        let client = SceneDetectionClient::new(config);

        let result = client.detect("/path/to/video.mp4").await;

        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(matches!(err, VideoError::SceneDetection(_)));
        assert!(err.to_string().contains("HTTP request failed"));
    }

    #[tokio::test]
    async fn test_health_healthy() {
        let mock_server = MockServer::start().await;

        Mock::given(method("GET"))
            .and(path("/health"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "status": "healthy"
            })))
            .mount(&mock_server)
            .await;

        let config = SceneDetectionConfig::with_base_url(mock_server.uri());
        let client = SceneDetectionClient::new(config);

        let result = client.health().await.unwrap();
        assert!(result);
    }

    #[tokio::test]
    async fn test_health_unhealthy_status() {
        let mock_server = MockServer::start().await;

        Mock::given(method("GET"))
            .and(path("/health"))
            .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
                "status": "unhealthy"
            })))
            .mount(&mock_server)
            .await;

        let config = SceneDetectionConfig::with_base_url(mock_server.uri());
        let client = SceneDetectionClient::new(config);

        let result = client.health().await.unwrap();
        assert!(!result);
    }

    #[tokio::test]
    async fn test_health_server_error() {
        let mock_server = MockServer::start().await;

        Mock::given(method("GET"))
            .and(path("/health"))
            .respond_with(ResponseTemplate::new(500))
            .mount(&mock_server)
            .await;

        let config = SceneDetectionConfig::with_base_url(mock_server.uri());
        let client = SceneDetectionClient::new(config);

        let result = client.health().await.unwrap();
        assert!(!result);
    }

    #[tokio::test]
    async fn test_health_connection_refused() {
        let config = SceneDetectionConfig::with_base_url("http://localhost:59999");
        let client = SceneDetectionClient::new(config);

        let result = client.health().await;

        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(matches!(err, VideoError::SceneDetection(_)));
        assert!(err.to_string().contains("Health check failed"));
    }

    #[tokio::test]
    async fn test_detect_with_custom_config() {
        let mock_server = MockServer::start().await;

        let expected_request = serde_json::json!({
            "video_path": "/path/to/video.mp4",
            "threshold": 35.0,
            "min_scene_len_frames": 30,
            "fallback_interval_seconds": 10.0
        });

        let mock_response = serde_json::json!({
            "scenes": [],
            "total_frames": 100,
            "fps": 25.0,
            "duration_ms": 4000,
            "detection_method": "content"
        });

        Mock::given(method("POST"))
            .and(path("/detect"))
            .and(body_json(&expected_request))
            .respond_with(ResponseTemplate::new(200).set_body_json(&mock_response))
            .mount(&mock_server)
            .await;

        let config = SceneDetectionConfig {
            base_url: mock_server.uri(),
            timeout_seconds: 60,
            threshold: 35.0,
            min_scene_len_frames: 30,
            fallback_interval_seconds: 10.0,
        };
        let client = SceneDetectionClient::new(config);

        let result = client.detect("/path/to/video.mp4").await.unwrap();

        assert!(result.scenes.is_empty());
        assert_eq!(result.total_frames, 100);
    }

    #[test]
    fn test_scene_detection_result_serialize() {
        let result = SceneDetectionResult {
            scenes: vec![SceneBoundary::new(0, 0, 5000, true)],
            total_frames: 150,
            fps: 30.0,
            duration_ms: 5000,
            detection_method: "content".to_string(),
        };

        let json = serde_json::to_string(&result).unwrap();
        assert!(json.contains("\"detection_method\":\"content\""));
        assert!(json.contains("\"total_frames\":150"));
    }

    #[test]
    fn test_scene_detection_result_deserialize() {
        let json = r#"{
            "scenes": [{"scene_index": 0, "start_ms": 0, "end_ms": 1000, "is_detected": true}],
            "total_frames": 30,
            "fps": 30.0,
            "duration_ms": 1000,
            "detection_method": "fallback"
        }"#;

        let result: SceneDetectionResult = serde_json::from_str(json).unwrap();
        assert_eq!(result.scenes.len(), 1);
        assert_eq!(result.detection_method, "fallback");
    }

    #[test]
    fn test_config_clone() {
        let config = SceneDetectionConfig::default();
        let cloned = config.clone();
        assert_eq!(config.base_url, cloned.base_url);
        assert_eq!(config.timeout_seconds, cloned.timeout_seconds);
    }

    #[test]
    fn test_config_debug() {
        let config = SceneDetectionConfig::default();
        let debug = format!("{config:?}");
        assert!(debug.contains("SceneDetectionConfig"));
        assert!(debug.contains("base_url"));
    }
}
