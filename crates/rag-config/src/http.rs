//! Shared HTTP client builder for RAG Pipeline services.
//!
//! Provides a consistent way to construct `reqwest::Client` instances
//! with standard timeout and TLS configuration.

use reqwest::Client;
use std::time::Duration;

/// Configuration for building an HTTP client.
#[derive(Debug, Clone)]
pub struct HttpClientConfig {
    /// Request timeout.
    pub timeout: Duration,
    /// Connection timeout (defaults to 5s).
    pub connect_timeout: Duration,
}

impl Default for HttpClientConfig {
    fn default() -> Self {
        Self {
            timeout: Duration::from_secs(30),
            connect_timeout: Duration::from_secs(5),
        }
    }
}

impl HttpClientConfig {
    #[must_use]
    pub fn with_timeout(mut self, timeout: Duration) -> Self {
        self.timeout = timeout;
        self
    }

    #[must_use]
    pub fn with_connect_timeout(mut self, connect_timeout: Duration) -> Self {
        self.connect_timeout = connect_timeout;
        self
    }
}

/// Build a `reqwest::Client` with standard configuration.
///
/// # Errors
///
/// Returns a string error if the client fails to build.
pub fn build_http_client(config: &HttpClientConfig) -> Result<Client, String> {
    Client::builder()
        .timeout(config.timeout)
        .connect_timeout(config.connect_timeout)
        .build()
        .map_err(|e| format!("Failed to build HTTP client: {e}"))
}

/// Build a `reqwest::Client` with just a timeout (convenience wrapper).
///
/// # Errors
///
/// Returns a string error if the client fails to build.
pub fn build_http_client_with_timeout(timeout: Duration) -> Result<Client, String> {
    build_http_client(&HttpClientConfig {
        timeout,
        ..HttpClientConfig::default()
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_build_default_client() {
        let client = build_http_client(&HttpClientConfig::default());
        assert!(client.is_ok());
    }

    #[test]
    fn test_build_client_with_timeout() {
        let client = build_http_client_with_timeout(Duration::from_secs(10));
        assert!(client.is_ok());
    }

    #[test]
    fn test_config_builder_pattern() {
        let config = HttpClientConfig::default()
            .with_timeout(Duration::from_secs(60))
            .with_connect_timeout(Duration::from_secs(10));
        assert_eq!(config.timeout, Duration::from_secs(60));
        assert_eq!(config.connect_timeout, Duration::from_secs(10));
    }
}
