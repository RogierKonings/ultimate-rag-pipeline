//! Tenant index configuration types.

use serde::{Deserialize, Serialize};
use std::str::FromStr;
use uuid::Uuid;

/// Index isolation mode.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize, Default)]
#[serde(rename_all = "lowercase")]
pub enum IsolationMode {
    /// All tenants share the same indices with tenant_id filtering.
    #[default]
    Shared,
    /// Each tenant has dedicated indices.
    Dedicated,
}

impl IsolationMode {
    /// Get the string representation.
    #[must_use]
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Shared => "shared",
            Self::Dedicated => "dedicated",
        }
    }
}

impl std::fmt::Display for IsolationMode {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

impl FromStr for IsolationMode {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "shared" => Ok(Self::Shared),
            "dedicated" => Ok(Self::Dedicated),
            _ => Err(format!("Invalid isolation mode: {s}")),
        }
    }
}

/// Tenant index configuration.
///
/// Defines which Qdrant collection and OpenSearch index a tenant uses.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TenantIndexConfig {
    /// Tenant identifier.
    pub tenant_id: Uuid,
    /// Qdrant collection name.
    pub qdrant_collection: String,
    /// OpenSearch index name.
    pub opensearch_index: String,
    /// Index isolation mode.
    pub isolation_mode: IsolationMode,
    /// Custom Qdrant settings (HNSW config, etc).
    #[serde(default)]
    pub qdrant_settings: Option<serde_json::Value>,
    /// Custom OpenSearch settings (shards, replicas, etc).
    #[serde(default)]
    pub opensearch_settings: Option<serde_json::Value>,
}

impl TenantIndexConfig {
    /// Create a shared index configuration.
    #[must_use]
    pub fn shared(tenant_id: Uuid) -> Self {
        Self {
            tenant_id,
            qdrant_collection: "documents".to_string(),
            opensearch_index: "documents".to_string(),
            isolation_mode: IsolationMode::Shared,
            qdrant_settings: None,
            opensearch_settings: None,
        }
    }

    /// Create a dedicated index configuration.
    #[must_use]
    pub fn dedicated(tenant_id: Uuid) -> Self {
        Self {
            tenant_id,
            qdrant_collection: format!("documents_{}", tenant_id),
            opensearch_index: format!("documents-{}", tenant_id),
            isolation_mode: IsolationMode::Dedicated,
            qdrant_settings: None,
            opensearch_settings: None,
        }
    }

    /// Create configuration with custom names.
    #[must_use]
    pub fn custom(
        tenant_id: Uuid,
        qdrant_collection: impl Into<String>,
        opensearch_index: impl Into<String>,
        isolation_mode: IsolationMode,
    ) -> Self {
        Self {
            tenant_id,
            qdrant_collection: qdrant_collection.into(),
            opensearch_index: opensearch_index.into(),
            isolation_mode,
            qdrant_settings: None,
            opensearch_settings: None,
        }
    }

    /// Check if this is a dedicated configuration.
    #[must_use]
    pub fn is_dedicated(&self) -> bool {
        self.isolation_mode == IsolationMode::Dedicated
    }

    /// Check if this is a shared configuration.
    #[must_use]
    pub fn is_shared(&self) -> bool {
        self.isolation_mode == IsolationMode::Shared
    }

    /// Set Qdrant settings.
    #[must_use]
    pub fn with_qdrant_settings(mut self, settings: serde_json::Value) -> Self {
        self.qdrant_settings = Some(settings);
        self
    }

    /// Set OpenSearch settings.
    #[must_use]
    pub fn with_opensearch_settings(mut self, settings: serde_json::Value) -> Self {
        self.opensearch_settings = Some(settings);
        self
    }
}

impl Default for TenantIndexConfig {
    fn default() -> Self {
        Self::shared(Uuid::nil())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_shared_config() {
        let tenant_id = Uuid::new_v4();
        let config = TenantIndexConfig::shared(tenant_id);

        assert_eq!(config.tenant_id, tenant_id);
        assert_eq!(config.qdrant_collection, "documents");
        assert_eq!(config.opensearch_index, "documents");
        assert!(config.is_shared());
        assert!(!config.is_dedicated());
    }

    #[test]
    fn test_dedicated_config() {
        let tenant_id = Uuid::new_v4();
        let config = TenantIndexConfig::dedicated(tenant_id);

        assert_eq!(config.tenant_id, tenant_id);
        assert!(config.qdrant_collection.contains(&tenant_id.to_string()));
        assert!(config.opensearch_index.contains(&tenant_id.to_string()));
        assert!(config.is_dedicated());
    }

    #[test]
    fn test_isolation_mode_from_str() {
        assert_eq!(IsolationMode::from_str("shared").unwrap(), IsolationMode::Shared);
        assert_eq!(IsolationMode::from_str("dedicated").unwrap(), IsolationMode::Dedicated);
        assert!(IsolationMode::from_str("invalid").is_err());
    }
}
