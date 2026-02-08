import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock $env module before importing module under test
vi.mock('$env/static/public', () => ({
	PUBLIC_DEMO_TENANT_ID: '00000000-0000-0000-0000-000000000001'
}));

describe('fetchCapabilities', () => {
	let originalFetch: typeof globalThis.fetch;

	beforeEach(() => {
		originalFetch = globalThis.fetch;
	});

	afterEach(() => {
		globalThis.fetch = originalFetch;
	});

	it('returns capabilities from the backend on success', async () => {
		const mockCapabilities = {
			version: '1',
			features: {
				streaming: true,
				reranker: true,
				llm: true,
				workflow: true,
				video_search: false,
				query_expansion: false,
				guardrails: true,
				answer_verification: false,
				session_memory: true,
				feedback: true
			}
		};

		globalThis.fetch = vi.fn().mockResolvedValue({
			ok: true,
			status: 200,
			json: async () => mockCapabilities
		} as unknown as Response);

		const { fetchCapabilities } = await import('./capabilities');
		const result = await fetchCapabilities();

		expect(result.version).toBe('1');
		expect(result.features.streaming).toBe(true);
		expect(result.features.video_search).toBe(false);
		expect(result.features.feedback).toBe(true);
	});

	it('returns conservative defaults when the endpoint is unreachable', async () => {
		globalThis.fetch = vi.fn().mockRejectedValue(new Error('Network error'));

		const { fetchCapabilities, DEFAULT_CAPABILITIES } = await import('./capabilities');
		const result = await fetchCapabilities();

		expect(result).toEqual(DEFAULT_CAPABILITIES);
		expect(result.version).toBe('0');
		// All features should be false in defaults
		for (const [key, value] of Object.entries(result.features)) {
			expect(value).toBe(false);
		}
	});

	it('returns conservative defaults when the endpoint returns an error status', async () => {
		globalThis.fetch = vi.fn().mockResolvedValue({
			ok: false,
			status: 500,
			json: async () => ({ error: 'Internal Server Error', message: 'Something broke' })
		} as unknown as Response);

		const { fetchCapabilities, DEFAULT_CAPABILITIES } = await import('./capabilities');
		const result = await fetchCapabilities();

		expect(result).toEqual(DEFAULT_CAPABILITIES);
	});

	it('default capabilities have all expected feature keys', async () => {
		const { DEFAULT_CAPABILITIES } = await import('./capabilities');

		const expectedKeys = [
			'streaming',
			'reranker',
			'llm',
			'workflow',
			'video_search',
			'query_expansion',
			'guardrails',
			'answer_verification',
			'session_memory',
			'feedback'
		];

		for (const key of expectedKeys) {
			expect(DEFAULT_CAPABILITIES.features).toHaveProperty(key);
		}
	});

	it('default capabilities version is "0" to distinguish from live data', async () => {
		const { DEFAULT_CAPABILITIES } = await import('./capabilities');

		expect(DEFAULT_CAPABILITIES.version).toBe('0');
	});
});
