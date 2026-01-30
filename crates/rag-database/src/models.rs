//! Database models corresponding to PostgreSQL tables.

mod audit;
mod chunk;
mod feedback;
mod source_document;
mod usage;
mod user;
mod video;

pub use audit::{AuditAction, AuditLog, AuditLogBuilder, NewAuditLog};
pub use chunk::{Chunk, ChunkBuilder, NewChunk};
pub use feedback::{FeedbackType, NewQueryFeedback, QueryFeedback, QueryFeedbackBuilder};
pub use source_document::{NewSourceDocument, SourceDocument, SourceDocumentBuilder, Visibility};
pub use usage::{NewTenantQuota, NewTokenUsage, TenantQuota, TokenUsage};
pub use user::{
    ApiKey, Group, NewApiKey, NewGroup, NewRole, NewTenant, NewUser, NewUserGroup, NewUserRole,
    Role, Tenant, User, UserGroup, UserRole,
};
pub use video::{
    NewSourceVideo, NewVideoKeyframe, NewVideoTranscript, ProcessingStage, SourceVideo,
    VideoKeyframe, VideoStatus, VideoTranscript,
};
