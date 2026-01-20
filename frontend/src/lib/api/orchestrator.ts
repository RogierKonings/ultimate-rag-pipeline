import { ApiClient } from './client';
import type { QueryRequest, QueryResponse } from './types';
import { PUBLIC_DEMO_TENANT_ID } from '$env/static/public';

// Lazy client initialization to avoid SSR fetch issues
let _client: ApiClient | null = null;
function getClient(): ApiClient {
	if (!_client) {
		_client = new ApiClient('/api/proxy/orchestrator');
	}
	return _client;
}

/**
 * Submit a query to the RAG pipeline
 */
export async function query(request: Omit<QueryRequest, 'tenant_id'>): Promise<QueryResponse> {
	return getClient().post<QueryResponse>('/query', {
		...request,
		tenant_id: PUBLIC_DEMO_TENANT_ID || '00000000-0000-0000-0000-000000000001',
		options: {
			include_citations: true,
			...request.options
		}
	});
}

/**
 * Submit feedback for a query response
 */
export async function submitFeedback(
	requestId: string,
	rating: number,
	feedbackType: 'helpful' | 'unhelpful' | 'wrong' | 'general' = 'general',
	comment?: string
): Promise<{ success: boolean; message: string; feedback_id: string }> {
	return getClient().post('/feedback', {
		request_id: requestId,
		rating,
		feedback_type: feedbackType,
		comment
	});
}
