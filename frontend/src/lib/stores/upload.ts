import { writable, derived } from 'svelte/store';
import type { JobStatusResponse, QueuedFile } from '$lib/api/types';
import { pollJobStatus } from '$lib/api/ingestion';
import { documents } from './documents';

type UploadApiResponse = {
	job_id: string;
};

type UploadQueueItem = {
	file: File;
	customName?: string;
};

export interface UploadJob {
	id: string;
	jobId: string;
	filename: string;
	status: 'pending' | 'uploading' | 'processing' | 'completed' | 'failed';
	progress: number;
	error: string | null;
	startedAt: Date;
	completedAt: Date | null;
}

interface UploadState {
	jobs: UploadJob[];
	modalOpen: boolean;
	currentFile: File | null;
	queuedFiles: QueuedFile[];
	uploading: boolean;
	uploadingIndex: number;
	uploadError: string | null;
}

function updateJobById(
	jobs: UploadJob[],
	jobId: string,
	updater: (job: UploadJob) => UploadJob
): UploadJob[] {
	return jobs.map((job) => (job.id === jobId ? updater(job) : job));
}

function createUploadJob(
	jobId: string,
	file: File,
	customName?: string,
	status: UploadJob['status'] = 'pending'
): UploadJob {
	return {
		id: jobId,
		jobId: '',
		filename: customName || file.name,
		status,
		progress: 0,
		error: null,
		startedAt: new Date(),
		completedAt: null
	};
}

function parseErrorMessage(error: unknown, fallback: string): string {
	return error instanceof Error ? error.message : fallback;
}

async function uploadToApi(file: File, customName?: string): Promise<UploadApiResponse> {
	const formData = new FormData();
	formData.append('file', file);
	if (customName) {
		formData.append('customName', customName);
	}

	const response = await fetch('/api/upload', {
		method: 'POST',
		body: formData
	});

	if (!response.ok) {
		const body = (await response.json().catch(() => ({}))) as { message?: string };
		throw new Error(body.message || 'Upload failed');
	}

	return (await response.json()) as UploadApiResponse;
}

function createUploadStore() {
	const { subscribe, update } = writable<UploadState>({
		jobs: [],
		modalOpen: false,
		currentFile: null,
		queuedFiles: [],
		uploading: false,
		uploadingIndex: -1,
		uploadError: null
	});

	const patchJob = (jobId: string, patch: Partial<UploadJob>) => {
		update((state) => ({
			...state,
			jobs: updateJobById(state.jobs, jobId, (job) => ({ ...job, ...patch }))
		}));
	};

	const failJob = (jobId: string, message: string) => {
		patchJob(jobId, { status: 'failed', error: message });
	};

	const beginProcessing = (jobId: string, serverJobId: string) => {
		patchJob(jobId, { jobId: serverJobId, status: 'processing', progress: 10 });
	};

	const pollJob = async (localId: string, serverJobId: string) => {
		try {
			await pollJobStatus(
				serverJobId,
				(status: JobStatusResponse) => {
					const progress = status.progress?.percentage ?? 50;
					patchJob(localId, { progress: Math.max(10, progress) });
				},
				2000
			);

			patchJob(localId, {
				status: 'completed',
				progress: 100,
				completedAt: new Date()
			});
			documents.fetch();
		} catch (error) {
			failJob(localId, parseErrorMessage(error, 'Processing failed'));
		}
	};

	const startUpload = async (localId: string, item: UploadQueueItem) => {
		const result = await uploadToApi(item.file, item.customName);
		beginProcessing(localId, result.job_id);
		void pollJob(localId, result.job_id);
	};

	return {
		subscribe,

		openModal() {
			update((state) => ({
				...state,
				modalOpen: true,
				currentFile: null,
				queuedFiles: [],
				uploadError: null
			}));
		},

		closeModal() {
			update((state) => ({
				...state,
				modalOpen: false,
				currentFile: null,
				queuedFiles: [],
				uploadError: null
			}));
		},

		setFile(file: File | null) {
			update((state) => ({ ...state, currentFile: file, uploadError: null }));
		},

		addFiles(files: QueuedFile[]) {
			update((state) => ({
				...state,
				queuedFiles: [...state.queuedFiles, ...files],
				uploadError: null
			}));
		},

		confirmRename(fileId: string, newName: string) {
			update((state) => ({
				...state,
				queuedFiles: state.queuedFiles.map((file) =>
					file.id === fileId
						? { ...file, status: 'valid', customName: newName, suggestedName: undefined }
						: file
				)
			}));
		},

		removeQueuedFile(id: string) {
			update((state) => ({
				...state,
				queuedFiles: state.queuedFiles.filter((file) => file.id !== id)
			}));
		},

		clearQueue() {
			update((state) => ({ ...state, queuedFiles: [], uploadError: null }));
		},

		async upload(file: File) {
			update((state) => ({ ...state, uploading: true, uploadError: null }));

			const localId = crypto.randomUUID();
			const uploadJob = createUploadJob(localId, file, undefined, 'uploading');
			update((state) => ({
				...state,
				jobs: [uploadJob, ...state.jobs]
			}));

			try {
				await startUpload(localId, { file });
				update((state) => ({
					...state,
					uploading: false,
					modalOpen: false,
					currentFile: null
				}));
			} catch (error) {
				const message = parseErrorMessage(error, 'Upload failed');
				update((state) => ({
					...state,
					uploading: false,
					uploadError: message,
					jobs: updateJobById(state.jobs, localId, (job) => ({
						...job,
						status: 'failed',
						error: message
					}))
				}));
			}
		},

		async uploadBatch(files: UploadQueueItem[]) {
			if (files.length === 0) return;

			const jobsToCreate = files.map(({ file, customName }) =>
				createUploadJob(crypto.randomUUID(), file, customName)
			);

			update((state) => ({
				...state,
				uploading: true,
				uploadingIndex: 0,
				modalOpen: false,
				queuedFiles: [],
				jobs: [...jobsToCreate, ...state.jobs]
			}));

			for (const [index, item] of files.entries()) {
				const localId = jobsToCreate[index].id;

				update((state) => ({
					...state,
					uploadingIndex: index,
					jobs: updateJobById(state.jobs, localId, (job) => ({
						...job,
						status: 'uploading'
					}))
				}));

				try {
					await startUpload(localId, item);
				} catch (error) {
					failJob(localId, parseErrorMessage(error, 'Upload failed'));
				}
			}

			update((state) => ({
				...state,
				uploading: false,
				uploadingIndex: -1
			}));
		},

		pollJob,

		removeJob(id: string) {
			update((state) => ({
				...state,
				jobs: state.jobs.filter((job) => job.id !== id)
			}));
		},

		clearCompleted() {
			update((state) => ({
				...state,
				jobs: state.jobs.filter((job) => job.status !== 'completed' && job.status !== 'failed')
			}));
		}
	};
}

export const upload = createUploadStore();

export const activeJobs = derived(upload, ($upload) =>
	$upload.jobs.filter(
		(job) => job.status === 'pending' || job.status === 'uploading' || job.status === 'processing'
	)
);

export const recentJobs = derived(upload, ($upload) => {
	const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000);
	return $upload.jobs.filter((job) => job.startedAt > oneHourAgo);
});
