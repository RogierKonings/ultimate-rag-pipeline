//! Access Control List (ACL) filtering for search results.
//!
//! This module provides visibility-level filtering for search results based on
//! user context. It implements the same ACL logic as the Python retrieval service
//! but in a unified filter format that can be converted to Qdrant or `OpenSearch`
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
//! 3. User must not be in `denied_groups` or `denied_users`
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
//!
//! # Backend-Specific Filters
//!
//! The unified filter can be converted to backend-specific formats:
//!
//! ```
//! use rag_retrieval::acl::{
//!     ACLFilter, ACLFilterConfig, QdrantFilterBuilder, OpenSearchFilterBuilder
//! };
//! use rag_retrieval::types::UserContext;
//! use uuid::Uuid;
//!
//! let config = ACLFilterConfig::default();
//! let acl = ACLFilter::new(config);
//!
//! let user = UserContext::new(Uuid::new_v4(), Uuid::new_v4())
//!     .with_groups(vec!["engineering".into()]);
//!
//! // Build unified filter first
//! let unified = acl.build_filter(&user, None);
//!
//! // Convert to Qdrant filter
//! let qdrant_filter = QdrantFilterBuilder::build(&unified);
//!
//! // Convert to OpenSearch filter clauses
//! let opensearch_clauses = OpenSearchFilterBuilder::build(&unified);
//! ```

mod builders;
mod config;
mod filter;
mod types;

pub use builders::{OpenSearchFilterBuilder, QdrantFilterBuilder};
pub use config::ACLFilterConfig;
pub use filter::ACLFilter;
pub use types::{FilterCondition, HasACLFields, MatchType, UnifiedFilter};
