import { writable, derived } from 'svelte/store';
import type { JobStatusResponse } from '$lib/api/types';
import { pollJobStatus } from '$lib/api/ingestion';
import { documents } from './documents';

export interface UploadJob {
	id: string;
	jobId: string;
	filename: string;
	status: 'uploading' | 'processing' | 'completed' | 'failed';
	progress: number;
	error: string | null;
	startedAt: Date;
	completedAt: Date | null;
}

interface UploadState {
	jobs: UploadJob[];
	modalOpen: boolean;
	currentFile: File | null;
	uploading: boolean;
	uploadError: string | null;
}

function createUploadStore() {
	const { subscribe, set, update } = writable<UploadState>({
		jobs: [],
		modalOpen: false,
		currentFile: null,
		uploading: false,
		uploadError: null
	});

	return {
		subscribe,

		openModal() {
			update((state) => ({ ...state, modalOpen: true, currentFile: null, uploadError: null }));
		},

		closeModal() {
			update((state) => ({ ...state, modalOpen: false, currentFile: null, uploadError: null }));
		},

		setFile(file: File | null) {
			update((state) => ({ ...state, currentFile: file, uploadError: null }));
		},

		async upload(file: File) {
			update((state) => ({ ...state, uploading: true, uploadError: null }));

			const jobId = crypto.randomUUID();
			const uploadJob: UploadJob = {
				id: jobId,
				jobId: '',
				filename: file.name,
				status: 'uploading',
				progress: 0,
				error: null,
				startedAt: new Date(),
				completedAt: null
			};

			// Add job to list
			update((state) => ({
				...state,
				jobs: [uploadJob, ...state.jobs]
			}));

			try {
				// Upload file to our SvelteKit API route
				const formData = new FormData();
				formData.append('file', file);

				const response = await fetch('/api/upload', {
					method: 'POST',
					body: formData
				});

				if (!response.ok) {
					const error = await response.json();
					throw new Error(error.message || 'Upload failed');
				}

				const result = await response.json();

				// Update job with server response
				update((state) => ({
					...state,
					uploading: false,
					modalOpen: false,
					currentFile: null,
					jobs: state.jobs.map((job) =>
						job.id === jobId
							? {
									...job,
									jobId: result.job_id,
									status: 'processing' as const,
									progress: 10
								}
							: job
					)
				}));

				// Start polling for job status
				this.pollJob(jobId, result.job_id);
			} catch (error) {
				const message = error instanceof Error ? error.message : 'Upload failed';
				update((state) => ({
					...state,
					uploading: false,
					uploadError: message,
					jobs: state.jobs.map((job) =>
						job.id === jobId
							? {
									...job,
									status: 'failed' as const,
									error: message
								}
							: job
					)
				}));
			}
		},

		async pollJob(localId: string, serverJobId: string) {
			try {
				await pollJobStatus(
					serverJobId,
					(status: JobStatusResponse) => {
						const progress = status.progress?.percentage ?? 50;
						update((state) => ({
							...state,
							jobs: state.jobs.map((job) =>
								job.id === localId
									? {
											...job,
											progress: Math.max(10, progress)
										}
									: job
							)
						}));
					},
					2000
				);

				// Job completed successfully
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

				// Refresh documents list
				documents.fetch();
			} catch (error) {
				const message = error instanceof Error ? error.message : 'Processing failed';
				update((state) => ({
					...state,
					jobs: state.jobs.map((job) =>
						job.id === localId
							? {
									...job,
									status: 'failed' as const,
									error: message
								}
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

// Derived store for active jobs
export const activeJobs = derived(upload, ($upload) =>
	$upload.jobs.filter((job) => job.status === 'uploading' || job.status === 'processing')
);

// Derived store for recent jobs (last hour)
export const recentJobs = derived(upload, ($upload) => {
	const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000);
	return $upload.jobs.filter((job) => job.startedAt > oneHourAgo);
});
