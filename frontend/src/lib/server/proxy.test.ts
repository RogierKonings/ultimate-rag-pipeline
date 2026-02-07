import { describe, it, expect, vi } from 'vitest';
import { forwardProxyRequest, createProxyHandlers } from './proxy';
import type { ProxyConfig } from './proxy';
import type { RequestEvent } from '@sveltejs/kit';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Minimal mock of a SvelteKit RequestEvent for proxy testing. */
function mockEvent(overrides: {
	method?: string;
	path?: string;
	search?: string;
	body?: string;
	contentType?: string;
	fetchResponse?: Response;
}): RequestEvent {
	const {
		method = 'GET',
		path = 'documents',
		search = '',
		body,
		contentType = 'application/json',
		fetchResponse = new Response(JSON.stringify({ ok: true }), {
			status: 200,
			headers: { 'Content-Type': 'application/json' }
		})
	} = overrides;

	const headersMap = new Map<string, string>();
	if (contentType) headersMap.set('Content-Type', contentType);

	return {
		params: { path },
		url: { search } as URL,
		request: {
			method,
			headers: {
				get: (name: string) => headersMap.get(name) ?? null
			},
			text: vi.fn().mockResolvedValue(body ?? '')
		} as unknown as Request,
		fetch: vi.fn().mockResolvedValue(fetchResponse)
	} as unknown as RequestEvent;
}

function defaultConfig(overrides?: Partial<ProxyConfig>): ProxyConfig {
	return {
		baseUrl: 'http://upstream:8000',
		serviceName: 'test-service',
		pathPrefix: '/api/v1',
		...overrides
	};
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('forwardProxyRequest', () => {
	// ---------- URL composition ----------

	it('composes URL with default /api/v1 prefix', async () => {
		const event = mockEvent({ path: 'search', search: '?q=hello' });
		await forwardProxyRequest(event, defaultConfig());

		expect(event.fetch).toHaveBeenCalledWith(
			'http://upstream:8000/api/v1/search?q=hello',
			expect.objectContaining({ method: 'GET' })
		);
	});

	it('composes URL without prefix when pathPrefix is empty', async () => {
		const event = mockEvent({ path: 'api/v1/ingest/single', search: '' });
		await forwardProxyRequest(event, defaultConfig({ pathPrefix: '' }));

		expect(event.fetch).toHaveBeenCalledWith(
			'http://upstream:8000/api/v1/ingest/single',
			expect.objectContaining({ method: 'GET' })
		);
	});

	// ---------- Method forwarding ----------

	it('forwards GET requests', async () => {
		const event = mockEvent({ method: 'GET' });
		await forwardProxyRequest(event, defaultConfig());

		expect(event.fetch).toHaveBeenCalledWith(
			expect.any(String),
			expect.objectContaining({ method: 'GET' })
		);
	});

	it('forwards POST requests with body', async () => {
		const body = JSON.stringify({ query: 'test' });
		const event = mockEvent({ method: 'POST', body });
		// Override the request method
		(event.request as unknown as Record<string, string>).method = 'POST';

		await forwardProxyRequest(event, defaultConfig());

		expect(event.request.text).toHaveBeenCalled();
		expect(event.fetch).toHaveBeenCalledWith(
			expect.any(String),
			expect.objectContaining({
				method: 'POST',
				body
			})
		);
	});

	it('forwards DELETE requests without body', async () => {
		const event = mockEvent({ method: 'DELETE' });
		(event.request as unknown as Record<string, string>).method = 'DELETE';

		await forwardProxyRequest(event, defaultConfig());

		expect(event.fetch).toHaveBeenCalledWith(
			expect.any(String),
			expect.objectContaining({ method: 'DELETE' })
		);
		// DELETE should NOT read the body
		expect(event.request.text).not.toHaveBeenCalled();
	});

	// ---------- Happy path response ----------

	it('returns upstream JSON data on success', async () => {
		const upstream = { results: [{ id: 1 }] };
		const event = mockEvent({
			fetchResponse: new Response(JSON.stringify(upstream), {
				status: 200,
				headers: { 'Content-Type': 'application/json' }
			})
		});

		const response = await forwardProxyRequest(event, defaultConfig());
		const data = await response.json();

		expect(response.status).toBe(200);
		expect(data).toEqual(upstream);
	});

	// ---------- Response transformation ----------

	it('applies transformResponse when provided', async () => {
		const upstream = { items: [1, 2, 3] };
		const event = mockEvent({
			fetchResponse: new Response(JSON.stringify(upstream), {
				status: 200,
				headers: { 'Content-Type': 'application/json' }
			})
		});

		const transform = vi.fn((data: unknown) => {
			(data as Record<string, unknown>).transformed = true;
			return data;
		});

		const response = await forwardProxyRequest(event, defaultConfig({ transformResponse: transform }));
		const data = await response.json();

		expect(transform).toHaveBeenCalledTimes(1);
		expect(data).toEqual({ items: [1, 2, 3], transformed: true });
	});

	// ---------- Upstream error ----------

	it('throws SvelteKit error with upstream status on non-ok response', async () => {
		const event = mockEvent({
			fetchResponse: new Response(JSON.stringify({ detail: 'Not found' }), {
				status: 404,
				headers: { 'Content-Type': 'application/json' }
			})
		});

		try {
			await forwardProxyRequest(event, defaultConfig());
			expect.fail('Should have thrown');
		} catch (err: unknown) {
			const e = err as { status: number; body: { message: string } };
			expect(e.status).toBe(404);
			expect(e.body.message).toBe('Not found');
		}
	});

	it('uses fallback message when upstream error body is not JSON', async () => {
		const event = mockEvent({
			fetchResponse: new Response('Internal Server Error', {
				status: 500,
				headers: { 'Content-Type': 'text/plain' }
			})
		});

		try {
			await forwardProxyRequest(event, defaultConfig());
			expect.fail('Should have thrown');
		} catch (err: unknown) {
			const e = err as { status: number; body: { message: string } };
			expect(e.status).toBe(500);
			expect(e.body.message).toBe('Request failed');
		}
	});

	// ---------- Network / fetch failure ----------

	it('throws 502 when fetch itself fails', async () => {
		const event = mockEvent({});
		(event.fetch as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('ECONNREFUSED'));

		try {
			await forwardProxyRequest(event, defaultConfig());
			expect.fail('Should have thrown');
		} catch (err: unknown) {
			const e = err as { status: number; body: { message: string } };
			expect(e.status).toBe(502);
			expect(e.body.message).toBe('ECONNREFUSED');
		}
	});

	// ---------- SSR-safe fetch ----------

	it('uses event.fetch instead of global fetch', async () => {
		const event = mockEvent({});
		await forwardProxyRequest(event, defaultConfig());

		// event.fetch should be called, not global fetch
		expect(event.fetch).toHaveBeenCalledTimes(1);
	});
});

describe('createProxyHandlers', () => {
	it('returns handlers for GET, POST, PUT, PATCH, DELETE', () => {
		const handlers = createProxyHandlers(defaultConfig());
		expect(handlers).toHaveProperty('GET');
		expect(handlers).toHaveProperty('POST');
		expect(handlers).toHaveProperty('PUT');
		expect(handlers).toHaveProperty('PATCH');
		expect(handlers).toHaveProperty('DELETE');
		expect(typeof handlers.GET).toBe('function');
	});

	it('handlers delegate to forwardProxyRequest', async () => {
		const event = mockEvent({});
		const handlers = createProxyHandlers(defaultConfig());

		const response = await handlers.GET(event);
		expect(event.fetch).toHaveBeenCalled();
		expect(response.status).toBe(200);
	});
});
