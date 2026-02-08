import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { S3Client, DeleteObjectCommand, PutObjectCommand } from '@aws-sdk/client-s3';
import {
	MINIO_ENDPOINT,
	MINIO_ACCESS_KEY,
	MINIO_SECRET_KEY,
	MINIO_BUCKET,
	INGESTION_URL,
	DEMO_TENANT_ID
} from '$env/static/private';
import { VIDEO_ENABLED } from '$lib/config';

const s3Client = new S3Client({
	endpoint: MINIO_ENDPOINT || 'http://localhost:9000',
	region: 'us-east-1',
	credentials: {
		accessKeyId: MINIO_ACCESS_KEY || 'minioadmin',
		secretAccessKey: MINIO_SECRET_KEY || 'minioadmin'
	},
	forcePathStyle: true
});

const BUCKET = MINIO_BUCKET || 'rag-documents';
const INGESTION_API = INGESTION_URL || 'http://localhost:8001';
const TENANT_ID = DEMO_TENANT_ID || '00000000-0000-0000-0000-000000000001';

const ALLOWED_EXTENSIONS = ['.mp4', '.mov', '.avi', '.mkv', '.webm'];
const ALLOWED_MIME_TYPES = [
	'video/mp4',
	'video/quicktime',
	'video/x-msvideo',
	'video/x-matroska',
	'video/webm'
];
const MAX_FILE_SIZE = 5 * 1024 * 1024 * 1024; // 5GB
const BACKEND_UNAVAILABLE_STATUSES = new Set([404, 405, 501]);

async function cleanupUploadedVideoObject(s3Key: string): Promise<void> {
	try {
		await s3Client.send(
			new DeleteObjectCommand({
				Bucket: BUCKET,
				Key: s3Key
			})
		);
	} catch (cleanupError) {
		// Best-effort cleanup to avoid orphaned uploads.
		console.warn('Failed to cleanup uploaded video object:', cleanupError);
	}
}

export const POST: RequestHandler = async ({ request }) => {
	if (!VIDEO_ENABLED) {
		throw error(503, {
			message: 'Video features are not enabled. Set PUBLIC_VIDEO_ENABLED=true to enable.'
		});
	}

	let uploadedS3Key: string | null = null;

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
		if (file.type && !ALLOWED_MIME_TYPES.includes(file.type)) {
			throw error(400, {
				message: `Invalid MIME type. Allowed: ${ALLOWED_MIME_TYPES.join(', ')}`
			});
		}

		// Validate file size
		if (file.size > MAX_FILE_SIZE) {
			throw error(400, {
				message: `File too large. Maximum size: 5GB`
			});
		}

		// Generate unique filename
		const timestamp = Date.now();
		const sanitizedName = file.name.replace(/[^a-zA-Z0-9.-]/g, '_');
		const s3Key = `videos/${TENANT_ID}/originals/${timestamp}-${sanitizedName}`;

		// Upload to MinIO
		const fileBuffer = Buffer.from(await file.arrayBuffer());

		await s3Client.send(
			new PutObjectCommand({
				Bucket: BUCKET,
				Key: s3Key,
				Body: fileBuffer,
				ContentType: file.type || 'video/mp4',
				Metadata: {
					'original-filename': file.name,
					'uploaded-at': new Date().toISOString()
				}
			})
		);
		uploadedS3Key = s3Key;

		// Trigger video processing via the ingestion API
		const ingestionResponse = await fetch(
			`${INGESTION_API}/api/v1/videos/upload?tenant_id=${TENANT_ID}`,
			{
				method: 'POST',
				headers: {
					'Content-Type': 'application/json'
				},
				body: JSON.stringify({
					filename: file.name,
					storage_path: s3Key,
					title: file.name.replace(/\.[^/.]+$/, ''), // Remove extension for title
					visibility: 'private',
					processing_options: {
						whisper_model: 'base',
						enable_vision: true,
						enable_ocr: true
					}
				})
			}
		);

		if (!ingestionResponse.ok) {
			const errorData = await ingestionResponse.json().catch(() => ({}));
			if (uploadedS3Key) {
				await cleanupUploadedVideoObject(uploadedS3Key);
				uploadedS3Key = null;
			}

			if (BACKEND_UNAVAILABLE_STATUSES.has(ingestionResponse.status)) {
				throw error(503, {
					message:
						'Video backend routes are unavailable in this environment. Disable video features or deploy the ingestion video API.'
				});
			}

			throw error(500, { message: errorData.detail || 'Failed to start video processing' });
		}

		const ingestionResult = await ingestionResponse.json();

		return json({
			success: true,
			video_id: ingestionResult.video_id,
			job_id: ingestionResult.job_id,
			filename: file.name,
			storage_path: s3Key,
			status: 'processing'
		});
	} catch (err) {
		console.error('Video upload error:', err);

		if (err && typeof err === 'object' && 'status' in err) {
			throw err;
		}

		if (uploadedS3Key) {
			await cleanupUploadedVideoObject(uploadedS3Key);
		}

		throw error(500, {
			message: err instanceof Error ? err.message : 'Upload failed'
		});
	}
};
