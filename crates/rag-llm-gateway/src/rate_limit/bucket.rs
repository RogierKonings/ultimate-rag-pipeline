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
        let burst_limit = (limit as f64 * self.config.burst_multiplier as f64) as u32;
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
