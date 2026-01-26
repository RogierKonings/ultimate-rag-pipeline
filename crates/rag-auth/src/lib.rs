//! JWT authentication for the RAG Pipeline.
//!
//! This crate provides JWT-based authentication supporting:
//! - RS256/RS384/RS512 (RSA) and HS256/HS384/HS512 (HMAC) algorithms
//! - User tokens with tenant isolation, roles, and groups
//! - Service-to-service tokens for internal API authentication
//! - Token blocklist for logout/revocation
//! - JWKS endpoint support for external IdP integration
//!
//! # Example
//!
//! ```no_run
//! use rag_auth::{JwtHandler, JwtConfig, TokenClaims, TokenType};
//! use uuid::Uuid;
//!
//! #[tokio::main]
//! async fn main() -> Result<(), Box<dyn std::error::Error>> {
//!     let config = JwtConfig::default();
//!     let handler = JwtHandler::new(config)?;
//!
//!     // Create user token claims
//!     let claims = TokenClaims::new(
//!         Uuid::new_v4(),  // user_id
//!         Uuid::new_v4(),  // tenant_id
//!     )
//!     .with_roles(vec!["user".into()])
//!     .with_groups(vec!["engineering".into()]);
//!
//!     // Create token pair
//!     let token_pair = handler.create_token_pair(&claims)?;
//!
//!     // Verify access token
//!     let verified = handler.verify_token(&token_pair.access_token, None)?;
//!     assert_eq!(verified.sub, claims.sub);
//!
//!     Ok(())
//! }
//! ```

mod blocklist;
mod claims;
mod config;
mod error;
mod handler;
mod service;

pub use blocklist::{InMemoryBlocklist, RedisBlocklist, TokenBlocklist};
pub use claims::{TokenClaims, TokenPair, TokenType};
pub use config::{JwtAlgorithm, JwtConfig};
pub use error::{AuthError, Result};
pub use handler::JwtHandler;
pub use service::ServiceTokenClaims;
