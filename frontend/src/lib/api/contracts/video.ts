export type VideoStatus = 'uploaded' | 'processing' | 'ready' | 'failed';

export type VideoProcessingStage =
	| 'audio_extraction'
	| 'transcription'
	| 'scene_detection'
	| 'visual_analysis'
	| 'ocr'
	| 'fusion'
	| 'embedding';

export interface Video {
	video_id: string;
	tenant_id: string;
	filename: string;
	title: string | null;
	description: string | null;
	duration_ms: number | null;
	duration_seconds: number | null;
	width: number | null;
	height: number | null;
	fps: number | null;
	codec: string | null;
	file_size_bytes: number | null;
	status: VideoStatus;
	processing_stage: VideoProcessingStage | null;
	processing_progress: number;
	error_message: string | null;
	detected_language: string | null;
	keyframe_count: number;
	chunk_count: number;
	visibility: 'public' | 'private' | 'group';
	allowed_groups: string[];
	tags: string[];
	thumbnail_url: string | null;
	stream_url: string | null;
	storage_path: string | null;
	created_at: string;
	uploaded_at: string | null;
	processed_at: string | null;
	updated_at: string | null;
}

export interface VideoListResponse {
	videos: Video[];
	pagination: {
		page: number;
		page_size: number;
		total: number;
		total_pages: number;
	};
}

export interface VideoUploadResponse {
	video_id: string;
	job_id: string;
	filename: string;
	status: VideoStatus;
	storage_path: string;
	message: string;
}

export interface VideoStatusResponse {
	video_id: string;
	status: VideoStatus;
	processing_stage: VideoProcessingStage | null;
	processing_progress: number;
	error_message: string | null;
	duration_seconds: number | null;
	keyframe_count: number;
	chunk_count: number;
	created_at: string;
	processed_at: string | null;
}

export interface VideoDeleteResult {
	video_id: string;
	deleted: boolean;
	message: string;
}

export interface VideoBatchDeleteResponse {
	deleted_count: number;
	failed_count: number;
	results: VideoDeleteResult[];
}

export interface VideoMatch {
	chunk_id: string;
	chunk_index: number;
	start_time_ms: number;
	end_time_ms: number;
	start_seconds: number;
	end_seconds: number;
	duration_seconds: number;
	fused_score: number;
	semantic_score: number | null;
	keyword_score: number | null;
	rerank_score: number | null;
	fused_text_preview: string;
	transcript_text: string | null;
	scene_description: string | null;
	keyframe_url: string | null;
	clip_url: string | null;
	source_modalities: string[];
}

export interface VideoSearchResult {
	video_id: string;
	tenant_id: string;
	title: string;
	thumbnail_url: string | null;
	duration_ms: number | null;
	max_score: number;
	avg_score: number;
	match_count: number;
	matches: VideoMatch[];
}

export interface VideoSearchResponse {
	query: string;
	mode: 'hybrid' | 'semantic' | 'keyword';
	videos: VideoSearchResult[];
	total_videos: number;
	total_matches: number;
	metrics: {
		total_ms: number;
		embedding_ms?: number;
		semantic_ms?: number;
		keyword_ms?: number;
		fusion_ms?: number;
		rerank_ms?: number;
	};
}

export interface VideoSearchRequest {
	query: string;
	mode?: 'hybrid' | 'semantic' | 'keyword';
	top_k?: number;
	video_id?: string;
	semantic_weight?: number;
	keyword_weight?: number;
	rerank?: boolean;
	max_matches_per_video?: number;
}

export interface QueuedVideoFile {
	id: string;
	file: File;
	status: 'valid' | 'invalid';
	error?: string;
}
