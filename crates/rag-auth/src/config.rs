//! JWT configuration.

use serde::{Deserialize, Serialize};
use std::time::Duration;

/// Supported JWT signing algorithms.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, Default)]
#[serde(rename_all = "UPPERCASE")]
pub enum JwtAlgorithm {
    /// RSA with SHA-256 (recommended for production).
    #[default]
    RS256,
    /// RSA with SHA-384.
    RS384,
    /// RSA with SHA-512.
    RS512,
    /// HMAC with SHA-256 (development only).
    HS256,
    /// HMAC with SHA-384.
    HS384,
    /// HMAC with SHA-512.
    HS512,
}

impl JwtAlgorithm {
    /// Check if this algorithm uses asymmetric keys (RSA).
    #[must_use]
    pub const fn is_asymmetric(&self) -> bool {
        matches!(self, Self::RS256 | Self::RS384 | Self::RS512)
    }

    /// Convert to jsonwebtoken algorithm.
    #[must_use]
    pub const fn to_jsonwebtoken(&self) -> jsonwebtoken::Algorithm {
        match self {
            Self::RS256 => jsonwebtoken::Algorithm::RS256,
            Self::RS384 => jsonwebtoken::Algorithm::RS384,
            Self::RS512 => jsonwebtoken::Algorithm::RS512,
            Self::HS256 => jsonwebtoken::Algorithm::HS256,
            Self::HS384 => jsonwebtoken::Algorithm::HS384,
            Self::HS512 => jsonwebtoken::Algorithm::HS512,
        }
    }
}

impl std::fmt::Display for JwtAlgorithm {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::RS256 => write!(f, "RS256"),
            Self::RS384 => write!(f, "RS384"),
            Self::RS512 => write!(f, "RS512"),
            Self::HS256 => write!(f, "HS256"),
            Self::HS384 => write!(f, "HS384"),
            Self::HS512 => write!(f, "HS512"),
        }
    }
}

/// JWT configuration settings.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JwtConfig {
    /// Secret key for HMAC or RSA private key content/path.
    pub secret_key: Option<String>,

    /// RSA public key content/path (for verification).
    pub public_key: Option<String>,

    /// Signing algorithm.
    #[serde(default)]
    pub algorithm: JwtAlgorithm,

    /// Access token expiration.
    #[serde(default = "default_access_token_duration")]
    #[serde(with = "humantime_serde")]
    pub access_token_duration: Duration,

    /// Refresh token expiration.
    #[serde(default = "default_refresh_token_duration")]
    #[serde(with = "humantime_serde")]
    pub refresh_token_duration: Duration,

    /// Token issuer (iss claim).
    #[serde(default = "default_issuer")]
    pub issuer: String,

    /// Token audience (aud claim).
    #[serde(default = "default_audience")]
    pub audience: String,

    /// JWKS URL for external IdP integration.
    pub jwks_url: Option<String>,

    /// Expected issuer from external IdP.
    pub idp_issuer: Option<String>,

    /// Verify token expiration.
    #[serde(default = "default_true")]
    pub verify_exp: bool,

    /// Verify token audience.
    #[serde(default = "default_true")]
    pub verify_aud: bool,

    /// Clock skew tolerance.
    #[serde(default)]
    #[serde(with = "humantime_serde")]
    pub leeway: Duration,
}

fn default_access_token_duration() -> Duration {
    Duration::from_secs(30 * 60) // 30 minutes
}

fn default_refresh_token_duration() -> Duration {
    Duration::from_secs(7 * 24 * 60 * 60) // 7 days
}

fn default_issuer() -> String {
    "rag-pipeline".into()
}

fn default_audience() -> String {
    "rag-api".into()
}

const fn default_true() -> bool {
    true
}

impl Default for JwtConfig {
    fn default() -> Self {
        Self {
            secret_key: None,
            public_key: None,
            algorithm: JwtAlgorithm::default(),
            access_token_duration: default_access_token_duration(),
            refresh_token_duration: default_refresh_token_duration(),
            issuer: default_issuer(),
            audience: default_audience(),
            jwks_url: None,
            idp_issuer: None,
            verify_exp: true,
            verify_aud: true,
            leeway: Duration::ZERO,
        }
    }
}

impl JwtConfig {
    /// Create a new config with HMAC secret (for development).
    #[must_use]
    pub fn with_hmac_secret(secret: impl Into<String>) -> Self {
        Self {
            secret_key: Some(secret.into()),
            algorithm: JwtAlgorithm::HS256,
            ..Default::default()
        }
    }

    /// Create a new config with RSA keys (for production).
    #[must_use]
    pub fn with_rsa_keys(
        private_key: impl Into<String>,
        public_key: impl Into<String>,
    ) -> Self {
        Self {
            secret_key: Some(private_key.into()),
            public_key: Some(public_key.into()),
            algorithm: JwtAlgorithm::RS256,
            ..Default::default()
        }
    }

    /// Set the access token duration.
    #[must_use]
    pub const fn with_access_token_duration(mut self, duration: Duration) -> Self {
        self.access_token_duration = duration;
        self
    }

    /// Set the refresh token duration.
    #[must_use]
    pub const fn with_refresh_token_duration(mut self, duration: Duration) -> Self {
        self.refresh_token_duration = duration;
        self
    }

    /// Set the issuer.
    #[must_use]
    pub fn with_issuer(mut self, issuer: impl Into<String>) -> Self {
        self.issuer = issuer.into();
        self
    }

    /// Set the audience.
    #[must_use]
    pub fn with_audience(mut self, audience: impl Into<String>) -> Self {
        self.audience = audience.into();
        self
    }

    /// Validate the configuration.
    ///
    /// # Errors
    ///
    /// Returns an error if required keys are not configured.
    pub fn validate(&self) -> crate::Result<()> {
        if self.algorithm.is_asymmetric() {
            if self.secret_key.is_none() && self.public_key.is_none() {
                return Err(crate::AuthError::KeyConfig(format!(
                    "Algorithm {} requires RSA keys. Set secret_key (private) and/or public_key.",
                    self.algorithm
                )));
            }
        } else if self.secret_key.is_none() {
            return Err(crate::AuthError::KeyConfig(format!(
                "Algorithm {} requires secret_key.",
                self.algorithm
            )));
        }
        Ok(())
    }
}

/// Serde module for humantime duration parsing.
mod humantime_serde {
    use serde::{Deserialize, Deserializer, Serializer};
    use std::time::Duration;

    pub fn serialize<S>(duration: &Duration, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let s = humantime::format_duration(*duration).to_string();
        serializer.serialize_str(&s)
    }

    pub fn deserialize<'de, D>(deserializer: D) -> Result<Duration, D::Error>
    where
        D: Deserializer<'de>,
    {
        let s = String::deserialize(deserializer)?;
        humantime::parse_duration(&s).map_err(serde::de::Error::custom)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_algorithm_is_asymmetric() {
        assert!(JwtAlgorithm::RS256.is_asymmetric());
        assert!(JwtAlgorithm::RS384.is_asymmetric());
        assert!(JwtAlgorithm::RS512.is_asymmetric());
        assert!(!JwtAlgorithm::HS256.is_asymmetric());
        assert!(!JwtAlgorithm::HS384.is_asymmetric());
        assert!(!JwtAlgorithm::HS512.is_asymmetric());
    }

    #[test]
    fn test_default_config() {
        let config = JwtConfig::default();
        assert_eq!(config.algorithm, JwtAlgorithm::RS256);
        assert_eq!(config.issuer, "rag-pipeline");
        assert_eq!(config.audience, "rag-api");
        assert!(config.verify_exp);
        assert!(config.verify_aud);
    }

    #[test]
    fn test_hmac_config() {
        let config = JwtConfig::with_hmac_secret("my-secret");
        assert_eq!(config.algorithm, JwtAlgorithm::HS256);
        assert_eq!(config.secret_key, Some("my-secret".into()));
    }
}
