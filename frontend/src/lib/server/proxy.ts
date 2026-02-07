import { json, error } from '@sveltejs/kit';
import type { RequestEvent } from '@sveltejs/kit';

/**
 * Configuration for the proxy helper.
 */
export interface ProxyConfig {
	/** Base URL of the upstream service (e.g. "http://localhost:8001") */
	baseUrl: string;

	/**
	 * Path prefix to insert between the base URL and the dynamic path segment.
	 * For example, "/api/v1" results in `${baseUrl}/api/v1/${path}`.
	 * When empty, the path is appended directly: `${baseUrl}/${path}`.
	 * @default "/api/v1"
	 */
	pathPrefix?: string;

	/** Human-readable service name used in error messages and logs. */
	serviceName: string;

	/**
	 * Optional callback to transform the upstream JSON response before
	 * returning it to the client. Receives the parsed JSON data and should
	 * return the (potentially modified) data.
	 */
	transformResponse?: (data: unknown) => unknown;
}

/**
 * Build the full upstream URL from the proxy config, dynamic path, and query string.
 */
function buildTargetUrl(config: ProxyConfig, path: string, queryString: string): string {
	const prefix = config.pathPrefix ?? '/api/v1';
	if (prefix) {
		return `${config.baseUrl}${prefix}/${path}${queryString}`;
	}
	return `${config.baseUrl}/${path}${queryString}`;
}

/**
 * Determine whether an error object is already a SvelteKit HttpError
 * (thrown via `error()`). These have a numeric `status` property and
 * should be re-thrown as-is.
 */
function isSvelteKitError(err: unknown): boolean {
	return err !== null && typeof err === 'object' && 'status' in err;
}

/**
 * Forward a proxy request to an upstream service.
 *
 * This helper centralises URL composition, header forwarding, error translation,
 * and optional response transformation. It uses `event.fetch` so that
 * SvelteKit's SSR credential / cookie handling works correctly.
 *
 * Supported HTTP methods: GET, POST, PUT, PATCH, DELETE.
 * Methods with a request body (POST, PUT, PATCH) will forward the raw body
 * and the original Content-Type header.
 */
export async function forwardProxyRequest(
	event: RequestEvent,
	config: ProxyConfig
): Promise<Response> {
	const path = (event.params as Record<string, string>).path ?? '';
	const queryString = event.url.search;
	const targetUrl = buildTargetUrl(config, path, queryString);
	const method = event.request.method;

	try {
		const headers: Record<string, string> = {
			'Content-Type': 'application/json'
		};

		const init: RequestInit = { method, headers };

		// Forward the body for methods that typically carry one.
		if (['POST', 'PUT', 'PATCH'].includes(method)) {
			const contentType = event.request.headers.get('Content-Type');
			if (contentType) {
				headers['Content-Type'] = contentType;
			}
			init.body = await event.request.text();
		}

		const response = await event.fetch(targetUrl, init);

		if (!response.ok) {
			const errorData = await response.json().catch(() => ({ detail: 'Request failed' }));
			throw error(response.status, {
				message: errorData.detail || errorData.message || 'Request failed'
			});
		}

		let data: unknown = await response.json();

		if (config.transformResponse) {
			data = config.transformResponse(data);
		}

		return json(data);
	} catch (err: unknown) {
		if (isSvelteKitError(err)) {
			throw err;
		}
		console.error(`${config.serviceName} proxy error:`, err);
		throw error(502, {
			message: err instanceof Error ? err.message : `Failed to reach ${config.serviceName}`
		});
	}
}

/**
 * Create a set of SvelteKit RequestHandler functions (GET, POST, PUT, PATCH, DELETE)
 * that all delegate to `forwardProxyRequest` with the supplied config.
 *
 * Usage:
 * ```ts
 * import { createProxyHandlers } from '$lib/server/proxy';
 *
 * const config = { baseUrl: '...', serviceName: 'retrieval' };
 * export const { GET, POST } = createProxyHandlers(config);
 * ```
 */
export function createProxyHandlers(config: ProxyConfig) {
	const handler = (event: RequestEvent) => forwardProxyRequest(event, config);
	return {
		GET: handler,
		POST: handler,
		PUT: handler,
		PATCH: handler,
		DELETE: handler
	};
}
