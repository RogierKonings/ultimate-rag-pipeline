//! Chat completion endpoints.

use std::sync::Arc;

use axum::{
    body::Body,
    extract::State,
    response::{IntoResponse, Response},
    Extension, Json,
};
use futures_util::StreamExt;
use tracing::instrument;

use crate::api::AppState;
use crate::auth::AuthContext;
use crate::clients::types::{ChatCompletionRequest, ChatCompletionResponse};
use crate::error::{GatewayError, Result};

/// Create chat completion endpoint.
///
/// Proxies chat completion requests to the vLLM backend.
/// Supports both streaming and non-streaming responses.
/// Compatible with OpenAI's `/v1/chat/completions` API.
#[instrument(skip(state, request, auth_context), fields(model = ?request.model, stream = request.stream))]
pub async fn create_chat_completion(
    State(state): State<Arc<AppState>>,
    auth_context: Option<Extension<AuthContext>>,
    Json(request): Json<ChatCompletionRequest>,
) -> Result<Response> {
    let client = state
        .vllm_client
        .as_ref()
        .ok_or_else(|| GatewayError::ServiceUnavailable("vLLM service not available".into()))?;

    // Extract auth context or use anonymous
    let auth = auth_context.map_or_else(AuthContext::anonymous, |ext| ext.0);

    if request.stream {
        // Streaming response using Server-Sent Events (SSE)
        let stream = client.chat_completion_stream(request, &auth).await?;

        let body = Body::from_stream(stream.map(|result| {
            result.map(|chunk| {
                let json = serde_json::to_string(&chunk).unwrap_or_default();
                format!("data: {json}\n\n")
            })
        }));

        Ok(Response::builder()
            .header("Content-Type", "text/event-stream")
            .header("Cache-Control", "no-cache")
            .header("Connection", "keep-alive")
            .body(body)
            .unwrap())
    } else {
        // Non-streaming response
        let response: ChatCompletionResponse = client.chat_completion(request, &auth).await?;
        Ok(Json(response).into_response())
    }
}
