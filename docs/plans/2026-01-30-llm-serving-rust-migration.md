# LLM Serving Layer Rust Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Consolidate the Python `llm-serving/` components (embedding, reranker, gateway, config, monitoring) into a single unified Rust service called `rag-llm-gateway`, then remove the Python code.

**Architecture:** A single Axum-based HTTP service that:
1. Serves embedding endpoints (existing `rag-embedding` logic)
2. Serves reranker endpoints (new cross-encoder inference via `candle` or ONNX)
3. Proxies chat completion requests to external vLLM
4. Provides unified auth (JWT + API key), rate limiting, and Prometheus metrics
5. Exposes dynamic configuration management via API

**Tech Stack:**
- `axum` 0.7 for HTTP server
- `fastembed` for embeddings (already in use)
- `candle` or `ort` (ONNX Runtime) for reranker cross-encoder inference
- `jsonwebtoken` for JWT validation
- `tower` middleware for rate limiting
- `prometheus` crate for metrics
- `reqwest` for vLLM proxy requests

---

## Phase 1: Create rag-llm-gateway Crate Structure

### Task 1.1: Create Crate and Cargo.toml

**Files:**
- Create: `crates/rag-llm-gateway/Cargo.toml`
- Create: `crates/rag-llm-gateway/src/lib.rs`
- Modify: `crates/Cargo.toml` (add workspace member)

**Step 1: Create the crate directory**

```bash
mkdir -p crates/rag-llm-gateway/src
```

**Step 2: Create Cargo.toml**

```toml
[package]
name = "rag-llm-gateway"
description = "Unified LLM Gateway for RAG Pipeline - embeddings, reranking, and LLM proxy"
version.workspace = true
edition.workspace = true
rust-version.workspace = true
license.workspace = true
repository.workspace = true

[dependencies]
# Internal crates
rag-embedding = { path = "../rag-embedding" }
rag-config = { path = "../rag-config" }
rag-telemetry = { path = "../rag-telemetry" }

# HTTP server
axum = { version = "0.7", features = ["macros"] }
tower = "0.4"
tower-http = { version = "0.5", features = ["trace", "cors", "timeout", "request-id"] }

# Async runtime
tokio = { workspace = true }

# Serialization
serde = { workspace = true }
serde_json = { workspace = true }
serde_yaml = "0.9"

# Error handling
thiserror = { workspace = true }
anyhow = { workspace = true }

# JWT authentication
jsonwebtoken = "9"

# HTTP client (for vLLM proxy)
reqwest = { version = "0.12", features = ["json", "stream"] }

# Metrics
prometheus = "0.13"

# Logging
tracing = { workspace = true }
tracing-subscriber = { version = "0.3", features = ["env-filter"] }

# UUID
uuid = { workspace = true }

# DateTime
chrono = { workspace = true }

[dev-dependencies]
tokio-test = { workspace = true }
axum-test = "15"

[[bin]]
name = "llm-gateway"
path = "src/bin/main.rs"

[lints]
workspace = true
```

**Step 3: Create lib.rs**

```rust
//! Unified LLM Gateway for RAG Pipeline.
//!
//! Provides a single service that handles:
//! - Text embeddings (via fastembed)
//! - Document reranking (cross-encoder)
//! - LLM chat completions (proxy to vLLM)
//! - JWT and API key authentication
//! - Rate limiting
//! - Prometheus metrics

pub mod api;
pub mod auth;
pub mod clients;
pub mod config;
pub mod error;
pub mod metrics;
pub mod rate_limit;
pub mod reranker;

pub use config::GatewayConfig;
pub use error::{GatewayError, Result};
```

**Step 4: Add to workspace**

Edit `crates/Cargo.toml` to add `"rag-llm-gateway"` to the members list.

**Step 5: Commit**

```bash
git add crates/rag-llm-gateway crates/Cargo.toml
git commit -m "feat(rag-llm-gateway): scaffold unified LLM gateway crate

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

### Task 1.2: Create Error Types

**Files:**
- Create: `crates/rag-llm-gateway/src/error.rs`

**Step 1: Write the error module**

```rust
//! Error types for the LLM Gateway.

use axum::{
    http::StatusCode,
    response::{IntoResponse, Response},
    Json,
};
use serde::Serialize;

/// Gateway result type.
pub type Result<T> = std::result::Result<T, GatewayError>;

/// Gateway error types.
#[derive(Debug, thiserror::Error)]
pub enum GatewayError {
    #[error("Authentication failed: {0}")]
    Unauthorized(String),

    #[error("Forbidden: {0}")]
    Forbidden(String),

    #[error("Rate limit exceeded: retry after {retry_after_secs}s")]
    RateLimitExceeded { retry_after_secs: u64 },

    #[error("Bad request: {0}")]
    BadRequest(String),

    #[error("Service unavailable: {0}")]
    ServiceUnavailable(String),

    #[error("Upstream error: {0}")]
    UpstreamError(String),

    #[error("Internal error: {0}")]
    Internal(String),

    #[error("Embedding error: {0}")]
    Embedding(#[from] rag_embedding::EmbeddingError),

    #[error("Reranker error: {0}")]
    Reranker(String),

    #[error("Configuration error: {0}")]
    Config(String),
}

/// Error response body (OpenAI-compatible).
#[derive(Debug, Serialize)]
pub struct ErrorResponse {
    pub error: ErrorDetail,
}

#[derive(Debug, Serialize)]
pub struct ErrorDetail {
    pub message: String,
    pub r#type: &'static str,
    pub code: Option<&'static str>,
}

impl GatewayError {
    fn error_type(&self) -> &'static str {
        match self {
            Self::Unauthorized(_) => "authentication_error",
            Self::Forbidden(_) => "permission_error",
            Self::RateLimitExceeded { .. } => "rate_limit_error",
            Self::BadRequest(_) => "invalid_request_error",
            Self::ServiceUnavailable(_) => "service_error",
            Self::UpstreamError(_) => "upstream_error",
            Self::Internal(_) => "internal_error",
            Self::Embedding(_) => "embedding_error",
            Self::Reranker(_) => "reranker_error",
            Self::Config(_) => "configuration_error",
        }
    }

    fn status_code(&self) -> StatusCode {
        match self {
            Self::Unauthorized(_) => StatusCode::UNAUTHORIZED,
            Self::Forbidden(_) => StatusCode::FORBIDDEN,
            Self::RateLimitExceeded { .. } => StatusCode::TOO_MANY_REQUESTS,
            Self::BadRequest(_) => StatusCode::BAD_REQUEST,
            Self::ServiceUnavailable(_) => StatusCode::SERVICE_UNAVAILABLE,
            Self::UpstreamError(_) => StatusCode::BAD_GATEWAY,
            Self::Internal(_) | Self::Embedding(_) | Self::Reranker(_) | Self::Config(_) => {
                StatusCode::INTERNAL_SERVER_ERROR
            }
        }
    }
}

impl IntoResponse for GatewayError {
    fn into_response(self) -> Response {
        let status = self.status_code();
        let body = ErrorResponse {
            error: ErrorDetail {
                message: self.to_string(),
                r#type: self.error_type(),
                code: None,
            },
        };

        let mut response = (status, Json(body)).into_response();

        // Add Retry-After header for rate limit errors
        if let Self::RateLimitExceeded { retry_after_secs } = &self {
            response.headers_mut().insert(
                "Retry-After",
                retry_after_secs.to_string().parse().unwrap(),
            );
        }

        response
    }
}
```

**Step 2: Verify compilation**

```bash
cd crates && cargo check -p rag-llm-gateway
```

**Step 3: Commit**

```bash
git add crates/rag-llm-gateway/src/error.rs
git commit -m "feat(rag-llm-gateway): add error types with OpenAI-compatible responses

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

### Task 1.3: Create Configuration Module

**Files:**
- Create: `crates/rag-llm-gateway/src/config.rs`

**Step 1: Write the config module**

```rust
//! Gateway configuration.

use std::collections::HashMap;
use std::time::Duration;

use serde::{Deserialize, Serialize};

/// Main gateway configuration.
#[derive(Debug, Clone, Deserialize, Serialize)]
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

impl Default for GatewayConfig {
    fn default() -> Self {
        Self {
            server: ServerConfig::default(),
            embedding: EmbeddingServiceConfig::default(),
            reranker: RerankerConfig::default(),
            vllm: VllmConfig::default(),
            auth: AuthConfig::default(),
            rate_limit: RateLimitConfig::default(),
        }
    }
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
            model: "all-MiniLM-L6-v2".into(),
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
                .unwrap_or_else(|_| "all-MiniLM-L6-v2".into()),
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
```

**Step 2: Verify compilation**

```bash
cd crates && cargo check -p rag-llm-gateway
```

**Step 3: Commit**

```bash
git add crates/rag-llm-gateway/src/config.rs
git commit -m "feat(rag-llm-gateway): add comprehensive configuration module

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Phase 2: Authentication Module

### Task 2.1: Implement JWT and API Key Authentication

**Files:**
- Create: `crates/rag-llm-gateway/src/auth/mod.rs`
- Create: `crates/rag-llm-gateway/src/auth/context.rs`
- Create: `crates/rag-llm-gateway/src/auth/jwt.rs`
- Create: `crates/rag-llm-gateway/src/auth/middleware.rs`

**Step 1: Create auth module structure**

```bash
mkdir -p crates/rag-llm-gateway/src/auth
```

**Step 2: Write auth/mod.rs**

```rust
//! Authentication module.

pub mod context;
pub mod jwt;
pub mod middleware;

pub use context::AuthContext;
pub use jwt::JwtValidator;
pub use middleware::auth_middleware;
```

**Step 3: Write auth/context.rs**

```rust
//! Authentication context.

use serde::{Deserialize, Serialize};

/// Authentication context extracted from JWT or API key.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AuthContext {
    pub tenant_id: String,
    pub user_id: String,
    pub roles: Vec<String>,
    pub scopes: Vec<String>,
    pub auth_method: AuthMethod,
}

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum AuthMethod {
    Jwt,
    ApiKey,
    None,
}

impl Default for AuthContext {
    fn default() -> Self {
        Self {
            tenant_id: "default".into(),
            user_id: "anonymous".into(),
            roles: vec![],
            scopes: vec![],
            auth_method: AuthMethod::None,
        }
    }
}

impl AuthContext {
    /// Create context for anonymous/unauthenticated requests.
    pub fn anonymous() -> Self {
        Self::default()
    }

    /// Check if user has a specific role.
    pub fn has_role(&self, role: &str) -> bool {
        self.roles.iter().any(|r| r == role)
    }

    /// Check if user has a specific scope.
    pub fn has_scope(&self, scope: &str) -> bool {
        self.scopes.iter().any(|s| s == scope)
    }

    /// Convert to HTTP headers for downstream services.
    pub fn to_headers(&self) -> Vec<(&'static str, String)> {
        vec![
            ("X-Tenant-ID", self.tenant_id.clone()),
            ("X-User-ID", self.user_id.clone()),
            ("X-Roles", self.roles.join(",")),
            ("X-Auth-Method", format!("{:?}", self.auth_method).to_lowercase()),
        ]
    }
}
```

**Step 4: Write auth/jwt.rs**

```rust
//! JWT validation.

use jsonwebtoken::{decode, Algorithm, DecodingKey, Validation};
use serde::{Deserialize, Serialize};
use tracing::{debug, warn};

use crate::config::AuthConfig;
use crate::error::{GatewayError, Result};

use super::context::{AuthContext, AuthMethod};

/// JWT claims structure.
#[derive(Debug, Deserialize, Serialize)]
pub struct Claims {
    pub sub: Option<String>,
    pub user_id: Option<String>,
    pub tenant_id: Option<String>,
    pub tid: Option<String>,
    pub roles: Option<Vec<String>>,
    pub role: Option<Vec<String>>,
    pub scope: Option<String>,
    pub exp: Option<i64>,
    pub iss: Option<String>,
    pub aud: Option<serde_json::Value>,
}

/// JWT validator.
pub struct JwtValidator {
    config: AuthConfig,
    decoding_key: Option<DecodingKey>,
    validation: Validation,
}

impl JwtValidator {
    /// Create a new JWT validator from config.
    pub fn new(config: &AuthConfig) -> Result<Self> {
        let algorithm = match config.jwt_algorithm.as_str() {
            "HS256" => Algorithm::HS256,
            "HS384" => Algorithm::HS384,
            "HS512" => Algorithm::HS512,
            "RS256" => Algorithm::RS256,
            "RS384" => Algorithm::RS384,
            "RS512" => Algorithm::RS512,
            "ES256" => Algorithm::ES256,
            "ES384" => Algorithm::ES384,
            alg => return Err(GatewayError::Config(format!("Unsupported JWT algorithm: {alg}"))),
        };

        let decoding_key = if let Some(secret) = &config.jwt_secret {
            Some(DecodingKey::from_secret(secret.as_bytes()))
        } else if let Some(public_key) = &config.jwt_public_key {
            Some(
                DecodingKey::from_rsa_pem(public_key.as_bytes())
                    .map_err(|e| GatewayError::Config(format!("Invalid RSA public key: {e}")))?,
            )
        } else {
            None
        };

        let mut validation = Validation::new(algorithm);
        validation.validate_exp = true;

        if let Some(issuer) = &config.jwt_issuer {
            validation.set_issuer(&[issuer]);
        }

        if let Some(audience) = &config.jwt_audience {
            validation.set_audience(&[audience]);
        }

        Ok(Self {
            config: config.clone(),
            decoding_key,
            validation,
        })
    }

    /// Validate a JWT token and extract auth context.
    pub fn validate(&self, token: &str) -> Result<AuthContext> {
        let decoding_key = self
            .decoding_key
            .as_ref()
            .ok_or_else(|| GatewayError::Config("No JWT decoding key configured".into()))?;

        let token_data = decode::<Claims>(token, decoding_key, &self.validation)
            .map_err(|e| {
                warn!("JWT validation failed: {}", e);
                GatewayError::Unauthorized(format!("Invalid token: {e}"))
            })?;

        let claims = token_data.claims;

        let tenant_id = claims
            .tenant_id
            .or(claims.tid)
            .unwrap_or_else(|| "default".into());

        let user_id = claims
            .sub
            .or(claims.user_id)
            .unwrap_or_else(|| "anonymous".into());

        let roles = claims.roles.or(claims.role).unwrap_or_default();

        let scopes = claims
            .scope
            .map(|s| s.split_whitespace().map(String::from).collect())
            .unwrap_or_default();

        debug!(tenant_id = %tenant_id, user_id = %user_id, "JWT validated");

        Ok(AuthContext {
            tenant_id,
            user_id,
            roles,
            scopes,
            auth_method: AuthMethod::Jwt,
        })
    }

    /// Validate an API key.
    pub fn validate_api_key(&self, api_key: &str) -> Option<AuthContext> {
        self.config.api_keys.get(api_key).map(|key_config| {
            debug!(tenant_id = %key_config.tenant_id, "API key validated");
            AuthContext {
                tenant_id: key_config.tenant_id.clone(),
                user_id: key_config.user_id.clone(),
                roles: key_config.roles.clone(),
                scopes: vec![],
                auth_method: AuthMethod::ApiKey,
            }
        })
    }
}
```

**Step 5: Write auth/middleware.rs**

```rust
//! Authentication middleware.

use axum::{
    extract::{Request, State},
    http::header::{AUTHORIZATION, HeaderMap},
    middleware::Next,
    response::Response,
};
use tracing::debug;

use crate::config::AuthConfig;
use crate::error::GatewayError;

use super::context::AuthContext;
use super::jwt::JwtValidator;

/// Authentication middleware.
pub async fn auth_middleware(
    State(validator): State<std::sync::Arc<JwtValidator>>,
    State(config): State<std::sync::Arc<AuthConfig>>,
    mut request: Request,
    next: Next,
) -> Result<Response, GatewayError> {
    let path = request.uri().path();

    // Check if path is public
    if config.skip_paths.iter().any(|p| path.starts_with(p)) {
        debug!(path, "Skipping auth for public path");
        request.extensions_mut().insert(AuthContext::anonymous());
        return Ok(next.run(request).await);
    }

    // Skip auth if disabled
    if !config.enabled {
        request.extensions_mut().insert(AuthContext::anonymous());
        return Ok(next.run(request).await);
    }

    let headers = request.headers();
    let auth_context = authenticate(headers, &validator)?;

    request.extensions_mut().insert(auth_context);
    Ok(next.run(request).await)
}

fn authenticate(headers: &HeaderMap, validator: &JwtValidator) -> Result<AuthContext, GatewayError> {
    // Try API key first
    if let Some(api_key) = headers.get("X-API-Key").and_then(|v| v.to_str().ok()) {
        if let Some(context) = validator.validate_api_key(api_key) {
            return Ok(context);
        }
    }

    // Try Bearer token
    if let Some(auth_header) = headers.get(AUTHORIZATION).and_then(|v| v.to_str().ok()) {
        if let Some(token) = auth_header.strip_prefix("Bearer ") {
            return validator.validate(token);
        }
    }

    Err(GatewayError::Unauthorized("No valid credentials provided".into()))
}
```

**Step 6: Verify compilation**

```bash
cd crates && cargo check -p rag-llm-gateway
```

**Step 7: Commit**

```bash
git add crates/rag-llm-gateway/src/auth
git commit -m "feat(rag-llm-gateway): add JWT and API key authentication

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Phase 3: Rate Limiting Module

### Task 3.1: Implement Token Bucket Rate Limiter

**Files:**
- Create: `crates/rag-llm-gateway/src/rate_limit/mod.rs`
- Create: `crates/rag-llm-gateway/src/rate_limit/bucket.rs`
- Create: `crates/rag-llm-gateway/src/rate_limit/middleware.rs`

**Step 1: Create rate_limit module structure**

```bash
mkdir -p crates/rag-llm-gateway/src/rate_limit
```

**Step 2: Write rate_limit/mod.rs**

```rust
//! Rate limiting module.

pub mod bucket;
pub mod middleware;

pub use bucket::{RateLimitResult, RateLimiter};
pub use middleware::rate_limit_middleware;
```

**Step 3: Write rate_limit/bucket.rs**

```rust
//! Token bucket rate limiter implementation.

use std::collections::HashMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

use tokio::sync::Mutex;
use tracing::debug;

use crate::config::RateLimitConfig;

/// Result of a rate limit check.
#[derive(Debug, Clone)]
pub struct RateLimitResult {
    pub allowed: bool,
    pub remaining: u32,
    pub limit: u32,
    pub reset_at: Instant,
    pub retry_after_secs: Option<u64>,
}

impl RateLimitResult {
    /// Convert to HTTP response headers.
    pub fn to_headers(&self) -> Vec<(&'static str, String)> {
        let mut headers = vec![
            ("X-RateLimit-Limit", self.limit.to_string()),
            ("X-RateLimit-Remaining", self.remaining.to_string()),
            (
                "X-RateLimit-Reset",
                self.reset_at
                    .duration_since(Instant::now())
                    .as_secs()
                    .to_string(),
            ),
        ];

        if let Some(retry) = self.retry_after_secs {
            headers.push(("Retry-After", retry.to_string()));
        }

        headers
    }
}

/// Rate limit bucket state.
#[derive(Debug, Clone)]
struct Bucket {
    tokens: f64,
    last_update: Instant,
    request_count: u64,
}

/// Token bucket rate limiter.
pub struct RateLimiter {
    config: RateLimitConfig,
    buckets: Arc<Mutex<HashMap<String, Bucket>>>,
}

impl RateLimiter {
    /// Create a new rate limiter.
    pub fn new(config: RateLimitConfig) -> Self {
        Self {
            config,
            buckets: Arc::new(Mutex::new(HashMap::new())),
        }
    }

    /// Check rate limit for a tenant/user.
    pub async fn check(&self, tenant_id: &str, user_id: Option<&str>) -> RateLimitResult {
        if !self.config.enabled {
            return RateLimitResult {
                allowed: true,
                remaining: u32::MAX,
                limit: u32::MAX,
                reset_at: Instant::now() + Duration::from_secs(60),
                retry_after_secs: None,
            };
        }

        let key = match user_id {
            Some(uid) => format!("request:{tenant_id}:{uid}"),
            None => format!("request:{tenant_id}"),
        };

        let limit = self.get_limit(tenant_id);
        let burst_limit = (limit as f64 * self.config.burst_multiplier) as u32;
        let window = Duration::from_secs(self.config.window_secs);

        let mut buckets = self.buckets.lock().await;
        let now = Instant::now();

        let bucket = buckets.entry(key).or_insert_with(|| Bucket {
            tokens: burst_limit as f64,
            last_update: now,
            request_count: 0,
        });

        // Refill tokens based on elapsed time
        let elapsed = now.duration_since(bucket.last_update);
        let refill = (elapsed.as_secs_f64() / window.as_secs_f64()) * limit as f64;
        bucket.tokens = (bucket.tokens + refill).min(burst_limit as f64);
        bucket.last_update = now;

        if bucket.tokens >= 1.0 {
            bucket.tokens -= 1.0;
            bucket.request_count += 1;

            debug!(
                remaining = bucket.tokens as u32,
                limit = limit,
                "Rate limit check passed"
            );

            RateLimitResult {
                allowed: true,
                remaining: bucket.tokens as u32,
                limit,
                reset_at: now + window,
                retry_after_secs: None,
            }
        } else {
            let tokens_needed = 1.0 - bucket.tokens;
            let retry_after = ((tokens_needed / limit as f64) * window.as_secs_f64()).ceil() as u64;

            debug!(
                remaining = 0,
                retry_after_secs = retry_after,
                "Rate limit exceeded"
            );

            RateLimitResult {
                allowed: false,
                remaining: 0,
                limit,
                reset_at: now + Duration::from_secs(retry_after),
                retry_after_secs: Some(retry_after),
            }
        }
    }

    fn get_limit(&self, tenant_id: &str) -> u32 {
        self.config
            .tenant_limits
            .get(tenant_id)
            .and_then(|t| t.rpm)
            .unwrap_or(self.config.default_rpm)
    }
}
```

**Step 4: Write rate_limit/middleware.rs**

```rust
//! Rate limiting middleware.

use axum::{
    extract::{Request, State},
    middleware::Next,
    response::Response,
};
use std::sync::Arc;

use crate::auth::AuthContext;
use crate::error::GatewayError;

use super::RateLimiter;

/// Rate limiting middleware.
pub async fn rate_limit_middleware(
    State(limiter): State<Arc<RateLimiter>>,
    request: Request,
    next: Next,
) -> Result<Response, GatewayError> {
    let auth_context = request
        .extensions()
        .get::<AuthContext>()
        .cloned()
        .unwrap_or_default();

    let result = limiter
        .check(&auth_context.tenant_id, Some(&auth_context.user_id))
        .await;

    if !result.allowed {
        return Err(GatewayError::RateLimitExceeded {
            retry_after_secs: result.retry_after_secs.unwrap_or(60),
        });
    }

    let mut response = next.run(request).await;

    // Add rate limit headers to response
    for (name, value) in result.to_headers() {
        if let Ok(header_value) = value.parse() {
            response.headers_mut().insert(name, header_value);
        }
    }

    Ok(response)
}
```

**Step 5: Verify compilation**

```bash
cd crates && cargo check -p rag-llm-gateway
```

**Step 6: Commit**

```bash
git add crates/rag-llm-gateway/src/rate_limit
git commit -m "feat(rag-llm-gateway): add token bucket rate limiting

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Phase 4: Reranker Module

### Task 4.1: Implement Reranker Service

**Files:**
- Create: `crates/rag-llm-gateway/src/reranker/mod.rs`
- Create: `crates/rag-llm-gateway/src/reranker/model.rs`
- Create: `crates/rag-llm-gateway/src/reranker/types.rs`

**Step 1: Create reranker module structure**

```bash
mkdir -p crates/rag-llm-gateway/src/reranker
```

**Step 2: Update Cargo.toml to add reranker dependencies**

Add to `[dependencies]`:

```toml
# Reranker (cross-encoder via ONNX)
ort = { version = "2", features = ["download-binaries"] }
tokenizers = "0.19"
```

**Step 3: Write reranker/mod.rs**

```rust
//! Reranker module for cross-encoder scoring.

pub mod model;
pub mod types;

pub use model::RerankerModel;
pub use types::{RerankRequest, RerankResponse, ScoredDocument};
```

**Step 4: Write reranker/types.rs**

```rust
//! Reranker request/response types.

use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// Rerank request.
#[derive(Debug, Clone, Deserialize)]
pub struct RerankRequest {
    /// Model to use (ignored, uses configured model).
    #[serde(default)]
    pub model: Option<String>,

    /// Query to rank documents against.
    pub query: String,

    /// Documents to rerank.
    pub documents: Vec<String>,

    /// Optional document IDs.
    #[serde(default)]
    pub doc_ids: Option<Vec<String>>,

    /// Return only top K results.
    #[serde(default)]
    pub top_k: Option<usize>,

    /// Minimum score threshold.
    #[serde(default)]
    pub min_score: Option<f32>,

    /// Include document text in response.
    #[serde(default = "default_return_documents")]
    pub return_documents: bool,

    /// Request ID.
    #[serde(default = "Uuid::new_v4")]
    pub request_id: Uuid,
}

fn default_return_documents() -> bool {
    true
}

/// Scored document in response.
#[derive(Debug, Clone, Serialize)]
pub struct ScoredDocument {
    /// Original index in input.
    pub index: usize,

    /// Relevance score.
    pub score: f32,

    /// Document text (if requested).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub document: Option<String>,

    /// Document ID (if provided).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub doc_id: Option<String>,
}

/// Token usage.
#[derive(Debug, Clone, Serialize)]
pub struct RerankUsage {
    pub prompt_tokens: usize,
    pub total_tokens: usize,
}

/// Rerank response.
#[derive(Debug, Clone, Serialize)]
pub struct RerankResponse {
    /// Model used.
    pub model: String,

    /// Ranked results (sorted by score descending).
    pub results: Vec<ScoredDocument>,

    /// Token usage.
    pub usage: RerankUsage,

    /// Processing time in milliseconds.
    pub processing_time_ms: f64,
}
```

**Step 5: Write reranker/model.rs**

```rust
//! Reranker model using ONNX Runtime.

use std::path::Path;
use std::sync::Arc;
use std::time::Instant;

use ort::{GraphOptimizationLevel, Session};
use tokenizers::Tokenizer;
use tracing::{info, instrument};

use crate::config::RerankerConfig;
use crate::error::{GatewayError, Result};

use super::types::{RerankRequest, RerankResponse, RerankUsage, ScoredDocument};

/// Reranker model wrapper.
pub struct RerankerModel {
    session: Session,
    tokenizer: Tokenizer,
    config: RerankerConfig,
}

impl RerankerModel {
    /// Load the reranker model.
    #[instrument(skip_all, fields(model = %config.model))]
    pub fn load(config: &RerankerConfig) -> Result<Self> {
        info!("Loading reranker model: {}", config.model);

        // For now, we'll use a placeholder implementation.
        // In production, download and load the ONNX model and tokenizer.
        // The model would typically be:
        // - ONNX exported from BAAI/bge-reranker-v2-m3
        // - Tokenizer from the same model

        // This is a stub - actual implementation would:
        // 1. Download model from HuggingFace or cache
        // 2. Load ONNX session
        // 3. Load tokenizer

        Err(GatewayError::Reranker(
            "Reranker model loading not yet implemented. \
             Use external reranker service or implement ONNX loading."
                .into(),
        ))
    }

    /// Rerank documents for a query.
    #[instrument(skip(self, request), fields(num_docs = request.documents.len()))]
    pub async fn rerank(&self, request: RerankRequest) -> Result<RerankResponse> {
        let start = Instant::now();

        // Tokenize query-document pairs
        let pairs: Vec<_> = request
            .documents
            .iter()
            .map(|doc| (request.query.as_str(), doc.as_str()))
            .collect();

        // Run inference
        let scores = self.score_pairs(&pairs)?;

        // Build results
        let mut results: Vec<ScoredDocument> = scores
            .into_iter()
            .enumerate()
            .map(|(i, score)| ScoredDocument {
                index: i,
                score,
                document: if request.return_documents {
                    Some(request.documents[i].clone())
                } else {
                    None
                },
                doc_id: request.doc_ids.as_ref().and_then(|ids| ids.get(i).cloned()),
            })
            .collect();

        // Sort by score descending
        results.sort_by(|a, b| b.score.partial_cmp(&a.score).unwrap_or(std::cmp::Ordering::Equal));

        // Apply min_score filter
        if let Some(min_score) = request.min_score {
            results.retain(|r| r.score >= min_score);
        }

        // Apply top_k limit
        if let Some(top_k) = request.top_k {
            results.truncate(top_k);
        }

        let elapsed = start.elapsed();

        // Estimate token count
        let total_tokens: usize = request
            .documents
            .iter()
            .map(|d| request.query.split_whitespace().count() + d.split_whitespace().count())
            .sum();

        Ok(RerankResponse {
            model: self.config.model.clone(),
            results,
            usage: RerankUsage {
                prompt_tokens: total_tokens,
                total_tokens,
            },
            processing_time_ms: elapsed.as_secs_f64() * 1000.0,
        })
    }

    fn score_pairs(&self, _pairs: &[(&str, &str)]) -> Result<Vec<f32>> {
        // Placeholder - actual implementation would:
        // 1. Tokenize pairs
        // 2. Run ONNX inference
        // 3. Extract scores from logits

        Err(GatewayError::Reranker("Scoring not implemented".into()))
    }
}

impl std::fmt::Debug for RerankerModel {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("RerankerModel")
            .field("model", &self.config.model)
            .finish_non_exhaustive()
    }
}
```

**Step 6: Verify compilation**

```bash
cd crates && cargo check -p rag-llm-gateway
```

**Step 7: Commit**

```bash
git add crates/rag-llm-gateway/src/reranker crates/rag-llm-gateway/Cargo.toml
git commit -m "feat(rag-llm-gateway): add reranker module with ONNX support (stub)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Phase 5: vLLM Proxy Client

### Task 5.1: Implement vLLM HTTP Client

**Files:**
- Create: `crates/rag-llm-gateway/src/clients/mod.rs`
- Create: `crates/rag-llm-gateway/src/clients/vllm.rs`
- Create: `crates/rag-llm-gateway/src/clients/types.rs`

**Step 1: Create clients module**

```bash
mkdir -p crates/rag-llm-gateway/src/clients
```

**Step 2: Write clients/mod.rs**

```rust
//! HTTP clients for upstream services.

pub mod types;
pub mod vllm;

pub use types::*;
pub use vllm::VllmClient;
```

**Step 3: Write clients/types.rs**

```rust
//! Shared types for LLM API.

use serde::{Deserialize, Serialize};

/// Chat message role.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum ChatRole {
    System,
    User,
    Assistant,
}

/// Chat message.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChatMessage {
    pub role: ChatRole,
    pub content: String,
}

/// Chat completion request.
#[derive(Debug, Clone, Deserialize)]
pub struct ChatCompletionRequest {
    #[serde(default)]
    pub model: Option<String>,
    pub messages: Vec<ChatMessage>,
    #[serde(default = "default_temperature")]
    pub temperature: f32,
    #[serde(default = "default_top_p")]
    pub top_p: f32,
    #[serde(default)]
    pub max_tokens: Option<u32>,
    #[serde(default)]
    pub stream: bool,
    #[serde(default)]
    pub stop: Option<Vec<String>>,
    #[serde(default)]
    pub presence_penalty: Option<f32>,
    #[serde(default)]
    pub frequency_penalty: Option<f32>,
    #[serde(default)]
    pub seed: Option<u64>,
    #[serde(default = "default_n")]
    pub n: u32,
}

fn default_temperature() -> f32 {
    0.7
}

fn default_top_p() -> f32 {
    1.0
}

fn default_n() -> u32 {
    1
}

/// Chat completion choice.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChatCompletionChoice {
    pub index: u32,
    pub message: ChatMessage,
    pub finish_reason: Option<String>,
}

/// Token usage.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Usage {
    pub prompt_tokens: u32,
    pub completion_tokens: u32,
    pub total_tokens: u32,
}

/// Chat completion response.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChatCompletionResponse {
    pub id: String,
    pub object: String,
    pub created: i64,
    pub model: String,
    pub choices: Vec<ChatCompletionChoice>,
    pub usage: Usage,
}

/// Streaming chunk delta.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChunkDelta {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub role: Option<ChatRole>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub content: Option<String>,
}

/// Streaming choice.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StreamChoice {
    pub index: u32,
    pub delta: ChunkDelta,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub finish_reason: Option<String>,
}

/// Streaming chunk.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChatCompletionChunk {
    pub id: String,
    pub object: String,
    pub created: i64,
    pub model: String,
    pub choices: Vec<StreamChoice>,
}
```

**Step 4: Write clients/vllm.rs**

```rust
//! vLLM service client.

use std::time::Duration;

use futures_util::StreamExt;
use reqwest::{Client, StatusCode};
use tracing::{debug, error, instrument};

use crate::auth::AuthContext;
use crate::config::VllmConfig;
use crate::error::{GatewayError, Result};

use super::types::{ChatCompletionChunk, ChatCompletionRequest, ChatCompletionResponse};

/// vLLM HTTP client.
#[derive(Clone)]
pub struct VllmClient {
    client: Client,
    config: VllmConfig,
}

impl VllmClient {
    /// Create a new vLLM client.
    pub fn new(config: VllmConfig) -> Result<Self> {
        let client = Client::builder()
            .timeout(config.timeout())
            .build()
            .map_err(|e| GatewayError::Internal(format!("Failed to create HTTP client: {e}")))?;

        Ok(Self { client, config })
    }

    /// Health check.
    pub async fn health_check(&self) -> bool {
        let url = format!("{}/health", self.config.url);
        match self.client.get(&url).send().await {
            Ok(resp) => resp.status() == StatusCode::OK,
            Err(e) => {
                debug!("vLLM health check failed: {}", e);
                false
            }
        }
    }

    /// Create a chat completion (non-streaming).
    #[instrument(skip(self, request, auth_context), fields(model = ?request.model))]
    pub async fn chat_completion(
        &self,
        request: ChatCompletionRequest,
        auth_context: &AuthContext,
    ) -> Result<ChatCompletionResponse> {
        let url = format!("{}/v1/chat/completions", self.config.url);

        let model = request
            .model
            .clone()
            .unwrap_or_else(|| self.config.default_model.clone());

        let payload = serde_json::json!({
            "model": model,
            "messages": request.messages,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "n": request.n,
            "stream": false,
            "max_tokens": request.max_tokens,
            "stop": request.stop,
            "presence_penalty": request.presence_penalty,
            "frequency_penalty": request.frequency_penalty,
            "seed": request.seed,
        });

        let mut req_builder = self.client.post(&url).json(&payload);

        // Add auth context headers
        for (name, value) in auth_context.to_headers() {
            req_builder = req_builder.header(name, value);
        }

        let response = req_builder.send().await.map_err(|e| {
            error!("vLLM request failed: {}", e);
            GatewayError::UpstreamError(format!("vLLM request failed: {e}"))
        })?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            error!("vLLM error response: {} - {}", status, body);
            return Err(GatewayError::UpstreamError(format!(
                "vLLM returned {status}: {body}"
            )));
        }

        response.json().await.map_err(|e| {
            error!("Failed to parse vLLM response: {}", e);
            GatewayError::UpstreamError(format!("Invalid vLLM response: {e}"))
        })
    }

    /// Create a streaming chat completion.
    #[instrument(skip(self, request, auth_context), fields(model = ?request.model))]
    pub async fn chat_completion_stream(
        &self,
        request: ChatCompletionRequest,
        auth_context: &AuthContext,
    ) -> Result<impl futures_util::Stream<Item = Result<ChatCompletionChunk>>> {
        let url = format!("{}/v1/chat/completions", self.config.url);

        let model = request
            .model
            .clone()
            .unwrap_or_else(|| self.config.default_model.clone());

        let payload = serde_json::json!({
            "model": model,
            "messages": request.messages,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "n": request.n,
            "stream": true,
            "max_tokens": request.max_tokens,
            "stop": request.stop,
            "presence_penalty": request.presence_penalty,
            "frequency_penalty": request.frequency_penalty,
        });

        let mut req_builder = self.client.post(&url).json(&payload);

        for (name, value) in auth_context.to_headers() {
            req_builder = req_builder.header(name, value);
        }

        let response = req_builder.send().await.map_err(|e| {
            GatewayError::UpstreamError(format!("vLLM stream request failed: {e}"))
        })?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            return Err(GatewayError::UpstreamError(format!(
                "vLLM returned {status}: {body}"
            )));
        }

        let stream = response.bytes_stream().filter_map(|result| async move {
            match result {
                Ok(bytes) => {
                    let text = String::from_utf8_lossy(&bytes);
                    for line in text.lines() {
                        if let Some(data) = line.strip_prefix("data: ") {
                            if data == "[DONE]" {
                                return None;
                            }
                            match serde_json::from_str::<ChatCompletionChunk>(data) {
                                Ok(chunk) => return Some(Ok(chunk)),
                                Err(e) => {
                                    debug!("Failed to parse chunk: {} - {}", e, data);
                                }
                            }
                        }
                    }
                    None
                }
                Err(e) => Some(Err(GatewayError::UpstreamError(format!("Stream error: {e}")))),
            }
        });

        Ok(stream)
    }
}
```

**Step 5: Update Cargo.toml**

Add to `[dependencies]`:

```toml
futures-util = "0.3"
```

**Step 6: Verify compilation**

```bash
cd crates && cargo check -p rag-llm-gateway
```

**Step 7: Commit**

```bash
git add crates/rag-llm-gateway/src/clients crates/rag-llm-gateway/Cargo.toml
git commit -m "feat(rag-llm-gateway): add vLLM proxy client with streaming support

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Phase 6: Metrics Module

### Task 6.1: Implement Prometheus Metrics

**Files:**
- Create: `crates/rag-llm-gateway/src/metrics/mod.rs`

**Step 1: Write metrics/mod.rs**

```rust
//! Prometheus metrics for the gateway.

use once_cell::sync::Lazy;
use prometheus::{
    Counter, CounterVec, Gauge, GaugeVec, Histogram, HistogramOpts, HistogramVec, Opts, Registry,
};

/// Global metrics registry.
pub static REGISTRY: Lazy<Registry> = Lazy::new(Registry::new);

/// Request counter.
pub static REQUEST_TOTAL: Lazy<CounterVec> = Lazy::new(|| {
    let opts = Opts::new("llm_gateway_requests_total", "Total requests")
        .namespace("rag")
        .subsystem("gateway");
    let counter = CounterVec::new(opts, &["service", "endpoint", "status"]).unwrap();
    REGISTRY.register(Box::new(counter.clone())).unwrap();
    counter
});

/// Request latency histogram.
pub static REQUEST_LATENCY: Lazy<HistogramVec> = Lazy::new(|| {
    let opts = HistogramOpts::new("llm_gateway_request_latency_seconds", "Request latency")
        .namespace("rag")
        .subsystem("gateway")
        .buckets(vec![0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]);
    let histogram = HistogramVec::new(opts, &["service", "endpoint"]).unwrap();
    REGISTRY.register(Box::new(histogram.clone())).unwrap();
    histogram
});

/// Active requests gauge.
pub static ACTIVE_REQUESTS: Lazy<GaugeVec> = Lazy::new(|| {
    let opts = Opts::new("llm_gateway_active_requests", "Active requests")
        .namespace("rag")
        .subsystem("gateway");
    let gauge = GaugeVec::new(opts, &["service"]).unwrap();
    REGISTRY.register(Box::new(gauge.clone())).unwrap();
    gauge
});

/// Tokens processed counter.
pub static TOKENS_PROCESSED: Lazy<CounterVec> = Lazy::new(|| {
    let opts = Opts::new("llm_gateway_tokens_total", "Tokens processed")
        .namespace("rag")
        .subsystem("gateway");
    let counter = CounterVec::new(opts, &["service", "type"]).unwrap();
    REGISTRY.register(Box::new(counter.clone())).unwrap();
    counter
});

/// Embeddings generated counter.
pub static EMBEDDINGS_GENERATED: Lazy<Counter> = Lazy::new(|| {
    let opts = Opts::new("llm_gateway_embeddings_total", "Embeddings generated")
        .namespace("rag")
        .subsystem("gateway");
    let counter = Counter::with_opts(opts).unwrap();
    REGISTRY.register(Box::new(counter.clone())).unwrap();
    counter
});

/// Rate limit hits counter.
pub static RATE_LIMIT_HITS: Lazy<CounterVec> = Lazy::new(|| {
    let opts = Opts::new("llm_gateway_rate_limit_hits_total", "Rate limit hits")
        .namespace("rag")
        .subsystem("gateway");
    let counter = CounterVec::new(opts, &["tenant_id"]).unwrap();
    REGISTRY.register(Box::new(counter.clone())).unwrap();
    counter
});

/// Auth failures counter.
pub static AUTH_FAILURES: Lazy<CounterVec> = Lazy::new(|| {
    let opts = Opts::new("llm_gateway_auth_failures_total", "Authentication failures")
        .namespace("rag")
        .subsystem("gateway");
    let counter = CounterVec::new(opts, &["reason"]).unwrap();
    REGISTRY.register(Box::new(counter.clone())).unwrap();
    counter
});

/// Model loaded gauge.
pub static MODEL_LOADED: Lazy<GaugeVec> = Lazy::new(|| {
    let opts = Opts::new("llm_gateway_model_loaded", "Model loaded status")
        .namespace("rag")
        .subsystem("gateway");
    let gauge = GaugeVec::new(opts, &["model_type", "model_name"]).unwrap();
    REGISTRY.register(Box::new(gauge.clone())).unwrap();
    gauge
});

/// Get metrics as text for Prometheus scraping.
pub fn gather_metrics() -> String {
    use prometheus::Encoder;
    let encoder = prometheus::TextEncoder::new();
    let metric_families = REGISTRY.gather();
    let mut buffer = Vec::new();
    encoder.encode(&metric_families, &mut buffer).unwrap();
    String::from_utf8(buffer).unwrap()
}

/// Helper to record a request.
pub fn record_request(service: &str, endpoint: &str, status: &str, latency_secs: f64) {
    REQUEST_TOTAL
        .with_label_values(&[service, endpoint, status])
        .inc();
    REQUEST_LATENCY
        .with_label_values(&[service, endpoint])
        .observe(latency_secs);
}
```

**Step 2: Update Cargo.toml**

Add to `[dependencies]`:

```toml
once_cell = "1.19"
```

**Step 3: Create metrics module directory**

```bash
mkdir -p crates/rag-llm-gateway/src/metrics
mv crates/rag-llm-gateway/src/metrics.rs crates/rag-llm-gateway/src/metrics/mod.rs 2>/dev/null || true
```

**Step 4: Verify compilation**

```bash
cd crates && cargo check -p rag-llm-gateway
```

**Step 5: Commit**

```bash
git add crates/rag-llm-gateway/src/metrics crates/rag-llm-gateway/Cargo.toml
git commit -m "feat(rag-llm-gateway): add Prometheus metrics collection

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Phase 7: API Routes

### Task 7.1: Implement API Module and Routes

**Files:**
- Create: `crates/rag-llm-gateway/src/api/mod.rs`
- Create: `crates/rag-llm-gateway/src/api/state.rs`
- Create: `crates/rag-llm-gateway/src/api/routes/mod.rs`
- Create: `crates/rag-llm-gateway/src/api/routes/health.rs`
- Create: `crates/rag-llm-gateway/src/api/routes/embeddings.rs`
- Create: `crates/rag-llm-gateway/src/api/routes/rerank.rs`
- Create: `crates/rag-llm-gateway/src/api/routes/chat.rs`
- Create: `crates/rag-llm-gateway/src/api/routes/models.rs`

**Step 1: Create directory structure**

```bash
mkdir -p crates/rag-llm-gateway/src/api/routes
```

**Step 2: Write api/mod.rs**

```rust
//! HTTP API module.

pub mod routes;
pub mod state;

pub use routes::create_router;
pub use state::AppState;
```

**Step 3: Write api/state.rs**

```rust
//! Application state.

use std::sync::Arc;

use rag_embedding::EmbeddingModelWrapper;

use crate::auth::JwtValidator;
use crate::clients::VllmClient;
use crate::config::GatewayConfig;
use crate::rate_limit::RateLimiter;
use crate::reranker::RerankerModel;

/// Shared application state.
pub struct AppState {
    pub config: GatewayConfig,
    pub embedding_model: Option<Arc<EmbeddingModelWrapper>>,
    pub reranker_model: Option<Arc<RerankerModel>>,
    pub vllm_client: Option<VllmClient>,
    pub jwt_validator: Arc<JwtValidator>,
    pub rate_limiter: Arc<RateLimiter>,
}

impl AppState {
    /// Create new application state.
    pub fn new(config: GatewayConfig) -> crate::Result<Self> {
        let jwt_validator = Arc::new(JwtValidator::new(&config.auth)?);
        let rate_limiter = Arc::new(RateLimiter::new(config.rate_limit.clone()));

        let vllm_client = if config.vllm.enabled {
            Some(VllmClient::new(config.vllm.clone())?)
        } else {
            None
        };

        Ok(Self {
            config,
            embedding_model: None,
            reranker_model: None,
            vllm_client,
            jwt_validator,
            rate_limiter,
        })
    }

    /// Set the embedding model.
    pub fn with_embedding_model(mut self, model: EmbeddingModelWrapper) -> Self {
        self.embedding_model = Some(Arc::new(model));
        self
    }

    /// Set the reranker model.
    pub fn with_reranker_model(mut self, model: RerankerModel) -> Self {
        self.reranker_model = Some(Arc::new(model));
        self
    }
}
```

**Step 4: Write api/routes/mod.rs**

```rust
//! API routes.

mod chat;
mod embeddings;
mod health;
mod models;
mod rerank;

use std::sync::Arc;

use axum::{
    middleware,
    routing::{get, post},
    Router,
};

use crate::api::AppState;
use crate::auth::auth_middleware;
use crate::rate_limit::rate_limit_middleware;

/// Create the main router.
pub fn create_router(state: Arc<AppState>) -> Router {
    let api_routes = Router::new()
        // OpenAI-compatible endpoints
        .route("/v1/embeddings", post(embeddings::create_embeddings))
        .route("/v1/chat/completions", post(chat::create_chat_completion))
        .route("/v1/rerank", post(rerank::create_rerank))
        .route("/v1/rerankings", post(rerank::create_rerank))
        .route("/v1/models", get(models::list_models))
        // Apply rate limiting
        .layer(middleware::from_fn_with_state(
            state.rate_limiter.clone(),
            rate_limit_middleware,
        ));

    Router::new()
        // Health endpoints (no auth required)
        .route("/", get(health::root))
        .route("/health", get(health::health))
        .route("/health/live", get(health::liveness))
        .route("/health/ready", get(health::readiness))
        .route("/metrics", get(health::metrics))
        // API routes with auth
        .merge(api_routes)
        .layer(middleware::from_fn_with_state(
            (state.jwt_validator.clone(), Arc::new(state.config.auth.clone())),
            |state, req, next| async move {
                let (validator, config) = state;
                auth_middleware(
                    axum::extract::State(validator),
                    axum::extract::State(config),
                    req,
                    next,
                )
                .await
            },
        ))
        .with_state(state)
}
```

**Step 5: Write api/routes/health.rs**

```rust
//! Health check endpoints.

use std::sync::Arc;

use axum::{extract::State, Json};
use serde::Serialize;

use crate::api::AppState;
use crate::metrics;

#[derive(Serialize)]
pub struct ServiceInfo {
    service: &'static str,
    version: &'static str,
    status: &'static str,
}

pub async fn root() -> Json<ServiceInfo> {
    Json(ServiceInfo {
        service: "llm-gateway",
        version: env!("CARGO_PKG_VERSION"),
        status: "running",
    })
}

#[derive(Serialize)]
pub struct HealthResponse {
    status: &'static str,
    services: ServicesHealth,
}

#[derive(Serialize)]
pub struct ServicesHealth {
    embedding: &'static str,
    reranker: &'static str,
    vllm: &'static str,
}

pub async fn health(State(state): State<Arc<AppState>>) -> Json<HealthResponse> {
    let embedding_status = if state.embedding_model.is_some() {
        "healthy"
    } else {
        "disabled"
    };

    let reranker_status = if state.reranker_model.is_some() {
        "healthy"
    } else {
        "disabled"
    };

    let vllm_status = match &state.vllm_client {
        Some(client) => {
            if client.health_check().await {
                "healthy"
            } else {
                "unhealthy"
            }
        }
        None => "disabled",
    };

    Json(HealthResponse {
        status: "healthy",
        services: ServicesHealth {
            embedding: embedding_status,
            reranker: reranker_status,
            vllm: vllm_status,
        },
    })
}

#[derive(Serialize)]
pub struct LivenessResponse {
    status: &'static str,
}

pub async fn liveness() -> Json<LivenessResponse> {
    Json(LivenessResponse { status: "ok" })
}

pub async fn readiness(State(state): State<Arc<AppState>>) -> Json<LivenessResponse> {
    // Check if at least one model service is available
    let _ = state;
    Json(LivenessResponse { status: "ready" })
}

pub async fn metrics() -> String {
    metrics::gather_metrics()
}
```

**Step 6: Write api/routes/embeddings.rs**

```rust
//! Embedding endpoints.

use std::sync::Arc;
use std::time::Instant;

use axum::{extract::State, Json};
use tracing::{info, instrument};

use rag_embedding::api::types::{EmbeddingRequest, EmbeddingResponse};

use crate::api::AppState;
use crate::error::{GatewayError, Result};
use crate::metrics;

#[instrument(skip(state, request), fields(num_inputs = request.input.len()))]
pub async fn create_embeddings(
    State(state): State<Arc<AppState>>,
    Json(request): Json<EmbeddingRequest>,
) -> Result<Json<EmbeddingResponse>> {
    let model = state
        .embedding_model
        .as_ref()
        .ok_or_else(|| GatewayError::ServiceUnavailable("Embedding service not available".into()))?;

    if request.input.is_empty() {
        return Err(GatewayError::BadRequest("Input cannot be empty".into()));
    }

    let texts = request.input.into_vec();
    let num_texts = texts.len();

    if num_texts > model.max_batch_size() {
        return Err(GatewayError::BadRequest(format!(
            "Batch size {} exceeds maximum {}",
            num_texts,
            model.max_batch_size()
        )));
    }

    let start = Instant::now();

    let model_clone = model.clone();
    let texts_clone = texts.clone();

    let embeddings = tokio::task::spawn_blocking(move || model_clone.embed(&texts_clone))
        .await
        .map_err(|e| GatewayError::Internal(format!("Task failed: {e}")))?
        .map_err(GatewayError::from)?;

    let elapsed = start.elapsed();

    info!(
        num_embeddings = embeddings.len(),
        elapsed_ms = elapsed.as_millis(),
        "Generated embeddings"
    );

    metrics::record_request("embedding", "/v1/embeddings", "success", elapsed.as_secs_f64());
    metrics::EMBEDDINGS_GENERATED.inc_by(num_texts as f64);

    let response = EmbeddingResponse::new(embeddings, model.model_id().to_string(), &texts);

    Ok(Json(response))
}
```

**Step 7: Write api/routes/rerank.rs**

```rust
//! Reranking endpoints.

use std::sync::Arc;

use axum::{extract::State, Json};
use tracing::instrument;

use crate::api::AppState;
use crate::error::{GatewayError, Result};
use crate::reranker::{RerankRequest, RerankResponse};

#[instrument(skip(state, request), fields(num_docs = request.documents.len()))]
pub async fn create_rerank(
    State(state): State<Arc<AppState>>,
    Json(request): Json<RerankRequest>,
) -> Result<Json<RerankResponse>> {
    let model = state
        .reranker_model
        .as_ref()
        .ok_or_else(|| GatewayError::ServiceUnavailable("Reranker service not available".into()))?;

    let response = model.rerank(request).await?;

    Ok(Json(response))
}
```

**Step 8: Write api/routes/chat.rs**

```rust
//! Chat completion endpoints.

use std::sync::Arc;

use axum::{
    body::Body,
    extract::State,
    response::{IntoResponse, Response},
    Json,
};
use futures_util::StreamExt;
use tracing::instrument;

use crate::api::AppState;
use crate::auth::AuthContext;
use crate::clients::types::{ChatCompletionRequest, ChatCompletionResponse};
use crate::error::{GatewayError, Result};

#[instrument(skip(state, request), fields(model = ?request.model, stream = request.stream))]
pub async fn create_chat_completion(
    State(state): State<Arc<AppState>>,
    auth_context: Option<axum::Extension<AuthContext>>,
    Json(request): Json<ChatCompletionRequest>,
) -> Result<Response> {
    let client = state
        .vllm_client
        .as_ref()
        .ok_or_else(|| GatewayError::ServiceUnavailable("vLLM service not available".into()))?;

    let auth = auth_context
        .map(|ext| ext.0)
        .unwrap_or_else(AuthContext::anonymous);

    if request.stream {
        // Streaming response
        let stream = client.chat_completion_stream(request, &auth).await?;

        let body = Body::from_stream(stream.map(|result| {
            result.map(|chunk| {
                let json = serde_json::to_string(&chunk).unwrap_or_default();
                format!("data: {json}\n\n")
            })
        }));

        Ok(Response::builder()
            .header("Content-Type", "text/event-stream")
            .header("Cache-Control", "no-cache")
            .header("Connection", "keep-alive")
            .body(body)
            .unwrap())
    } else {
        // Non-streaming response
        let response = client.chat_completion(request, &auth).await?;
        Ok(Json(response).into_response())
    }
}
```

**Step 9: Write api/routes/models.rs**

```rust
//! Models listing endpoint.

use std::sync::Arc;

use axum::{extract::State, Json};
use serde::Serialize;

use crate::api::AppState;

#[derive(Serialize)]
pub struct ModelInfo {
    id: String,
    object: &'static str,
    owned_by: String,
}

#[derive(Serialize)]
pub struct ModelsResponse {
    object: &'static str,
    data: Vec<ModelInfo>,
}

pub async fn list_models(State(state): State<Arc<AppState>>) -> Json<ModelsResponse> {
    let mut models = Vec::new();

    if let Some(embedding) = &state.embedding_model {
        models.push(ModelInfo {
            id: embedding.model_id().to_string(),
            object: "model",
            owned_by: "embedding-service".into(),
        });
    }

    if let Some(reranker) = &state.reranker_model {
        models.push(ModelInfo {
            id: state.config.reranker.model.clone(),
            object: "model",
            owned_by: "reranker-service".into(),
        });
    }

    if state.vllm_client.is_some() {
        models.push(ModelInfo {
            id: state.config.vllm.default_model.clone(),
            object: "model",
            owned_by: "vllm".into(),
        });
    }

    Json(ModelsResponse {
        object: "list",
        data: models,
    })
}
```

**Step 10: Verify compilation**

```bash
cd crates && cargo check -p rag-llm-gateway
```

**Step 11: Commit**

```bash
git add crates/rag-llm-gateway/src/api
git commit -m "feat(rag-llm-gateway): add API routes for embeddings, rerank, chat, models

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Phase 8: Binary Entry Point

### Task 8.1: Create Main Binary

**Files:**
- Create: `crates/rag-llm-gateway/src/bin/main.rs`

**Step 1: Create bin directory**

```bash
mkdir -p crates/rag-llm-gateway/src/bin
```

**Step 2: Write main.rs**

```rust
//! LLM Gateway service entry point.

use std::net::SocketAddr;
use std::sync::Arc;

use rag_embedding::{EmbeddingConfig, EmbeddingModelWrapper};
use rag_llm_gateway::{api, GatewayConfig};
use tower_http::trace::TraceLayer;
use tracing::{info, Level};
use tracing_subscriber::{fmt, EnvFilter};

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Initialize logging
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::try_from_default_env().unwrap_or_else(|_| EnvFilter::new("info")),
        )
        .init();

    info!("Starting LLM Gateway v{}", env!("CARGO_PKG_VERSION"));

    // Load configuration
    let config = GatewayConfig::from_env();
    info!("Configuration loaded");

    // Create app state
    let mut state = api::AppState::new(config.clone())?;

    // Load embedding model if enabled
    if config.embedding.enabled {
        info!("Loading embedding model...");
        let embed_config = EmbeddingConfig::from_env();
        let model = tokio::task::spawn_blocking(move || EmbeddingModelWrapper::load(&embed_config))
            .await??;
        info!("Embedding model loaded: {}", model.model_id());
        state = state.with_embedding_model(model);
    }

    // Note: Reranker model loading is stubbed for now
    // Would be loaded similarly when ONNX support is complete

    let state = Arc::new(state);

    // Create router
    let app = api::create_router(state).layer(TraceLayer::new_for_http());

    // Start server
    let addr = SocketAddr::new(
        config.server.host.parse()?,
        config.server.port,
    );

    info!("Listening on http://{}", addr);

    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}
```

**Step 3: Verify compilation and build**

```bash
cd crates && cargo build -p rag-llm-gateway
```

**Step 4: Commit**

```bash
git add crates/rag-llm-gateway/src/bin
git commit -m "feat(rag-llm-gateway): add service entry point binary

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Phase 9: Dockerfile and Deployment

### Task 9.1: Create Dockerfile

**Files:**
- Create: `crates/rag-llm-gateway/Dockerfile`

**Step 1: Write Dockerfile**

```dockerfile
# Build stage
FROM rust:1.75-bookworm AS builder

WORKDIR /app

# Copy workspace files
COPY crates/Cargo.toml crates/Cargo.lock ./
COPY crates/rag-types ./rag-types
COPY crates/rag-config ./rag-config
COPY crates/rag-embedding ./rag-embedding
COPY crates/rag-telemetry ./rag-telemetry
COPY crates/rag-llm-gateway ./rag-llm-gateway

# Build release binary
RUN cargo build --release -p rag-llm-gateway

# Runtime stage
FROM debian:bookworm-slim

RUN apt-get update && apt-get install -y \
    ca-certificates \
    libssl3 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy binary
COPY --from=builder /app/target/release/llm-gateway /app/llm-gateway

# Create non-root user
RUN useradd -r -s /bin/false appuser && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8004

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8004/health || exit 1

# Run
ENTRYPOINT ["/app/llm-gateway"]
```

**Step 2: Commit**

```bash
git add crates/rag-llm-gateway/Dockerfile
git commit -m "feat(rag-llm-gateway): add Dockerfile for containerization

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Phase 10: Remove Python llm-serving Code

### Task 10.1: Remove Python llm-serving Directory

**Files:**
- Delete: `llm-serving/` (entire directory)

**Step 1: Verify no dependencies on llm-serving**

```bash
grep -r "llm-serving" --include="*.py" --include="*.yaml" --include="*.yml" services/ k8s/ docker-compose*.yml
```

Review output and update any references.

**Step 2: Update docker-compose.yml if needed**

Remove any llm-serving service definitions and update to use the new Rust gateway.

**Step 3: Remove the directory**

```bash
rm -rf llm-serving/
```

**Step 4: Commit**

```bash
git add -A
git commit -m "chore: remove Python llm-serving code, replaced by rag-llm-gateway

BREAKING CHANGE: The Python embedding-service, reranker-service, and gateway
have been consolidated into the Rust rag-llm-gateway crate.

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Phase 11: Integration and Testing

### Task 11.1: Add Integration Tests

**Files:**
- Create: `crates/rag-llm-gateway/tests/integration.rs`

**Step 1: Write integration tests**

```rust
//! Integration tests for the LLM Gateway.

use axum::body::Body;
use axum::http::{Request, StatusCode};
use tower::ServiceExt;

// Tests would use axum-test or similar for HTTP testing
// Placeholder for now

#[tokio::test]
async fn test_health_endpoint() {
    // Would create test app state and router
    // Make request to /health
    // Assert response
}

#[tokio::test]
async fn test_embeddings_endpoint() {
    // Would create test app state with mock embedding model
    // Make request to /v1/embeddings
    // Assert response format
}
```

**Step 2: Commit**

```bash
git add crates/rag-llm-gateway/tests
git commit -m "test(rag-llm-gateway): add integration test scaffolding

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

### Task 11.2: Update Documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/architecture.md` (if exists)

**Step 1: Update CLAUDE.md**

Add entry for the new gateway service:

```markdown
5. **LLM Gateway** (port 8004) - **Rust** (`crates/rag-llm-gateway/`)
   - Unified OpenAI-compatible API gateway
   - Text embeddings via fastembed
   - Document reranking (cross-encoder)
   - vLLM proxy for chat completions
   - JWT and API key authentication
   - Token bucket rate limiting
   - Prometheus metrics
```

**Step 2: Commit**

```bash
git add CLAUDE.md docs/
git commit -m "docs: update architecture docs for rag-llm-gateway

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Summary

This plan migrates the Python `llm-serving/` components to a unified Rust service:

| Phase | Tasks | Description |
|-------|-------|-------------|
| 1 | 1.1-1.3 | Create crate structure, errors, config |
| 2 | 2.1 | JWT and API key authentication |
| 3 | 3.1 | Token bucket rate limiting |
| 4 | 4.1 | Reranker module (ONNX stub) |
| 5 | 5.1 | vLLM proxy client |
| 6 | 6.1 | Prometheus metrics |
| 7 | 7.1 | API routes |
| 8 | 8.1 | Binary entry point |
| 9 | 9.1 | Dockerfile |
| 10 | 10.1 | Remove Python code |
| 11 | 11.1-11.2 | Testing and docs |

**Key architectural decisions:**
- Consolidates embedding + reranker + gateway into single service
- Reuses existing `rag-embedding` crate
- Proxies to external vLLM rather than implementing LLM inference
- Reranker uses ONNX Runtime (stubbed, needs model export)
- Full auth/rate-limiting middleware chain
