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

		removeVideos(videoIds: string[]) {
			const idsSet = new Set(videoIds);
			update((state) => ({
				...state,
				videos: state.videos.filter((v) => !idsSet.has(v.video_id))
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

// Selection store for batch operations
function createVideoSelectionStore() {
	const { subscribe, set, update } = writable<Set<string>>(new Set());

	return {
		subscribe,

		toggle(videoId: string) {
			update((selected) => {
				const newSelected = new Set(selected);
				if (newSelected.has(videoId)) {
					newSelected.delete(videoId);
				} else {
					newSelected.add(videoId);
				}
				return newSelected;
			});
		},

		select(videoId: string) {
			update((selected) => {
				const newSelected = new Set(selected);
				newSelected.add(videoId);
				return newSelected;
			});
		},

		deselect(videoId: string) {
			update((selected) => {
				const newSelected = new Set(selected);
				newSelected.delete(videoId);
				return newSelected;
			});
		},

		selectAll(videoIds: string[]) {
			set(new Set(videoIds));
		},

		deselectAll() {
			set(new Set());
		},

		isSelected(videoId: string): boolean {
			let result = false;
			subscribe((selected) => {
				result = selected.has(videoId);
			})();
			return result;
		}
	};
}

export const selectedVideos = createVideoSelectionStore();

// Derived store for selection count
export const selectedVideoCount = derived(selectedVideos, ($selected) => $selected.size);
