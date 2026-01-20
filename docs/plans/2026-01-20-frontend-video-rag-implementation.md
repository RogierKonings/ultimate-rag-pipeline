# Frontend Video RAG Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add video upload, search with timeline results, and clip playback to the frontend application.

**Architecture:** Tab-based navigation separates Documents and Videos views. Video search returns timeline-based results grouped by video. A persistent side panel shows the video player with clip context. Upload follows the existing drag-and-drop pattern.

**Tech Stack:** SvelteKit 2, Svelte 5 (runes), TypeScript, Tailwind CSS, lucide-svelte icons, bits-ui components

**Design Document:** [2026-01-20-frontend-video-rag-design.md](./2026-01-20-frontend-video-rag-design.md)

---

## Task 1: Add Video Types

**Files:**
- Modify: `frontend/src/lib/api/types.ts`

**Step 1: Add video types to types.ts**

Add these types after the existing document types:

```typescript
// Video types
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

// Video search types
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

// Queued video file for upload modal
export interface QueuedVideoFile {
	id: string;
	file: File;
	status: 'valid' | 'invalid';
	error?: string;
}
```

**Step 2: Verify types compile**

Run: `cd frontend && npm run check`
Expected: No type errors

**Step 3: Commit**

```bash
git add frontend/src/lib/api/types.ts
git commit -m "feat(frontend): add video API types"
```

---

## Task 2: Add Retrieval Proxy Route

**Files:**
- Create: `frontend/src/routes/api/proxy/retrieval/[...path]/+server.ts`

**Step 1: Create the proxy route**

```typescript
import { json, error } from '@sveltejs/kit';
import type { RequestHandler } from './$types';
import { RETRIEVAL_URL } from '$env/static/private';

const RETRIEVAL_API = RETRIEVAL_URL || 'http://localhost:8002';

export const GET: RequestHandler = async ({ params, url, fetch }) => {
	const path = params.path || '';
	const queryString = url.search;
	const targetUrl = `${RETRIEVAL_API}/api/v1/${path}${queryString}`;

	try {
		const response = await fetch(targetUrl, {
			method: 'GET',
			headers: {
				'Content-Type': 'application/json'
			}
		});

		if (!response.ok) {
			const errorData = await response.json().catch(() => ({ detail: 'Request failed' }));
			throw error(response.status, { message: errorData.detail || 'Request failed' });
		}

		const data = await response.json();
		return json(data);
	} catch (err) {
		console.error('Retrieval proxy error:', err);
		if (err && typeof err === 'object' && 'status' in err) {
			throw err;
		}
		throw error(500, { message: err instanceof Error ? err.message : 'Proxy request failed' });
	}
};

export const POST: RequestHandler = async ({ params, url, request, fetch }) => {
	const path = params.path || '';
	const queryString = url.search;
	const targetUrl = `${RETRIEVAL_API}/api/v1/${path}${queryString}`;

	try {
		const body = await request.json();
		const response = await fetch(targetUrl, {
			method: 'POST',
			headers: {
				'Content-Type': 'application/json'
			},
			body: JSON.stringify(body)
		});

		if (!response.ok) {
			const errorData = await response.json().catch(() => ({ detail: 'Request failed' }));
			throw error(response.status, { message: errorData.detail || 'Request failed' });
		}

		const data = await response.json();
		return json(data);
	} catch (err) {
		console.error('Retrieval proxy error:', err);
		if (err && typeof err === 'object' && 'status' in err) {
			throw err;
		}
		throw error(500, { message: err instanceof Error ? err.message : 'Proxy request failed' });
	}
};
```

**Step 2: Add RETRIEVAL_URL to environment**

Add to `frontend/.env.example`:

```bash
RETRIEVAL_URL=http://localhost:8002
```

**Step 3: Verify route loads**

Run: `cd frontend && npm run dev`
Test: `curl http://localhost:5173/api/proxy/retrieval/health`
Expected: Response from retrieval service (or connection refused if service not running)

**Step 4: Commit**

```bash
git add frontend/src/routes/api/proxy/retrieval/
git add frontend/.env.example
git commit -m "feat(frontend): add retrieval service proxy route"
```

---

## Task 3: Create Video API Client

**Files:**
- Create: `frontend/src/lib/api/video.ts`

**Step 1: Create the video API client**

```typescript
import { ApiClient } from './client';
import type {
	Video,
	VideoListResponse,
	VideoUploadResponse,
	VideoStatusResponse,
	VideoSearchRequest,
	VideoSearchResponse
} from './types';
import { PUBLIC_DEMO_TENANT_ID } from '$env/static/public';

// Ingestion service proxy for video management
const ingestionClient = new ApiClient('/api/proxy/ingestion');

// Retrieval service proxy for video search
const retrievalClient = new ApiClient('/api/proxy/retrieval');

const TENANT_ID = PUBLIC_DEMO_TENANT_ID || '00000000-0000-0000-0000-000000000001';

/**
 * List all videos for the demo tenant
 */
export async function listVideos(
	page = 1,
	pageSize = 50,
	filters?: {
		status?: string;
		search?: string;
	}
): Promise<VideoListResponse> {
	return ingestionClient.get<VideoListResponse>('/videos', {
		tenant_id: TENANT_ID,
		page,
		page_size: pageSize,
		...filters
	});
}

/**
 * Get a single video by ID
 */
export async function getVideo(videoId: string): Promise<Video> {
	return ingestionClient.get<Video>(`/videos/${videoId}`, {
		tenant_id: TENANT_ID
	});
}

/**
 * Get video processing status
 */
export async function getVideoStatus(videoId: string): Promise<VideoStatusResponse> {
	return ingestionClient.get<VideoStatusResponse>(`/videos/${videoId}/status`, {
		tenant_id: TENANT_ID
	});
}

/**
 * Delete a video and all its data
 */
export async function deleteVideo(videoId: string): Promise<{ deleted: boolean; message: string }> {
	return ingestionClient.delete(`/videos/${videoId}`, {
		tenant_id: TENANT_ID
	});
}

/**
 * Search videos with hybrid search
 */
export async function searchVideos(request: VideoSearchRequest): Promise<VideoSearchResponse> {
	return retrievalClient.post<VideoSearchResponse>(`/retrieve/video?tenant_id=${TENANT_ID}`, {
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
 * Get clip URL for a video segment
 */
export function getClipUrl(videoId: string, startMs: number, endMs: number): string {
	return `/api/proxy/retrieval/videos/${videoId}/clip?start=${startMs}&end=${endMs}&tenant_id=${TENANT_ID}`;
}

/**
 * Get stream URL for full video
 */
export function getStreamUrl(videoId: string): string {
	return `/api/proxy/retrieval/videos/${videoId}/stream?tenant_id=${TENANT_ID}`;
}

/**
 * Poll video status until complete or failed
 */
export async function pollVideoStatus(
	videoId: string,
	onProgress?: (status: VideoStatusResponse) => void,
	intervalMs = 3000,
	maxAttempts = 600 // 30 minutes max
): Promise<VideoStatusResponse> {
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
```

**Step 2: Verify imports work**

Run: `cd frontend && npm run check`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/lib/api/video.ts
git commit -m "feat(frontend): add video API client"
```

---

## Task 4: Create Videos Store

**Files:**
- Create: `frontend/src/lib/stores/videos.ts`

**Step 1: Create the videos store**

```typescript
import { writable, derived } from 'svelte/store';
import type { Video, VideoStatusResponse, QueuedVideoFile } from '$lib/api/types';
import { listVideos, pollVideoStatus } from '$lib/api/video';

interface VideosState {
	videos: Video[];
	loading: boolean;
	error: string | null;
	lastFetched: Date | null;
}

function createVideosStore() {
	const { subscribe, set, update } = writable<VideosState>({
		videos: [],
		loading: false,
		error: null,
		lastFetched: null
	});

	return {
		subscribe,

		async fetch() {
			update((state) => ({ ...state, loading: true, error: null }));

			try {
				const response = await listVideos();
				update((state) => ({
					...state,
					videos: response.videos,
					loading: false,
					lastFetched: new Date()
				}));
			} catch (error) {
				const message = error instanceof Error ? error.message : 'Failed to fetch videos';
				update((state) => ({
					...state,
					loading: false,
					error: message
				}));
			}
		},

		addVideo(video: Video) {
			update((state) => ({
				...state,
				videos: [video, ...state.videos]
			}));
		},

		updateVideo(videoId: string, updates: Partial<Video>) {
			update((state) => ({
				...state,
				videos: state.videos.map((v) =>
					v.video_id === videoId ? { ...v, ...updates } : v
				)
			}));
		},

		removeVideo(videoId: string) {
			update((state) => ({
				...state,
				videos: state.videos.filter((v) => v.video_id !== videoId)
			}));
		},

		reset() {
			set({
				videos: [],
				loading: false,
				error: null,
				lastFetched: null
			});
		}
	};
}

export const videos = createVideosStore();

// Video upload store
export interface VideoUploadJob {
	id: string;
	videoId: string;
	filename: string;
	status: 'pending' | 'uploading' | 'processing' | 'completed' | 'failed';
	processingStage: string | null;
	progress: number;
	error: string | null;
	startedAt: Date;
	completedAt: Date | null;
}

interface VideoUploadState {
	jobs: VideoUploadJob[];
	modalOpen: boolean;
	queuedFiles: QueuedVideoFile[];
	uploading: boolean;
	uploadError: string | null;
}

function createVideoUploadStore() {
	const { subscribe, set, update } = writable<VideoUploadState>({
		jobs: [],
		modalOpen: false,
		queuedFiles: [],
		uploading: false,
		uploadError: null
	});

	return {
		subscribe,

		openModal() {
			update((state) => ({
				...state,
				modalOpen: true,
				queuedFiles: [],
				uploadError: null
			}));
		},

		closeModal() {
			update((state) => ({
				...state,
				modalOpen: false,
				queuedFiles: [],
				uploadError: null
			}));
		},

		addFiles(files: QueuedVideoFile[]) {
			update((state) => {
				const existingNames = new Set(state.queuedFiles.map((f) => f.file.name));
				const newFiles = files.filter((f) => !existingNames.has(f.file.name));
				return {
					...state,
					queuedFiles: [...state.queuedFiles, ...newFiles],
					uploadError: null
				};
			});
		},

		removeQueuedFile(id: string) {
			update((state) => ({
				...state,
				queuedFiles: state.queuedFiles.filter((f) => f.id !== id)
			}));
		},

		async uploadBatch(files: File[]) {
			if (files.length === 0) return;

			const jobsToCreate: VideoUploadJob[] = files.map((file) => ({
				id: crypto.randomUUID(),
				videoId: '',
				filename: file.name,
				status: 'pending' as const,
				processingStage: null,
				progress: 0,
				error: null,
				startedAt: new Date(),
				completedAt: null
			}));

			update((state) => ({
				...state,
				uploading: true,
				modalOpen: false,
				queuedFiles: [],
				jobs: [...jobsToCreate, ...state.jobs]
			}));

			for (let i = 0; i < files.length; i++) {
				const file = files[i];
				const jobId = jobsToCreate[i].id;

				update((state) => ({
					...state,
					jobs: state.jobs.map((job) =>
						job.id === jobId ? { ...job, status: 'uploading' as const } : job
					)
				}));

				try {
					const formData = new FormData();
					formData.append('file', file);

					const response = await fetch('/api/upload/video', {
						method: 'POST',
						body: formData
					});

					if (!response.ok) {
						const error = await response.json();
						throw new Error(error.message || 'Upload failed');
					}

					const result = await response.json();

					update((state) => ({
						...state,
						jobs: state.jobs.map((job) =>
							job.id === jobId
								? {
										...job,
										videoId: result.video_id,
										status: 'processing' as const,
										progress: 10
									}
								: job
						)
					}));

					// Start polling for video status
					this.pollVideoJob(jobId, result.video_id);
				} catch (error) {
					const message = error instanceof Error ? error.message : 'Upload failed';
					update((state) => ({
						...state,
						jobs: state.jobs.map((job) =>
							job.id === jobId
								? { ...job, status: 'failed' as const, error: message }
								: job
						)
					}));
				}
			}

			update((state) => ({
				...state,
				uploading: false
			}));
		},

		async pollVideoJob(localId: string, videoId: string) {
			try {
				await pollVideoStatus(
					videoId,
					(status: VideoStatusResponse) => {
						update((state) => ({
							...state,
							jobs: state.jobs.map((job) =>
								job.id === localId
									? {
											...job,
											processingStage: status.processing_stage,
											progress: Math.max(10, status.processing_progress)
										}
									: job
							)
						}));
					},
					3000
				);

				update((state) => ({
					...state,
					jobs: state.jobs.map((job) =>
						job.id === localId
							? {
									...job,
									status: 'completed' as const,
									progress: 100,
									completedAt: new Date()
								}
							: job
					)
				}));

				// Refresh videos list
				videos.fetch();
			} catch (error) {
				const message = error instanceof Error ? error.message : 'Processing failed';
				update((state) => ({
					...state,
					jobs: state.jobs.map((job) =>
						job.id === localId
							? { ...job, status: 'failed' as const, error: message }
							: job
					)
				}));
			}
		},

		removeJob(id: string) {
			update((state) => ({
				...state,
				jobs: state.jobs.filter((job) => job.id !== id)
			}));
		}
	};
}

export const videoUpload = createVideoUploadStore();

// Derived stores
export const processingVideos = derived(videos, ($videos) =>
	$videos.videos.filter((v) => v.status === 'processing')
);

export const readyVideos = derived(videos, ($videos) =>
	$videos.videos.filter((v) => v.status === 'ready')
);

export const activeVideoJobs = derived(videoUpload, ($upload) =>
	$upload.jobs.filter(
		(job) => job.status === 'pending' || job.status === 'uploading' || job.status === 'processing'
	)
);
```

**Step 2: Verify store compiles**

Run: `cd frontend && npm run check`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/lib/stores/videos.ts
git commit -m "feat(frontend): add videos store with upload handling"
```

---

## Task 5: Create Video Search Store

**Files:**
- Create: `frontend/src/lib/stores/videoSearch.ts`

**Step 1: Create the video search store**

```typescript
import { writable } from 'svelte/store';
import type { VideoSearchResponse, VideoMatch, VideoSearchResult } from '$lib/api/types';
import { searchVideos } from '$lib/api/video';

interface VideoSearchState {
	query: string;
	loading: boolean;
	error: string | null;
	response: VideoSearchResponse | null;
}

function createVideoSearchStore() {
	const { subscribe, set, update } = writable<VideoSearchState>({
		query: '',
		loading: false,
		error: null,
		response: null
	});

	return {
		subscribe,

		setQuery(query: string) {
			update((state) => ({ ...state, query }));
		},

		async search(queryText: string) {
			if (!queryText.trim()) return;

			update((state) => ({
				...state,
				query: queryText,
				loading: true,
				error: null,
				response: null
			}));

			try {
				const response = await searchVideos({ query: queryText });
				update((state) => ({
					...state,
					loading: false,
					response
				}));
			} catch (error) {
				const message = error instanceof Error ? error.message : 'Search failed';
				update((state) => ({
					...state,
					loading: false,
					error: message
				}));
			}
		},

		clear() {
			set({
				query: '',
				loading: false,
				error: null,
				response: null
			});
		}
	};
}

export const videoSearch = createVideoSearchStore();

// Video player state
interface VideoPlayerState {
	selectedVideo: VideoSearchResult | null;
	selectedMatch: VideoMatch | null;
	isPlaying: boolean;
	currentTime: number;
	isPanelOpen: boolean;
}

function createVideoPlayerStore() {
	const { subscribe, set, update } = writable<VideoPlayerState>({
		selectedVideo: null,
		selectedMatch: null,
		isPlaying: false,
		currentTime: 0,
		isPanelOpen: false
	});

	return {
		subscribe,

		selectMatch(video: VideoSearchResult, match: VideoMatch) {
			update((state) => ({
				...state,
				selectedVideo: video,
				selectedMatch: match,
				isPanelOpen: true,
				isPlaying: false,
				currentTime: match.start_seconds
			}));
		},

		selectVideo(video: VideoSearchResult) {
			const firstMatch = video.matches[0] || null;
			update((state) => ({
				...state,
				selectedVideo: video,
				selectedMatch: firstMatch,
				isPanelOpen: true,
				isPlaying: false,
				currentTime: firstMatch?.start_seconds || 0
			}));
		},

		nextMatch() {
			update((state) => {
				if (!state.selectedVideo || !state.selectedMatch) return state;
				const matches = state.selectedVideo.matches;
				const currentIndex = matches.findIndex(
					(m) => m.chunk_id === state.selectedMatch?.chunk_id
				);
				const nextIndex = (currentIndex + 1) % matches.length;
				const nextMatch = matches[nextIndex];
				return {
					...state,
					selectedMatch: nextMatch,
					currentTime: nextMatch.start_seconds
				};
			});
		},

		previousMatch() {
			update((state) => {
				if (!state.selectedVideo || !state.selectedMatch) return state;
				const matches = state.selectedVideo.matches;
				const currentIndex = matches.findIndex(
					(m) => m.chunk_id === state.selectedMatch?.chunk_id
				);
				const prevIndex = currentIndex === 0 ? matches.length - 1 : currentIndex - 1;
				const prevMatch = matches[prevIndex];
				return {
					...state,
					selectedMatch: prevMatch,
					currentTime: prevMatch.start_seconds
				};
			});
		},

		setPlaying(isPlaying: boolean) {
			update((state) => ({ ...state, isPlaying }));
		},

		setCurrentTime(time: number) {
			update((state) => ({ ...state, currentTime: time }));
		},

		togglePanel() {
			update((state) => ({ ...state, isPanelOpen: !state.isPanelOpen }));
		},

		closePanel() {
			update((state) => ({ ...state, isPanelOpen: false }));
		},

		clear() {
			set({
				selectedVideo: null,
				selectedMatch: null,
				isPlaying: false,
				currentTime: 0,
				isPanelOpen: false
			});
		}
	};
}

export const videoPlayer = createVideoPlayerStore();

// Example queries for video search
export const videoExampleQueries = [
	'product demo features',
	'when the speaker mentions pricing',
	'slides about architecture',
	'introduction segment'
];
```

**Step 2: Verify store compiles**

Run: `cd frontend && npm run check`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/lib/stores/videoSearch.ts
git commit -m "feat(frontend): add video search and player stores"
```

---

## Task 6: Create Video Upload Server Route

**Files:**
- Create: `frontend/src/routes/api/upload/video/+server.ts`

**Step 1: Create the video upload route**

```typescript
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
			throw error(500, {
				message: errorData.detail || 'Failed to start video processing'
			});
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

		throw error(500, {
			message: err instanceof Error ? err.message : 'Upload failed'
		});
	}
};
```

**Step 2: Verify route compiles**

Run: `cd frontend && npm run check`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/routes/api/upload/video/
git commit -m "feat(frontend): add video upload server route"
```

---

## Task 7: Create Content Tabs Component

**Files:**
- Create: `frontend/src/lib/components/ContentTabs.svelte`

**Step 1: Create the tabs component**

```svelte
<script lang="ts">
	import { FileText, Video } from 'lucide-svelte';

	interface Props {
		activeTab: 'documents' | 'videos';
		onTabChange: (tab: 'documents' | 'videos') => void;
	}

	let { activeTab, onTabChange }: Props = $props();
</script>

<div class="flex border-b border-[var(--color-border)]">
	<button
		type="button"
		onclick={() => onTabChange('documents')}
		class="flex items-center gap-2 px-4 py-3 text-sm font-medium transition-colors {activeTab ===
		'documents'
			? 'border-b-2 border-[var(--color-accent)] text-[var(--color-accent)]'
			: 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]'}"
	>
		<FileText class="h-4 w-4" />
		Documents
	</button>
	<button
		type="button"
		onclick={() => onTabChange('videos')}
		class="flex items-center gap-2 px-4 py-3 text-sm font-medium transition-colors {activeTab ===
		'videos'
			? 'border-b-2 border-[var(--color-accent)] text-[var(--color-accent)]'
			: 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]'}"
	>
		<Video class="h-4 w-4" />
		Videos
	</button>
</div>
```

**Step 2: Verify component compiles**

Run: `cd frontend && npm run check`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/lib/components/ContentTabs.svelte
git commit -m "feat(frontend): add ContentTabs component"
```

---

## Task 8: Create VideoItem Component

**Files:**
- Create: `frontend/src/lib/components/VideoItem.svelte`

**Step 1: Create the video item component**

```svelte
<script lang="ts">
	import { Loader2, CheckCircle, AlertCircle, Trash2, Play } from 'lucide-svelte';
	import type { Video } from '$lib/api/types';

	interface Props {
		video: Video;
		selected?: boolean;
		onSelect?: () => void;
		onDelete?: () => void;
	}

	let { video, selected = false, onSelect, onDelete }: Props = $props();

	let showDeleteButton = $state(false);

	function formatDuration(ms: number | null): string {
		if (!ms) return '--:--';
		const seconds = Math.floor(ms / 1000);
		const mins = Math.floor(seconds / 60);
		const secs = seconds % 60;
		return `${mins}:${secs.toString().padStart(2, '0')}`;
	}

	function getProcessingLabel(stage: string | null): string {
		if (!stage) return 'Processing...';
		const labels: Record<string, string> = {
			audio_extraction: 'Extracting audio...',
			transcription: 'Transcribing...',
			scene_detection: 'Detecting scenes...',
			visual_analysis: 'Analyzing visuals...',
			ocr: 'Reading text...',
			fusion: 'Combining content...',
			embedding: 'Indexing...'
		};
		return labels[stage] || 'Processing...';
	}
</script>

<button
	type="button"
	onclick={onSelect}
	onmouseenter={() => (showDeleteButton = true)}
	onmouseleave={() => (showDeleteButton = false)}
	class="group flex w-full items-center gap-3 rounded-lg p-2 text-left transition-colors {selected
		? 'bg-[var(--color-accent)]/10'
		: 'hover:bg-gray-50'}"
>
	<!-- Thumbnail -->
	<div
		class="relative h-10 w-16 shrink-0 overflow-hidden rounded bg-gray-100"
	>
		{#if video.thumbnail_url}
			<img
				src={video.thumbnail_url}
				alt=""
				class="h-full w-full object-cover"
			/>
		{:else}
			<div class="flex h-full w-full items-center justify-center">
				<Play class="h-4 w-4 text-gray-400" />
			</div>
		{/if}

		{#if video.status === 'processing'}
			<div class="absolute inset-0 flex items-center justify-center bg-black/50">
				<Loader2 class="h-4 w-4 animate-spin text-white" />
			</div>
		{/if}
	</div>

	<!-- Info -->
	<div class="min-w-0 flex-1">
		<p class="truncate text-sm font-medium text-[var(--color-text-primary)]">
			{video.title || video.filename}
		</p>

		{#if video.status === 'processing'}
			<p class="text-xs text-[var(--color-accent)]">
				{getProcessingLabel(video.processing_stage)}
			</p>
		{:else if video.status === 'failed'}
			<p class="flex items-center gap-1 text-xs text-red-600">
				<AlertCircle class="h-3 w-3" />
				Failed
			</p>
		{:else}
			<p class="text-xs text-[var(--color-text-secondary)]">
				{formatDuration(video.duration_ms)}
			</p>
		{/if}
	</div>

	<!-- Status/Actions -->
	<div class="shrink-0">
		{#if video.status === 'ready'}
			{#if showDeleteButton && onDelete}
				<button
					type="button"
					onclick={(e) => {
						e.stopPropagation();
						onDelete?.();
					}}
					class="rounded p-1 text-[var(--color-text-secondary)] hover:bg-red-50 hover:text-red-600"
				>
					<Trash2 class="h-4 w-4" />
				</button>
			{:else}
				<CheckCircle class="h-4 w-4 text-green-500" />
			{/if}
		{:else if video.status === 'processing'}
			<span class="text-xs text-[var(--color-text-secondary)]">
				{video.processing_progress}%
			</span>
		{/if}
	</div>
</button>
```

**Step 2: Verify component compiles**

Run: `cd frontend && npm run check`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/lib/components/VideoItem.svelte
git commit -m "feat(frontend): add VideoItem component"
```

---

## Task 9: Create VideoSidebar Component

**Files:**
- Create: `frontend/src/lib/components/VideoSidebar.svelte`

**Step 1: Create the video sidebar component**

```svelte
<script lang="ts">
	import { Loader2, FolderOpen, Video, AlertCircle } from 'lucide-svelte';
	import { videos, processingVideos, readyVideos, activeVideoJobs } from '$lib/stores/videos';
	import { deleteVideo } from '$lib/api/video';
	import VideoItem from './VideoItem.svelte';

	interface Props {
		selectedVideoId?: string | null;
		onSelectVideo?: (videoId: string) => void;
	}

	let { selectedVideoId = null, onSelectVideo }: Props = $props();

	let deleteConfirmId = $state<string | null>(null);
	let isDeleting = $state(false);
	let deleteError = $state<string | null>(null);

	async function handleDelete(videoId: string) {
		isDeleting = true;
		deleteError = null;

		try {
			await deleteVideo(videoId);
			videos.removeVideo(videoId);
			deleteConfirmId = null;
		} catch (error) {
			deleteError = error instanceof Error ? error.message : 'Failed to delete video';
		} finally {
			isDeleting = false;
		}
	}
</script>

<aside
	class="w-[var(--spacing-sidebar)] shrink-0 overflow-y-auto border-r border-[var(--color-border)] bg-[var(--color-surface)]"
>
	<div class="p-4">
		<!-- Active Processing Jobs -->
		{#if $activeVideoJobs.length > 0}
			<div class="mb-6">
				<h3
					class="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-[var(--color-text-secondary)]"
				>
					<Loader2 class="h-3 w-3 animate-spin" />
					Processing
				</h3>
				<div class="space-y-2">
					{#each $activeVideoJobs as job (job.id)}
						<div class="rounded-lg border border-[var(--color-border)] p-2">
							<p class="truncate text-sm font-medium text-[var(--color-text-primary)]">
								{job.filename}
							</p>
							<div class="mt-1 flex items-center gap-2">
								<div class="h-1.5 flex-1 overflow-hidden rounded-full bg-gray-200">
									<div
										class="h-full rounded-full bg-[var(--color-accent)] transition-all duration-300"
										style="width: {job.progress}%"
									></div>
								</div>
								<span class="text-xs text-[var(--color-text-secondary)]">{job.progress}%</span>
							</div>
							{#if job.processingStage}
								<p class="mt-1 text-xs text-[var(--color-accent)]">
									{job.processingStage.replace(/_/g, ' ')}
								</p>
							{/if}
						</div>
					{/each}
				</div>
			</div>
		{/if}

		<!-- Your Videos -->
		{#if $readyVideos.length > 0}
			<div class="mb-6">
				<h3
					class="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-[var(--color-text-secondary)]"
				>
					<FolderOpen class="h-3 w-3" />
					Your Videos
				</h3>
				<div class="space-y-1">
					{#each $readyVideos as video (video.video_id)}
						<VideoItem
							{video}
							selected={selectedVideoId === video.video_id}
							onSelect={() => onSelectVideo?.(video.video_id)}
							onDelete={() => (deleteConfirmId = video.video_id)}
						/>
					{/each}
				</div>
			</div>
		{/if}

		<!-- Empty State -->
		{#if $videos.videos.length === 0 && $activeVideoJobs.length === 0 && !$videos.loading}
			<div class="py-8 text-center">
				<Video class="mx-auto h-8 w-8 text-gray-300" />
				<p class="mt-2 text-sm text-[var(--color-text-secondary)]">No videos yet</p>
				<p class="mt-1 text-xs text-[var(--color-text-secondary)]">
					Upload a video to get started
				</p>
			</div>
		{/if}

		<!-- Loading State -->
		{#if $videos.loading}
			<div class="flex items-center justify-center py-8">
				<Loader2 class="h-6 w-6 animate-spin text-[var(--color-accent)]" />
			</div>
		{/if}
	</div>
</aside>

<!-- Delete Confirmation Modal -->
{#if deleteConfirmId}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
		onclick={() => (deleteConfirmId = null)}
		onkeydown={(e) => e.key === 'Escape' && (deleteConfirmId = null)}
		role="dialog"
		aria-modal="true"
		tabindex="-1"
	>
		<div
			class="mx-4 w-full max-w-sm rounded-lg bg-white p-6 shadow-xl"
			onclick={(e) => e.stopPropagation()}
			role="document"
		>
			<h3 class="text-lg font-semibold text-[var(--color-text-primary)]">Delete Video</h3>
			<p class="mt-2 text-sm text-[var(--color-text-secondary)]">
				Are you sure you want to delete this video? All associated data including transcripts,
				keyframes, and search index will be removed. This action cannot be undone.
			</p>

			{#if deleteError}
				<div class="mt-3 flex items-center gap-2 rounded-lg bg-red-50 p-3 text-sm text-red-700">
					<AlertCircle class="h-4 w-4 shrink-0" />
					<span>{deleteError}</span>
				</div>
			{/if}

			<div class="mt-4 flex justify-end gap-3">
				<button
					type="button"
					onclick={() => (deleteConfirmId = null)}
					disabled={isDeleting}
					class="rounded-lg px-4 py-2 text-sm font-medium text-[var(--color-text-secondary)] hover:bg-gray-100 disabled:opacity-50"
				>
					Cancel
				</button>
				<button
					type="button"
					onclick={() => deleteConfirmId && handleDelete(deleteConfirmId)}
					disabled={isDeleting}
					class="flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
				>
					{#if isDeleting}
						<Loader2 class="h-4 w-4 animate-spin" />
						Deleting...
					{:else}
						Delete Video
					{/if}
				</button>
			</div>
		</div>
	</div>
{/if}
```

**Step 2: Verify component compiles**

Run: `cd frontend && npm run check`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/lib/components/VideoSidebar.svelte
git commit -m "feat(frontend): add VideoSidebar component"
```

---

## Task 10: Create VideoUploadModal Component

**Files:**
- Create: `frontend/src/lib/components/VideoUploadModal.svelte`

**Step 1: Create the video upload modal**

```svelte
<script lang="ts">
	import { X, Upload, Video, AlertCircle, Loader2, AlertTriangle } from 'lucide-svelte';
	import { videoUpload, videos } from '$lib/stores/videos';
	import type { QueuedVideoFile } from '$lib/api/types';

	let dragOver = $state(false);
	let inputElement: HTMLInputElement;

	const ALLOWED_EXTENSIONS = ['.mp4', '.mov', '.avi', '.mkv', '.webm'];
	const MAX_SIZE_GB = 5;

	const existingFilenames = $derived(new Set($videos.videos.map((v) => v.filename)));

	const validFiles = $derived($videoUpload.queuedFiles.filter((f) => f.status === 'valid'));
	const hasValidFiles = $derived(validFiles.length > 0);

	function handleClose() {
		videoUpload.closeModal();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			handleClose();
		}
	}

	function handleBackdropClick(e: MouseEvent) {
		if (e.target === e.currentTarget) {
			handleClose();
		}
	}

	function handleDragOver(e: DragEvent) {
		e.preventDefault();
		dragOver = true;
	}

	function handleDragLeave(e: DragEvent) {
		e.preventDefault();
		dragOver = false;
	}

	function handleDrop(e: DragEvent) {
		e.preventDefault();
		dragOver = false;

		const files = e.dataTransfer?.files;
		if (files && files.length > 0) {
			processFiles(Array.from(files));
		}
	}

	function handleFileSelect(e: Event) {
		const target = e.target as HTMLInputElement;
		const files = target.files;
		if (files && files.length > 0) {
			processFiles(Array.from(files));
		}
		target.value = '';
	}

	function processFiles(files: File[]) {
		const batchFilenames = new Set<string>();

		const queuedFiles: QueuedVideoFile[] = files.map((file) => {
			const extension = '.' + file.name.split('.').pop()?.toLowerCase();
			let status: 'valid' | 'invalid' = 'valid';
			let error: string | undefined;

			if (!ALLOWED_EXTENSIONS.includes(extension)) {
				status = 'invalid';
				error = 'Invalid file type';
			} else if (file.size > MAX_SIZE_GB * 1024 * 1024 * 1024) {
				status = 'invalid';
				error = `Exceeds ${MAX_SIZE_GB}GB limit`;
			} else if (existingFilenames.has(file.name)) {
				status = 'invalid';
				error = 'Video already exists';
			} else if (batchFilenames.has(file.name)) {
				status = 'invalid';
				error = 'Duplicate in batch';
			}

			batchFilenames.add(file.name);

			return {
				id: crypto.randomUUID(),
				file,
				status,
				error
			};
		});

		videoUpload.addFiles(queuedFiles);
	}

	function handleUploadAll() {
		const filesToUpload = validFiles.map((qf) => qf.file);
		videoUpload.uploadBatch(filesToUpload);
	}

	function handleBrowseClick() {
		inputElement?.click();
	}

	function formatFileSize(bytes: number): string {
		if (bytes < 1024) return `${bytes} B`;
		if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
		if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
		return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
	}
</script>

<div
	class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
	onclick={handleBackdropClick}
	onkeydown={handleKeydown}
	role="dialog"
	aria-modal="true"
	aria-labelledby="upload-title"
	tabindex="-1"
>
	<div class="w-full max-w-lg rounded-xl bg-[var(--color-surface)] shadow-xl" role="document">
		<!-- Header -->
		<div class="flex items-center justify-between border-b border-[var(--color-border)] px-6 py-4">
			<h2 id="upload-title" class="text-lg font-semibold text-[var(--color-text-primary)]">
				Upload Videos
			</h2>
			<button
				onclick={handleClose}
				class="rounded-lg p-1 text-[var(--color-text-secondary)] hover:bg-gray-100 hover:text-[var(--color-text-primary)]"
				aria-label="Close dialog"
			>
				<X class="h-5 w-5" />
			</button>
		</div>

		<!-- Content -->
		<div class="p-6">
			<!-- File Queue -->
			{#if $videoUpload.queuedFiles.length > 0}
				<div class="mb-4 max-h-48 overflow-y-auto rounded-lg border border-[var(--color-border)]">
					{#each $videoUpload.queuedFiles as queuedFile (queuedFile.id)}
						<div
							class="flex items-center gap-3 border-b border-[var(--color-border)] px-3 py-2 last:border-b-0"
						>
							{#if queuedFile.status === 'valid'}
								<Video class="h-4 w-4 shrink-0 text-[var(--color-accent)]" />
							{:else}
								<AlertTriangle class="h-4 w-4 shrink-0 text-amber-500" />
							{/if}

							<div class="min-w-0 flex-1">
								<p
									class="truncate text-sm font-medium {queuedFile.status === 'invalid'
										? 'text-[var(--color-text-secondary)]'
										: 'text-[var(--color-text-primary)]'}"
								>
									{queuedFile.file.name}
								</p>
								{#if queuedFile.error}
									<p class="text-xs text-amber-600">{queuedFile.error}</p>
								{:else}
									<p class="text-xs text-[var(--color-text-secondary)]">
										{formatFileSize(queuedFile.file.size)}
									</p>
								{/if}
							</div>

							<button
								onclick={() => videoUpload.removeQueuedFile(queuedFile.id)}
								class="shrink-0 rounded p-1 text-[var(--color-text-secondary)] hover:bg-gray-100 hover:text-[var(--color-text-primary)]"
								aria-label="Remove file"
							>
								<X class="h-4 w-4" />
							</button>
						</div>
					{/each}
				</div>
			{/if}

			<!-- Drop Zone -->
			<div
				class={`relative rounded-lg border-2 border-dashed p-6 text-center transition-colors ${
					dragOver
						? 'border-[var(--color-accent)] bg-[var(--color-accent)]/5'
						: 'border-[var(--color-border)] hover:border-[var(--color-accent)]/50'
				}`}
				ondragover={handleDragOver}
				ondragleave={handleDragLeave}
				ondrop={handleDrop}
				role="region"
				aria-label="Video drop zone"
			>
				<input
					bind:this={inputElement}
					type="file"
					accept={ALLOWED_EXTENSIONS.join(',')}
					multiple
					onchange={handleFileSelect}
					class="hidden"
				/>

				<div class="flex flex-col items-center">
					<div class="flex h-10 w-10 items-center justify-center rounded-full bg-gray-100">
						<Upload class="h-5 w-5 text-[var(--color-text-secondary)]" />
					</div>
					<p class="mt-2 text-sm text-[var(--color-text-primary)]">
						<button
							onclick={handleBrowseClick}
							class="font-medium text-[var(--color-accent)] hover:underline"
						>
							Click to upload
						</button>
						{' '}or drag and drop
					</p>
					<p class="mt-1 text-xs text-[var(--color-text-secondary)]">
						MP4, MOV, AVI, MKV, or WebM (max {MAX_SIZE_GB}GB)
					</p>
					<p class="mt-0.5 text-xs text-[var(--color-text-secondary)]">
						Duration: 10 seconds - 60 minutes
					</p>
				</div>
			</div>

			<!-- Error Message -->
			{#if $videoUpload.uploadError}
				<div
					class="mt-4 flex items-center gap-2 rounded-lg bg-red-50 p-3 text-sm text-red-700"
					role="alert"
				>
					<AlertCircle class="h-4 w-4 shrink-0" />
					<span>{$videoUpload.uploadError}</span>
				</div>
			{/if}
		</div>

		<!-- Footer -->
		<div class="flex justify-end gap-3 border-t border-[var(--color-border)] px-6 py-4">
			<button
				onclick={handleClose}
				disabled={$videoUpload.uploading}
				class="rounded-lg px-4 py-2 text-sm font-medium text-[var(--color-text-secondary)] hover:bg-gray-100 disabled:opacity-50"
			>
				Cancel
			</button>
			<button
				onclick={handleUploadAll}
				disabled={!hasValidFiles || $videoUpload.uploading}
				class="flex items-center gap-2 rounded-lg bg-[var(--color-accent)] px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-[var(--color-accent-hover)] disabled:cursor-not-allowed disabled:opacity-50"
			>
				{#if $videoUpload.uploading}
					<Loader2 class="h-4 w-4 animate-spin" />
					Uploading...
				{:else}
					<Upload class="h-4 w-4" />
					{#if validFiles.length === 1}
						Upload Video
					{:else if validFiles.length > 1}
						Upload {validFiles.length} Videos
					{:else}
						Upload
					{/if}
				{/if}
			</button>
		</div>
	</div>
</div>
```

**Step 2: Verify component compiles**

Run: `cd frontend && npm run check`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/lib/components/VideoUploadModal.svelte
git commit -m "feat(frontend): add VideoUploadModal component"
```

---

## Task 11: Create TimelineStrip Component

**Files:**
- Create: `frontend/src/lib/components/TimelineStrip.svelte`

**Step 1: Create the timeline strip component**

```svelte
<script lang="ts">
	import type { VideoMatch } from '$lib/api/types';

	interface Props {
		durationMs: number;
		matches: VideoMatch[];
		selectedMatchId?: string | null;
		onSelectMatch: (match: VideoMatch) => void;
	}

	let { durationMs, matches, selectedMatchId = null, onSelectMatch }: Props = $props();

	let containerRef: HTMLDivElement;
	let hoveredMatch = $state<VideoMatch | null>(null);
	let tooltipX = $state(0);

	function formatTime(ms: number): string {
		const seconds = Math.floor(ms / 1000);
		const mins = Math.floor(seconds / 60);
		const secs = seconds % 60;
		return `${mins}:${secs.toString().padStart(2, '0')}`;
	}

	function getMarkerPosition(match: VideoMatch): number {
		if (!durationMs) return 0;
		const midpoint = (match.start_time_ms + match.end_time_ms) / 2;
		return (midpoint / durationMs) * 100;
	}

	function getMarkerOpacity(match: VideoMatch): number {
		// Map score (0-1) to opacity (0.4-1)
		return 0.4 + match.fused_score * 0.6;
	}

	function handleMarkerHover(match: VideoMatch, event: MouseEvent) {
		hoveredMatch = match;
		const rect = containerRef.getBoundingClientRect();
		tooltipX = event.clientX - rect.left;
	}

	function handleMarkerLeave() {
		hoveredMatch = null;
	}
</script>

<div bind:this={containerRef} class="relative">
	<!-- Timeline bar -->
	<div class="relative h-6 rounded-full bg-gray-100">
		<!-- Match markers -->
		{#each matches as match (match.chunk_id)}
			<button
				type="button"
				onclick={() => onSelectMatch(match)}
				onmouseenter={(e) => handleMarkerHover(match, e)}
				onmouseleave={handleMarkerLeave}
				class="absolute top-0 h-full w-1 -translate-x-1/2 cursor-pointer rounded-full transition-all hover:w-1.5 {selectedMatchId ===
				match.chunk_id
					? 'bg-[var(--color-accent)] ring-2 ring-[var(--color-accent)] ring-offset-1'
					: 'bg-[var(--color-accent)]'}"
				style="left: {getMarkerPosition(match)}%; opacity: {getMarkerOpacity(match)}"
				aria-label="Match at {formatTime(match.start_time_ms)}"
			></button>
		{/each}
	</div>

	<!-- Time labels -->
	<div class="mt-1 flex justify-between text-xs text-[var(--color-text-secondary)]">
		<span>0:00</span>
		<span>{formatTime(durationMs)}</span>
	</div>

	<!-- Tooltip -->
	{#if hoveredMatch}
		<div
			class="pointer-events-none absolute bottom-full mb-2 -translate-x-1/2 rounded-lg bg-gray-900 px-3 py-2 text-xs text-white shadow-lg"
			style="left: {tooltipX}px"
		>
			<p class="font-medium">{formatTime(hoveredMatch.start_time_ms)}</p>
			<p class="mt-1 max-w-48 truncate opacity-80">
				{hoveredMatch.fused_text_preview}
			</p>
			<p class="mt-1 opacity-60">Score: {(hoveredMatch.fused_score * 100).toFixed(0)}%</p>
		</div>
	{/if}
</div>
```

**Step 2: Verify component compiles**

Run: `cd frontend && npm run check`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/lib/components/TimelineStrip.svelte
git commit -m "feat(frontend): add TimelineStrip component"
```

---

## Task 12: Create VideoResultCard Component

**Files:**
- Create: `frontend/src/lib/components/VideoResultCard.svelte`

**Step 1: Create the video result card component**

```svelte
<script lang="ts">
	import { Play, ChevronDown, ChevronUp } from 'lucide-svelte';
	import type { VideoSearchResult, VideoMatch } from '$lib/api/types';
	import TimelineStrip from './TimelineStrip.svelte';

	interface Props {
		result: VideoSearchResult;
		selectedMatchId?: string | null;
		onSelectMatch: (match: VideoMatch) => void;
	}

	let { result, selectedMatchId = null, onSelectMatch }: Props = $props();

	let expanded = $state(false);
	const MAX_VISIBLE_MATCHES = 3;

	function formatDuration(ms: number | null): string {
		if (!ms) return '--:--';
		const seconds = Math.floor(ms / 1000);
		const mins = Math.floor(seconds / 60);
		const secs = seconds % 60;
		return `${mins}:${secs.toString().padStart(2, '0')}`;
	}

	function formatTimestamp(seconds: number): string {
		const mins = Math.floor(seconds / 60);
		const secs = Math.floor(seconds % 60);
		return `${mins}:${secs.toString().padStart(2, '0')}`;
	}

	const visibleMatches = $derived(
		expanded ? result.matches : result.matches.slice(0, MAX_VISIBLE_MATCHES)
	);

	const hasMoreMatches = $derived(result.matches.length > MAX_VISIBLE_MATCHES);
</script>

<div class="rounded-lg border border-[var(--color-border)] bg-white p-4">
	<!-- Header -->
	<div class="flex items-start gap-3">
		<!-- Thumbnail -->
		<div class="relative h-16 w-24 shrink-0 overflow-hidden rounded bg-gray-100">
			{#if result.thumbnail_url}
				<img src={result.thumbnail_url} alt="" class="h-full w-full object-cover" />
			{:else}
				<div class="flex h-full w-full items-center justify-center">
					<Play class="h-6 w-6 text-gray-400" />
				</div>
			{/if}
		</div>

		<!-- Title and meta -->
		<div class="min-w-0 flex-1">
			<h3 class="font-medium text-[var(--color-text-primary)]">
				{result.title || 'Untitled Video'}
			</h3>
			<div class="mt-1 flex items-center gap-3 text-xs text-[var(--color-text-secondary)]">
				<span>{formatDuration(result.duration_ms)}</span>
				<span
					class="rounded-full bg-[var(--color-accent)]/10 px-2 py-0.5 text-[var(--color-accent)]"
				>
					{result.match_count} match{result.match_count === 1 ? '' : 'es'}
				</span>
			</div>
		</div>
	</div>

	<!-- Timeline Strip -->
	{#if result.duration_ms}
		<div class="mt-4">
			<TimelineStrip
				durationMs={result.duration_ms}
				matches={result.matches}
				{selectedMatchId}
				{onSelectMatch}
			/>
		</div>
	{/if}

	<!-- Match List -->
	<div class="mt-4 space-y-2">
		{#each visibleMatches as match (match.chunk_id)}
			<button
				type="button"
				onclick={() => onSelectMatch(match)}
				class="flex w-full items-start gap-2 rounded-lg p-2 text-left transition-colors hover:bg-gray-50 {selectedMatchId ===
				match.chunk_id
					? 'bg-[var(--color-accent)]/5 ring-1 ring-[var(--color-accent)]'
					: ''}"
			>
				<span
					class="shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-xs font-medium text-[var(--color-text-secondary)]"
				>
					{formatTimestamp(match.start_seconds)}
				</span>
				<p class="line-clamp-2 flex-1 text-sm text-[var(--color-text-primary)]">
					{match.fused_text_preview}
				</p>
			</button>
		{/each}
	</div>

	<!-- Show more/less -->
	{#if hasMoreMatches}
		<button
			type="button"
			onclick={() => (expanded = !expanded)}
			class="mt-2 flex w-full items-center justify-center gap-1 rounded-lg py-2 text-xs font-medium text-[var(--color-accent)] hover:bg-gray-50"
		>
			{#if expanded}
				<ChevronUp class="h-3 w-3" />
				Show less
			{:else}
				<ChevronDown class="h-3 w-3" />
				Show all {result.match_count} matches
			{/if}
		</button>
	{/if}
</div>
```

**Step 2: Verify component compiles**

Run: `cd frontend && npm run check`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/lib/components/VideoResultCard.svelte
git commit -m "feat(frontend): add VideoResultCard component"
```

---

## Task 13: Create VideoPlayerPanel Component

**Files:**
- Create: `frontend/src/lib/components/VideoPlayerPanel.svelte`

**Step 1: Create the video player panel component**

```svelte
<script lang="ts">
	import {
		ChevronLeft,
		ChevronRight,
		X,
		Play,
		MessageSquare,
		Eye,
		Type,
		Maximize2
	} from 'lucide-svelte';
	import { videoPlayer } from '$lib/stores/videoSearch';
	import { getClipUrl, getStreamUrl } from '$lib/api/video';

	type ContentTab = 'transcript' | 'scene' | 'ocr';
	let activeTab = $state<ContentTab>('transcript');

	let videoElement: HTMLVideoElement;

	function formatTimestamp(seconds: number): string {
		const mins = Math.floor(seconds / 60);
		const secs = Math.floor(seconds % 60);
		return `${mins}:${secs.toString().padStart(2, '0')}`;
	}

	function formatTimeRange(startSec: number, endSec: number): string {
		return `${formatTimestamp(startSec)} - ${formatTimestamp(endSec)}`;
	}

	const clipUrl = $derived(
		$videoPlayer.selectedVideo && $videoPlayer.selectedMatch
			? getClipUrl(
					$videoPlayer.selectedVideo.video_id,
					$videoPlayer.selectedMatch.start_time_ms,
					$videoPlayer.selectedMatch.end_time_ms
				)
			: null
	);

	const fullVideoUrl = $derived(
		$videoPlayer.selectedVideo ? getStreamUrl($videoPlayer.selectedVideo.video_id) : null
	);

	function handleTimeUpdate() {
		if (videoElement) {
			videoPlayer.setCurrentTime(videoElement.currentTime);
		}
	}

	function handlePlay() {
		videoPlayer.setPlaying(true);
	}

	function handlePause() {
		videoPlayer.setPlaying(false);
	}
</script>

{#if $videoPlayer.isPanelOpen}
	<div
		class="flex w-[400px] shrink-0 flex-col border-l border-[var(--color-border)] bg-[var(--color-surface)]"
	>
		<!-- Header -->
		<div class="flex items-center justify-between border-b border-[var(--color-border)] px-4 py-3">
			<h3 class="font-medium text-[var(--color-text-primary)]">Video Preview</h3>
			<button
				type="button"
				onclick={() => videoPlayer.closePanel()}
				class="rounded p-1 text-[var(--color-text-secondary)] hover:bg-gray-100"
				aria-label="Close panel"
			>
				<X class="h-4 w-4" />
			</button>
		</div>

		{#if $videoPlayer.selectedVideo && $videoPlayer.selectedMatch}
			<!-- Video Player -->
			<div class="relative aspect-video bg-black">
				{#if clipUrl}
					<video
						bind:this={videoElement}
						src={clipUrl}
						class="h-full w-full"
						controls
						ontimeupdate={handleTimeUpdate}
						onplay={handlePlay}
						onpause={handlePause}
					>
						<track kind="captions" />
					</video>
				{:else}
					<div class="flex h-full w-full items-center justify-center">
						<Play class="h-12 w-12 text-gray-400" />
					</div>
				{/if}
			</div>

			<!-- Video Info -->
			<div class="border-b border-[var(--color-border)] p-4">
				<h4 class="font-medium text-[var(--color-text-primary)]">
					{$videoPlayer.selectedVideo.title || 'Untitled Video'}
				</h4>
				<div class="mt-2 flex items-center gap-3 text-sm text-[var(--color-text-secondary)]">
					<span>
						{formatTimeRange(
							$videoPlayer.selectedMatch.start_seconds,
							$videoPlayer.selectedMatch.end_seconds
						)}
					</span>
					<span
						class="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700"
					>
						{($videoPlayer.selectedMatch.fused_score * 100).toFixed(0)}% match
					</span>
				</div>

				<!-- Navigation -->
				{#if $videoPlayer.selectedVideo.matches.length > 1}
					<div class="mt-3 flex items-center justify-between">
						<button
							type="button"
							onclick={() => videoPlayer.previousMatch()}
							class="flex items-center gap-1 rounded px-2 py-1 text-xs text-[var(--color-text-secondary)] hover:bg-gray-100"
						>
							<ChevronLeft class="h-3 w-3" />
							Previous
						</button>
						<span class="text-xs text-[var(--color-text-secondary)]">
							{$videoPlayer.selectedVideo.matches.findIndex(
								(m) => m.chunk_id === $videoPlayer.selectedMatch?.chunk_id
							) + 1} of {$videoPlayer.selectedVideo.matches.length}
						</span>
						<button
							type="button"
							onclick={() => videoPlayer.nextMatch()}
							class="flex items-center gap-1 rounded px-2 py-1 text-xs text-[var(--color-text-secondary)] hover:bg-gray-100"
						>
							Next
							<ChevronRight class="h-3 w-3" />
						</button>
					</div>
				{/if}
			</div>

			<!-- Content Tabs -->
			<div class="flex border-b border-[var(--color-border)]">
				<button
					type="button"
					onclick={() => (activeTab = 'transcript')}
					class="flex flex-1 items-center justify-center gap-1.5 py-2 text-xs font-medium transition-colors {activeTab ===
					'transcript'
						? 'border-b-2 border-[var(--color-accent)] text-[var(--color-accent)]'
						: 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]'}"
				>
					<MessageSquare class="h-3 w-3" />
					Transcript
				</button>
				<button
					type="button"
					onclick={() => (activeTab = 'scene')}
					class="flex flex-1 items-center justify-center gap-1.5 py-2 text-xs font-medium transition-colors {activeTab ===
					'scene'
						? 'border-b-2 border-[var(--color-accent)] text-[var(--color-accent)]'
						: 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]'}"
				>
					<Eye class="h-3 w-3" />
					Scene
				</button>
				<button
					type="button"
					onclick={() => (activeTab = 'ocr')}
					class="flex flex-1 items-center justify-center gap-1.5 py-2 text-xs font-medium transition-colors {activeTab ===
					'ocr'
						? 'border-b-2 border-[var(--color-accent)] text-[var(--color-accent)]'
						: 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]'}"
				>
					<Type class="h-3 w-3" />
					OCR
				</button>
			</div>

			<!-- Tab Content -->
			<div class="flex-1 overflow-y-auto p-4">
				{#if activeTab === 'transcript'}
					{#if $videoPlayer.selectedMatch.transcript_text}
						<p class="text-sm leading-relaxed text-[var(--color-text-primary)]">
							{$videoPlayer.selectedMatch.transcript_text}
						</p>
					{:else}
						<p class="text-sm text-[var(--color-text-secondary)]">No transcript available</p>
					{/if}
				{:else if activeTab === 'scene'}
					{#if $videoPlayer.selectedMatch.scene_description}
						<p class="text-sm leading-relaxed text-[var(--color-text-primary)]">
							{$videoPlayer.selectedMatch.scene_description}
						</p>
					{:else}
						<p class="text-sm text-[var(--color-text-secondary)]">No scene description available</p>
					{/if}
				{:else if activeTab === 'ocr'}
					{#if $videoPlayer.selectedMatch.source_modalities.includes('ocr')}
						<p class="text-sm leading-relaxed text-[var(--color-text-primary)]">
							{$videoPlayer.selectedMatch.fused_text_preview}
						</p>
					{:else}
						<p class="text-sm text-[var(--color-text-secondary)]">No on-screen text detected</p>
					{/if}
				{/if}
			</div>

			<!-- Footer -->
			{#if fullVideoUrl}
				<div class="border-t border-[var(--color-border)] p-4">
					<a
						href={fullVideoUrl}
						target="_blank"
						rel="noopener noreferrer"
						class="flex items-center justify-center gap-2 rounded-lg border border-[var(--color-border)] py-2 text-sm font-medium text-[var(--color-text-primary)] hover:bg-gray-50"
					>
						<Maximize2 class="h-4 w-4" />
						Open full video
					</a>
				</div>
			{/if}
		{:else}
			<!-- Empty State -->
			<div class="flex flex-1 flex-col items-center justify-center p-8 text-center">
				<Play class="h-12 w-12 text-gray-300" />
				<p class="mt-4 text-sm text-[var(--color-text-secondary)]">
					Select a video or click a timeline marker to preview
				</p>
			</div>
		{/if}
	</div>
{/if}
```

**Step 2: Verify component compiles**

Run: `cd frontend && npm run check`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/lib/components/VideoPlayerPanel.svelte
git commit -m "feat(frontend): add VideoPlayerPanel component"
```

---

## Task 14: Create VideoSearchBar Component

**Files:**
- Create: `frontend/src/lib/components/VideoSearchBar.svelte`

**Step 1: Create the video search bar component**

```svelte
<script lang="ts">
	import { Search, Loader2 } from 'lucide-svelte';
	import { videoSearch } from '$lib/stores/videoSearch';

	let inputValue = $state($videoSearch.query);

	function handleSubmit(e: Event) {
		e.preventDefault();
		if (inputValue.trim()) {
			videoSearch.search(inputValue.trim());
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			handleSubmit(e);
		}
	}
</script>

<form onsubmit={handleSubmit} class="relative">
	<div class="relative">
		<input
			type="text"
			bind:value={inputValue}
			onkeydown={handleKeydown}
			placeholder="Search within your videos..."
			class="w-full rounded-xl border border-[var(--color-border)] bg-white py-3 pl-12 pr-4 text-[var(--color-text-primary)] placeholder-[var(--color-text-secondary)] outline-none transition-shadow focus:border-[var(--color-accent)] focus:ring-2 focus:ring-[var(--color-accent)]/20"
		/>
		<div class="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2">
			{#if $videoSearch.loading}
				<Loader2 class="h-5 w-5 animate-spin text-[var(--color-accent)]" />
			{:else}
				<Search class="h-5 w-5 text-[var(--color-text-secondary)]" />
			{/if}
		</div>
	</div>
</form>
```

**Step 2: Verify component compiles**

Run: `cd frontend && npm run check`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/lib/components/VideoSearchBar.svelte
git commit -m "feat(frontend): add VideoSearchBar component"
```

---

## Task 15: Update Main Page with Tabs

**Files:**
- Modify: `frontend/src/routes/+page.svelte`

**Step 1: Update the main page to support tabs**

Replace the entire content of `+page.svelte`:

```svelte
<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { documents } from '$lib/stores/documents';
	import { videos, videoUpload } from '$lib/stores/videos';
	import { search } from '$lib/stores/search';
	import { videoSearch, videoPlayer, videoExampleQueries } from '$lib/stores/videoSearch';
	import { upload } from '$lib/stores/upload';

	// Document components
	import DocumentSidebar from '$lib/components/DocumentSidebar.svelte';
	import SearchBar from '$lib/components/SearchBar.svelte';
	import AnswerCard from '$lib/components/AnswerCard.svelte';
	import SourcesPanel from '$lib/components/SourcesPanel.svelte';
	import UploadModal from '$lib/components/UploadModal.svelte';

	// Video components
	import ContentTabs from '$lib/components/ContentTabs.svelte';
	import VideoSidebar from '$lib/components/VideoSidebar.svelte';
	import VideoSearchBar from '$lib/components/VideoSearchBar.svelte';
	import VideoResultCard from '$lib/components/VideoResultCard.svelte';
	import VideoPlayerPanel from '$lib/components/VideoPlayerPanel.svelte';
	import VideoUploadModal from '$lib/components/VideoUploadModal.svelte';

	type Tab = 'documents' | 'videos';

	// Get tab from URL or default to documents
	let activeTab = $derived<Tab>(($page.url.searchParams.get('tab') as Tab) || 'documents');

	function handleTabChange(tab: Tab) {
		const url = new URL($page.url);
		if (tab === 'documents') {
			url.searchParams.delete('tab');
		} else {
			url.searchParams.set('tab', tab);
		}
		goto(url.toString(), { replaceState: true });
	}

	onMount(() => {
		documents.fetch();
		videos.fetch();
	});

	function handleVideoMatchSelect(
		video: import('$lib/api/types').VideoSearchResult,
		match: import('$lib/api/types').VideoMatch
	) {
		videoPlayer.selectMatch(video, match);
	}
</script>

<div class="flex h-[calc(100vh-4rem)]">
	<!-- Sidebar -->
	{#if activeTab === 'documents'}
		<DocumentSidebar />
	{:else}
		<VideoSidebar
			selectedVideoId={$videoPlayer.selectedVideo?.video_id}
			onSelectVideo={(id) => {
				const video = $videoSearch.response?.videos.find((v) => v.video_id === id);
				if (video) {
					videoPlayer.selectVideo(video);
				}
			}}
		/>
	{/if}

	<!-- Main Content -->
	<div class="flex flex-1 flex-col overflow-hidden">
		<!-- Tabs -->
		<ContentTabs {activeTab} onTabChange={handleTabChange} />

		{#if activeTab === 'documents'}
			<!-- Documents View -->
			<div class="flex-1 overflow-y-auto">
				<div class="mx-auto max-w-4xl px-6 py-8">
					<SearchBar />

					{#if $search.loading}
						<div class="mt-8 space-y-4">
							<div class="skeleton h-32 w-full"></div>
							<div class="skeleton h-24 w-full"></div>
							<div class="skeleton h-24 w-full"></div>
						</div>
					{:else if $search.error}
						<div
							class="mt-8 rounded-lg border border-red-200 bg-red-50 p-6 text-center text-red-700"
						>
							<p class="font-medium">Search failed</p>
							<p class="mt-1 text-sm">{$search.error}</p>
						</div>
					{:else if $search.response}
						<div class="mt-8 space-y-6">
							<AnswerCard />
							<SourcesPanel />
						</div>
					{:else}
						<div class="mt-16 text-center">
							<div
								class="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-gray-100"
							>
								<svg
									class="h-8 w-8 text-gray-400"
									fill="none"
									stroke="currentColor"
									viewBox="0 0 24 24"
								>
									<path
										stroke-linecap="round"
										stroke-linejoin="round"
										stroke-width="2"
										d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
									></path>
								</svg>
							</div>
							<h2 class="mt-4 text-lg font-medium text-[var(--color-text-primary)]">
								Search your documents
							</h2>
							<p class="mt-2 text-sm text-[var(--color-text-secondary)]">
								Ask questions about your legal and compliance documents
							</p>

							<div class="mt-8">
								<p
									class="mb-3 text-xs font-medium uppercase tracking-wide text-[var(--color-text-secondary)]"
								>
									Try asking
								</p>
								<div class="flex flex-wrap justify-center gap-2">
									<button
										onclick={() => search.search('What are the GDPR requirements for data deletion?')}
										class="rounded-full border border-[var(--color-border)] bg-white px-4 py-2 text-sm text-[var(--color-text-primary)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
									>
										GDPR data deletion requirements
									</button>
									<button
										onclick={() => search.search('How long is the confidentiality period in the NDA?')}
										class="rounded-full border border-[var(--color-border)] bg-white px-4 py-2 text-sm text-[var(--color-text-primary)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
									>
										NDA confidentiality period
									</button>
									<button
										onclick={() => search.search("What are the data processor's obligations?")}
										class="rounded-full border border-[var(--color-border)] bg-white px-4 py-2 text-sm text-[var(--color-text-primary)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
									>
										Data processor obligations
									</button>
								</div>
							</div>
						</div>
					{/if}
				</div>
			</div>
		{:else}
			<!-- Videos View -->
			<div class="flex flex-1 overflow-hidden">
				<!-- Search Results -->
				<div class="flex-1 overflow-y-auto">
					<div class="mx-auto max-w-3xl px-6 py-8">
						<VideoSearchBar />

						{#if $videoSearch.loading}
							<div class="mt-8 space-y-4">
								<div class="skeleton h-40 w-full rounded-lg"></div>
								<div class="skeleton h-40 w-full rounded-lg"></div>
							</div>
						{:else if $videoSearch.error}
							<div
								class="mt-8 rounded-lg border border-red-200 bg-red-50 p-6 text-center text-red-700"
							>
								<p class="font-medium">Search failed</p>
								<p class="mt-1 text-sm">{$videoSearch.error}</p>
							</div>
						{:else if $videoSearch.response && $videoSearch.response.videos.length > 0}
							<div class="mt-8 space-y-4">
								<p class="text-sm text-[var(--color-text-secondary)]">
									Found {$videoSearch.response.total_matches} matches in {$videoSearch.response
										.total_videos} videos
								</p>
								{#each $videoSearch.response.videos as result (result.video_id)}
									<VideoResultCard
										{result}
										selectedMatchId={$videoPlayer.selectedMatch?.chunk_id}
										onSelectMatch={(match) => handleVideoMatchSelect(result, match)}
									/>
								{/each}
							</div>
						{:else if $videoSearch.response && $videoSearch.response.videos.length === 0}
							<div class="mt-16 text-center">
								<p class="text-[var(--color-text-secondary)]">
									No matches found. Try different search terms.
								</p>
							</div>
						{:else}
							<!-- Empty State -->
							<div class="mt-16 text-center">
								<div
									class="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-gray-100"
								>
									<svg
										class="h-8 w-8 text-gray-400"
										fill="none"
										stroke="currentColor"
										viewBox="0 0 24 24"
									>
										<path
											stroke-linecap="round"
											stroke-linejoin="round"
											stroke-width="2"
											d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"
										></path>
									</svg>
								</div>
								<h2 class="mt-4 text-lg font-medium text-[var(--color-text-primary)]">
									Search your videos
								</h2>
								<p class="mt-2 text-sm text-[var(--color-text-secondary)]">
									Find specific moments by searching transcripts, scene descriptions, and on-screen
									text
								</p>

								<div class="mt-8">
									<p
										class="mb-3 text-xs font-medium uppercase tracking-wide text-[var(--color-text-secondary)]"
									>
										Try searching
									</p>
									<div class="flex flex-wrap justify-center gap-2">
										{#each videoExampleQueries as query}
											<button
												onclick={() => videoSearch.search(query)}
												class="rounded-full border border-[var(--color-border)] bg-white px-4 py-2 text-sm text-[var(--color-text-primary)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
											>
												{query}
											</button>
										{/each}
									</div>
								</div>
							</div>
						{/if}
					</div>
				</div>

				<!-- Video Player Panel -->
				<VideoPlayerPanel />
			</div>
		{/if}
	</div>
</div>

<!-- Upload Modals -->
{#if $upload.modalOpen}
	<UploadModal />
{/if}

{#if $videoUpload.modalOpen}
	<VideoUploadModal />
{/if}
```

**Step 2: Verify page compiles**

Run: `cd frontend && npm run check`
Expected: No errors

**Step 3: Commit**

```bash
git add frontend/src/routes/+page.svelte
git commit -m "feat(frontend): integrate video tab view into main page"
```

---

## Task 16: Update Layout for Context-Aware Upload

**Files:**
- Modify: `frontend/src/routes/+layout.svelte`

**Step 1: Read current layout**

First read the current layout file to understand its structure.

**Step 2: Update layout to handle both upload types**

Update the layout to open the appropriate upload modal based on active tab:

```svelte
<script lang="ts">
	import '../app.css';
	import { Upload, Search } from 'lucide-svelte';
	import { page } from '$app/stores';
	import { upload } from '$lib/stores/upload';
	import { videoUpload } from '$lib/stores/videos';

	let { children } = $props();

	// Determine active tab from URL
	const activeTab = $derived($page.url.searchParams.get('tab') || 'documents');

	function handleUploadClick() {
		if (activeTab === 'videos') {
			videoUpload.openModal();
		} else {
			upload.openModal();
		}
	}
</script>

<div class="flex min-h-screen flex-col bg-[var(--color-background)]">
	<!-- Header -->
	<header class="sticky top-0 z-40 border-b border-[var(--color-border)] bg-[var(--color-surface)]">
		<div class="flex h-16 items-center justify-between px-6">
			<!-- Logo -->
			<div class="flex items-center gap-3">
				<div class="flex h-8 w-8 items-center justify-center rounded-lg bg-[var(--color-accent)]">
					<Search class="h-4 w-4 text-white" />
				</div>
				<span class="text-lg font-semibold text-[var(--color-text-primary)]">RAG Demo</span>
			</div>

			<!-- Actions -->
			<div class="flex items-center gap-4">
				<button
					onclick={handleUploadClick}
					class="flex items-center gap-2 rounded-lg bg-[var(--color-accent)] px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-[var(--color-accent-hover)]"
				>
					<Upload class="h-4 w-4" />
					Upload
				</button>
			</div>
		</div>
	</header>

	<!-- Main Content -->
	<main class="flex-1">
		{@render children()}
	</main>
</div>
```

**Step 3: Verify layout compiles**

Run: `cd frontend && npm run check`
Expected: No errors

**Step 4: Commit**

```bash
git add frontend/src/routes/+layout.svelte
git commit -m "feat(frontend): update layout for context-aware upload button"
```

---

## Task 17: Final Integration Test

**Step 1: Run type check**

Run: `cd frontend && npm run check`
Expected: All checks pass

**Step 2: Start dev server**

Run: `cd frontend && npm run dev`
Expected: Server starts without errors

**Step 3: Manual testing checklist**

Open http://localhost:5173 and verify:

- [ ] Documents tab is active by default
- [ ] Clicking Videos tab switches view and updates URL
- [ ] Sidebar changes based on active tab
- [ ] Upload button opens correct modal per tab
- [ ] Video search bar accepts input
- [ ] Empty states display correctly

**Step 4: Commit final integration**

```bash
git add -A
git commit -m "feat(frontend): complete video RAG frontend integration"
```

---

## Summary

This plan implements 17 tasks covering:

1. **Types** (Task 1): Video API types in types.ts
2. **API Layer** (Tasks 2-3): Retrieval proxy route, video API client
3. **State Management** (Tasks 4-5): Videos store, video search/player stores
4. **Server Routes** (Task 6): Video upload endpoint
5. **Components** (Tasks 7-14): ContentTabs, VideoItem, VideoSidebar, VideoUploadModal, TimelineStrip, VideoResultCard, VideoPlayerPanel, VideoSearchBar
6. **Integration** (Tasks 15-17): Main page update, layout update, final testing

Each task is atomic with clear verification steps and commits.
