import { ApiClient } from './client';
import type {
	QueryRequest,
	QueryResponse,
	StreamQueryRequest,
	StreamEventType,
	StreamStartData,
	StreamDeltaData,
	StreamCitationsData,
	StreamDoneData,
	StreamErrorData
} from './types';
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
 * Callbacks for handling individual SSE events during streaming.
 */
export interface StreamCallbacks {
	onStart?: (data: StreamStartData) => void;
	onDelta?: (data: StreamDeltaData) => void;
	onCitations?: (data: StreamCitationsData) => void;
	onDone?: (data: StreamDoneData) => void;
	onError?: (data: StreamErrorData) => void;
}

/**
 * Parse a single SSE line pair into event type and data.
 * SSE format: "event: <type>\ndata: <json>\n\n"
 */
function parseSSEChunk(
	chunk: string
): { event: StreamEventType; data: Record<string, unknown> } | null {
	const lines = chunk.trim().split('\n');
	let eventType: StreamEventType | null = null;
	let dataStr: string | null = null;

	for (const line of lines) {
		if (line.startsWith('event: ')) {
			eventType = line.slice(7).trim() as StreamEventType;
		} else if (line.startsWith('data: ')) {
			dataStr = line.slice(6);
		}
	}

	if (!eventType || !dataStr) return null;

	try {
		const data = JSON.parse(dataStr) as Record<string, unknown>;
		return { event: eventType, data };
	} catch {
		return null;
	}
}

/**
 * Submit a streaming query to the RAG pipeline via SSE.
 *
 * Returns an AbortController that can be used to cancel the stream.
 * The stream is consumed and events are dispatched to the provided callbacks.
 */
export function queryStream(
	request: Omit<StreamQueryRequest, 'tenant_id'>,
	callbacks: StreamCallbacks
): AbortController {
	const controller = new AbortController();

	const body: StreamQueryRequest = {
		...request,
		tenant_id: PUBLIC_DEMO_TENANT_ID || '00000000-0000-0000-0000-000000000001',
		options: {
			include_citations: true,
			...request.options
		}
	};

	// Start the streaming request asynchronously
	(async () => {
		try {
			const response = await fetch('/api/proxy/orchestrator/query/stream', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify(body),
				signal: controller.signal
			});

			if (!response.ok) {
				let errorMessage = `Stream request failed with status ${response.status}`;
				try {
					const errorBody = await response.json();
					errorMessage = errorBody.detail || errorBody.message || errorMessage;
				} catch {
					// Ignore parse errors
				}
				callbacks.onError?.({
					error: errorMessage,
					code: 'HTTP_ERROR',
					recoverable: response.status >= 500,
					request_id: '',
					timestamp: Date.now() / 1000
				});
				return;
			}

			const reader = response.body?.getReader();
			if (!reader) {
				callbacks.onError?.({
					error: 'Response body is not readable',
					code: 'NO_BODY',
					recoverable: false,
					request_id: '',
					timestamp: Date.now() / 1000
				});
				return;
			}

			const decoder = new TextDecoder();
			let buffer = '';

			while (true) {
				const { done, value } = await reader.read();
				if (done) break;

				buffer += decoder.decode(value, { stream: true });

				// SSE events are separated by double newlines
				const parts = buffer.split('\n\n');
				// Keep the last incomplete chunk in the buffer
				buffer = parts.pop() || '';

				for (const part of parts) {
					if (!part.trim()) continue;

					const parsed = parseSSEChunk(part);
					if (!parsed) continue;

					switch (parsed.event) {
						case 'start':
							callbacks.onStart?.(parsed.data as unknown as StreamStartData);
							break;
						case 'delta':
							callbacks.onDelta?.(parsed.data as unknown as StreamDeltaData);
							break;
						case 'citations':
							callbacks.onCitations?.(parsed.data as unknown as StreamCitationsData);
							break;
						case 'done':
							callbacks.onDone?.(parsed.data as unknown as StreamDoneData);
							break;
						case 'error':
							callbacks.onError?.(parsed.data as unknown as StreamErrorData);
							break;
					}
				}
			}
		} catch (err: unknown) {
			// Don't report abort errors - they're intentional cancellations
			if (err instanceof DOMException && err.name === 'AbortError') {
				return;
			}
			callbacks.onError?.({
				error: err instanceof Error ? err.message : 'Stream failed unexpectedly',
				code: 'NETWORK_ERROR',
				recoverable: true,
				request_id: '',
				timestamp: Date.now() / 1000
			});
		}
	})();

	return controller;
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
