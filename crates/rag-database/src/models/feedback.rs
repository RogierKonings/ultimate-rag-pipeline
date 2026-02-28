//! QueryFeedback model for storing user feedback on RAG responses.
//!
//! Stores feedback submitted by users which is correlated with the original
//! query via request_id. Used for quality monitoring and improvement.

use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use sqlx::FromRow;
use uuid::Uuid;

/// Feedback type categories.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
#[derive(Default)]
pub enum FeedbackType {
    #[default]
    General,
    Helpful,
    Unhelpful,
    Wrong,
    Incomplete,
    Irrelevant,
}

impl FeedbackType {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::General => "general",
            Self::Helpful => "helpful",
            Self::Unhelpful => "unhelpful",
            Self::Wrong => "wrong",
            Self::Incomplete => "incomplete",
            Self::Irrelevant => "irrelevant",
        }
    }
}

impl std::fmt::Display for FeedbackType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.as_str())
    }
}

/// User feedback on RAG query responses.
///
/// Stores feedback submitted by users which is correlated with the original
/// query via request_id. Used for quality monitoring and improvement.
#[derive(Debug, Clone, Serialize, Deserialize, FromRow)]
pub struct QueryFeedback {
    pub id: Uuid,
    pub request_id: String,
    pub tenant_id: Option<String>,
    pub rating: i32,
    pub feedback_type: String,
    pub comment: Option<String>,
    pub session_id: Option<String>,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

impl QueryFeedback {
    /// Get the feedback type as an enum.
    pub fn feedback_type_enum(&self) -> Option<FeedbackType> {
        match self.feedback_type.as_str() {
            "general" => Some(FeedbackType::General),
            "helpful" => Some(FeedbackType::Helpful),
            "unhelpful" => Some(FeedbackType::Unhelpful),
            "wrong" => Some(FeedbackType::Wrong),
            "incomplete" => Some(FeedbackType::Incomplete),
            "irrelevant" => Some(FeedbackType::Irrelevant),
            _ => None,
        }
    }

    /// Check if the feedback is positive (rating >= 4).
    pub fn is_positive(&self) -> bool {
        self.rating >= 4
    }

    /// Check if the feedback is negative (rating <= 2).
    pub fn is_negative(&self) -> bool {
        self.rating <= 2
    }
}

/// Data for creating a new query feedback.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NewQueryFeedback {
    pub request_id: String,
    pub tenant_id: Option<String>,
    pub rating: i32,
    pub feedback_type: Option<String>,
    pub comment: Option<String>,
    pub session_id: Option<String>,
}

impl NewQueryFeedback {
    /// Create a new feedback entry.
    pub fn new(request_id: impl Into<String>, rating: i32) -> Self {
        Self {
            request_id: request_id.into(),
            tenant_id: None,
            rating,
            feedback_type: Some(FeedbackType::General.to_string()),
            comment: None,
            session_id: None,
        }
    }

    /// Set the tenant ID.
    pub fn with_tenant(mut self, tenant_id: impl Into<String>) -> Self {
        self.tenant_id = Some(tenant_id.into());
        self
    }

    /// Set the feedback type.
    pub fn with_type(mut self, feedback_type: FeedbackType) -> Self {
        self.feedback_type = Some(feedback_type.to_string());
        self
    }

    /// Set the comment.
    pub fn with_comment(mut self, comment: impl Into<String>) -> Self {
        self.comment = Some(comment.into());
        self
    }

    /// Set the session ID.
    pub fn with_session(mut self, session_id: impl Into<String>) -> Self {
        self.session_id = Some(session_id.into());
        self
    }
}

/// Builder for query feedback.
#[derive(Debug, Default)]
pub struct QueryFeedbackBuilder {
    request_id: Option<String>,
    tenant_id: Option<String>,
    rating: Option<i32>,
    feedback_type: Option<String>,
    comment: Option<String>,
    session_id: Option<String>,
}

impl QueryFeedbackBuilder {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn request_id(mut self, request_id: impl Into<String>) -> Self {
        self.request_id = Some(request_id.into());
        self
    }

    pub fn tenant_id(mut self, tenant_id: impl Into<String>) -> Self {
        self.tenant_id = Some(tenant_id.into());
        self
    }

    pub fn rating(mut self, rating: i32) -> Self {
        self.rating = Some(rating);
        self
    }

    pub fn feedback_type(mut self, feedback_type: FeedbackType) -> Self {
        self.feedback_type = Some(feedback_type.to_string());
        self
    }

    pub fn comment(mut self, comment: impl Into<String>) -> Self {
        self.comment = Some(comment.into());
        self
    }

    pub fn session_id(mut self, session_id: impl Into<String>) -> Self {
        self.session_id = Some(session_id.into());
        self
    }

    /// Build the NewQueryFeedback.
    pub fn build(self) -> Result<NewQueryFeedback, &'static str> {
        Ok(NewQueryFeedback {
            request_id: self.request_id.ok_or("request_id is required")?,
            tenant_id: self.tenant_id,
            rating: self.rating.ok_or("rating is required")?,
            feedback_type: self
                .feedback_type
                .or(Some(FeedbackType::General.to_string())),
            comment: self.comment,
            session_id: self.session_id,
        })
    }
}
