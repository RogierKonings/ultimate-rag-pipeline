// API Types matching backend schemas

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
