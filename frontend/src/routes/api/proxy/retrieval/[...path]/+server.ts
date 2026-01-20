import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { RETRIEVAL_URL } from '$env/static/private';

const RETRIEVAL_API = RETRIEVAL_URL || 'http://localhost:8002';

export const GET: RequestHandler = async ({ params, url, fetch }) => {
	const path = params.path || '';
	const queryString = url.search;
	const targetUrl = `${RETRIEVAL_API}/api/v1/${path}${queryString}`;

	try {
		const response = await fetch(targetUrl, {
			method: 'GET',
			headers: {
				'Content-Type': 'application/json'
			}
		});

		if (!response.ok) {
			const errorData = await response.json().catch(() => ({ detail: 'Request failed' }));
			throw error(response.status, { message: errorData.detail || 'Request failed' });
		}

		const data = await response.json();
		return json(data);
	} catch (err) {
		console.error('Retrieval proxy error:', err);
		if (err && typeof err === 'object' && 'status' in err) {
			throw err;
		}
		throw error(500, { message: err instanceof Error ? err.message : 'Proxy request failed' });
	}
};

export const POST: RequestHandler = async ({ params, url, request, fetch }) => {
	const path = params.path || '';
	const queryString = url.search;
	const targetUrl = `${RETRIEVAL_API}/api/v1/${path}${queryString}`;

	try {
		const body = await request.json();
		const response = await fetch(targetUrl, {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json'
			},
			body: JSON.stringify(body)
		});

		if (!response.ok) {
			const errorData = await response.json().catch(() => ({ detail: 'Request failed' }));
			throw error(response.status, { message: errorData.detail || 'Request failed' });
		}

		const data = await response.json();
		return json(data);
	} catch (err) {
		console.error('Retrieval proxy error:', err);
		if (err && typeof err === 'object' && 'status' in err) {
			throw err;
		}
		throw error(500, { message: err instanceof Error ? err.message : 'Proxy request failed' });
	}
};
