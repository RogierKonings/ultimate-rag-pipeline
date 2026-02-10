//! Shared retry logic with exponential backoff for RAG Pipeline services.
//!
//! Provides a configurable retry policy with exponential backoff and jitter,
//! replacing hand-rolled retry loops across multiple crates.

use std::time::Duration;

/// Configuration for retry behavior with exponential backoff.
#[derive(Debug, Clone)]
pub struct RetryPolicy {
    /// Maximum number of retries (0 = no retries, just the initial attempt).
    pub max_retries: u32,
    /// Base wait time in milliseconds for the first retry.
    pub base_wait_ms: u64,
    /// Maximum wait time in milliseconds (backoff cap).
    pub max_wait_ms: u64,
}

impl Default for RetryPolicy {
    fn default() -> Self {
        Self {
            max_retries: 2,
            base_wait_ms: 100,
            max_wait_ms: 5000,
        }
    }
}

impl RetryPolicy {
    #[must_use]
    pub fn new(max_retries: u32, base_wait_ms: u64, max_wait_ms: u64) -> Self {
        Self {
            max_retries,
            base_wait_ms,
            max_wait_ms,
        }
    }

    /// No retries - just the initial attempt.
    #[must_use]
    pub fn no_retry() -> Self {
        Self {
            max_retries: 0,
            ..Self::default()
        }
    }

    /// Calculate the backoff duration for a given attempt number (0-indexed).
    ///
    /// Uses exponential backoff: `min(base_ms * 2^attempt, max_ms)` with ±25% jitter.
    #[must_use]
    #[allow(clippy::cast_possible_truncation)]
    pub fn backoff_duration(&self, attempt: u32) -> Duration {
        let base_backoff = self.base_wait_ms.saturating_mul(1u64 << attempt.min(10));
        let capped_backoff = base_backoff.min(self.max_wait_ms);

        // Add ±25% jitter using system time nanoseconds as pseudo-random source
        let jitter_range = capped_backoff / 4;
        let jitter = if jitter_range > 0 {
            let seed = std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .map_or(0, |d| d.as_nanos() as u64);
            (seed % (jitter_range * 2)) as i64 - jitter_range as i64
        } else {
            0
        };

        #[allow(clippy::cast_sign_loss)]
        let total_ms = (capped_backoff as i64 + jitter).max(0) as u64;
        Duration::from_millis(total_ms)
    }

    /// Execute an async operation with retry.
    ///
    /// The `is_retryable` closure determines whether a failed attempt should be retried.
    /// Returns the first successful result, or the last error if all attempts fail.
    #[allow(clippy::missing_panics_doc)]
    pub async fn execute<F, Fut, T, E>(
        &self,
        mut operation: F,
        is_retryable: impl Fn(&E) -> bool,
    ) -> Result<T, E>
    where
        F: FnMut() -> Fut,
        Fut: std::future::Future<Output = Result<T, E>>,
        E: std::fmt::Display,
    {
        let mut last_error = None;

        for attempt in 0..=self.max_retries {
            if attempt > 0 {
                let backoff = self.backoff_duration(attempt - 1);
                tracing::debug!(attempt, backoff_ms = backoff.as_millis(), "Retrying operation");
                tokio::time::sleep(backoff).await;
            }

            match operation().await {
                Ok(result) => return Ok(result),
                Err(e) => {
                    if is_retryable(&e) && attempt < self.max_retries {
                        tracing::warn!(attempt, error = %e, "Operation failed, will retry");
                        last_error = Some(e);
                    } else {
                        return Err(e);
                    }
                }
            }
        }

        Err(last_error.expect("retry loop should have set last_error"))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_policy() {
        let policy = RetryPolicy::default();
        assert_eq!(policy.max_retries, 2);
        assert_eq!(policy.base_wait_ms, 100);
        assert_eq!(policy.max_wait_ms, 5000);
    }

    #[test]
    fn test_no_retry_policy() {
        let policy = RetryPolicy::no_retry();
        assert_eq!(policy.max_retries, 0);
    }

    #[test]
    fn test_backoff_increases() {
        let policy = RetryPolicy::new(5, 100, 5000);

        // Attempt 0: base = 100ms
        let b0 = policy.backoff_duration(0);
        // Attempt 3: base = 800ms
        let b3 = policy.backoff_duration(3);

        // b3 should generally be larger than b0 (jitter may cause overlap, but base is higher)
        // We check the rough range instead of exact values due to jitter
        assert!(b0.as_millis() >= 75); // 100 - 25% jitter
        assert!(b0.as_millis() <= 125); // 100 + 25% jitter
        assert!(b3.as_millis() >= 600); // 800 - 25% jitter
        assert!(b3.as_millis() <= 1000); // 800 + 25% jitter
    }

    #[test]
    fn test_backoff_caps_at_max() {
        let policy = RetryPolicy::new(5, 100, 5000);
        let b20 = policy.backoff_duration(20);
        // Should be capped at max_wait_ms (5000) + 25% jitter max
        assert!(b20.as_millis() <= 6250);
    }

    #[tokio::test]
    async fn test_execute_succeeds_first_try() {
        let policy = RetryPolicy::new(3, 10, 100);
        let result: Result<i32, String> =
            policy.execute(|| async { Ok(42) }, |_: &String| true).await;
        assert_eq!(result.unwrap(), 42);
    }

    #[tokio::test]
    async fn test_execute_retries_then_succeeds() {
        let policy = RetryPolicy::new(3, 10, 100);
        let attempt = std::sync::atomic::AtomicU32::new(0);

        let result: Result<i32, String> = policy
            .execute(
                || {
                    let current = attempt.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
                    async move {
                        if current < 2 {
                            Err("transient error".to_string())
                        } else {
                            Ok(42)
                        }
                    }
                },
                |_: &String| true,
            )
            .await;

        assert_eq!(result.unwrap(), 42);
        assert_eq!(attempt.load(std::sync::atomic::Ordering::SeqCst), 3);
    }

    #[tokio::test]
    async fn test_execute_non_retryable_fails_immediately() {
        let policy = RetryPolicy::new(3, 10, 100);
        let attempt = std::sync::atomic::AtomicU32::new(0);

        let result: Result<i32, String> = policy
            .execute(
                || {
                    attempt.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
                    async { Err("non-retryable".to_string()) }
                },
                |_: &String| false, // never retry
            )
            .await;

        assert!(result.is_err());
        assert_eq!(attempt.load(std::sync::atomic::Ordering::SeqCst), 1);
    }
}
