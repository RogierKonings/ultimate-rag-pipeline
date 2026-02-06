//! Shared health check types for all services.
//!
//! Provides a canonical health response format with component details,
//! liveness/readiness probes, and capability reporting.

use std::collections::HashMap;

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

/// Full health check response.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HealthResponse {
    /// Overall health status: "healthy", "degraded", or "unhealthy".
    pub status: String,

    /// Service version.
    pub version: String,

    /// Component health status (component name -> healthy).
    pub components: HashMap<String, bool>,

    /// Detailed component health information.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub component_details: Vec<ComponentHealth>,

    /// Current degradation level.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub degradation_level: Option<String>,

    /// Service capabilities based on component health.
    #[serde(default, skip_serializing_if = "HashMap::is_empty")]
    pub capabilities: HashMap<String, bool>,

    /// When this health check was performed.
    pub timestamp: DateTime<Utc>,
}

/// Detailed health information for a single component.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ComponentHealth {
    /// Component name.
    pub name: String,

    /// Whether the component is healthy.
    pub healthy: bool,

    /// Response latency in milliseconds.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub latency_ms: Option<f64>,

    /// Error message if unhealthy.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,

    /// Circuit breaker state.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub circuit_state: Option<String>,
}

impl HealthResponse {
    /// Create a healthy response.
    #[must_use]
    pub fn healthy(version: impl Into<String>) -> Self {
        Self {
            status: "healthy".to_string(),
            version: version.into(),
            components: HashMap::new(),
            component_details: Vec::new(),
            degradation_level: None,
            capabilities: HashMap::new(),
            timestamp: Utc::now(),
        }
    }

    /// Create a degraded response.
    #[must_use]
    pub fn degraded(version: impl Into<String>) -> Self {
        Self {
            status: "degraded".to_string(),
            version: version.into(),
            components: HashMap::new(),
            component_details: Vec::new(),
            degradation_level: None,
            capabilities: HashMap::new(),
            timestamp: Utc::now(),
        }
    }

    /// Create an unhealthy response.
    #[must_use]
    pub fn unhealthy(version: impl Into<String>) -> Self {
        Self {
            status: "unhealthy".to_string(),
            version: version.into(),
            components: HashMap::new(),
            component_details: Vec::new(),
            degradation_level: None,
            capabilities: HashMap::new(),
            timestamp: Utc::now(),
        }
    }

    /// Add a component health entry.
    #[must_use]
    pub fn with_component(mut self, name: impl Into<String>, healthy: bool) -> Self {
        let name = name.into();
        self.components.insert(name.clone(), healthy);
        self
    }

    /// Add detailed component health.
    #[must_use]
    pub fn with_component_detail(mut self, detail: ComponentHealth) -> Self {
        self.components
            .insert(detail.name.clone(), detail.healthy);
        self.component_details.push(detail);
        self
    }

    /// Set degradation level.
    #[must_use]
    pub fn with_degradation(mut self, level: impl Into<String>) -> Self {
        self.degradation_level = Some(level.into());
        self
    }

    /// Add a capability.
    #[must_use]
    pub fn with_capability(mut self, name: impl Into<String>, available: bool) -> Self {
        self.capabilities.insert(name.into(), available);
        self
    }
}

/// Kubernetes liveness probe response.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LivenessResponse {
    /// Status: "alive".
    pub status: String,
}

impl Default for LivenessResponse {
    fn default() -> Self {
        Self {
            status: "alive".to_string(),
        }
    }
}

/// Kubernetes readiness probe response.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ReadinessResponse {
    /// Status: "ready".
    pub status: String,

    /// Current degradation mode if service is degraded.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub degradation_mode: Option<String>,
}

impl Default for ReadinessResponse {
    fn default() -> Self {
        Self {
            status: "ready".to_string(),
            degradation_mode: None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_healthy_response() {
        let resp = HealthResponse::healthy("1.0.0");
        assert_eq!(resp.status, "healthy");
        assert_eq!(resp.version, "1.0.0");
        assert!(resp.components.is_empty());
    }

    #[test]
    fn test_with_components() {
        let resp = HealthResponse::healthy("1.0.0")
            .with_component("database", true)
            .with_component("cache", false);
        assert_eq!(resp.components.len(), 2);
        assert!(resp.components["database"]);
        assert!(!resp.components["cache"]);
    }

    #[test]
    fn test_with_component_detail() {
        let detail = ComponentHealth {
            name: "qdrant".to_string(),
            healthy: true,
            latency_ms: Some(5.0),
            error: None,
            circuit_state: None,
        };
        let resp = HealthResponse::healthy("1.0.0").with_component_detail(detail);
        assert_eq!(resp.component_details.len(), 1);
        assert!(resp.components["qdrant"]);
    }

    #[test]
    fn test_liveness_default() {
        let resp = LivenessResponse::default();
        assert_eq!(resp.status, "alive");
    }

    #[test]
    fn test_readiness_default() {
        let resp = ReadinessResponse::default();
        assert_eq!(resp.status, "ready");
        assert!(resp.degradation_mode.is_none());
    }

    #[test]
    fn test_serialization_roundtrip() {
        let resp = HealthResponse::healthy("1.0.0")
            .with_component("db", true)
            .with_degradation("partial");
        let json = serde_json::to_string(&resp).unwrap();
        let deserialized: HealthResponse = serde_json::from_str(&json).unwrap();
        assert_eq!(deserialized.status, "healthy");
        assert_eq!(deserialized.degradation_level, Some("partial".to_string()));
    }
}
