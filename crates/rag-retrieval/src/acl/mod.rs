//! Access Control List (ACL) filtering for search results.
//!
//! This module provides visibility-level filtering for search results based on
//! user context. It implements the same ACL logic as the Python retrieval service
//! but in a unified filter format that can be converted to Qdrant or OpenSearch
//! filter syntax.
//!
//! # ACL Logic
//!
//! 1. Document must belong to user's tenant (unless super tenant)
//! 2. Document must be:
//!    - PUBLIC visibility, OR
//!    - TENANT visibility (same tenant), OR
//!    - GROUP visibility with matching groups, OR
//!    - Explicitly allowed for user, OR
//!    - Owned by user
//! 3. User must not be in denied_groups or denied_users
//!
//! # Example
//!
//! ```
//! use rag_retrieval::acl::{ACLFilter, ACLFilterConfig, UnifiedFilter};
//! use rag_retrieval::types::{UserContext, Visibility};
//! use uuid::Uuid;
//!
//! let config = ACLFilterConfig::default();
//! let acl_filter = ACLFilter::new(config);
//!
//! let user_context = UserContext::new(Uuid::new_v4(), Uuid::new_v4())
//!     .with_groups(vec!["engineering".into(), "product".into()])
//!     .with_admin(false);
//!
//! let filter = acl_filter.build_filter(&user_context, None);
//!
//! // The filter will include:
//! // - must: tenant_id match, status = "active"
//! // - should: public OR tenant OR matching groups OR allowed_users OR owner
//! // - must_not: denied_groups, denied_users
//! ```

mod config;
mod filter;

pub use config::ACLFilterConfig;
pub use filter::{ACLFilter, FilterCondition, HasACLFields, MatchType, UnifiedFilter};
