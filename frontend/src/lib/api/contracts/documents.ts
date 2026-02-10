export interface Document {
	document_id: string;
	source_id: string;
	source_type: 'filesystem' | 'database' | 'web' | 'api';
	filename: string;
	mime_type: string;
	title: string | null;
	author: string | null;
	chunk_count: number;
	total_tokens: number;
	tenant_id: string;
	visibility: 'public' | 'private' | 'group';
	created_at: string;
	updated_at: string;
	indexed_at: string | null;
	status: 'pending' | 'indexed' | 'failed';
}

export interface DocumentListResponse {
	documents: Document[];
	total: number;
	page: number;
	page_size: number;
	pages: number;
}

export interface DocumentDeleteResponse {
	document_id: string;
	deleted: boolean;
	chunks_deleted: number;
	message: string;
}

export interface BatchDeleteResponse {
	deleted_count: number;
	failed_count: number;
	results: DocumentDeleteResponse[];
}
