//! HTTP API for the embedding service.

pub mod error;
pub mod routes;
pub mod state;
pub mod types;

pub use error::{ApiError, ApiResult};
pub use routes::create_router;
pub use state::AppState;
pub use types::{EmbeddingRequest, EmbeddingResponse};
