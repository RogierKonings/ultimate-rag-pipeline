// API Types matching backend schemas
//
// Source of truth: services/orchestrator/api/models/ (Pydantic models)
// Generated reference: frontend/src/lib/api/generated-types.ts
//
// To regenerate the reference types from backend models:
//   ./scripts/generate-api-types.sh
// To check for contract drift:
//   ./scripts/check-api-contracts.sh

// Document types
export interface Document {
	document_id: string;
	source_id: string;
	source_type: 'filesystem' | 'database' | 'web' | 'api';
	filename: string;
	mime_type: string;
	title: string | null;
	author: string | null;
	chunk_count: number;
	total_tokens: number;
	tenant_id: string;
	visibility: 'public' | 'private' | 'group';
	created_at: string;
	updated_at: string;
	indexed_at: string | null;
	status: 'pending' | 'indexed' | 'failed';
}

export interface DocumentListResponse {
	documents: Document[];
	total: number;
	page: number;
	page_size: number;
	pages: number;
}

// Ingestion types
export interface IngestResponse {
	job_id: string;
	status: 'pending' | 'started' | 'progress' | 'success' | 'failure' | 'revoked';
	message: string;
	created_at: string;
}

export interface JobProgress {
	current: number;
	total: number;
	stage: string;
	percentage: number;
}

export interface JobStatusResponse {
	job_id: string;
	status: 'pending' | 'started' | 'progress' | 'success' | 'failure' | 'revoked';
	progress: JobProgress | null;
	documents_processed: number;
	chunks_created: number;
	started_at: string | null;
	completed_at: string | null;
	duration_seconds: number | null;
	error_message: string | null;
	errors: string[];
}

// Query types
export interface SourceDocument {
	id: string;
	title: string | null;
	uri: string | null;
	score: number | null;
	snippet: string | null;
}

export interface UsageInfo {
	prompt_tokens: number;
	completion_tokens: number;
	total_tokens: number;
}

export interface VerificationInfo {
	score: number;
	label: string;
	claims_total: number;
	claims_supported: number;
	claims_partial: number;
	claims_unsupported: number;
	verification_time_ms: number;
	skipped: boolean;
	skip_reason: string | null;
}

export interface QueryRequest {
	query: string;
	tenant_id?: string;
	user_id?: string;
	session_id?: string;
	options?: {
		include_citations?: boolean;
		mode?: 'qa' | 'chat';
		max_tokens?: number;
		temperature?: number;
	};
}

export interface QueryResponse {
	request_id: string;
	response: string;
	sources: SourceDocument[];
	session_id: string | null;
	model: string;
	usage: UsageInfo;
	latency_ms: number;
	strategy_used: string | null;
	// Fields added from backend contract (R13)
	verification?: VerificationInfo | null;
	retrieval_mode?: string | null;
	context_quality?: string | null;
	components_available?: Record<string, boolean> | null;
	fallbacks_used?: string[];
	cache_hit?: boolean;
}

// Upload types (for our frontend upload flow)
export interface UploadRequest {
	file: File;
	title?: string;
}

export interface UploadResponse {
	document_id: string;
	job_id: string;
	filename: string;
	status: 'queued';
}

// Queued file for batch upload modal
export interface QueuedFile {
	id: string;
	file: File;
	status: 'valid' | 'invalid';
	error?: string;
}

// Delete types
export interface DocumentDeleteResponse {
	document_id: string;
	deleted: boolean;
	chunks_deleted: number;
	message: string;
}

export interface BatchDeleteResponse {
	deleted_count: number;
	failed_count: number;
	results: DocumentDeleteResponse[];
}

// Streaming query types (SSE events)
export type StreamEventType = 'start' | 'delta' | 'citations' | 'done' | 'error';

export interface StreamStartData {
	request_id: string;
	model: string;
	session_id: string | null;
	degradation: {
		level: string;
		mode: string;
		message: string;
	} | null;
	timestamp: number;
}

export interface StreamDeltaData {
	token: string;
	request_id: string;
	timestamp: number;
}

export interface StreamCitationsData {
	sources: Array<{
		title: string;
		uri: string;
		chunk_id: string;
	}>;
	request_id: string;
	timestamp: number;
}

export interface StreamDoneData {
	request_id: string;
	usage: {
		prompt_tokens: number;
		completion_tokens: number;
		total_tokens: number;
	};
	latency_ms: number;
	context_quality: string;
	retrieval_mode: string;
	timestamp: number;
}

export interface StreamErrorData {
	error: string;
	code: string;
	recoverable: boolean;
	request_id: string;
	timestamp: number;
}

export type StreamEventData =
	| StreamStartData
	| StreamDeltaData
	| StreamCitationsData
	| StreamDoneData
	| StreamErrorData;

export interface StreamQueryRequest {
	query: string;
	tenant_id?: string;
	user_id?: string;
	session_id?: string;
	options?: {
		include_citations?: boolean;
		mode?: 'qa' | 'chat';
		max_tokens?: number;
		temperature?: number;
	};
}

// Error types
export interface ApiError {
	error: string;
	message: string;
	request_id?: string;
	details?: Array<{
		field: string | null;
		message: string;
		code: string | null;
	}>;
}

// Video types
export type VideoStatus = 'uploaded' | 'processing' | 'ready' | 'failed';
export type VideoProcessingStage =
	| 'audio_extraction'
	| 'transcription'
	| 'scene_detection'
	| 'visual_analysis'
	| 'ocr'
	| 'fusion'
	| 'embedding';

export interface Video {
	video_id: string;
	tenant_id: string;
	filename: string;
	title: string | null;
	description: string | null;
	duration_ms: number | null;
	duration_seconds: number | null;
	width: number | null;
	height: number | null;
	fps: number | null;
	codec: string | null;
	file_size_bytes: number | null;
	status: VideoStatus;
	processing_stage: VideoProcessingStage | null;
	processing_progress: number;
	error_message: string | null;
	detected_language: string | null;
	keyframe_count: number;
	chunk_count: number;
	visibility: 'public' | 'private' | 'group';
	allowed_groups: string[];
	tags: string[];
	thumbnail_url: string | null;
	stream_url: string | null;
	storage_path: string | null;
	created_at: string;
	uploaded_at: string | null;
	processed_at: string | null;
	updated_at: string | null;
}

export interface VideoListResponse {
	videos: Video[];
	pagination: {
		page: number;
		page_size: number;
		total: number;
		total_pages: number;
	};
}

export interface VideoUploadResponse {
	video_id: string;
	job_id: string;
	filename: string;
	status: VideoStatus;
	storage_path: string;
	message: string;
}

export interface VideoStatusResponse {
	video_id: string;
	status: VideoStatus;
	processing_stage: VideoProcessingStage | null;
	processing_progress: number;
	error_message: string | null;
	duration_seconds: number | null;
	keyframe_count: number;
	chunk_count: number;
	created_at: string;
	processed_at: string | null;
}

export interface VideoDeleteResult {
	video_id: string;
	deleted: boolean;
	message: string;
}

export interface VideoBatchDeleteResponse {
	deleted_count: number;
	failed_count: number;
	results: VideoDeleteResult[];
}

// Video search types
export interface VideoMatch {
	chunk_id: string;
	chunk_index: number;
	start_time_ms: number;
	end_time_ms: number;
	start_seconds: number;
	end_seconds: number;
	duration_seconds: number;
	fused_score: number;
	semantic_score: number | null;
	keyword_score: number | null;
	rerank_score: number | null;
	fused_text_preview: string;
	transcript_text: string | null;
	scene_description: string | null;
	keyframe_url: string | null;
	clip_url: string | null;
	source_modalities: string[];
}

export interface VideoSearchResult {
	video_id: string;
	tenant_id: string;
	title: string;
	thumbnail_url: string | null;
	duration_ms: number | null;
	max_score: number;
	avg_score: number;
	match_count: number;
	matches: VideoMatch[];
}

export interface VideoSearchResponse {
	query: string;
	mode: 'hybrid' | 'semantic' | 'keyword';
	videos: VideoSearchResult[];
	total_videos: number;
	total_matches: number;
	metrics: {
		total_ms: number;
		embedding_ms?: number;
		semantic_ms?: number;
		keyword_ms?: number;
		fusion_ms?: number;
		rerank_ms?: number;
	};
}

export interface VideoSearchRequest {
	query: string;
	mode?: 'hybrid' | 'semantic' | 'keyword';
	top_k?: number;
	video_id?: string;
	semantic_weight?: number;
	keyword_weight?: number;
	rerank?: boolean;
	max_matches_per_video?: number;
}

// Queued video file for upload modal
export interface QueuedVideoFile {
	id: string;
	file: File;
	status: 'valid' | 'invalid';
	error?: string;
}

// Capability discovery types
export interface ServiceCapabilities {
	version: string;
	features: Record<string, boolean>;
}
