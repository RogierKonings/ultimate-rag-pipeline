import { ApiClient } from './client';
import type { QueryRequest, QueryResponse } from './types';
import { PUBLIC_DEMO_TENANT_ID } from '$env/static/public';

// Use proxy route to avoid CORS issues
const client = new ApiClient('/api/proxy/orchestrator');

/**
 * Submit a query to the RAG pipeline
 */
export async function query(request: Omit<QueryRequest, 'tenant_id'>): Promise<QueryResponse> {
	return client.post<QueryResponse>('/query', {
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
	return client.post('/feedback', {
		request_id: requestId,
		rating,
		feedback_type: feedbackType,
		comment
	});
}
