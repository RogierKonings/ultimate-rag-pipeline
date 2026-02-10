//! Transcription HTTP client for communicating with the transcription service.

use std::path::Path;
use std::time::Duration;

use reqwest::Client;
use serde::{Deserialize, Serialize};

use super::types::TranscriptSegment;
use crate::{Result, VideoError};

/// Configuration for the transcription client.
#[derive(Debug, Clone)]
pub struct TranscriptionConfig {
    /// Base URL of the transcription service.
    pub base_url: String,
    /// Request timeout in seconds.
    pub timeout_seconds: u64,
    /// Whisper model to use (e.g., "tiny", "base", "small", "medium", "large").
    pub model: String,
    /// Language code for transcription (None for auto-detect).
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

impl TranscriptionConfig {
    /// Creates a new configuration with the given base URL.
    pub fn with_base_url(base_url: impl Into<String>) -> Self {
        Self {
            base_url: base_url.into(),
            ..Default::default()
        }
    }
}

/// Result from transcription.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct TranscriptionResult {
    /// Transcript segments with timing information.
    pub segments: Vec<TranscriptSegment>,
    /// Detected or specified language code.
    pub language: String,
    /// Total duration of the audio in milliseconds.
    pub duration_ms: u64,
}

/// Request body for the transcription API.
#[derive(Debug, Serialize)]
struct TranscriptionRequest {
    audio_path: String,
    model: String,
    language: Option<String>,
}

/// Response from the transcription API.
#[derive(Debug, Deserialize)]
struct TranscriptionResponse {
    segments: Vec<TranscriptSegmentResponse>,
    language: String,
    duration_seconds: f64,
}

/// Transcript segment in the API response format.
#[derive(Debug, Deserialize)]
struct TranscriptSegmentResponse {
    start_ms: u64,
    end_ms: u64,
    text: String,
    confidence: Option<f32>,
}

/// Response from the health endpoint.
#[derive(Debug, Deserialize)]
struct HealthResponse {
    status: String,
}

/// HTTP client for the transcription service.
pub struct TranscriptionClient {
    client: Client,
    config: TranscriptionConfig,
}

impl TranscriptionClient {
    /// Creates a new transcription client with the given configuration.
    #[allow(clippy::missing_panics_doc)]
    pub fn new(config: TranscriptionConfig) -> Self {
        let client = Client::builder()
            .timeout(Duration::from_secs(config.timeout_seconds))
            .build()
            .expect("Failed to build HTTP client");

        Self { client, config }
    }

    /// Transcribes the given audio file.
    ///
    /// # Arguments
    ///
    /// * `audio_path` - Path to the audio file to transcribe.
    ///
    /// # Returns
    ///
    /// Returns `TranscriptionResult` containing the transcript segments and metadata.
    ///
    /// # Errors
    ///
    /// Returns `VideoError::Transcription` if the request fails or the response is invalid.
    pub async fn transcribe(&self, audio_path: impl AsRef<Path>) -> Result<TranscriptionResult> {
        let audio_path_str = audio_path
            .as_ref()
            .to_str()
            .ok_or_else(|| VideoError::Transcription("Invalid audio path encoding".to_string()))?
            .to_string();

        let request = TranscriptionRequest {
            audio_path: audio_path_str,
            model: self.config.model.clone(),
            language: self.config.language.clone(),
        };

        let url = format!("{}/transcribe", self.config.base_url);

        let response = self
            .client
            .post(&url)
            .json(&request)
            .send()
            .await
            .map_err(|e| VideoError::Transcription(format!("HTTP request failed: {e}")))?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response
                .text()
                .await
                .unwrap_or_else(|_| "Failed to read response body".to_string());
            return Err(VideoError::Transcription(format!(
                "Transcription failed with status {status}: {body}"
            )));
        }

        let transcription_response: TranscriptionResponse = response
            .json()
            .await
            .map_err(|e| VideoError::Transcription(format!("Failed to parse response: {e}")))?;

        let segments = transcription_response
            .segments
            .into_iter()
            .map(|s| TranscriptSegment {
                start_ms: s.start_ms,
                end_ms: s.end_ms,
                text: s.text,
                confidence: s.confidence,
            })
            .collect();

        #[allow(clippy::cast_possible_truncation, clippy::cast_sign_loss)]
        let duration_ms = (transcription_response.duration_seconds * 1000.0) as u64;

        Ok(TranscriptionResult {
            segments,
            language: transcription_response.language,
            duration_ms,
        })
    }

    /// Checks if the transcription service is healthy.
    ///
    /// # Returns
    ///
    /// Returns `true` if the service is healthy, `false` otherwise.
    ///
    /// # Errors
    ///
    /// Returns `VideoError::Transcription` if the request fails.
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

        let health_response: HealthResponse = response
            .json()
            .await
            .map_err(|e| VideoError::Transcription(format!("Failed to parse health response: {e}")))?;

        Ok(health_response.status == "healthy")
    }

    /// Returns a reference to the client configuration.
    pub fn config(&self) -> &TranscriptionConfig {
        &self.config
    }

    /// Concatenates all segment texts into a single string with spaces.
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
    use wiremock::matchers::{body_json, method, path};
    use wiremock::{Mock, MockServer, ResponseTemplate};

    #[test]
    fn test_config_default() {
        let config = TranscriptionConfig::default();
        assert_eq!(config.base_url, "http://localhost:8011");
        assert_eq!(config.timeout_seconds, 300);
        assert_eq!(config.model, "base");
        assert!(config.language.is_none());
    }

    #[test]
    fn test_config_with_base_url() {
        let config = TranscriptionConfig::with_base_url("http://custom:9000");
        assert_eq!(config.base_url, "http://custom:9000");
        assert_eq!(config.timeout_seconds, 300);
        assert_eq!(config.model, "base");
    }

    #[test]
    fn test_client_new() {
        let config = TranscriptionConfig::default();
        let client = TranscriptionClient::new(config.clone());
        assert_eq!(client.config().base_url, config.base_url);
    }

    #[tokio::test]
    async fn test_transcribe_success() {
        let mock_server = MockServer::start().await;

        let expected_request = serde_json::json!({
            "audio_path": "/path/to/audio.wav",
            "model": "base",
            "language": null
        });

        let mock_response = serde_json::json!({
            "segments": [
                {"start_ms": 0, "end_ms": 2000, "text": "Hello world", "confidence": 0.95},
                {"start_ms": 2000, "end_ms": 4000, "text": "How are you", "confidence": 0.92}
            ],
            "language": "en",
            "duration_seconds": 4.0
        });

        Mock::given(method("POST"))
            .and(path("/transcribe"))
            .and(body_json(&expected_request))
            .respond_with(ResponseTemplate::new(200).set_body_json(&mock_response))
            .mount(&mock_server)
            .await;

        let config = TranscriptionConfig::with_base_url(mock_server.uri());
        let client = TranscriptionClient::new(config);

        let result = client.transcribe("/path/to/audio.wav").await.unwrap();

        assert_eq!(result.segments.len(), 2);
        assert_eq!(result.segments[0].start_ms, 0);
        assert_eq!(result.segments[0].end_ms, 2000);
        assert_eq!(result.segments[0].text, "Hello world");
        assert_eq!(result.segments[0].confidence, Some(0.95));
        assert_eq!(result.segments[1].start_ms, 2000);
        assert_eq!(result.segments[1].end_ms, 4000);
        assert_eq!(result.segments[1].text, "How are you");
        assert_eq!(result.segments[1].confidence, Some(0.92));
        assert_eq!(result.language, "en");
        assert_eq!(result.duration_ms, 4000);
    }

    #[tokio::test]
    async fn test_transcribe_with_language() {
        let mock_server = MockServer::start().await;

        let expected_request = serde_json::json!({
            "audio_path": "/path/to/audio.wav",
            "model": "small",
            "language": "fr"
        });

        let mock_response = serde_json::json!({
            "segments": [
                {"start_ms": 0, "end_ms": 2000, "text": "Bonjour monde", "confidence": 0.9}
            ],
            "language": "fr",
            "duration_seconds": 2.0
        });

        Mock::given(method("POST"))
            .and(path("/transcribe"))
            .and(body_json(&expected_request))
            .respond_with(ResponseTemplate::new(200).set_body_json(&mock_response))
            .mount(&mock_server)
            .await;

        let config = TranscriptionConfig {
            base_url: mock_server.uri(),
            timeout_seconds: 300,
            model: "small".to_string(),
            language: Some("fr".to_string()),
        };
        let client = TranscriptionClient::new(config);

        let result = client.transcribe("/path/to/audio.wav").await.unwrap();

        assert_eq!(result.segments.len(), 1);
        assert_eq!(result.segments[0].text, "Bonjour monde");
        assert_eq!(result.language, "fr");
    }

    #[tokio::test]
    async fn test_transcribe_empty_segments() {
        let mock_server = MockServer::start().await;

        let mock_response = serde_json::json!({
            "segments": [],
            "language": "en",
            "duration_seconds": 0.0
        });

        Mock::given(method("POST"))
            .and(path("/transcribe"))
            .respond_with(ResponseTemplate::new(200).set_body_json(&mock_response))
            .mount(&mock_server)
            .await;

        let config = TranscriptionConfig::with_base_url(mock_server.uri());
        let client = TranscriptionClient::new(config);

        let result = client.transcribe("/path/to/audio.wav").await.unwrap();

        assert!(result.segments.is_empty());
        assert_eq!(result.duration_ms, 0);
    }

    #[tokio::test]
    async fn test_transcribe_server_error() {
        let mock_server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/transcribe"))
            .respond_with(ResponseTemplate::new(500).set_body_string("Internal Server Error"))
            .mount(&mock_server)
            .await;

        let config = TranscriptionConfig::with_base_url(mock_server.uri());
        let client = TranscriptionClient::new(config);

        let result = client.transcribe("/path/to/audio.wav").await;

        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(matches!(err, VideoError::Transcription(_)));
        assert!(err.to_string().contains("500"));
    }

    #[tokio::test]
    async fn test_transcribe_invalid_json_response() {
        let mock_server = MockServer::start().await;

        Mock::given(method("POST"))
            .and(path("/transcribe"))
            .respond_with(ResponseTemplate::new(200).set_body_string("not json"))
            .mount(&mock_server)
            .await;

        let config = TranscriptionConfig::with_base_url(mock_server.uri());
        let client = TranscriptionClient::new(config);

        let result = client.transcribe("/path/to/audio.wav").await;

        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(matches!(err, VideoError::Transcription(_)));
        assert!(err.to_string().contains("Failed to parse response"));
    }

    #[tokio::test]
    async fn test_transcribe_connection_refused() {
        let config = TranscriptionConfig::with_base_url("http://localhost:59998");
        let client = TranscriptionClient::new(config);

        let result = client.transcribe("/path/to/audio.wav").await;

        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(matches!(err, VideoError::Transcription(_)));
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

        let config = TranscriptionConfig::with_base_url(mock_server.uri());
        let client = TranscriptionClient::new(config);

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

        let config = TranscriptionConfig::with_base_url(mock_server.uri());
        let client = TranscriptionClient::new(config);

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

        let config = TranscriptionConfig::with_base_url(mock_server.uri());
        let client = TranscriptionClient::new(config);

        let result = client.health().await.unwrap();
        assert!(!result);
    }

    #[tokio::test]
    async fn test_health_connection_refused() {
        let config = TranscriptionConfig::with_base_url("http://localhost:59998");
        let client = TranscriptionClient::new(config);

        let result = client.health().await;

        assert!(result.is_err());
        let err = result.unwrap_err();
        assert!(matches!(err, VideoError::Transcription(_)));
        assert!(err.to_string().contains("Health check failed"));
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

    #[test]
    fn test_full_text_empty() {
        let result = TranscriptionResult {
            segments: vec![],
            language: "en".to_string(),
            duration_ms: 0,
        };

        assert_eq!(TranscriptionClient::full_text(&result), "");
    }

    #[test]
    fn test_full_text_single_segment() {
        let result = TranscriptionResult {
            segments: vec![TranscriptSegment {
                start_ms: 0,
                end_ms: 1000,
                text: "Single".to_string(),
                confidence: Some(0.99),
            }],
            language: "en".to_string(),
            duration_ms: 1000,
        };

        assert_eq!(TranscriptionClient::full_text(&result), "Single");
    }

    #[test]
    fn test_transcription_result_serialize() {
        let result = TranscriptionResult {
            segments: vec![TranscriptSegment::new(0, 1000, "Test", Some(0.9))],
            language: "en".to_string(),
            duration_ms: 1000,
        };

        let json = serde_json::to_string(&result).unwrap();
        assert!(json.contains("\"language\":\"en\""));
        assert!(json.contains("\"duration_ms\":1000"));
    }

    #[test]
    fn test_transcription_result_deserialize() {
        let json = r#"{
            "segments": [{"start_ms": 0, "end_ms": 1000, "text": "Test", "confidence": 0.9}],
            "language": "en",
            "duration_ms": 1000
        }"#;

        let result: TranscriptionResult = serde_json::from_str(json).unwrap();
        assert_eq!(result.segments.len(), 1);
        assert_eq!(result.language, "en");
    }

    #[test]
    fn test_config_clone() {
        let config = TranscriptionConfig::default();
        let cloned = config.clone();
        assert_eq!(config.base_url, cloned.base_url);
        assert_eq!(config.timeout_seconds, cloned.timeout_seconds);
        assert_eq!(config.model, cloned.model);
    }

    #[test]
    fn test_config_debug() {
        let config = TranscriptionConfig::default();
        let debug = format!("{config:?}");
        assert!(debug.contains("TranscriptionConfig"));
        assert!(debug.contains("base_url"));
    }
}
