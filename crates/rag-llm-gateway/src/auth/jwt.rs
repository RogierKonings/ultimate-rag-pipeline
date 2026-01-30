//! JWT validation.

use jsonwebtoken::{decode, Algorithm, DecodingKey, Validation};
use serde::{Deserialize, Serialize};
use tracing::{debug, warn};

use crate::config::AuthConfig;
use crate::error::{GatewayError, Result};

use super::context::{AuthContext, AuthMethod};

/// JWT claims structure.
#[derive(Debug, Deserialize, Serialize)]
pub struct Claims {
    pub sub: Option<String>,
    pub user_id: Option<String>,
    pub tenant_id: Option<String>,
    pub tid: Option<String>,
    pub roles: Option<Vec<String>>,
    pub role: Option<Vec<String>>,
    pub scope: Option<String>,
    pub exp: Option<i64>,
    pub iss: Option<String>,
    pub aud: Option<serde_json::Value>,
}

/// JWT validator.
pub struct JwtValidator {
    config: AuthConfig,
    decoding_key: Option<DecodingKey>,
    validation: Validation,
}

impl JwtValidator {
    /// Create a new JWT validator from config.
    ///
    /// # Errors
    ///
    /// Returns an error if:
    /// - The JWT algorithm is unsupported
    /// - The RSA public key is invalid
    pub fn new(config: &AuthConfig) -> Result<Self> {
        let algorithm = match config.jwt_algorithm.as_str() {
            "HS256" => Algorithm::HS256,
            "HS384" => Algorithm::HS384,
            "HS512" => Algorithm::HS512,
            "RS256" => Algorithm::RS256,
            "RS384" => Algorithm::RS384,
            "RS512" => Algorithm::RS512,
            "ES256" => Algorithm::ES256,
            "ES384" => Algorithm::ES384,
            alg => {
                return Err(GatewayError::Config(format!(
                    "Unsupported JWT algorithm: {alg}"
                )))
            }
        };

        let decoding_key = if let Some(secret) = &config.jwt_secret {
            Some(DecodingKey::from_secret(secret.as_bytes()))
        } else if let Some(public_key) = &config.jwt_public_key {
            Some(
                DecodingKey::from_rsa_pem(public_key.as_bytes())
                    .map_err(|e| GatewayError::Config(format!("Invalid RSA public key: {e}")))?,
            )
        } else {
            None
        };

        let mut validation = Validation::new(algorithm);
        validation.validate_exp = true;

        if let Some(issuer) = &config.jwt_issuer {
            validation.set_issuer(&[issuer]);
        }

        if let Some(audience) = &config.jwt_audience {
            validation.set_audience(&[audience]);
        }

        Ok(Self {
            config: config.clone(),
            decoding_key,
            validation,
        })
    }

    /// Validate a JWT token and extract auth context.
    ///
    /// # Errors
    ///
    /// Returns an error if:
    /// - No decoding key is configured
    /// - The token is invalid or expired
    pub fn validate(&self, token: &str) -> Result<AuthContext> {
        let decoding_key = self
            .decoding_key
            .as_ref()
            .ok_or_else(|| GatewayError::Config("No JWT decoding key configured".into()))?;

        let token_data = decode::<Claims>(token, decoding_key, &self.validation).map_err(|e| {
            warn!("JWT validation failed: {}", e);
            GatewayError::Unauthorized(format!("Invalid token: {e}"))
        })?;

        let claims = token_data.claims;

        let tenant_id = claims
            .tenant_id
            .or(claims.tid)
            .unwrap_or_else(|| "default".into());

        let user_id = claims
            .sub
            .or(claims.user_id)
            .unwrap_or_else(|| "anonymous".into());

        let roles = claims.roles.or(claims.role).unwrap_or_default();

        let scopes = claims
            .scope
            .map(|s| s.split_whitespace().map(String::from).collect())
            .unwrap_or_default();

        debug!(tenant_id = %tenant_id, user_id = %user_id, "JWT validated");

        Ok(AuthContext {
            tenant_id,
            user_id,
            roles,
            scopes,
            auth_method: AuthMethod::Jwt,
        })
    }

    /// Validate an API key.
    #[must_use]
    pub fn validate_api_key(&self, api_key: &str) -> Option<AuthContext> {
        self.config.api_keys.get(api_key).map(|key_config| {
            debug!(tenant_id = %key_config.tenant_id, "API key validated");
            AuthContext {
                tenant_id: key_config.tenant_id.clone(),
                user_id: key_config.user_id.clone(),
                roles: key_config.roles.clone(),
                scopes: vec![],
                auth_method: AuthMethod::ApiKey,
            }
        })
    }
}
