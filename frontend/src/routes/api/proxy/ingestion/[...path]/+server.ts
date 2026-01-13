import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { INGESTION_URL } from '$env/static/private';

const INGESTION_API = INGESTION_URL || 'http://localhost:8001';

export const GET: RequestHandler = async ({ params, url }) => {
	const path = params.path;
	const queryString = url.search;
	const targetUrl = `${INGESTION_API}/${path}${queryString}`;

	try {
		const response = await fetch(targetUrl, {
			method: 'GET',
			headers: {
				'Content-Type': 'application/json'
			}
		});

		if (!response.ok) {
			const errorData = await response.json().catch(() => ({ detail: 'Request failed' }));
			throw error(response.status, errorData);
		}

		const data = await response.json();
		return json(data);
	} catch (err) {
		if (err && typeof err === 'object' && 'status' in err) {
			throw err;
		}
		console.error('Proxy error:', err);
		throw error(502, { message: 'Failed to reach ingestion service' });
	}
};

export const POST: RequestHandler = async ({ params, url, request }) => {
	const path = params.path;
	const queryString = url.search;
	const targetUrl = `${INGESTION_API}/${path}${queryString}`;

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
			throw error(response.status, errorData);
		}

		const data = await response.json();
		return json(data);
	} catch (err) {
		if (err && typeof err === 'object' && 'status' in err) {
			throw err;
		}
		console.error('Proxy error:', err);
		throw error(502, { message: 'Failed to reach ingestion service' });
	}
};

export const DELETE: RequestHandler = async ({ params, url }) => {
	const path = params.path;
	const queryString = url.search;
	const targetUrl = `${INGESTION_API}/${path}${queryString}`;

	try {
		const response = await fetch(targetUrl, {
			method: 'DELETE',
			headers: {
				'Content-Type': 'application/json'
			}
		});

		if (!response.ok) {
			const errorData = await response.json().catch(() => ({ detail: 'Request failed' }));
			throw error(response.status, errorData);
		}

		const data = await response.json();
		return json(data);
	} catch (err) {
		if (err && typeof err === 'object' && 'status' in err) {
			throw err;
		}
		console.error('Proxy error:', err);
		throw error(502, { message: 'Failed to reach ingestion service' });
	}
};
