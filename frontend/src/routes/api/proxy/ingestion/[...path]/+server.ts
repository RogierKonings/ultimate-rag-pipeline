import { createProxyHandlers } from '$lib/server/proxy';
import { INGESTION_URL } from '$env/static/private';

/**
 * Extract a clean filename from a source_uri like:
 * "uploads/{tenant_id}/{timestamp}-{filename}" -> "filename"
 */
function extractFilename(sourceUri: string): string | null {
	const lastSegment = sourceUri.split('/').pop();
	if (!lastSegment) return null;
	const dashIndex = lastSegment.indexOf('-');
	if (dashIndex > 0 && /^\d+$/.test(lastSegment.substring(0, dashIndex))) {
		return lastSegment.substring(dashIndex + 1);
	}
	return lastSegment;
}

/**
 * Post-process ingestion responses to normalise document filenames.
 * When the upstream returns a `documents` array, each item's `source_id`
 * is parsed to produce a human-readable `filename` and the `title` is
 * cleared if it duplicates `source_id`.
 */
function normaliseDocumentFilenames(data: unknown): unknown {
	if (
		data !== null &&
		typeof data === 'object' &&
		'documents' in data &&
		Array.isArray((data as Record<string, unknown>).documents)
	) {
		const docs = (data as Record<string, unknown>).documents as Record<string, unknown>[];
		for (const doc of docs) {
			if (doc.source_id && typeof doc.source_id === 'string') {
				const cleanName = extractFilename(doc.source_id);
				if (cleanName) {
					doc.filename = cleanName;
				}
				if (doc.title === doc.source_id) {
					doc.title = null;
				}
			}
		}
	}
	return data;
}

const config = {
	baseUrl: INGESTION_URL || 'http://localhost:8001',
	pathPrefix: '',
	serviceName: 'ingestion',
	transformResponse: normaliseDocumentFilenames
};

export const { GET, POST, DELETE } = createProxyHandlers(config);
