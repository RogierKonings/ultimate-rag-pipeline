//! Gateway configuration.

use std::collections::HashMap;
use std::time::Duration;

use serde::{Deserialize, Serialize};

/// Main gateway configuration.
#[derive(Debug, Clone, Deserialize, Serialize)]
#[derive(Default)]
pub struct GatewayConfig {
    /// Server configuration.
    #[serde(default)]
    pub server: ServerConfig,

    /// Embedding service configuration.
    #[serde(default)]
    pub embedding: EmbeddingServiceConfig,

    /// Reranker service configuration.
    #[serde(default)]
    pub reranker: RerankerConfig,

    /// vLLM proxy configuration.
    #[serde(default)]
    pub vllm: VllmConfig,

    /// Authentication configuration.
    #[serde(default)]
    pub auth: AuthConfig,

    /// Rate limiting configuration.
    #[serde(default)]
    pub rate_limit: RateLimitConfig,
}


impl GatewayConfig {
    /// Load configuration from environment variables.
    pub fn from_env() -> Self {
        Self {
            server: ServerConfig::from_env(),
            embedding: EmbeddingServiceConfig::from_env(),
            reranker: RerankerConfig::from_env(),
            vllm: VllmConfig::from_env(),
            auth: AuthConfig::from_env(),
            rate_limit: RateLimitConfig::from_env(),
        }
    }
}

/// Server configuration.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ServerConfig {
    pub host: String,
    pub port: u16,
    pub request_timeout_secs: u64,
}

impl Default for ServerConfig {
    fn default() -> Self {
        Self {
            host: "0.0.0.0".into(),
            port: 8004,
            request_timeout_secs: 60,
        }
    }
}

impl ServerConfig {
    pub fn from_env() -> Self {
        Self {
            host: std::env::var("HOST").unwrap_or_else(|_| "0.0.0.0".into()),
            port: std::env::var("PORT")
                .ok()
                .and_then(|p| p.parse().ok())
                .unwrap_or(8004),
            request_timeout_secs: std::env::var("REQUEST_TIMEOUT_SECS")
                .ok()
                .and_then(|t| t.parse().ok())
                .unwrap_or(60),
        }
    }

    pub fn request_timeout(&self) -> Duration {
        Duration::from_secs(self.request_timeout_secs)
    }
}

/// Embedding service configuration.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct EmbeddingServiceConfig {
    pub enabled: bool,
    pub model: String,
    pub max_batch_size: usize,
}

impl Default for EmbeddingServiceConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            model: "bge-small-en-v1.5".into(),
            max_batch_size: 32,
        }
    }
}

impl EmbeddingServiceConfig {
    pub fn from_env() -> Self {
        Self {
            enabled: std::env::var("EMBEDDING_ENABLED")
                .map(|v| v != "false")
                .unwrap_or(true),
            model: std::env::var("EMBEDDING_MODEL")
                .unwrap_or_else(|_| "bge-small-en-v1.5".into()),
            max_batch_size: std::env::var("EMBEDDING_MAX_BATCH_SIZE")
                .ok()
                .and_then(|s| s.parse().ok())
                .unwrap_or(32),
        }
    }
}

/// Reranker configuration.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RerankerConfig {
    pub enabled: bool,
    pub model: String,
    pub max_batch_size: usize,
    pub max_sequence_length: usize,
    pub normalize_scores: bool,
}

impl Default for RerankerConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            model: "BAAI/bge-reranker-v2-m3".into(),
            max_batch_size: 32,
            max_sequence_length: 512,
            normalize_scores: false,
        }
    }
}

impl RerankerConfig {
    pub fn from_env() -> Self {
        Self {
            enabled: std::env::var("RERANKER_ENABLED")
                .map(|v| v != "false")
                .unwrap_or(true),
            model: std::env::var("RERANKER_MODEL")
                .unwrap_or_else(|_| "BAAI/bge-reranker-v2-m3".into()),
            max_batch_size: std::env::var("RERANKER_MAX_BATCH_SIZE")
                .ok()
                .and_then(|s| s.parse().ok())
                .unwrap_or(32),
            max_sequence_length: std::env::var("RERANKER_MAX_SEQ_LENGTH")
                .ok()
                .and_then(|s| s.parse().ok())
                .unwrap_or(512),
            normalize_scores: std::env::var("RERANKER_NORMALIZE_SCORES")
                .map(|v| v == "true")
                .unwrap_or(false),
        }
    }
}

/// vLLM proxy configuration.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct VllmConfig {
    pub enabled: bool,
    pub url: String,
    pub default_model: String,
    pub timeout_secs: u64,
}

impl Default for VllmConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            url: "http://localhost:8000".into(),
            default_model: "Qwen/Qwen2.5-7B-Instruct".into(),
            timeout_secs: 60,
        }
    }
}

impl VllmConfig {
    pub fn from_env() -> Self {
        Self {
            enabled: std::env::var("VLLM_ENABLED")
                .map(|v| v != "false")
                .unwrap_or(true),
            url: std::env::var("VLLM_URL").unwrap_or_else(|_| "http://localhost:8000".into()),
            default_model: std::env::var("VLLM_DEFAULT_MODEL")
                .unwrap_or_else(|_| "Qwen/Qwen2.5-7B-Instruct".into()),
            timeout_secs: std::env::var("VLLM_TIMEOUT_SECS")
                .ok()
                .and_then(|s| s.parse().ok())
                .unwrap_or(60),
        }
    }

    pub fn timeout(&self) -> Duration {
        Duration::from_secs(self.timeout_secs)
    }
}

/// Authentication configuration.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct AuthConfig {
    pub enabled: bool,
    pub jwt_secret: Option<String>,
    pub jwt_public_key: Option<String>,
    pub jwt_algorithm: String,
    pub jwt_issuer: Option<String>,
    pub jwt_audience: Option<String>,
    pub jwks_url: Option<String>,
    pub api_keys: HashMap<String, ApiKeyConfig>,
    pub skip_paths: Vec<String>,
}

impl Default for AuthConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            jwt_secret: None,
            jwt_public_key: None,
            jwt_algorithm: "RS256".into(),
            jwt_issuer: None,
            jwt_audience: None,
            jwks_url: None,
            api_keys: HashMap::new(),
            skip_paths: vec![
                "/health".into(),
                "/health/live".into(),
                "/health/ready".into(),
                "/metrics".into(),
                "/".into(),
            ],
        }
    }
}

impl AuthConfig {
    pub fn from_env() -> Self {
        let mut config = Self {
            enabled: std::env::var("AUTH_ENABLED")
                .map(|v| v == "true")
                .unwrap_or(false),
            jwt_secret: std::env::var("JWT_SECRET").ok(),
            jwt_public_key: std::env::var("JWT_PUBLIC_KEY").ok(),
            jwt_algorithm: std::env::var("JWT_ALGORITHM").unwrap_or_else(|_| "RS256".into()),
            jwt_issuer: std::env::var("JWT_ISSUER").ok(),
            jwt_audience: std::env::var("JWT_AUDIENCE").ok(),
            jwks_url: std::env::var("JWKS_URL").ok(),
            api_keys: HashMap::new(),
            skip_paths: vec![
                "/health".into(),
                "/health/live".into(),
                "/health/ready".into(),
                "/metrics".into(),
                "/".into(),
            ],
        };

        // Parse API keys: KEY1:tenant1:user1:role1,role2;KEY2:...
        if let Ok(keys_str) = std::env::var("API_KEYS") {
            for spec in keys_str.split(';') {
                let parts: Vec<&str> = spec.split(':').collect();
                if parts.len() >= 3 {
                    let roles = if parts.len() > 3 {
                        parts[3].split(',').map(String::from).collect()
                    } else {
                        vec![]
                    };
                    config.api_keys.insert(
                        parts[0].to_string(),
                        ApiKeyConfig {
                            tenant_id: parts[1].to_string(),
                            user_id: parts[2].to_string(),
                            roles,
                        },
                    );
                }
            }
        }

        config
    }
}

/// API key configuration.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct ApiKeyConfig {
    pub tenant_id: String,
    pub user_id: String,
    pub roles: Vec<String>,
}

/// Rate limiting configuration.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RateLimitConfig {
    pub enabled: bool,
    pub default_rpm: u32,
    pub default_tpm: u32,
    pub burst_multiplier: f32,
    pub window_secs: u64,
    pub tenant_limits: HashMap<String, TenantLimit>,
}

impl Default for RateLimitConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            default_rpm: 60,
            default_tpm: 100_000,
            burst_multiplier: 1.5,
            window_secs: 60,
            tenant_limits: HashMap::new(),
        }
    }
}

impl RateLimitConfig {
    pub fn from_env() -> Self {
        Self {
            enabled: std::env::var("RATE_LIMIT_ENABLED")
                .map(|v| v != "false")
                .unwrap_or(true),
            default_rpm: std::env::var("RATE_LIMIT_RPM")
                .ok()
                .and_then(|s| s.parse().ok())
                .unwrap_or(60),
            default_tpm: std::env::var("RATE_LIMIT_TPM")
                .ok()
                .and_then(|s| s.parse().ok())
                .unwrap_or(100_000),
            burst_multiplier: std::env::var("RATE_LIMIT_BURST")
                .ok()
                .and_then(|s| s.parse().ok())
                .unwrap_or(1.5),
            window_secs: 60,
            tenant_limits: HashMap::new(),
        }
    }
}

/// Per-tenant rate limits.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct TenantLimit {
    pub rpm: Option<u32>,
    pub tpm: Option<u32>,
}
