//! JWT handler for token creation and verification.

use std::sync::Arc;
use std::time::Duration;

use chrono::Utc;
use jsonwebtoken::{decode, encode, DecodingKey, EncodingKey, Header, Validation};
use uuid::Uuid;

use crate::{
    AuthError, JwtConfig, Result, ServiceTokenClaims, TokenBlocklist, TokenClaims, TokenPair,
    TokenType,
};

/// JWT handler for creating and verifying tokens.
///
/// Supports:
/// - RS256/RS384/RS512 (RSA) and HS256/HS384/HS512 (HMAC)
/// - User tokens and service-to-service tokens
/// - Token blocklist for revocation
pub struct JwtHandler {
    config: JwtConfig,
    encoding_key: Option<EncodingKey>,
    decoding_key: Option<DecodingKey>,
    blocklist: Option<Arc<dyn TokenBlocklist>>,
}

impl JwtHandler {
    /// Create a new JWT handler.
    ///
    /// # Errors
    ///
    /// Returns an error if key configuration is invalid.
    pub fn new(config: JwtConfig) -> Result<Self> {
        config.validate()?;

        let encoding_key = Self::load_encoding_key(&config)?;
        let decoding_key = Self::load_decoding_key(&config)?;

        Ok(Self {
            config,
            encoding_key,
            decoding_key,
            blocklist: None,
        })
    }

    /// Set the token blocklist.
    #[must_use]
    pub fn with_blocklist(mut self, blocklist: Arc<dyn TokenBlocklist>) -> Self {
        self.blocklist = Some(blocklist);
        self
    }

    fn load_encoding_key(config: &JwtConfig) -> Result<Option<EncodingKey>> {
        let Some(secret) = &config.secret_key else {
            return Ok(None);
        };

        let key = if config.algorithm.is_asymmetric() {
            // Load RSA private key
            let pem = Self::load_key_content(secret)?;
            EncodingKey::from_rsa_pem(pem.as_bytes())
                .map_err(|e| AuthError::KeyConfig(format!("Invalid RSA private key: {e}")))?
        } else {
            // HMAC secret
            EncodingKey::from_secret(secret.as_bytes())
        };

        Ok(Some(key))
    }

    fn load_decoding_key(config: &JwtConfig) -> Result<Option<DecodingKey>> {
        // For asymmetric, prefer public key; for symmetric, use secret
        let key_content = if config.algorithm.is_asymmetric() {
            config.public_key.as_ref().or(config.secret_key.as_ref())
        } else {
            config.secret_key.as_ref()
        };

        let Some(key_str) = key_content else {
            return Ok(None);
        };

        let key = if config.algorithm.is_asymmetric() {
            let pem = Self::load_key_content(key_str)?;
            // Try public key first, then private key
            DecodingKey::from_rsa_pem(pem.as_bytes()).map_err(|e| {
                AuthError::KeyConfig(format!("Invalid RSA key: {e}"))
            })?
        } else {
            DecodingKey::from_secret(key_str.as_bytes())
        };

        Ok(Some(key))
    }

    fn load_key_content(key_path_or_content: &str) -> Result<String> {
        // Check if it looks like a PEM key
        if key_path_or_content.contains("-----BEGIN") {
            return Ok(key_path_or_content.to_string());
        }

        // Try to read as file path
        let path = std::path::Path::new(key_path_or_content);
        if path.exists() && path.is_file() {
            std::fs::read_to_string(path)
                .map_err(|e| AuthError::KeyConfig(format!("Failed to read key file: {e}")))
        } else {
            // Return as-is (for HMAC secrets)
            Ok(key_path_or_content.to_string())
        }
    }

    /// Create an access token.
    ///
    /// # Errors
    ///
    /// Returns an error if token creation fails.
    pub fn create_access_token(&self, claims: &TokenClaims) -> Result<String> {
        self.create_token(claims, TokenType::Access, self.config.access_token_duration)
    }

    /// Create a refresh token.
    ///
    /// # Errors
    ///
    /// Returns an error if token creation fails.
    pub fn create_refresh_token(&self, claims: &TokenClaims) -> Result<String> {
        self.create_token(claims, TokenType::Refresh, self.config.refresh_token_duration)
    }

    /// Create an access/refresh token pair.
    ///
    /// # Errors
    ///
    /// Returns an error if token creation fails.
    pub fn create_token_pair(&self, claims: &TokenClaims) -> Result<TokenPair> {
        let access_token = self.create_access_token(claims)?;
        let refresh_token = self.create_refresh_token(claims)?;

        Ok(TokenPair::new(
            access_token,
            refresh_token,
            self.config.access_token_duration.as_secs(),
            self.config.refresh_token_duration.as_secs(),
        ))
    }

    fn create_token(
        &self,
        claims: &TokenClaims,
        token_type: TokenType,
        duration: Duration,
    ) -> Result<String> {
        let encoding_key = self
            .encoding_key
            .as_ref()
            .ok_or_else(|| AuthError::KeyConfig("Encoding key not configured".into()))?;

        let now = Utc::now();
        let exp = now + chrono::Duration::from_std(duration).unwrap_or_default();

        let mut token_claims = claims.clone();
        token_claims.token_type = token_type;
        token_claims.iss = Some(self.config.issuer.clone());
        token_claims.aud = Some(self.config.audience.clone());
        token_claims.iat = Some(now.timestamp());
        token_claims.nbf = Some(now.timestamp());
        token_claims.exp = Some(exp.timestamp());
        token_claims.jti = Some(Uuid::new_v4().to_string());

        let header = Header::new(self.config.algorithm.to_jsonwebtoken());
        encode(&header, &token_claims, encoding_key).map_err(AuthError::Jwt)
    }

    /// Verify and decode a token.
    ///
    /// # Errors
    ///
    /// Returns an error if the token is invalid, expired, or revoked.
    pub fn verify_token(
        &self,
        token: &str,
        expected_type: Option<TokenType>,
    ) -> Result<TokenClaims> {
        let decoding_key = self
            .decoding_key
            .as_ref()
            .ok_or_else(|| AuthError::KeyConfig("Decoding key not configured".into()))?;

        let mut validation = Validation::new(self.config.algorithm.to_jsonwebtoken());
        validation.set_issuer(&[&self.config.issuer]);

        if self.config.verify_aud {
            validation.set_audience(&[&self.config.audience]);
        } else {
            validation.validate_aud = false;
        }

        validation.validate_exp = self.config.verify_exp;
        validation.leeway = self.config.leeway.as_secs();

        let token_data = decode::<TokenClaims>(token, decoding_key, &validation)?;
        let claims = token_data.claims;

        // Verify token type
        if let Some(expected) = expected_type {
            if claims.token_type != expected {
                return Err(AuthError::TokenTypeMismatch {
                    expected: expected.to_string(),
                    actual: claims.token_type.to_string(),
                });
            }
        }

        // Check blocklist - note: this sync version cannot check blocklist
        // Use verify_token_async for full blocklist support
        if self.blocklist.is_some() && claims.jti.is_some() {
            tracing::warn!("Blocklist check requires async context, skipping in sync verify_token");
        }

        Ok(claims)
    }

    /// Verify and decode a token (async version with blocklist check).
    ///
    /// # Errors
    ///
    /// Returns an error if the token is invalid, expired, or revoked.
    pub async fn verify_token_async(
        &self,
        token: &str,
        expected_type: Option<TokenType>,
    ) -> Result<TokenClaims> {
        let claims = self.verify_token(token, expected_type)?;

        // Check blocklist
        if let (Some(blocklist), Some(jti)) = (&self.blocklist, &claims.jti) {
            if blocklist.is_blocked(jti).await? {
                return Err(AuthError::TokenRevoked);
            }
        }

        Ok(claims)
    }

    /// Create a service-to-service token.
    ///
    /// # Errors
    ///
    /// Returns an error if token creation fails.
    pub fn create_service_token(
        &self,
        service_name: &str,
        target_service: &str,
        allowed_endpoints: Option<Vec<String>>,
        duration: Option<Duration>,
    ) -> Result<String> {
        let encoding_key = self
            .encoding_key
            .as_ref()
            .ok_or_else(|| AuthError::KeyConfig("Encoding key not configured".into()))?;

        let now = Utc::now();
        let duration = duration.unwrap_or_else(|| Duration::from_secs(5 * 60)); // 5 minutes default
        let exp = now + chrono::Duration::from_std(duration).unwrap_or_default();

        let claims = ServiceTokenClaims {
            service_name: service_name.into(),
            target_service: target_service.into(),
            allowed_endpoints: allowed_endpoints.unwrap_or_default(),
            iss: Some(self.config.issuer.clone()),
            aud: Some(target_service.into()),
            exp: Some(exp.timestamp()),
            iat: Some(now.timestamp()),
            jti: Some(Uuid::new_v4().to_string()),
            token_type: TokenType::Service,
        };

        let header = Header::new(self.config.algorithm.to_jsonwebtoken());
        encode(&header, &claims, encoding_key).map_err(AuthError::Jwt)
    }

    /// Verify a service-to-service token.
    ///
    /// # Errors
    ///
    /// Returns an error if the token is invalid or not authorized.
    pub fn verify_service_token(
        &self,
        token: &str,
        expected_audience: &str,
        endpoint: Option<&str>,
    ) -> Result<ServiceTokenClaims> {
        let decoding_key = self
            .decoding_key
            .as_ref()
            .ok_or_else(|| AuthError::KeyConfig("Decoding key not configured".into()))?;

        let mut validation = Validation::new(self.config.algorithm.to_jsonwebtoken());
        validation.set_issuer(&[&self.config.issuer]);
        validation.set_audience(&[expected_audience]);
        validation.validate_exp = self.config.verify_exp;
        validation.leeway = self.config.leeway.as_secs();

        let token_data = decode::<ServiceTokenClaims>(token, decoding_key, &validation)?;
        let claims = token_data.claims;

        // Verify it's a service token
        if claims.token_type != TokenType::Service {
            return Err(AuthError::TokenTypeMismatch {
                expected: "service".into(),
                actual: claims.token_type.to_string(),
            });
        }

        // Check endpoint authorization
        if let Some(ep) = endpoint {
            if !claims.can_access_endpoint(ep) {
                return Err(AuthError::EndpointNotAuthorized {
                    service: claims.service_name.clone(),
                    endpoint: ep.into(),
                });
            }
        }

        Ok(claims)
    }

    /// Verify a service token (async version with blocklist check).
    ///
    /// # Errors
    ///
    /// Returns an error if the token is invalid, expired, or revoked.
    pub async fn verify_service_token_async(
        &self,
        token: &str,
        expected_audience: &str,
        endpoint: Option<&str>,
    ) -> Result<ServiceTokenClaims> {
        let claims = self.verify_service_token(token, expected_audience, endpoint)?;

        // Check blocklist
        if let (Some(blocklist), Some(jti)) = (&self.blocklist, &claims.jti) {
            if blocklist.is_blocked(jti).await? {
                return Err(AuthError::TokenRevoked);
            }
        }

        Ok(claims)
    }

    /// Revoke a token by adding it to the blocklist.
    ///
    /// # Errors
    ///
    /// Returns an error if blocklist is not configured or operation fails.
    pub async fn revoke_token(&self, token: &str) -> Result<bool> {
        let Some(blocklist) = &self.blocklist else {
            return Ok(false);
        };

        // Decode without verification to get JTI and exp
        let decoding_key = self
            .decoding_key
            .as_ref()
            .ok_or_else(|| AuthError::KeyConfig("Decoding key not configured".into()))?;

        let mut validation = Validation::new(self.config.algorithm.to_jsonwebtoken());
        validation.insecure_disable_signature_validation();
        validation.validate_exp = false;

        let token_data = decode::<TokenClaims>(token, decoding_key, &validation)?;

        let Some(jti) = token_data.claims.jti else {
            return Ok(false);
        };

        // Calculate TTL (block until token would have expired)
        let ttl = token_data.claims.exp.map(|exp| {
            let now = Utc::now().timestamp();
            let remaining = exp - now;
            if remaining > 0 {
                Duration::from_secs(remaining as u64)
            } else {
                Duration::ZERO
            }
        });

        // Don't block already expired tokens
        if ttl.map_or(false, |t| t.is_zero()) {
            return Ok(true);
        }

        blocklist.block(&jti, ttl).await?;
        Ok(true)
    }

    /// Decode a token without verification (for debugging).
    ///
    /// # Errors
    ///
    /// Returns an error if the token format is invalid.
    pub fn decode_unverified(&self, token: &str) -> Result<TokenClaims> {
        let decoding_key = self
            .decoding_key
            .as_ref()
            .ok_or_else(|| AuthError::KeyConfig("Decoding key not configured".into()))?;

        let mut validation = Validation::new(self.config.algorithm.to_jsonwebtoken());
        validation.insecure_disable_signature_validation();
        validation.validate_exp = false;
        validation.validate_aud = false;

        let token_data = decode::<TokenClaims>(token, decoding_key, &validation)?;
        Ok(token_data.claims)
    }

    /// Check if a token is a service token.
    #[must_use]
    pub fn is_service_token(&self, token: &str) -> bool {
        self.decode_unverified(token)
            .map(|c| c.token_type == TokenType::Service)
            .unwrap_or(false)
    }

    /// Refresh tokens using a refresh token.
    ///
    /// # Errors
    ///
    /// Returns an error if the refresh token is invalid.
    pub async fn refresh_tokens(&self, refresh_token: &str) -> Result<TokenPair> {
        let claims = self
            .verify_token_async(refresh_token, Some(TokenType::Refresh))
            .await?;

        // Revoke old refresh token
        let _ = self.revoke_token(refresh_token).await;

        // Create new token pair
        let new_claims = TokenClaims::new(claims.sub, claims.tenant_id)
            .with_roles(claims.roles)
            .with_groups(claims.groups)
            .with_permissions(claims.permissions);

        self.create_token_pair(&new_claims)
    }
}

impl std::fmt::Debug for JwtHandler {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("JwtHandler")
            .field("config", &self.config)
            .field("has_encoding_key", &self.encoding_key.is_some())
            .field("has_decoding_key", &self.decoding_key.is_some())
            .field("has_blocklist", &self.blocklist.is_some())
            .finish()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_config() -> JwtConfig {
        JwtConfig::with_hmac_secret("test-secret-key-that-is-long-enough-for-hs256")
    }

    #[test]
    fn test_create_and_verify_access_token() {
        let handler = JwtHandler::new(test_config()).unwrap();
        let claims = TokenClaims::new(Uuid::new_v4(), Uuid::new_v4())
            .with_roles(vec!["user".into()]);

        let token = handler.create_access_token(&claims).unwrap();
        let verified = handler.verify_token(&token, Some(TokenType::Access)).unwrap();

        assert_eq!(verified.sub, claims.sub);
        assert_eq!(verified.tenant_id, claims.tenant_id);
        assert!(verified.has_role("user"));
    }

    #[test]
    fn test_create_token_pair() {
        let handler = JwtHandler::new(test_config()).unwrap();
        let claims = TokenClaims::new(Uuid::new_v4(), Uuid::new_v4());

        let pair = handler.create_token_pair(&claims).unwrap();

        // Verify access token
        let access_claims = handler
            .verify_token(&pair.access_token, Some(TokenType::Access))
            .unwrap();
        assert_eq!(access_claims.sub, claims.sub);

        // Verify refresh token
        let refresh_claims = handler
            .verify_token(&pair.refresh_token, Some(TokenType::Refresh))
            .unwrap();
        assert_eq!(refresh_claims.sub, claims.sub);
    }

    #[test]
    fn test_token_type_mismatch() {
        let handler = JwtHandler::new(test_config()).unwrap();
        let claims = TokenClaims::new(Uuid::new_v4(), Uuid::new_v4());

        let access_token = handler.create_access_token(&claims).unwrap();

        // Try to verify as refresh token
        let result = handler.verify_token(&access_token, Some(TokenType::Refresh));
        assert!(matches!(result, Err(AuthError::TokenTypeMismatch { .. })));
    }

    #[test]
    fn test_create_and_verify_service_token() {
        let handler = JwtHandler::new(test_config()).unwrap();

        let token = handler
            .create_service_token(
                "orchestrator",
                "retrieval",
                Some(vec!["/internal/*".into()]),
                None,
            )
            .unwrap();

        let claims = handler
            .verify_service_token(&token, "retrieval", Some("/internal/search"))
            .unwrap();

        assert_eq!(claims.service_name, "orchestrator");
        assert_eq!(claims.target_service, "retrieval");
    }

    #[test]
    fn test_service_token_endpoint_not_authorized() {
        let handler = JwtHandler::new(test_config()).unwrap();

        let token = handler
            .create_service_token(
                "orchestrator",
                "retrieval",
                Some(vec!["/internal/*".into()]),
                None,
            )
            .unwrap();

        let result = handler.verify_service_token(&token, "retrieval", Some("/admin/users"));
        assert!(matches!(result, Err(AuthError::EndpointNotAuthorized { .. })));
    }

    #[tokio::test]
    async fn test_blocklist_integration() {
        let blocklist = Arc::new(crate::InMemoryBlocklist::new());
        let handler = JwtHandler::new(test_config())
            .unwrap()
            .with_blocklist(blocklist);

        let claims = TokenClaims::new(Uuid::new_v4(), Uuid::new_v4());
        let token = handler.create_access_token(&claims).unwrap();

        // Token should be valid
        assert!(handler.verify_token_async(&token, None).await.is_ok());

        // Revoke token
        handler.revoke_token(&token).await.unwrap();

        // Token should be revoked
        let result = handler.verify_token_async(&token, None).await;
        assert!(matches!(result, Err(AuthError::TokenRevoked)));
    }
}
