import { writable, derived } from 'svelte/store';
import type { JobStatusResponse, QueuedFile } from '$lib/api/types';
import { pollJobStatus } from '$lib/api/ingestion';
import { documents } from './documents';

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

function createUploadStore() {
	const { subscribe, set, update } = writable<UploadState>({
		jobs: [],
		modalOpen: false,
		currentFile: null,
		queuedFiles: [],
		uploading: false,
		uploadingIndex: -1,
		uploadError: null
	});

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
			update((state) => {
				// Filter out duplicates by filename
				const existingNames = new Set(state.queuedFiles.map((f) => f.file.name));
				const newFiles = files.filter((f) => !existingNames.has(f.file.name));
				return {
					...state,
					queuedFiles: [...state.queuedFiles, ...newFiles],
					uploadError: null
				};
			});
		},

		confirmRename(fileId: string, newName: string) {
			update((state) => ({
				...state,
				queuedFiles: state.queuedFiles.map((f) =>
					f.id === fileId
						? { ...f, status: 'valid' as const, customName: newName, suggestedName: undefined }
						: f
				)
			}));
		},

		removeQueuedFile(id: string) {
			update((state) => ({
				...state,
				queuedFiles: state.queuedFiles.filter((f) => f.id !== id)
			}));
		},

		clearQueue() {
			update((state) => ({ ...state, queuedFiles: [], uploadError: null }));
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

		async uploadBatch(files: Array<{ file: File; customName?: string }>) {
			if (files.length === 0) return;

			// Create all jobs upfront with 'pending' status
			const jobsToCreate: UploadJob[] = files.map(({ file, customName }) => ({
				id: crypto.randomUUID(),
				jobId: '',
				filename: customName || file.name,
				status: 'pending' as const,
				progress: 0,
				error: null,
				startedAt: new Date(),
				completedAt: null
			}));

			// Add all jobs to the list
			update((state) => ({
				...state,
				uploading: true,
				uploadingIndex: 0,
				modalOpen: false,
				queuedFiles: [],
				jobs: [...jobsToCreate, ...state.jobs]
			}));

			// Process files sequentially
			for (let i = 0; i < files.length; i++) {
				const { file, customName } = files[i];
				const jobId = jobsToCreate[i].id;

				update((state) => ({
					...state,
					uploadingIndex: i,
					jobs: state.jobs.map((job) =>
						job.id === jobId ? { ...job, status: 'uploading' as const } : job
					)
				}));

				try {
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
						const error = await response.json();
						throw new Error(error.message || 'Upload failed');
					}

					const result = await response.json();

					// Update job with server response
					update((state) => ({
						...state,
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

					// Start polling for job status (don't await - let it run in background)
					this.pollJob(jobId, result.job_id);
				} catch (error) {
					const message = error instanceof Error ? error.message : 'Upload failed';
					update((state) => ({
						...state,
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
			}

			// All uploads initiated
			update((state) => ({
				...state,
				uploading: false,
				uploadingIndex: -1
			}));
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
	$upload.jobs.filter(
		(job) => job.status === 'pending' || job.status === 'uploading' || job.status === 'processing'
	)
);

// Derived store for recent jobs (last hour)
export const recentJobs = derived(upload, ($upload) => {
	const oneHourAgo = new Date(Date.now() - 60 * 60 * 1000);
	return $upload.jobs.filter((job) => job.startedAt > oneHourAgo);
});
