// =============================================================================
// GENERATED FILE - DO NOT EDIT MANUALLY
// =============================================================================
// Generated from backend Pydantic models by scripts/generate-api-types.sh
// Source of truth: services/orchestrator/api/models/
//
// To regenerate: ./scripts/generate-api-types.sh
// To check for drift: ./scripts/check-api-contracts.sh
// =============================================================================

/** Source document included in query response. */
export interface SourceDocument {
	/** Document/chunk identifier */
	id: string;
	/** Document title */
	title?: string | null;
	/** Source URI or path */
	uri?: string | null;
	/** Relevance score */
	score?: number | null;
	/** Content snippet */
	snippet?: string | null;
}

/** Token usage information. */
export interface UsageInfo {
	/** Tokens in the prompt */
	prompt_tokens?: number;
	/** Tokens in the completion */
	completion_tokens?: number;
	/** Total tokens used */
	total_tokens?: number;
}

/** Answer verification result (CRAG-style claim verification). */
export interface VerificationInfo {
	/** Verification score */
	score?: number;
	/** Verification label */
	label?: string;
	/** Total claims verified */
	claims_total?: number;
	/** Supported claims */
	claims_supported?: number;
	/** Partially supported claims */
	claims_partial?: number;
	/** Unsupported claims */
	claims_unsupported?: number;
	/** Verification time */
	verification_time_ms?: number;
	/** Whether verification was skipped */
	skipped?: boolean;
	/** Reason for skipping */
	skip_reason?: string | null;
}

/** Response model for synchronous RAG query. */
export interface QueryResponse {
	/** Unique request identifier */
	request_id: string;
	/** Generated response text */
	response: string;
	/** Source documents used in response */
	sources?: SourceDocument[];
	/** Session ID for conversation tracking */
	session_id?: string | null;
	/** Model used for generation */
	model: string;
	/** Token usage statistics */
	usage?: UsageInfo;
	/** Response latency in milliseconds */
	latency_ms?: number;
	/** Retrieval strategy used */
	strategy_used?: string | null;
	/** Answer verification result (CRAG-style) */
	verification?: VerificationInfo | null;
	/** Retrieval mode used (hybrid_full, semantic_only, etc) */
	retrieval_mode?: string | null;
	/** Quality of retrieved context (full, partial, minimal) */
	context_quality?: string | null;
	/** Which retrieval components were available */
	components_available?: Record<string, boolean> | null;
	/** List of fallback strategies applied */
	fallbacks_used?: string[];
	/** Whether response was served from answer cache */
	cache_hit?: boolean;
}

/** Session information model. */
export interface SessionInfo {
	/** Session identifier */
	id: string;
	/** User identifier */
	user_id?: string | null;
	/** Tenant identifier */
	tenant_id?: string | null;
	/** Session creation timestamp */
	created_at: string;
	/** Last update timestamp */
	updated_at: string;
	/** Number of messages */
	message_count?: number;
	/** Total tokens used */
	total_tokens?: number;
}

/** Response model for session operations. */
export interface SessionResponse {
	/** Session information */
	session: SessionInfo;
	/** Status message */
	message?: string | null;
}

/** Message information model. */
export interface MessageInfo {
	/** Message identifier */
	id: string;
	/** Message role */
	role: string;
	/** Message content */
	content: string;
	/** Message timestamp */
	timestamp: string;
	/** Source references for assistant messages */
	sources?: string[] | null;
}

/** Response model for session history. */
export interface HistoryResponse {
	/** Session identifier */
	session_id: string;
	/** Messages in the session */
	messages?: MessageInfo[];
	/** Whether session is summarized */
	has_summary?: boolean;
	/** Summary of earlier messages */
	summary?: string | null;
}

/** Health status of a single component. */
export interface ComponentHealth {
	/** Component name */
	name: string;
	/** Health status */
	status: string;
	/** Latency in ms */
	latency_ms?: number | null;
	/** Status message */
	message?: string | null;
}

/** Response model for health check endpoints. */
export interface HealthResponse {
	/** Overall health status */
	status: string;
	/** Service name */
	service?: string;
	/** Service version */
	version?: string;
	/** Service uptime */
	uptime_seconds?: number;
	/** Component health status */
	components?: ComponentHealth[];
	/** Health check timestamp */
	timestamp?: string;
}

/** Detailed error information. */
export interface ErrorDetail {
	/** Field causing error */
	field?: string | null;
	/** Error message */
	message: string;
	/** Error code */
	code?: string | null;
}

/** Response model for error responses. */
export interface ErrorResponse {
	/** Error type/name */
	error: string;
	/** Human-readable error message */
	message: string;
	/** Request identifier */
	request_id?: string | null;
	/** Detailed error information */
	details?: ErrorDetail[] | null;
	/** Error timestamp */
	timestamp?: string;
}

/** Response model for feedback submission. */
export interface FeedbackResponse {
	/** Whether feedback was recorded */
	success: boolean;
	/** Status message */
	message: string;
	/** Identifier for recorded feedback */
	feedback_id?: string | null;
}

/** Response model for clearing a session. */
export interface ClearSessionResponse {
	/** Whether session was cleared */
	success: boolean;
	/** Cleared session identifier */
	session_id: string;
	/** Status message */
	message: string;
}

/** Response model for deleting a session. */
export interface DeleteSessionResponse {
	/** Whether session was deleted */
	success: boolean;
	/** Deleted session identifier */
	session_id: string;
	/** Status message */
	message: string;
}

/** Typed configuration overrides for a query request. */
export interface QueryOptions {
	/** LLM model name to use for answer generation */
	model?: string | null;
	/** Sampling temperature (0.0–2.0) */
	temperature?: number | null;
	/** Maximum number of retrieved chunks (1–100) */
	top_k?: number | null;
	/** Weight for semantic search in hybrid fusion (0.0–1.0) */
	semantic_weight?: number | null;
	/** Weight for keyword search in hybrid fusion (0.0–1.0) */
	keyword_weight?: number | null;
	/** Whether to enable cross-encoder reranking */
	rerank?: boolean | null;
	/** Whether to use the answer cache */
	answer_cache?: boolean | null;
	/** Maximum tokens in the generated answer (1–8192) */
	max_tokens?: number | null;
}

/** Request model for synchronous RAG query. */
export interface QueryRequest {
	/** The user's query text */
	query: string;
	/** Session ID for conversation continuity */
	session_id?: string | null;
	/** User identifier for ACL filtering */
	user_id?: string | null;
	/** Tenant identifier for multi-tenancy */
	tenant_id?: string | null;
	/** Optional configuration overrides (model, temperature, etc.) */
	options?: QueryOptions | null;
}

/** Request model for streaming RAG query. */
export interface StreamQueryRequest {
	/** The user's query text */
	query: string;
	/** Session ID for conversation continuity */
	session_id?: string | null;
	/** User identifier for ACL filtering */
	user_id?: string | null;
	/** Tenant identifier for multi-tenancy */
	tenant_id?: string | null;
	/** Optional configuration overrides */
	options?: QueryOptions | null;
}

/** Request model for submitting user feedback. */
export interface FeedbackRequest {
	/** The request ID to provide feedback for */
	request_id: string;
	/** User rating from 1 (poor) to 5 (excellent) */
	rating: number;
	/** Type of feedback (helpful, unhelpful, wrong, general) */
	feedback_type?: string;
	/** Optional user comment */
	comment?: string | null;
	/** Session ID for context */
	session_id?: string | null;
}

/** Request model for creating a new session. */
export interface CreateSessionRequest {
	/** User identifier */
	user_id?: string | null;
	/** Tenant identifier */
	tenant_id?: string | null;
	/** Custom system prompt for this session */
	system_prompt?: string | null;
	/** Additional metadata for the session */
	metadata?: Record<string, unknown> | null;
}

/** Token usage breakdown by model. */
export interface UsageByModel {
	/** Model identifier */
	model: string;
	/** Prompt tokens consumed */
	prompt_tokens?: number;
	/** Completion tokens generated */
	completion_tokens?: number;
	/** Embedding tokens processed */
	embedding_tokens?: number;
	/** Total tokens */
	total_tokens?: number;
}

/** Response model for usage statistics. */
export interface UsageStatsResponse {
	/** Tenant identifier */
	tenant_id: string;
	/** Time period */
	period: string;
	/** Period start date */
	start_date: string;
	/** Period end date */
	end_date: string;
	/** Usage per model */
	usage_by_model?: UsageByModel[];
	/** Total prompt tokens */
	total_prompt_tokens?: number;
	/** Total completion tokens */
	total_completion_tokens?: number;
	/** Total embedding tokens */
	total_embedding_tokens?: number;
	/** Grand total tokens */
	total_tokens?: number;
}

/** Response model for quota status. */
export interface QuotaStatusResponse {
	/** Tenant identifier */
	tenant_id: string;
	/** Quota enforcement enabled */
	quota_enabled?: boolean;
	/** Monthly token limit */
	monthly_limit?: number | null;
	/** Current month usage */
	current_usage?: number;
	/** Tokens remaining */
	remaining?: number | null;
	/** Usage percentage */
	usage_percent?: number | null;
	/** Alert threshold */
	alert_threshold_percent?: number;
	/** Usage exceeds limit */
	is_over_limit?: boolean;
}

/** Request model for updating quota configuration. */
export interface QuotaUpdateRequest {
	/** Monthly token limit (null for unlimited) */
	monthly_token_limit?: number | null;
	/** Enable quota enforcement */
	quota_enabled?: boolean;
	/** Alert threshold percentage */
	alert_threshold_percent?: number;
}

/** Response model for quota update. */
export interface QuotaUpdateResponse {
	/** Tenant identifier */
	tenant_id: string;
	/** Monthly limit */
	monthly_token_limit?: number | null;
	/** Quota enabled */
	quota_enabled?: boolean;
	/** Alert threshold */
	alert_threshold_percent?: number;
	/** Status message */
	message?: string;
}

