import { ApiClient, isApiError } from './client';
import type { Document, DocumentListResponse, DocumentDeleteResponse, BatchDeleteResponse, JobStatusResponse } from './types';
import { PUBLIC_DEMO_TENANT_ID } from '$env/static/public';

// Lazy client initialization to avoid SSR fetch issues
let _client: ApiClient | null = null;
function getClient(): ApiClient {
	if (!_client) {
		_client = new ApiClient('/api/proxy/ingestion');
	}
	return _client;
}

const TENANT_ID = PUBLIC_DEMO_TENANT_ID || '00000000-0000-0000-0000-000000000001';

/**
 * Determine whether an API error is transient (retryable) or fatal.
 * 5xx errors and network failures are transient; 4xx errors are fatal.
 */
export function isTransientError(error: unknown): boolean {
	if (isApiError(error)) {
		return error.status >= 500;
	}
	// Non-ApiClientError (e.g., network failure) is assumed transient
	return true;
}

/**
 * Convert a polling error into a user-friendly message.
 */
export function getPollingErrorMessage(error: unknown): string {
	if (isApiError(error)) {
		switch (error.status) {
			case 404:
				return 'Job not found. The server may have restarted. Please try uploading again.';
			case 502:
			case 503:
			case 504:
				return 'The processing service is temporarily unavailable. Please try again later.';
			default:
				return error.error?.message || `Processing failed (error ${error.status})`;
		}
	}
	if (error instanceof Error) {
		return error.message;
	}
	return 'Processing failed unexpectedly';
}

export type PollingErrorKind = 'fatal' | 'transient_exhausted';

export class PollingError extends Error {
	public readonly kind: PollingErrorKind;
	public readonly cause: unknown;

	constructor(message: string, kind: PollingErrorKind, cause?: unknown) {
		super(message);
		this.name = 'PollingError';
		this.kind = kind;
		this.cause = cause;
	}
}

/**
 * List all documents for the demo tenant
 */
export async function listDocuments(
	page = 1,
	pageSize = 50,
	filters?: {
		source_type?: string;
		status?: string;
		search?: string;
	}
): Promise<DocumentListResponse> {
	return getClient().get<DocumentListResponse>('/api/v1/documents', {
		tenant_id: TENANT_ID,
		page,
		page_size: pageSize,
		...filters
	});
}

/**
 * Get a single document by ID
 */
export async function getDocument(documentId: string): Promise<Document> {
	return getClient().get<Document>(`/api/v1/documents/${documentId}`);
}

/**
 * Get the status of an ingestion job
 */
export async function getJobStatus(jobId: string): Promise<JobStatusResponse> {
	return getClient().get<JobStatusResponse>(`/api/v1/ingest/${jobId}`);
}

/**
 * Delete a document and all its chunks
 */
export async function deleteDocument(documentId: string): Promise<DocumentDeleteResponse> {
	return getClient().delete<DocumentDeleteResponse>(`/api/v1/documents/${documentId}`, {
		tenant_id: TENANT_ID
	});
}

/**
 * Delete multiple documents at once
 */
export async function batchDeleteDocuments(documentIds: string[]): Promise<BatchDeleteResponse> {
	return getClient().post<BatchDeleteResponse>(`/api/v1/documents/batch-delete?tenant_id=${TENANT_ID}`, {
		document_ids: documentIds
	});
}

/**
 * Poll job status until complete, with retry logic for transient errors.
 *
 * Transient errors (5xx, network failures) are retried up to maxConsecutiveErrors
 * times before giving up. Fatal errors (4xx like 404) fail immediately.
 */
export async function pollJobStatus(
	jobId: string,
	onProgress?: (status: JobStatusResponse) => void,
	intervalMs = 2000,
	maxAttempts = 300, // 10 minutes max
	maxConsecutiveErrors = 5
): Promise<JobStatusResponse> {
	let attempts = 0;
	let consecutiveErrors = 0;

	return new Promise((resolve, reject) => {
		const poll = async () => {
			try {
				const status = await getJobStatus(jobId);
				consecutiveErrors = 0;
				onProgress?.(status);

				if (status.status === 'success') {
					resolve(status);
					return;
				}

				if (status.status === 'failure' || status.status === 'revoked') {
					reject(new Error(status.error_message || 'Job failed'));
					return;
				}

				attempts++;
				if (attempts >= maxAttempts) {
					reject(new Error('Processing is taking longer than expected. The document may still be processing in the background.'));
					return;
				}

				setTimeout(poll, intervalMs);
			} catch (error) {
				if (!isTransientError(error)) {
					reject(new PollingError(getPollingErrorMessage(error), 'fatal', error));
					return;
				}

				consecutiveErrors++;
				if (consecutiveErrors >= maxConsecutiveErrors) {
					reject(new PollingError(
						'The processing service appears to be unavailable. Please try again later.',
						'transient_exhausted',
						error
					));
					return;
				}

				attempts++;
				if (attempts >= maxAttempts) {
					reject(new Error('Processing is taking longer than expected. The document may still be processing in the background.'));
					return;
				}

				setTimeout(poll, intervalMs);
			}
		};

		poll();
	});
}
