import type { ApiError } from './types';

export class ApiClient {
	private baseUrl: string;

	constructor(baseUrl: string) {
		this.baseUrl = baseUrl.replace(/\/$/, '');
	}

	async fetch<T>(path: string, options: RequestInit = {}): Promise<T> {
		const url = `${this.baseUrl}${path}`;

		const response = await fetch(url, {
			...options,
			headers: {
				'Content-Type': 'application/json',
				...options.headers
			}
		});

		if (!response.ok) {
			let error: ApiError;
			try {
				error = await response.json();
			} catch {
				error = {
					error: 'request_failed',
					message: `Request failed with status ${response.status}`
				};
			}
			throw new ApiClientError(error, response.status);
		}

		return response.json();
	}

	async get<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
		let url = path;
		if (params) {
			const searchParams = new URLSearchParams();
			for (const [key, value] of Object.entries(params)) {
				if (value !== undefined) {
					searchParams.set(key, String(value));
				}
			}
			const queryString = searchParams.toString();
			if (queryString) {
				url = `${path}?${queryString}`;
			}
		}
		return this.fetch<T>(url, { method: 'GET' });
	}

	async post<T>(path: string, body?: unknown): Promise<T> {
		return this.fetch<T>(path, {
			method: 'POST',
			body: body ? JSON.stringify(body) : undefined
		});
	}

	async delete<T>(path: string): Promise<T> {
		return this.fetch<T>(path, { method: 'DELETE' });
	}
}

export class ApiClientError extends Error {
	public readonly error: ApiError;
	public readonly status: number;

	constructor(error: ApiError, status: number) {
		super(error.message);
		this.name = 'ApiClientError';
		this.error = error;
		this.status = status;
	}
}

// Helper to check if error is an ApiClientError
export function isApiError(error: unknown): error is ApiClientError {
	return error instanceof ApiClientError;
}
