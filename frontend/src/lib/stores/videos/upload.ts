import { derived, writable } from 'svelte/store';
import type { QueuedVideoFile, VideoStatusResponse } from '$lib/api/types';
import { pollVideoStatus } from '$lib/api/video';
import { videos } from './catalog';

type VideoUploadApiResponse = {
	video_id: string;
};

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

function updateJobById(
	jobs: VideoUploadJob[],
	jobId: string,
	updater: (job: VideoUploadJob) => VideoUploadJob
): VideoUploadJob[] {
	return jobs.map((job) => (job.id === jobId ? updater(job) : job));
}

function createVideoUploadJob(
	jobId: string,
	file: File,
	status: VideoUploadJob['status'] = 'pending'
): VideoUploadJob {
	return {
		id: jobId,
		videoId: '',
		filename: file.name,
		status,
		processingStage: null,
		progress: 0,
		error: null,
		startedAt: new Date(),
		completedAt: null
	};
}

function parseErrorMessage(error: unknown, fallback: string): string {
	return error instanceof Error ? error.message : fallback;
}

async function uploadVideoToApi(file: File): Promise<VideoUploadApiResponse> {
	const formData = new FormData();
	formData.append('file', file);

	const response = await fetch('/api/upload/video', {
		method: 'POST',
		body: formData
	});

	if (!response.ok) {
		const body = (await response.json().catch(() => ({}))) as { message?: string };
		throw new Error(body.message || 'Upload failed');
	}

	return (await response.json()) as VideoUploadApiResponse;
}

function createVideoUploadStore() {
	const { subscribe, update } = writable<VideoUploadState>({
		jobs: [],
		modalOpen: false,
		queuedFiles: [],
		uploading: false,
		uploadError: null
	});

	const patchJob = (jobId: string, patch: Partial<VideoUploadJob>) => {
		update((state) => ({
			...state,
			jobs: updateJobById(state.jobs, jobId, (job) => ({ ...job, ...patch }))
		}));
	};

	const failJob = (jobId: string, message: string) => {
		patchJob(jobId, { status: 'failed', error: message });
	};

	const beginProcessing = (jobId: string, videoId: string) => {
		patchJob(jobId, { videoId, status: 'processing', progress: 10 });
	};

	const pollVideoJob = async (localId: string, videoId: string) => {
		try {
			await pollVideoStatus(
				videoId,
				(status: VideoStatusResponse) => {
					patchJob(localId, {
						processingStage: status.processing_stage,
						progress: Math.max(10, status.processing_progress)
					});
				},
				3000
			);

			patchJob(localId, {
				status: 'completed',
				progress: 100,
				completedAt: new Date()
			});
			videos.fetch();
		} catch (error) {
			failJob(localId, parseErrorMessage(error, 'Processing failed'));
		}
	};

	const startUpload = async (localId: string, file: File) => {
		const result = await uploadVideoToApi(file);
		beginProcessing(localId, result.video_id);
		void pollVideoJob(localId, result.video_id);
	};

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
			update((state) => ({
				...state,
				queuedFiles: [...state.queuedFiles, ...files],
				uploadError: null
			}));
		},

		removeQueuedFile(id: string) {
			update((state) => ({
				...state,
				queuedFiles: state.queuedFiles.filter((file) => file.id !== id)
			}));
		},

		async uploadBatch(files: File[]) {
			if (files.length === 0) return;

			const jobsToCreate = files.map((file) => createVideoUploadJob(crypto.randomUUID(), file));

			update((state) => ({
				...state,
				uploading: true,
				modalOpen: false,
				queuedFiles: [],
				jobs: [...jobsToCreate, ...state.jobs]
			}));

			for (const [index, file] of files.entries()) {
				const localId = jobsToCreate[index].id;
				patchJob(localId, { status: 'uploading' });

				try {
					await startUpload(localId, file);
				} catch (error) {
					failJob(localId, parseErrorMessage(error, 'Upload failed'));
				}
			}

			update((state) => ({
				...state,
				uploading: false
			}));
		},

		pollVideoJob,

		removeJob(id: string) {
			update((state) => ({
				...state,
				jobs: state.jobs.filter((job) => job.id !== id)
			}));
		}
	};
}

export const videoUpload = createVideoUploadStore();

export const activeVideoJobs = derived(videoUpload, ($upload) =>
	$upload.jobs.filter(
		(job) => job.status === 'pending' || job.status === 'uploading' || job.status === 'processing'
	)
);
