import { ApiClient } from './client';
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
 * Poll job status until complete
 */
export async function pollJobStatus(
	jobId: string,
	onProgress?: (status: JobStatusResponse) => void,
	intervalMs = 2000,
	maxAttempts = 300 // 10 minutes max
): Promise<JobStatusResponse> {
	let attempts = 0;

	return new Promise((resolve, reject) => {
		const poll = async () => {
			try {
				const status = await getJobStatus(jobId);
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
					reject(new Error('Job polling timed out'));
					return;
				}

				setTimeout(poll, intervalMs);
			} catch (error) {
				reject(error);
			}
		};

		poll();
	});
}
