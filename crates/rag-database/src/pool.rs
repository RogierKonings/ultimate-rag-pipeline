//! Database connection pool.

use sqlx::postgres::{PgConnectOptions, PgPoolOptions};
use sqlx::PgPool;
use std::str::FromStr;

use crate::{DatabaseConfig, DatabaseError, Result};

/// Database connection pool wrapper.
#[derive(Clone)]
pub struct DatabasePool {
    pool: PgPool,
}

impl DatabasePool {
    /// Connect to the database with the given configuration.
    ///
    /// # Errors
    ///
    /// Returns an error if the connection fails.
    pub async fn connect(config: &DatabaseConfig) -> Result<Self> {
        let connect_options = PgConnectOptions::from_str(&config.url)
            .map_err(|e| DatabaseError::Config(format!("Invalid database URL: {e}")))?
            .application_name(&config.application_name);

        let pool = PgPoolOptions::new()
            .max_connections(config.max_connections)
            .min_connections(config.min_connections)
            .acquire_timeout(config.connect_timeout)
            .idle_timeout(Some(config.idle_timeout))
            .max_lifetime(Some(config.max_lifetime))
            .connect_with(connect_options)
            .await
            .map_err(|e| DatabaseError::Connection(format!("Failed to connect: {e}")))?;

        tracing::info!(
            max_connections = config.max_connections,
            min_connections = config.min_connections,
            "Database pool initialized"
        );

        Ok(Self { pool })
    }

    /// Connect using default configuration from environment.
    ///
    /// # Errors
    ///
    /// Returns an error if the connection fails.
    pub async fn connect_from_env() -> Result<Self> {
        let config = DatabaseConfig::from_env();
        Self::connect(&config).await
    }

    /// Get a reference to the underlying pool.
    #[must_use]
    pub fn inner(&self) -> &PgPool {
        &self.pool
    }

    /// Get the current pool size.
    #[must_use]
    pub fn size(&self) -> u32 {
        self.pool.size()
    }

    /// Get the number of idle connections.
    #[must_use]
    pub fn num_idle(&self) -> usize {
        self.pool.num_idle()
    }

    /// Check if the pool is closed.
    #[must_use]
    pub fn is_closed(&self) -> bool {
        self.pool.is_closed()
    }

    /// Close the pool.
    pub async fn close(&self) {
        self.pool.close().await;
    }

    /// Acquire a connection from the pool.
    ///
    /// # Errors
    ///
    /// Returns an error if a connection cannot be acquired.
    pub async fn acquire(&self) -> Result<sqlx::pool::PoolConnection<sqlx::Postgres>> {
        self.pool
            .acquire()
            .await
            .map_err(|e| DatabaseError::Pool(format!("Failed to acquire connection: {e}")))
    }

    /// Begin a transaction.
    ///
    /// # Errors
    ///
    /// Returns an error if the transaction cannot be started.
    pub async fn begin(&self) -> Result<sqlx::Transaction<'_, sqlx::Postgres>> {
        self.pool
            .begin()
            .await
            .map_err(|e| DatabaseError::Transaction(format!("Failed to begin transaction: {e}")))
    }

    /// Execute a simple query (for health checks, etc.).
    ///
    /// # Errors
    ///
    /// Returns an error if the query fails.
    pub async fn ping(&self) -> Result<()> {
        sqlx::query("SELECT 1")
            .execute(&self.pool)
            .await
            .map_err(|e| DatabaseError::Query(format!("Ping failed: {e}")))?;
        Ok(())
    }

    /// Check database health.
    ///
    /// # Errors
    ///
    /// Returns an error if the health check fails.
    pub async fn health_check(&self) -> Result<HealthStatus> {
        let start = std::time::Instant::now();

        match self.ping().await {
            Ok(()) => Ok(HealthStatus {
                healthy: true,
                latency_ms: start.elapsed().as_millis() as u64,
                pool_size: self.size(),
                idle_connections: self.num_idle(),
                error: None,
            }),
            Err(e) => Ok(HealthStatus {
                healthy: false,
                latency_ms: start.elapsed().as_millis() as u64,
                pool_size: self.size(),
                idle_connections: self.num_idle(),
                error: Some(e.to_string()),
            }),
        }
    }
}

impl std::fmt::Debug for DatabasePool {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("DatabasePool")
            .field("size", &self.size())
            .field("num_idle", &self.num_idle())
            .field("is_closed", &self.is_closed())
            .finish()
    }
}

/// Database health status.
#[derive(Debug, Clone)]
pub struct HealthStatus {
    /// Whether the database is healthy.
    pub healthy: bool,
    /// Ping latency in milliseconds.
    pub latency_ms: u64,
    /// Current pool size.
    pub pool_size: u32,
    /// Number of idle connections.
    pub idle_connections: usize,
    /// Error message if unhealthy.
    pub error: Option<String>,
}
