//! Database configuration.

use std::time::Duration;

/// Database configuration.
#[derive(Debug, Clone)]
pub struct DatabaseConfig {
    /// Database URL (postgres://user:pass@host:port/database).
    pub url: String,
    /// Maximum number of connections in the pool.
    pub max_connections: u32,
    /// Minimum number of connections in the pool.
    pub min_connections: u32,
    /// Connection timeout.
    pub connect_timeout: Duration,
    /// Idle connection timeout.
    pub idle_timeout: Duration,
    /// Maximum lifetime of a connection.
    pub max_lifetime: Duration,
    /// Enable statement caching.
    pub statement_cache_capacity: usize,
    /// Application name (shown in pg_stat_activity).
    pub application_name: String,
}

impl Default for DatabaseConfig {
    fn default() -> Self {
        Self {
            url: "postgres://localhost:5432/ragpipeline".to_string(),
            max_connections: 10,
            min_connections: 1,
            connect_timeout: Duration::from_secs(30),
            idle_timeout: Duration::from_secs(600),
            max_lifetime: Duration::from_secs(1800),
            statement_cache_capacity: 100,
            application_name: "rag-pipeline".to_string(),
        }
    }
}

impl DatabaseConfig {
    /// Create a new database configuration.
    #[must_use]
    pub fn new(url: impl Into<String>) -> Self {
        Self {
            url: url.into(),
            ..Default::default()
        }
    }

    /// Create configuration from environment variables.
    #[must_use]
    pub fn from_env() -> Self {
        let url = std::env::var("DATABASE_URL").unwrap_or_else(|_| {
            "postgres://raguser:ragpassword@localhost:5432/ragpipeline".to_string()
        });

        let max_connections = std::env::var("DATABASE_MAX_CONNECTIONS")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(10);

        let min_connections = std::env::var("DATABASE_MIN_CONNECTIONS")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(1);

        let connect_timeout_secs = std::env::var("DATABASE_CONNECT_TIMEOUT_SECS")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(30);

        let idle_timeout_secs = std::env::var("DATABASE_IDLE_TIMEOUT_SECS")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(600);

        let max_lifetime_secs = std::env::var("DATABASE_MAX_LIFETIME_SECS")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(1800);

        let statement_cache_capacity = std::env::var("DATABASE_STATEMENT_CACHE_SIZE")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(100);

        let application_name = std::env::var("DATABASE_APPLICATION_NAME")
            .unwrap_or_else(|_| "rag-pipeline".to_string());

        Self {
            url,
            max_connections,
            min_connections,
            connect_timeout: Duration::from_secs(connect_timeout_secs),
            idle_timeout: Duration::from_secs(idle_timeout_secs),
            max_lifetime: Duration::from_secs(max_lifetime_secs),
            statement_cache_capacity,
            application_name,
        }
    }

    /// Set maximum connections.
    #[must_use]
    pub const fn with_max_connections(mut self, max: u32) -> Self {
        self.max_connections = max;
        self
    }

    /// Set minimum connections.
    #[must_use]
    pub const fn with_min_connections(mut self, min: u32) -> Self {
        self.min_connections = min;
        self
    }

    /// Set connection timeout.
    #[must_use]
    pub const fn with_connect_timeout(mut self, timeout: Duration) -> Self {
        self.connect_timeout = timeout;
        self
    }

    /// Set application name.
    #[must_use]
    pub fn with_application_name(mut self, name: impl Into<String>) -> Self {
        self.application_name = name.into();
        self
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_default_config() {
        let config = DatabaseConfig::default();
        assert_eq!(config.max_connections, 10);
        assert_eq!(config.min_connections, 1);
    }

    #[test]
    fn test_builder_pattern() {
        let config = DatabaseConfig::new("postgres://localhost/test")
            .with_max_connections(20)
            .with_min_connections(5)
            .with_application_name("test-app");

        assert_eq!(config.max_connections, 20);
        assert_eq!(config.min_connections, 5);
        assert_eq!(config.application_name, "test-app");
    }
}
