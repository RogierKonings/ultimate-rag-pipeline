import { ApiClient } from './client';
import type { ServiceCapabilities } from './types';

// Lazy client initialization to avoid SSR fetch issues
let _client: ApiClient | null = null;
function getClient(): ApiClient {
	if (!_client) {
		_client = new ApiClient('/api/proxy/orchestrator');
	}
	return _client;
}

/**
 * Conservative default capabilities assumed when the backend
 * capabilities endpoint is unreachable. This ensures the UI
 * degrades gracefully rather than showing features that may
 * not work.
 */
export const DEFAULT_CAPABILITIES: ServiceCapabilities = {
	version: '0',
	features: {
		streaming: false,
		reranker: false,
		llm: false,
		workflow: false,
		video_search: false,
		query_expansion: false,
		guardrails: false,
		answer_verification: false,
		session_memory: false,
		feedback: false
	}
};

/**
 * Fetch runtime service capabilities from the orchestrator.
 *
 * Returns conservative defaults if the endpoint is unreachable,
 * ensuring the UI never enables features the backend cannot support.
 */
export async function fetchCapabilities(): Promise<ServiceCapabilities> {
	try {
		return await getClient().get<ServiceCapabilities>('/capabilities');
	} catch {
		console.warn('Capabilities endpoint unreachable, using conservative defaults');
		return DEFAULT_CAPABILITIES;
	}
}
