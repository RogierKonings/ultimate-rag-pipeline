import type { QueuedVideoFile } from '$lib/api/types';

export const ALLOWED_VIDEO_UPLOAD_EXTENSIONS = ['.mp4', '.mov', '.avi', '.mkv', '.webm'] as const;
export const MAX_VIDEO_UPLOAD_SIZE_GB = 5;
const ALLOWED_VIDEO_UPLOAD_EXTENSION_SET = new Set<string>(ALLOWED_VIDEO_UPLOAD_EXTENSIONS);

type QueueBuildParams = {
	files: File[];
	existingFilenames: Iterable<string>;
	queuedFiles: QueuedVideoFile[];
};

export function getVideoFileExtension(filename: string): string {
	const dotIndex = filename.lastIndexOf('.');
	if (dotIndex <= 0 || dotIndex === filename.length - 1) {
		return '';
	}

	return filename.slice(dotIndex).toLowerCase();
}

export function collectKnownVideoFilenames(
	existingFilenames: Iterable<string>,
	queuedFiles: QueuedVideoFile[]
): Set<string> {
	return new Set([
		...existingFilenames,
		...queuedFiles.filter((file) => file.status === 'valid').map((file) => file.file.name)
	]);
}

export function buildQueuedVideoFilesForUpload({
	files,
	existingFilenames,
	queuedFiles
}: QueueBuildParams): QueuedVideoFile[] {
	const batchFilenames = new Set<string>();
	const knownFilenames = collectKnownVideoFilenames(existingFilenames, queuedFiles);

	return files.map((file) => {
		const extension = getVideoFileExtension(file.name);
		let status: QueuedVideoFile['status'] = 'valid';
		let error: string | undefined;

		if (!ALLOWED_VIDEO_UPLOAD_EXTENSION_SET.has(extension)) {
			status = 'invalid';
			error = 'Invalid file type';
		} else if (file.size > MAX_VIDEO_UPLOAD_SIZE_GB * 1024 * 1024 * 1024) {
			status = 'invalid';
			error = `Exceeds ${MAX_VIDEO_UPLOAD_SIZE_GB}GB limit`;
		} else if (knownFilenames.has(file.name)) {
			status = 'invalid';
			error = 'Video already exists';
		} else if (batchFilenames.has(file.name)) {
			status = 'invalid';
			error = 'Duplicate in batch';
		}

		batchFilenames.add(file.name);
		if (status === 'valid') {
			knownFilenames.add(file.name);
		}

		return {
			id: crypto.randomUUID(),
			file,
			status,
			error
		};
	});
}

export function formatVideoFileSize(bytes: number): string {
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
	if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
	return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}
