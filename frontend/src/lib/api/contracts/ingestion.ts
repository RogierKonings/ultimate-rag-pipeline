export type IngestionJobStatus =
	| 'pending'
	| 'started'
	| 'progress'
	| 'success'
	| 'failure'
	| 'revoked';

export interface IngestResponse {
	job_id: string;
	status: IngestionJobStatus;
	message: string;
	created_at: string;
}

export interface JobProgress {
	current: number;
	total: number;
	stage: string;
	percentage: number;
}

export interface JobStatusResponse {
	job_id: string;
	status: IngestionJobStatus;
	progress: JobProgress | null;
	documents_processed: number;
	chunks_created: number;
	started_at: string | null;
	completed_at: string | null;
	duration_seconds: number | null;
	error_message: string | null;
	errors: string[];
}

export interface UploadRequest {
	file: File;
	title?: string;
}

export interface UploadResponse {
	document_id: string;
	job_id: string;
	filename: string;
	status: 'queued';
}

export interface QueuedFile {
	id: string;
	file: File;
	status: 'valid' | 'invalid' | 'rename_pending';
	error?: string;
	/** When status is 'rename_pending', holds the suggested new filename */
	suggestedName?: string;
	/** When a file has been renamed by the user, holds the custom display name */
	customName?: string;
}
