import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { S3Client, PutObjectCommand } from '@aws-sdk/client-s3';
import {
	MINIO_ENDPOINT,
	MINIO_ACCESS_KEY,
	MINIO_SECRET_KEY,
	MINIO_BUCKET,
	INGESTION_URL,
	DEMO_TENANT_ID
} from '$env/static/private';

// Initialize S3 client for MinIO
const s3Client = new S3Client({
	endpoint: MINIO_ENDPOINT || 'http://localhost:9000',
	region: 'us-east-1', // Required but ignored by MinIO
	credentials: {
		accessKeyId: MINIO_ACCESS_KEY || 'minioadmin',
		secretAccessKey: MINIO_SECRET_KEY || 'minioadmin'
	},
	forcePathStyle: true // Required for MinIO
});

const BUCKET = MINIO_BUCKET || 'rag-documents';
const INGESTION_API = INGESTION_URL || 'http://localhost:8001';
const TENANT_ID = DEMO_TENANT_ID || '00000000-0000-0000-0000-000000000001';

// Allowed file types
const ALLOWED_TYPES = [
	'application/pdf',
	'application/vnd.openxmlformats-officedocument.wordprocessingml.document', // .docx
	'text/plain',
	'text/markdown'
];

const ALLOWED_EXTENSIONS = ['.pdf', '.docx', '.txt', '.md'];

const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50MB

export const POST: RequestHandler = async ({ request }) => {
	try {
		const formData = await request.formData();
		const file = formData.get('file') as File | null;

		if (!file) {
			throw error(400, { message: 'No file provided' });
		}

		// Validate file type
		const extension = '.' + file.name.split('.').pop()?.toLowerCase();
		if (!ALLOWED_EXTENSIONS.includes(extension)) {
			throw error(400, {
				message: `Invalid file type. Allowed: ${ALLOWED_EXTENSIONS.join(', ')}`
			});
		}

		// Validate file size
		if (file.size > MAX_FILE_SIZE) {
			throw error(400, {
				message: `File too large. Maximum size: ${MAX_FILE_SIZE / 1024 / 1024}MB`
			});
		}

		// Generate unique filename
		const timestamp = Date.now();
		const sanitizedName = file.name.replace(/[^a-zA-Z0-9.-]/g, '_');
		const s3Key = `uploads/${TENANT_ID}/${timestamp}-${sanitizedName}`;

		// Upload to MinIO
		const fileBuffer = Buffer.from(await file.arrayBuffer());

		await s3Client.send(
			new PutObjectCommand({
				Bucket: BUCKET,
				Key: s3Key,
				Body: fileBuffer,
				ContentType: file.type || 'application/octet-stream',
				Metadata: {
					'original-filename': file.name,
					'uploaded-at': new Date().toISOString()
				}
			})
		);

		// Trigger ingestion via the ingestion API (include tenant_id for dev mode auth bypass)
		const ingestionResponse = await fetch(`${INGESTION_API}/ingest?tenant_id=${TENANT_ID}`, {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json'
			},
			body: JSON.stringify({
				source_type: 'filesystem',
				source_config: {
					path: s3Key,
					storage_type: 's3',
					s3_endpoint: 'http://minio:9000',
					s3_bucket: BUCKET,
					s3_access_key: MINIO_ACCESS_KEY || 'minioadmin',
					s3_secret_key: MINIO_SECRET_KEY || 'minioadmin123'
				},
				processing: {
					chunking_strategy: 'recursive',
					chunk_size: 512,
					chunk_overlap: 50
				},
				acl: {
					tenant_id: TENANT_ID,
					visibility: 'private'
				}
			})
		});

		if (!ingestionResponse.ok) {
			const errorData = await ingestionResponse.json().catch(() => ({}));
			throw error(500, {
				message: errorData.detail || 'Failed to start ingestion'
			});
		}

		const ingestionResult = await ingestionResponse.json();

		return json({
			success: true,
			document_id: ingestionResult.document_id,
			job_id: ingestionResult.job_id,
			filename: file.name,
			s3_key: s3Key,
			status: 'queued'
		});
	} catch (err) {
		console.error('Upload error:', err);

		if (err && typeof err === 'object' && 'status' in err) {
			throw err; // Re-throw SvelteKit errors
		}

		throw error(500, {
			message: err instanceof Error ? err.message : 'Upload failed'
		});
	}
};
