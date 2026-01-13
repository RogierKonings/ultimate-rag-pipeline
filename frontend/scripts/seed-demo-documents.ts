/**
 * Seed script to load sample documents into the RAG pipeline.
 *
 * This script:
 * 1. Uploads sample documents to MinIO
 * 2. Triggers ingestion for each document
 * 3. Waits for processing to complete
 *
 * Usage: npx tsx scripts/seed-demo-documents.ts
 */

import { S3Client, PutObjectCommand, HeadBucketCommand, CreateBucketCommand } from '@aws-sdk/client-s3';
import * as fs from 'fs';
import * as path from 'path';

// Configuration
const MINIO_ENDPOINT = process.env.MINIO_ENDPOINT || 'http://localhost:9000';
const MINIO_ACCESS_KEY = process.env.MINIO_ACCESS_KEY || 'minioadmin';
const MINIO_SECRET_KEY = process.env.MINIO_SECRET_KEY || 'minioadmin';
const MINIO_BUCKET = process.env.MINIO_BUCKET || 'rag-documents';
const INGESTION_URL = process.env.INGESTION_URL || 'http://localhost:8001';
const TENANT_ID = process.env.DEMO_TENANT_ID || '00000000-0000-0000-0000-000000000001';

// Sample documents
const SAMPLE_DOCUMENTS = [
	{
		filename: 'gdpr-article-17.txt',
		title: 'GDPR Article 17 - Right to Erasure',
		description: 'EU GDPR requirements for data deletion and the right to be forgotten'
	},
	{
		filename: 'sample-nda.txt',
		title: 'Mutual Non-Disclosure Agreement',
		description: 'Template NDA for business partnerships'
	},
	{
		filename: 'data-processing-agreement.txt',
		title: 'Data Processing Agreement',
		description: 'GDPR-compliant DPA template for data processors'
	},
	{
		filename: 'employee-compliance-policy.txt',
		title: 'Employee Compliance and Ethics Policy',
		description: 'Internal compliance policy for employees'
	},
	{
		filename: 'sox-compliance-checklist.txt',
		title: 'SOX Compliance Checklist',
		description: 'Sarbanes-Oxley compliance requirements checklist'
	}
];

// Initialize S3 client for MinIO
const s3Client = new S3Client({
	endpoint: MINIO_ENDPOINT,
	region: 'us-east-1',
	credentials: {
		accessKeyId: MINIO_ACCESS_KEY,
		secretAccessKey: MINIO_SECRET_KEY
	},
	forcePathStyle: true
});

async function ensureBucketExists() {
	try {
		await s3Client.send(new HeadBucketCommand({ Bucket: MINIO_BUCKET }));
		console.log(`✓ Bucket '${MINIO_BUCKET}' exists`);
	} catch (error: any) {
		if (error.name === 'NotFound' || error.$metadata?.httpStatusCode === 404) {
			console.log(`Creating bucket '${MINIO_BUCKET}'...`);
			await s3Client.send(new CreateBucketCommand({ Bucket: MINIO_BUCKET }));
			console.log(`✓ Bucket '${MINIO_BUCKET}' created`);
		} else {
			throw error;
		}
	}
}

async function uploadToMinio(filename: string, content: Buffer): Promise<string> {
	const key = `sample/${filename}`;

	await s3Client.send(new PutObjectCommand({
		Bucket: MINIO_BUCKET,
		Key: key,
		Body: content,
		ContentType: 'text/plain',
		Metadata: {
			'demo-sample': 'true'
		}
	}));

	return key;
}

async function triggerIngestion(s3Key: string, title: string): Promise<string> {
	const response = await fetch(`${INGESTION_URL}/api/v1/ingest`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json'
		},
		body: JSON.stringify({
			source_type: 'filesystem',
			source_config: {
				path: s3Key,
				storage_type: 's3',
				s3_endpoint: MINIO_ENDPOINT.replace('localhost', 'minio'), // Use Docker service name
				s3_bucket: MINIO_BUCKET
			},
			processing: {
				chunking_strategy: 'recursive',
				chunk_size: 512,
				chunk_overlap: 50
			},
			acl: {
				tenant_id: TENANT_ID,
				visibility: 'public'
			}
		})
	});

	if (!response.ok) {
		const error = await response.text();
		throw new Error(`Ingestion failed: ${error}`);
	}

	const result = await response.json();
	return result.job_id;
}

async function waitForJob(jobId: string, timeout = 300000): Promise<void> {
	const startTime = Date.now();

	while (Date.now() - startTime < timeout) {
		const response = await fetch(`${INGESTION_URL}/api/v1/ingest/${jobId}`);

		if (!response.ok) {
			throw new Error(`Failed to get job status: ${response.statusText}`);
		}

		const status = await response.json();

		if (status.status === 'success') {
			return;
		}

		if (status.status === 'failure') {
			throw new Error(`Job failed: ${status.error_message}`);
		}

		// Wait 2 seconds before checking again
		await new Promise(resolve => setTimeout(resolve, 2000));
	}

	throw new Error('Job timed out');
}

async function main() {
	console.log('🚀 Starting demo document seeding...\n');

	try {
		// Ensure bucket exists
		await ensureBucketExists();
		console.log();

		// Process each sample document
		for (const doc of SAMPLE_DOCUMENTS) {
			console.log(`📄 Processing: ${doc.title}`);

			// Read file
			const filePath = path.join(__dirname, '..', 'static', 'samples', doc.filename);

			if (!fs.existsSync(filePath)) {
				console.log(`   ⚠️  File not found: ${filePath}`);
				continue;
			}

			const content = fs.readFileSync(filePath);
			console.log(`   ✓ Read file (${content.length} bytes)`);

			// Upload to MinIO
			const s3Key = await uploadToMinio(doc.filename, content);
			console.log(`   ✓ Uploaded to MinIO: ${s3Key}`);

			// Trigger ingestion
			try {
				const jobId = await triggerIngestion(s3Key, doc.title);
				console.log(`   ✓ Ingestion started: ${jobId}`);

				// Wait for completion
				console.log(`   ⏳ Waiting for processing...`);
				await waitForJob(jobId);
				console.log(`   ✓ Processing complete`);
			} catch (error) {
				console.log(`   ⚠️  Ingestion skipped (service may not be running)`);
			}

			console.log();
		}

		console.log('✅ Demo seeding complete!\n');
		console.log('You can now access the demo at http://localhost:5173');

	} catch (error) {
		console.error('❌ Seeding failed:', error);
		process.exit(1);
	}
}

main();
