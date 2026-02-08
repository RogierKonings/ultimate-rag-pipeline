import { describe, it, expect, vi, beforeEach } from 'vitest';

// We need to mock the $env module before importing the module under test
vi.mock('$env/static/public', () => ({
	PUBLIC_DEMO_TENANT_ID: '00000000-0000-0000-0000-000000000001'
}));

// Import the module functions - we'll test parseSSEChunk and queryStream behavior
// Since parseSSEChunk is not exported, we test it indirectly through queryStream

describe('queryStream', () => {
	let originalFetch: typeof globalThis.fetch;

	beforeEach(() => {
		originalFetch = globalThis.fetch;
	});

	afterEach(() => {
		globalThis.fetch = originalFetch;
	});

	/**
	 * Helper: create a ReadableStream from a list of SSE event strings.
	 */
	function createSSEStream(events: string[]): ReadableStream<Uint8Array> {
		const encoder = new TextEncoder();
		let index = 0;
		return new ReadableStream({
			pull(controller) {
				if (index < events.length) {
					controller.enqueue(encoder.encode(events[index]));
					index++;
				} else {
					controller.close();
				}
			}
		});
	}

	/**
	 * Helper: mock globalThis.fetch to return a streaming response.
	 */
	function mockFetchWithSSE(events: string[], status = 200) {
		globalThis.fetch = vi.fn().mockResolvedValue({
			ok: status >= 200 && status < 300,
			status,
			body: createSSEStream(events),
			json: async () => ({ detail: 'Error' })
		} as unknown as Response);
	}

	it('dispatches onStart when a start event is received', async () => {
		const { queryStream } = await import('./orchestrator');
		const startData = JSON.stringify({
			request_id: 'req-1',
			model: 'llama',
			session_id: null,
			degradation: null,
			timestamp: 1234567890
		});

		mockFetchWithSSE([`event: start\ndata: ${startData}\n\n`]);

		const onStart = vi.fn();
		queryStream({ query: 'test' }, { onStart });

		// Wait for async processing
		await new Promise((r) => setTimeout(r, 50));

		expect(onStart).toHaveBeenCalledTimes(1);
		expect(onStart).toHaveBeenCalledWith(
			expect.objectContaining({
				request_id: 'req-1',
				model: 'llama'
			})
		);
	});

	it('accumulates delta tokens and dispatches onDelta for each', async () => {
		const { queryStream } = await import('./orchestrator');
		const startData = JSON.stringify({
			request_id: 'req-2',
			model: 'llama',
			session_id: null,
			timestamp: 1234567890
		});
		const delta1 = JSON.stringify({ token: 'Hello', request_id: 'req-2', timestamp: 1234567891 });
		const delta2 = JSON.stringify({
			token: ' world',
			request_id: 'req-2',
			timestamp: 1234567892
		});

		mockFetchWithSSE([
			`event: start\ndata: ${startData}\n\n`,
			`event: delta\ndata: ${delta1}\n\n`,
			`event: delta\ndata: ${delta2}\n\n`
		]);

		const onDelta = vi.fn();
		queryStream({ query: 'test' }, { onDelta });

		await new Promise((r) => setTimeout(r, 100));

		expect(onDelta).toHaveBeenCalledTimes(2);
		expect(onDelta.mock.calls[0][0].token).toBe('Hello');
		expect(onDelta.mock.calls[1][0].token).toBe(' world');
	});

	it('dispatches onCitations with source documents', async () => {
		const { queryStream } = await import('./orchestrator');
		const citationsData = JSON.stringify({
			sources: [
				{ title: 'Doc 1', uri: 'doc1.pdf', chunk_id: 'c1' },
				{ title: 'Doc 2', uri: 'doc2.pdf', chunk_id: 'c2' }
			],
			request_id: 'req-3',
			timestamp: 1234567893
		});

		mockFetchWithSSE([`event: citations\ndata: ${citationsData}\n\n`]);

		const onCitations = vi.fn();
		queryStream({ query: 'test' }, { onCitations });

		await new Promise((r) => setTimeout(r, 50));

		expect(onCitations).toHaveBeenCalledTimes(1);
		expect(onCitations.mock.calls[0][0].sources).toHaveLength(2);
		expect(onCitations.mock.calls[0][0].sources[0].title).toBe('Doc 1');
	});

	it('dispatches onDone with usage statistics', async () => {
		const { queryStream } = await import('./orchestrator');
		const doneData = JSON.stringify({
			request_id: 'req-4',
			usage: { prompt_tokens: 50, completion_tokens: 100, total_tokens: 150 },
			latency_ms: 1234.56,
			context_quality: 'full',
			retrieval_mode: 'hybrid_full',
			timestamp: 1234567894
		});

		mockFetchWithSSE([`event: done\ndata: ${doneData}\n\n`]);

		const onDone = vi.fn();
		queryStream({ query: 'test' }, { onDone });

		await new Promise((r) => setTimeout(r, 50));

		expect(onDone).toHaveBeenCalledTimes(1);
		expect(onDone.mock.calls[0][0].usage.total_tokens).toBe(150);
		expect(onDone.mock.calls[0][0].latency_ms).toBe(1234.56);
	});

	it('dispatches onError when server sends an error event', async () => {
		const { queryStream } = await import('./orchestrator');
		const errorData = JSON.stringify({
			error: 'Model unavailable',
			code: 'MODEL_ERROR',
			recoverable: true,
			request_id: 'req-5',
			timestamp: 1234567895
		});

		mockFetchWithSSE([`event: error\ndata: ${errorData}\n\n`]);

		const onError = vi.fn();
		queryStream({ query: 'test' }, { onError });

		await new Promise((r) => setTimeout(r, 50));

		expect(onError).toHaveBeenCalledTimes(1);
		expect(onError.mock.calls[0][0].error).toBe('Model unavailable');
		expect(onError.mock.calls[0][0].recoverable).toBe(true);
	});

	it('dispatches onError when HTTP response is not ok', async () => {
		const { queryStream } = await import('./orchestrator');

		globalThis.fetch = vi.fn().mockResolvedValue({
			ok: false,
			status: 503,
			json: async () => ({ detail: 'Service unavailable' })
		} as unknown as Response);

		const onError = vi.fn();
		queryStream({ query: 'test' }, { onError });

		await new Promise((r) => setTimeout(r, 50));

		expect(onError).toHaveBeenCalledTimes(1);
		expect(onError.mock.calls[0][0].code).toBe('HTTP_ERROR');
		expect(onError.mock.calls[0][0].recoverable).toBe(true);
	});

	it('does not dispatch onError when abort signal fires', async () => {
		const { queryStream } = await import('./orchestrator');

		// Create a fetch that will be aborted
		globalThis.fetch = vi.fn().mockImplementation((_url: string, init: RequestInit) => {
			return new Promise((_resolve, reject) => {
				if (init.signal) {
					init.signal.addEventListener('abort', () => {
						reject(new DOMException('The operation was aborted.', 'AbortError'));
					});
				}
			});
		});

		const onError = vi.fn();
		const controller = queryStream({ query: 'test' }, { onError });

		// Abort immediately
		controller.abort();

		await new Promise((r) => setTimeout(r, 50));

		// AbortError should NOT trigger onError
		expect(onError).not.toHaveBeenCalled();
	});

	it('returns an AbortController that can cancel the stream', async () => {
		const { queryStream } = await import('./orchestrator');

		mockFetchWithSSE([]);

		const controller = queryStream({ query: 'test' }, {});

		expect(controller).toBeInstanceOf(AbortController);
		expect(controller.signal.aborted).toBe(false);

		controller.abort();
		expect(controller.signal.aborted).toBe(true);
	});

	it('handles multiple events in a single chunk', async () => {
		const { queryStream } = await import('./orchestrator');
		const start = JSON.stringify({
			request_id: 'req-6',
			model: 'llama',
			session_id: null,
			timestamp: 1
		});
		const delta = JSON.stringify({ token: 'Hi', request_id: 'req-6', timestamp: 2 });

		// Both events in a single chunk
		mockFetchWithSSE([`event: start\ndata: ${start}\n\nevent: delta\ndata: ${delta}\n\n`]);

		const onStart = vi.fn();
		const onDelta = vi.fn();
		queryStream({ query: 'test' }, { onStart, onDelta });

		await new Promise((r) => setTimeout(r, 50));

		expect(onStart).toHaveBeenCalledTimes(1);
		expect(onDelta).toHaveBeenCalledTimes(1);
	});
});

// Need afterEach in vitest without explicit import
import { afterEach } from 'vitest';
