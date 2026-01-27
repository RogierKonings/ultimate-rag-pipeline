//! Index status tracking.

use serde::{Deserialize, Serialize};

/// Status of document indexing.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum IndexStatus {
    /// Indexing is in progress.
    Pending,
    /// Successfully indexed to all stores.
    Ok,
    /// Indexing failed.
    Error,
    /// Document content changed, needs re-indexing.
    Stale,
}

impl Default for IndexStatus {
    fn default() -> Self {
        Self::Pending
    }
}

impl std::fmt::Display for IndexStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Pending => write!(f, "pending"),
            Self::Ok => write!(f, "ok"),
            Self::Error => write!(f, "error"),
            Self::Stale => write!(f, "stale"),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_status_default() {
        assert_eq!(IndexStatus::default(), IndexStatus::Pending);
    }

    #[test]
    fn test_status_display() {
        assert_eq!(IndexStatus::Ok.to_string(), "ok");
        assert_eq!(IndexStatus::Error.to_string(), "error");
    }

    #[test]
    fn test_status_serde() {
        let status = IndexStatus::Ok;
        let json = serde_json::to_string(&status).unwrap();
        assert_eq!(json, "\"ok\"");

        let parsed: IndexStatus = serde_json::from_str("\"pending\"").unwrap();
        assert_eq!(parsed, IndexStatus::Pending);
    }
}
