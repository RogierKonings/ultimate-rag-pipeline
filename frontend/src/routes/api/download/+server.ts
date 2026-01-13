import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { S3Client, GetObjectCommand } from '@aws-sdk/client-s3';
import { getSignedUrl } from '@aws-sdk/s3-request-presigner';
import {
	MINIO_ENDPOINT,
	MINIO_ACCESS_KEY,
	MINIO_SECRET_KEY,
	MINIO_BUCKET
} from '$env/static/private';

// Initialize S3 client for MinIO
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
const PRESIGNED_URL_EXPIRY = 3600; // 1 hour

export const GET: RequestHandler = async ({ url }) => {
	try {
		const s3Key = url.searchParams.get('key');

		if (!s3Key) {
			throw error(400, { message: 'Missing key parameter' });
		}

		// Validate the key looks like a valid document path
		if (!s3Key.startsWith('uploads/')) {
			throw error(400, { message: 'Invalid document key' });
		}

		// Generate presigned URL for download
		const command = new GetObjectCommand({
			Bucket: BUCKET,
			Key: s3Key
		});

		const presignedUrl = await getSignedUrl(s3Client, command, {
			expiresIn: PRESIGNED_URL_EXPIRY
		});

		return json({
			url: presignedUrl,
			expiresIn: PRESIGNED_URL_EXPIRY
		});
	} catch (err) {
		console.error('Download URL generation error:', err);

		if (err && typeof err === 'object' && 'status' in err) {
			throw err;
		}

		throw error(500, {
			message: err instanceof Error ? err.message : 'Failed to generate download URL'
		});
	}
};
