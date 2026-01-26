//! Newtype wrappers for type-safe identifiers.
//!
//! These types prevent accidental mixing of different ID types at compile time.

use serde::{Deserialize, Serialize};
use std::fmt;
use std::str::FromStr;
use uuid::Uuid;

/// Macro to generate newtype wrappers for UUIDs.
macro_rules! define_id {
    ($(#[$meta:meta])* $name:ident) => {
        $(#[$meta])*
        #[derive(Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
        #[serde(transparent)]
        pub struct $name(Uuid);

        impl $name {
            /// Create a new random ID.
            #[must_use]
            pub fn new() -> Self {
                Self(Uuid::new_v4())
            }

            /// Create an ID from an existing UUID.
            #[must_use]
            pub const fn from_uuid(uuid: Uuid) -> Self {
                Self(uuid)
            }

            /// Get the underlying UUID.
            #[must_use]
            pub const fn as_uuid(&self) -> &Uuid {
                &self.0
            }

            /// Convert to the underlying UUID.
            #[must_use]
            pub const fn into_uuid(self) -> Uuid {
                self.0
            }

            /// Create from a string representation.
            ///
            /// # Errors
            ///
            /// Returns an error if the string is not a valid UUID.
            pub fn parse_str(s: &str) -> Result<Self, uuid::Error> {
                Uuid::parse_str(s).map(Self)
            }
        }

        impl Default for $name {
            fn default() -> Self {
                Self::new()
            }
        }

        impl fmt::Debug for $name {
            fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                write!(f, "{}({})", stringify!($name), self.0)
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
                write!(f, "{}", self.0)
            }
        }

        impl FromStr for $name {
            type Err = uuid::Error;

            fn from_str(s: &str) -> Result<Self, Self::Err> {
                Self::parse_str(s)
            }
        }

        impl From<Uuid> for $name {
            fn from(uuid: Uuid) -> Self {
                Self(uuid)
            }
        }

        impl From<$name> for Uuid {
            fn from(id: $name) -> Self {
                id.0
            }
        }

        impl AsRef<Uuid> for $name {
            fn as_ref(&self) -> &Uuid {
                &self.0
            }
        }
    };
}

define_id!(
    /// A tenant identifier for multi-tenancy support.
    ///
    /// All data in the RAG pipeline is scoped to a tenant.
    TenantId
);

define_id!(
    /// A document identifier.
    ///
    /// Documents are the top-level units of ingested content.
    DocumentId
);

define_id!(
    /// A chunk identifier.
    ///
    /// Chunks are segments of documents created during ingestion.
    ChunkId
);

define_id!(
    /// A user identifier.
    UserId
);

define_id!(
    /// A video identifier.
    VideoId
);

define_id!(
    /// A group identifier for ACL.
    GroupId
);

define_id!(
    /// A job identifier for async operations.
    JobId
);

define_id!(
    /// A conversation identifier.
    ConversationId
);

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_tenant_id_creation() {
        let id = TenantId::new();
        assert!(!id.to_string().is_empty());
    }

    #[test]
    fn test_tenant_id_from_str() {
        let uuid_str = "550e8400-e29b-41d4-a716-446655440000";
        let id = TenantId::parse_str(uuid_str).unwrap();
        assert_eq!(id.to_string(), uuid_str);
    }

    #[test]
    fn test_tenant_id_serialization() {
        let id = TenantId::parse_str("550e8400-e29b-41d4-a716-446655440000").unwrap();
        let json = serde_json::to_string(&id).unwrap();
        assert_eq!(json, "\"550e8400-e29b-41d4-a716-446655440000\"");

        let deserialized: TenantId = serde_json::from_str(&json).unwrap();
        assert_eq!(id, deserialized);
    }

    #[test]
    fn test_different_id_types_not_mixable() {
        // This test verifies type safety - these shouldn't compile if uncommented:
        // let tenant_id: TenantId = DocumentId::new(); // Should not compile
        // let doc_id: DocumentId = TenantId::new(); // Should not compile

        let tenant_id = TenantId::new();
        let doc_id = DocumentId::new();

        // They can both be converted to UUID explicitly
        let _uuid1: Uuid = tenant_id.into();
        let _uuid2: Uuid = doc_id.into();
    }
}
