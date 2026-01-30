//! Role-Based Access Control (RBAC) module.
//!
//! This module provides:
//! - Permission definitions for fine-grained access control
//! - Role definitions with permission inheritance
//! - Authorization service for permission checking
//! - Axum middleware for route protection

mod middleware;
mod permission;
mod role;
mod service;

pub use middleware::{require_permission, require_role, AuthLayer};
pub use permission::Permission;
pub use role::Role;
pub use service::AuthorizationService;
