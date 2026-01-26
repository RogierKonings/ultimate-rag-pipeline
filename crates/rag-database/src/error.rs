//! Database error types.

use thiserror::Error;

/// Database errors.
#[derive(Debug, Error)]
pub enum DatabaseError {
    /// Connection error.
    #[error("Connection error: {0}")]
    Connection(String),

    /// Query execution error.
    #[error("Query error: {0}")]
    Query(String),

    /// Transaction error.
    #[error("Transaction error: {0}")]
    Transaction(String),

    /// Row not found.
    #[error("Not found: {0}")]
    NotFound(String),

    /// Constraint violation (unique, foreign key, etc.).
    #[error("Constraint violation: {0}")]
    Constraint(String),

    /// Serialization/deserialization error.
    #[error("Serialization error: {0}")]
    Serialization(String),

    /// Migration error.
    #[error("Migration error: {0}")]
    Migration(String),

    /// Configuration error.
    #[error("Configuration error: {0}")]
    Config(String),

    /// Pool error.
    #[error("Pool error: {0}")]
    Pool(String),
}

impl From<sqlx::Error> for DatabaseError {
    fn from(err: sqlx::Error) -> Self {
        match err {
            sqlx::Error::RowNotFound => Self::NotFound("Row not found".to_string()),
            sqlx::Error::Database(db_err) => {
                // Check for constraint violations
                if let Some(constraint) = db_err.constraint() {
                    Self::Constraint(format!("{}: {}", constraint, db_err))
                } else {
                    Self::Query(db_err.to_string())
                }
            }
            sqlx::Error::PoolTimedOut => Self::Pool("Connection pool timeout".to_string()),
            sqlx::Error::PoolClosed => Self::Pool("Connection pool closed".to_string()),
            _ => Self::Query(err.to_string()),
        }
    }
}

impl From<sqlx::migrate::MigrateError> for DatabaseError {
    fn from(err: sqlx::migrate::MigrateError) -> Self {
        Self::Migration(err.to_string())
    }
}

/// Result type alias for database operations.
pub type Result<T> = std::result::Result<T, DatabaseError>;
