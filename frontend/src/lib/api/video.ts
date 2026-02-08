import { ApiClient } from './client';
import type {
	Video,
	VideoBatchDeleteResponse,
	VideoListResponse,
	VideoUploadResponse,
	VideoStatusResponse,
	VideoSearchRequest,
	VideoSearchResponse
} from './types';
import { PUBLIC_DEMO_TENANT_ID } from '$env/static/public';
import { VIDEO_ENABLED } from '$lib/config';

/**
 * Error thrown when video API functions are called while the feature is disabled.
 */
export class VideoFeatureDisabledError extends Error {
	constructor() {
		super('Video features are not enabled. Set PUBLIC_VIDEO_ENABLED=true to enable.');
		this.name = 'VideoFeatureDisabledError';
	}
}

/**
 * Guard that throws if video features are disabled.
 * All video API functions call this before making network requests.
 */
function assertVideoEnabled(): void {
	if (!VIDEO_ENABLED) {
		throw new VideoFeatureDisabledError();
	}
}

// Lazy client initialization to avoid SSR fetch issues
let _ingestionClient: ApiClient | null = null;
let _retrievalClient: ApiClient | null = null;

function getIngestionClient(): ApiClient {
	if (!_ingestionClient) {
		_ingestionClient = new ApiClient('/api/proxy/ingestion');
	}
	return _ingestionClient;
}

function getRetrievalClient(): ApiClient {
	if (!_retrievalClient) {
		_retrievalClient = new ApiClient('/api/proxy/retrieval');
	}
	return _retrievalClient;
}

const TENANT_ID = PUBLIC_DEMO_TENANT_ID || '00000000-0000-0000-0000-000000000001';

/**
 * List all videos for the demo tenant.
 * Throws VideoFeatureDisabledError when VIDEO_ENABLED is false.
 */
export async function listVideos(
	page = 1,
	pageSize = 50,
	filters?: {
		status?: string;
		search?: string;
	}
): Promise<VideoListResponse> {
	assertVideoEnabled();
	return getIngestionClient().get<VideoListResponse>('/api/v1/videos', {
		tenant_id: TENANT_ID,
		page,
		page_size: pageSize,
		...filters
	});
}

/**
 * Get a single video by ID.
 * Throws VideoFeatureDisabledError when VIDEO_ENABLED is false.
 */
export async function getVideo(videoId: string): Promise<Video> {
	assertVideoEnabled();
	return getIngestionClient().get<Video>(`/api/v1/videos/${videoId}`, {
		tenant_id: TENANT_ID
	});
}

/**
 * Get video processing status.
 * Throws VideoFeatureDisabledError when VIDEO_ENABLED is false.
 */
export async function getVideoStatus(videoId: string): Promise<VideoStatusResponse> {
	assertVideoEnabled();
	return getIngestionClient().get<VideoStatusResponse>(`/api/v1/videos/${videoId}`, {
		tenant_id: TENANT_ID
	});
}

/**
 * Delete a video and all its data.
 * Throws VideoFeatureDisabledError when VIDEO_ENABLED is false.
 */
export async function deleteVideo(videoId: string): Promise<{ deleted: boolean; message: string }> {
	assertVideoEnabled();
	return getIngestionClient().delete(`/api/v1/videos/${videoId}`, {
		tenant_id: TENANT_ID
	});
}

/**
 * Delete multiple videos at once.
 * Throws VideoFeatureDisabledError when VIDEO_ENABLED is false.
 */
export async function batchDeleteVideos(videoIds: string[]): Promise<VideoBatchDeleteResponse> {
	assertVideoEnabled();
	return getIngestionClient().post<VideoBatchDeleteResponse>(
		`/api/v1/videos/batch-delete?tenant_id=${TENANT_ID}`,
		{
			video_ids: videoIds
		}
	);
}

/**
 * Search videos with hybrid search.
 * Throws VideoFeatureDisabledError when VIDEO_ENABLED is false.
 */
export async function searchVideos(request: VideoSearchRequest): Promise<VideoSearchResponse> {
	assertVideoEnabled();
	return getRetrievalClient().post<VideoSearchResponse>(`/retrieve/video?tenant_id=${TENANT_ID}`, {
		query: request.query,
		mode: request.mode || 'hybrid',
		top_k: request.top_k || 10,
		video_id: request.video_id,
		semantic_weight: request.semantic_weight ?? 0.7,
		keyword_weight: request.keyword_weight ?? 0.3,
		rerank: request.rerank ?? true,
		max_matches_per_video: request.max_matches_per_video || 10
	});
}

/**
 * Get clip URL for a video segment.
 * Returns empty string when VIDEO_ENABLED is false.
 */
export function getClipUrl(videoId: string, startMs: number, endMs: number): string {
	if (!VIDEO_ENABLED) return '';
	return `/api/proxy/retrieval/videos/${videoId}/clip?start=${startMs}&end=${endMs}&tenant_id=${TENANT_ID}`;
}

/**
 * Get stream URL for full video.
 * Returns empty string when VIDEO_ENABLED is false.
 */
export function getStreamUrl(videoId: string): string {
	if (!VIDEO_ENABLED) return '';
	return `/api/proxy/retrieval/videos/${videoId}/stream?tenant_id=${TENANT_ID}`;
}

/**
 * Poll video status until complete or failed.
 * Throws VideoFeatureDisabledError when VIDEO_ENABLED is false.
 */
export async function pollVideoStatus(
	videoId: string,
	onProgress?: (status: VideoStatusResponse) => void,
	intervalMs = 3000,
	maxAttempts = 600 // 30 minutes max
): Promise<VideoStatusResponse> {
	assertVideoEnabled();
	let attempts = 0;

	return new Promise((resolve, reject) => {
		const poll = async () => {
			try {
				const status = await getVideoStatus(videoId);
				onProgress?.(status);

				if (status.status === 'ready') {
					resolve(status);
					return;
				}

				if (status.status === 'failed') {
					reject(new Error(status.error_message || 'Video processing failed'));
					return;
				}

				attempts++;
				if (attempts >= maxAttempts) {
					reject(new Error('Video processing timed out'));
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
