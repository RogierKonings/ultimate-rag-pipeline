//! Configuration for ACL filtering.
//!
//! This module provides the configuration structure for the ACL filter,
//! allowing control over admin bypass, super tenant behavior, and
//! default visibility settings.

use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::types::Visibility;

/// Configuration for ACL filtering behavior.
///
/// Controls how access control is enforced during search operations.
///
/// # Example
///
/// ```
/// use rag_retrieval::acl::ACLFilterConfig;
/// use rag_retrieval::types::Visibility;
/// use uuid::Uuid;
///
/// // Default configuration
/// let config = ACLFilterConfig::default();
/// assert!(config.enabled);
/// assert!(config.admin_bypass);
/// assert_eq!(config.default_visibility, Visibility::Private);
///
/// // Custom configuration with super tenant
/// let config = ACLFilterConfig::builder()
///     .admin_bypass(false)
///     .super_tenant_id(Some(Uuid::new_v4()))
///     .build();
/// ```
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ACLFilterConfig {
    /// Whether ACL filtering is enabled.
    ///
    /// When disabled, no ACL filters are applied to searches.
    /// Default: `true`
    pub enabled: bool,

    /// Whether admin users bypass ACL filtering.
    ///
    /// When enabled, users with `is_admin = true` see all documents
    /// regardless of visibility settings.
    /// Default: `true`
    pub admin_bypass: bool,

    /// Super tenant ID that can see all tenants.
    ///
    /// If set, users in this tenant can search across all tenants.
    /// Default: `None`
    pub super_tenant_id: Option<Uuid>,

    /// Default visibility for documents without explicit ACL.
    ///
    /// Used when a document doesn't have a visibility field set.
    /// Default: `Visibility::Private`
    pub default_visibility: Visibility,
}

impl Default for ACLFilterConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            admin_bypass: true,
            super_tenant_id: None,
            default_visibility: Visibility::Private,
        }
    }
}

impl ACLFilterConfig {
    /// Create a new ACL filter configuration with all settings.
    #[must_use]
    pub fn new(
        enabled: bool,
        admin_bypass: bool,
        super_tenant_id: Option<Uuid>,
        default_visibility: Visibility,
    ) -> Self {
        Self {
            enabled,
            admin_bypass,
            super_tenant_id,
            default_visibility,
        }
    }

    /// Create a builder for constructing ACL filter configuration.
    #[must_use]
    pub fn builder() -> ACLFilterConfigBuilder {
        ACLFilterConfigBuilder::default()
    }

    /// Create a disabled ACL filter configuration.
    ///
    /// Useful for testing or when ACL should be completely bypassed.
    #[must_use]
    pub fn disabled() -> Self {
        Self {
            enabled: false,
            ..Default::default()
        }
    }

    /// Check if ACL filtering should be applied.
    #[must_use]
    pub const fn is_enabled(&self) -> bool {
        self.enabled
    }

    /// Check if the given tenant is the super tenant.
    #[must_use]
    pub fn is_super_tenant(&self, tenant_id: Uuid) -> bool {
        self.super_tenant_id.map_or(false, |super_id| super_id == tenant_id)
    }
}

/// Builder for [`ACLFilterConfig`].
#[derive(Debug, Clone, Default)]
pub struct ACLFilterConfigBuilder {
    enabled: Option<bool>,
    admin_bypass: Option<bool>,
    super_tenant_id: Option<Option<Uuid>>,
    default_visibility: Option<Visibility>,
}

impl ACLFilterConfigBuilder {
    /// Set whether ACL filtering is enabled.
    #[must_use]
    pub const fn enabled(mut self, enabled: bool) -> Self {
        self.enabled = Some(enabled);
        self
    }

    /// Set whether admin users bypass ACL filtering.
    #[must_use]
    pub const fn admin_bypass(mut self, admin_bypass: bool) -> Self {
        self.admin_bypass = Some(admin_bypass);
        self
    }

    /// Set the super tenant ID.
    #[must_use]
    pub const fn super_tenant_id(mut self, super_tenant_id: Option<Uuid>) -> Self {
        self.super_tenant_id = Some(super_tenant_id);
        self
    }

    /// Set the default visibility.
    #[must_use]
    pub const fn default_visibility(mut self, default_visibility: Visibility) -> Self {
        self.default_visibility = Some(default_visibility);
        self
    }

    /// Build the [`ACLFilterConfig`].
    #[must_use]
    pub fn build(self) -> ACLFilterConfig {
        let default = ACLFilterConfig::default();
        ACLFilterConfig {
            enabled: self.enabled.unwrap_or(default.enabled),
            admin_bypass: self.admin_bypass.unwrap_or(default.admin_bypass),
            super_tenant_id: self.super_tenant_id.unwrap_or(default.super_tenant_id),
            default_visibility: self.default_visibility.unwrap_or(default.default_visibility),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_acl_filter_config_default() {
        let config = ACLFilterConfig::default();

        assert!(config.enabled);
        assert!(config.admin_bypass);
        assert!(config.super_tenant_id.is_none());
        assert_eq!(config.default_visibility, Visibility::Private);
    }

    #[test]
    fn test_acl_filter_config_new() {
        let super_tenant = Uuid::new_v4();
        let config = ACLFilterConfig::new(false, false, Some(super_tenant), Visibility::Public);

        assert!(!config.enabled);
        assert!(!config.admin_bypass);
        assert_eq!(config.super_tenant_id, Some(super_tenant));
        assert_eq!(config.default_visibility, Visibility::Public);
    }

    #[test]
    fn test_acl_filter_config_builder() {
        let super_tenant = Uuid::new_v4();

        let config = ACLFilterConfig::builder()
            .enabled(true)
            .admin_bypass(false)
            .super_tenant_id(Some(super_tenant))
            .default_visibility(Visibility::Tenant)
            .build();

        assert!(config.enabled);
        assert!(!config.admin_bypass);
        assert_eq!(config.super_tenant_id, Some(super_tenant));
        assert_eq!(config.default_visibility, Visibility::Tenant);
    }

    #[test]
    fn test_acl_filter_config_builder_partial() {
        // Only set some fields, others should use defaults
        let config = ACLFilterConfig::builder().admin_bypass(false).build();

        assert!(config.enabled); // default
        assert!(!config.admin_bypass); // overridden
        assert!(config.super_tenant_id.is_none()); // default
        assert_eq!(config.default_visibility, Visibility::Private); // default
    }

    #[test]
    fn test_acl_filter_config_disabled() {
        let config = ACLFilterConfig::disabled();

        assert!(!config.enabled);
        assert!(config.admin_bypass); // other defaults preserved
    }

    #[test]
    fn test_is_enabled() {
        let enabled = ACLFilterConfig::default();
        let disabled = ACLFilterConfig::disabled();

        assert!(enabled.is_enabled());
        assert!(!disabled.is_enabled());
    }

    #[test]
    fn test_is_super_tenant() {
        let super_tenant = Uuid::new_v4();
        let other_tenant = Uuid::new_v4();

        let config = ACLFilterConfig::builder()
            .super_tenant_id(Some(super_tenant))
            .build();

        assert!(config.is_super_tenant(super_tenant));
        assert!(!config.is_super_tenant(other_tenant));
    }

    #[test]
    fn test_is_super_tenant_no_super_tenant_configured() {
        let config = ACLFilterConfig::default();
        let any_tenant = Uuid::new_v4();

        // When no super tenant is configured, no tenant is super
        assert!(!config.is_super_tenant(any_tenant));
    }

    #[test]
    fn test_acl_filter_config_serialization() {
        let config = ACLFilterConfig::default();

        let json = serde_json::to_string(&config).unwrap();
        let deserialized: ACLFilterConfig = serde_json::from_str(&json).unwrap();

        assert_eq!(config.enabled, deserialized.enabled);
        assert_eq!(config.admin_bypass, deserialized.admin_bypass);
        assert_eq!(config.super_tenant_id, deserialized.super_tenant_id);
        assert_eq!(config.default_visibility, deserialized.default_visibility);
    }
}
