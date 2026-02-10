export type QueryMode = 'qa' | 'chat';

export interface QueryOptions {
	include_citations?: boolean;
	mode?: QueryMode;
	max_tokens?: number;
	temperature?: number;
}

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
	options?: QueryOptions;
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
	verification?: VerificationInfo | null;
	retrieval_mode?: string | null;
	context_quality?: string | null;
	components_available?: Record<string, boolean> | null;
	fallbacks_used?: string[];
	cache_hit?: boolean;
}

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
	options?: QueryOptions;
}
