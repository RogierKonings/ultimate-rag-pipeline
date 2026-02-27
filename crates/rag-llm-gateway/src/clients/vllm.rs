//! vLLM service client.

use futures_util::StreamExt;
use rag_config::build_http_client_with_timeout;
use reqwest::{Client, StatusCode};
use tracing::{debug, error, instrument};

use crate::auth::AuthContext;
use crate::config::VllmConfig;
use crate::error::{GatewayError, Result};

use super::types::{ChatCompletionChunk, ChatCompletionRequest, ChatCompletionResponse};

/// vLLM HTTP client.
#[derive(Clone)]
pub struct VllmClient {
    client: Client,
    config: VllmConfig,
}

impl VllmClient {
    /// Create a new vLLM client.
    pub fn new(config: VllmConfig) -> Result<Self> {
        let client =
            build_http_client_with_timeout(config.timeout()).map_err(GatewayError::Internal)?;

        Ok(Self { client, config })
    }

    /// Health check.
    pub async fn health_check(&self) -> bool {
        let url = format!("{}/health", self.config.url);
        match self.client.get(&url).send().await {
            Ok(resp) => resp.status() == StatusCode::OK,
            Err(e) => {
                debug!("vLLM health check failed: {}", e);
                false
            }
        }
    }

    /// Create a chat completion (non-streaming).
    #[instrument(skip(self, request, auth_context), fields(model = ?request.model))]
    pub async fn chat_completion(
        &self,
        request: ChatCompletionRequest,
        auth_context: &AuthContext,
    ) -> Result<ChatCompletionResponse> {
        let url = format!("{}/v1/chat/completions", self.config.url);

        let model = request
            .model
            .clone()
            .unwrap_or_else(|| self.config.default_model.clone());

        let payload = serde_json::json!({
            "model": model,
            "messages": request.messages,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "n": request.n,
            "stream": false,
            "max_tokens": request.max_tokens,
            "stop": request.stop,
            "presence_penalty": request.presence_penalty,
            "frequency_penalty": request.frequency_penalty,
            "seed": request.seed,
        });

        let mut req_builder = self.client.post(&url).json(&payload);

        // Add auth context headers
        for (name, value) in auth_context.to_headers() {
            req_builder = req_builder.header(name, value);
        }

        let response = req_builder.send().await.map_err(|e| {
            error!("vLLM request failed: {}", e);
            GatewayError::UpstreamError(format!("vLLM request failed: {e}"))
        })?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            error!("vLLM error response: {} - {}", status, body);
            return Err(GatewayError::UpstreamError(format!(
                "vLLM returned {status}: {body}"
            )));
        }

        response.json().await.map_err(|e| {
            error!("Failed to parse vLLM response: {}", e);
            GatewayError::UpstreamError(format!("Invalid vLLM response: {e}"))
        })
    }

    /// Create a streaming chat completion.
    #[instrument(skip(self, request, auth_context), fields(model = ?request.model))]
    pub async fn chat_completion_stream(
        &self,
        request: ChatCompletionRequest,
        auth_context: &AuthContext,
    ) -> Result<impl futures_util::Stream<Item = Result<ChatCompletionChunk>>> {
        let url = format!("{}/v1/chat/completions", self.config.url);

        let model = request
            .model
            .clone()
            .unwrap_or_else(|| self.config.default_model.clone());

        let payload = serde_json::json!({
            "model": model,
            "messages": request.messages,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "n": request.n,
            "stream": true,
            "max_tokens": request.max_tokens,
            "stop": request.stop,
            "presence_penalty": request.presence_penalty,
            "frequency_penalty": request.frequency_penalty,
        });

        let mut req_builder = self.client.post(&url).json(&payload);

        for (name, value) in auth_context.to_headers() {
            req_builder = req_builder.header(name, value);
        }

        let response = req_builder
            .send()
            .await
            .map_err(|e| GatewayError::UpstreamError(format!("vLLM stream request failed: {e}")))?;

        if !response.status().is_success() {
            let status = response.status();
            let body = response.text().await.unwrap_or_default();
            return Err(GatewayError::UpstreamError(format!(
                "vLLM returned {status}: {body}"
            )));
        }

        let stream = response.bytes_stream().filter_map(|result| async move {
            match result {
                Ok(bytes) => {
                    let text = String::from_utf8_lossy(&bytes);
                    for line in text.lines() {
                        if let Some(data) = line.strip_prefix("data: ") {
                            if data == "[DONE]" {
                                return None;
                            }
                            match serde_json::from_str::<ChatCompletionChunk>(data) {
                                Ok(chunk) => return Some(Ok(chunk)),
                                Err(e) => {
                                    debug!("Failed to parse chunk: {} - {}", e, data);
                                }
                            }
                        }
                    }
                    None
                }
                Err(e) => Some(Err(GatewayError::UpstreamError(format!(
                    "Stream error: {e}"
                )))),
            }
        });

        Ok(stream)
    }
}
