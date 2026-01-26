//! Structured logging helpers for the retrieval service.
//!
//! This module provides request context propagation and logging helpers
//! for consistent, structured log output.

use serde::{Deserialize, Serialize};
use tracing::{error, info, warn};
use uuid::Uuid;

/// Request context for logging and tracing.
///
/// This context carries identifying information through the request lifecycle
/// and ensures consistent logging across all pipeline stages.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RequestContext {
    /// Unique request identifier.
    pub request_id: Uuid,

    /// Tenant identifier for multi-tenancy.
    pub tenant_id: Uuid,

    /// Optional user identifier.
    pub user_id: Option<Uuid>,

    /// Optional correlation ID for distributed tracing.
    pub correlation_id: Option<String>,
}

impl RequestContext {
    /// Create a new request context with a generated request ID.
    ///
    /// # Arguments
    ///
    /// * `tenant_id` - The tenant identifier
    #[must_use]
    pub fn new(tenant_id: Uuid) -> Self {
        Self {
            request_id: Uuid::new_v4(),
            tenant_id,
            user_id: None,
            correlation_id: None,
        }
    }

    /// Create a request context with a specific request ID.
    ///
    /// # Arguments
    ///
    /// * `request_id` - The request identifier
    /// * `tenant_id` - The tenant identifier
    #[must_use]
    pub const fn with_request_id(request_id: Uuid, tenant_id: Uuid) -> Self {
        Self {
            request_id,
            tenant_id,
            user_id: None,
            correlation_id: None,
        }
    }

    /// Set the user ID.
    #[must_use]
    pub fn with_user(mut self, user_id: Uuid) -> Self {
        self.user_id = Some(user_id);
        self
    }

    /// Set the correlation ID for distributed tracing.
    #[must_use]
    pub fn with_correlation_id(mut self, correlation_id: impl Into<String>) -> Self {
        self.correlation_id = Some(correlation_id.into());
        self
    }

    /// Get the request ID as a string.
    #[must_use]
    pub fn request_id_str(&self) -> String {
        self.request_id.to_string()
    }

    /// Get the tenant ID as a string.
    #[must_use]
    pub fn tenant_id_str(&self) -> String {
        self.tenant_id.to_string()
    }
}

impl Default for RequestContext {
    fn default() -> Self {
        Self {
            request_id: Uuid::new_v4(),
            tenant_id: Uuid::nil(),
            user_id: None,
            correlation_id: None,
        }
    }
}

/// Log the start of a retrieval request.
///
/// # Arguments
///
/// * `ctx` - Request context
/// * `query` - The search query
/// * `mode` - Search mode (hybrid, semantic, keyword)
pub fn log_request_start(ctx: &RequestContext, query: &str, mode: &str) {
    info!(
        request_id = %ctx.request_id,
        tenant_id = %ctx.tenant_id,
        user_id = ?ctx.user_id,
        correlation_id = ?ctx.correlation_id,
        query_length = query.len(),
        mode = mode,
        "Starting retrieval request"
    );
}

/// Log the completion of a retrieval request.
///
/// # Arguments
///
/// * `ctx` - Request context
/// * `latency_ms` - Request latency in milliseconds
/// * `result_count` - Number of results returned
pub fn log_request_complete(ctx: &RequestContext, latency_ms: f64, result_count: usize) {
    info!(
        request_id = %ctx.request_id,
        tenant_id = %ctx.tenant_id,
        latency_ms = latency_ms,
        result_count = result_count,
        "Retrieval request completed"
    );
}

/// Log the completion of a pipeline stage.
///
/// # Arguments
///
/// * `ctx` - Request context
/// * `stage` - Stage name
/// * `latency_ms` - Stage latency in milliseconds
pub fn log_stage_complete(ctx: &RequestContext, stage: &str, latency_ms: f64) {
    info!(
        request_id = %ctx.request_id,
        stage = stage,
        latency_ms = latency_ms,
        "Pipeline stage completed"
    );
}

/// Log stage completion with result count.
///
/// # Arguments
///
/// * `ctx` - Request context
/// * `stage` - Stage name
/// * `latency_ms` - Stage latency in milliseconds
/// * `result_count` - Number of results after this stage
pub fn log_stage_with_count(
    ctx: &RequestContext,
    stage: &str,
    latency_ms: f64,
    result_count: usize,
) {
    info!(
        request_id = %ctx.request_id,
        stage = stage,
        latency_ms = latency_ms,
        result_count = result_count,
        "Pipeline stage completed"
    );
}

/// Log an error in the pipeline.
///
/// # Arguments
///
/// * `ctx` - Request context
/// * `stage` - Stage where the error occurred
/// * `error` - Error message
pub fn log_error(ctx: &RequestContext, stage: &str, error: &str) {
    error!(
        request_id = %ctx.request_id,
        tenant_id = %ctx.tenant_id,
        stage = stage,
        error = error,
        "Pipeline stage failed"
    );
}

/// Log an error with additional context.
///
/// # Arguments
///
/// * `ctx` - Request context
/// * `stage` - Stage where the error occurred
/// * `error` - Error message
/// * `error_type` - Error type/category
pub fn log_error_with_type(ctx: &RequestContext, stage: &str, error: &str, error_type: &str) {
    error!(
        request_id = %ctx.request_id,
        tenant_id = %ctx.tenant_id,
        stage = stage,
        error = error,
        error_type = error_type,
        "Pipeline stage failed"
    );
}

/// Log a warning in the pipeline.
///
/// # Arguments
///
/// * `ctx` - Request context
/// * `stage` - Stage where the warning occurred
/// * `message` - Warning message
pub fn log_warning(ctx: &RequestContext, stage: &str, message: &str) {
    warn!(
        request_id = %ctx.request_id,
        tenant_id = %ctx.tenant_id,
        stage = stage,
        message = message,
        "Pipeline warning"
    );
}

/// Log a cache hit.
///
/// # Arguments
///
/// * `ctx` - Request context
/// * `cache_key` - The cache key that was hit
pub fn log_cache_hit(ctx: &RequestContext, cache_key: &str) {
    info!(
        request_id = %ctx.request_id,
        cache_key = cache_key,
        cache_hit = true,
        "Cache hit"
    );
}

/// Log a cache miss.
///
/// # Arguments
///
/// * `ctx` - Request context
/// * `cache_key` - The cache key that was missed
pub fn log_cache_miss(ctx: &RequestContext, cache_key: &str) {
    info!(
        request_id = %ctx.request_id,
        cache_key = cache_key,
        cache_hit = false,
        "Cache miss"
    );
}

/// Log component health check result.
///
/// # Arguments
///
/// * `component` - Component name
/// * `healthy` - Whether the component is healthy
/// * `latency_ms` - Health check latency in milliseconds
pub fn log_health_check(component: &str, healthy: bool, latency_ms: f64) {
    if healthy {
        info!(
            component = component,
            healthy = true,
            latency_ms = latency_ms,
            "Health check passed"
        );
    } else {
        warn!(
            component = component,
            healthy = false,
            latency_ms = latency_ms,
            "Health check failed"
        );
    }
}

/// Log reranking operation details.
///
/// # Arguments
///
/// * `ctx` - Request context
/// * `input_count` - Number of documents input to reranker
/// * `output_count` - Number of documents after reranking
/// * `latency_ms` - Reranking latency in milliseconds
pub fn log_rerank(ctx: &RequestContext, input_count: usize, output_count: usize, latency_ms: f64) {
    info!(
        request_id = %ctx.request_id,
        stage = "rerank",
        input_count = input_count,
        output_count = output_count,
        latency_ms = latency_ms,
        "Reranking completed"
    );
}

/// Log ACL filtering details.
///
/// # Arguments
///
/// * `ctx` - Request context
/// * `before_count` - Number of results before filtering
/// * `after_count` - Number of results after filtering
/// * `filtered_count` - Number of results filtered out
pub fn log_acl_filter(
    ctx: &RequestContext,
    before_count: usize,
    after_count: usize,
    filtered_count: usize,
) {
    info!(
        request_id = %ctx.request_id,
        stage = "acl_filter",
        before_count = before_count,
        after_count = after_count,
        filtered_count = filtered_count,
        "ACL filtering completed"
    );
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_request_context_creation() {
        let tenant_id = Uuid::new_v4();
        let ctx = RequestContext::new(tenant_id);

        assert_eq!(ctx.tenant_id, tenant_id);
        assert!(ctx.user_id.is_none());
        assert!(ctx.correlation_id.is_none());
    }

    #[test]
    fn test_request_context_with_user() {
        let tenant_id = Uuid::new_v4();
        let user_id = Uuid::new_v4();

        let ctx = RequestContext::new(tenant_id).with_user(user_id);

        assert_eq!(ctx.tenant_id, tenant_id);
        assert_eq!(ctx.user_id, Some(user_id));
    }

    #[test]
    fn test_request_context_with_correlation_id() {
        let tenant_id = Uuid::new_v4();
        let correlation_id = "trace-123";

        let ctx = RequestContext::new(tenant_id).with_correlation_id(correlation_id);

        assert_eq!(ctx.correlation_id, Some("trace-123".to_string()));
    }

    #[test]
    fn test_request_context_with_request_id() {
        let request_id = Uuid::new_v4();
        let tenant_id = Uuid::new_v4();

        let ctx = RequestContext::with_request_id(request_id, tenant_id);

        assert_eq!(ctx.request_id, request_id);
        assert_eq!(ctx.tenant_id, tenant_id);
    }

    #[test]
    fn test_request_context_default() {
        let ctx = RequestContext::default();

        assert_eq!(ctx.tenant_id, Uuid::nil());
        assert!(ctx.user_id.is_none());
    }

    #[test]
    fn test_request_id_str() {
        let ctx = RequestContext::new(Uuid::new_v4());
        let id_str = ctx.request_id_str();

        assert!(!id_str.is_empty());
        assert!(Uuid::parse_str(&id_str).is_ok());
    }

    #[test]
    fn test_tenant_id_str() {
        let tenant_id = Uuid::new_v4();
        let ctx = RequestContext::new(tenant_id);

        assert_eq!(ctx.tenant_id_str(), tenant_id.to_string());
    }

    #[test]
    fn test_request_context_serialization() {
        let tenant_id = Uuid::new_v4();
        let ctx = RequestContext::new(tenant_id).with_correlation_id("test-correlation");

        let json = serde_json::to_string(&ctx).unwrap();
        let deserialized: RequestContext = serde_json::from_str(&json).unwrap();

        assert_eq!(deserialized.tenant_id, tenant_id);
        assert_eq!(
            deserialized.correlation_id,
            Some("test-correlation".to_string())
        );
    }
}
