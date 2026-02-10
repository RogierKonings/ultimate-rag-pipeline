import type { QueuedFile } from '$lib/api/types';

export const ALLOWED_UPLOAD_EXTENSIONS = ['.pdf', '.docx', '.txt', '.md'] as const;
export const MAX_UPLOAD_FILE_SIZE_MB = 50;
const ALLOWED_UPLOAD_EXTENSION_SET = new Set<string>(ALLOWED_UPLOAD_EXTENSIONS);

type QueueBuildParams = {
	files: File[];
	existingFilenames: Iterable<string>;
	queuedFiles: QueuedFile[];
};

export function getFileExtension(filename: string): string {
	const dotIndex = filename.lastIndexOf('.');
	if (dotIndex <= 0 || dotIndex === filename.length - 1) {
		return '';
	}

	return filename.slice(dotIndex).toLowerCase();
}

export function stripFileExtension(filename: string): string {
	const dotIndex = filename.lastIndexOf('.');
	return dotIndex > 0 ? filename.slice(0, dotIndex) : filename;
}

export function getQueuedFilename(file: QueuedFile): string {
	return file.customName || file.file.name;
}

export function collectFinalizedFilenames(
	existingFilenames: Iterable<string>,
	queuedFiles: QueuedFile[],
	excludeFileId?: string
): Set<string> {
	return new Set([
		...existingFilenames,
		...queuedFiles
			.filter((file) => file.status === 'valid' && file.id !== excludeFileId)
			.map(getQueuedFilename)
	]);
}

export function generateSuggestedFilename(filename: string, allNames: Set<string>): string {
	const extension = getFileExtension(filename);
	const baseName = stripFileExtension(filename);
	const copyMatch = baseName.match(/^(.+)\s\((\d+)\)$/);
	const rootName = copyMatch ? copyMatch[1] : baseName;
	let counter = copyMatch ? Number.parseInt(copyMatch[2], 10) + 1 : 2;

	let suggested = `${rootName} (${counter})${extension}`;
	while (allNames.has(suggested)) {
		counter += 1;
		suggested = `${rootName} (${counter})${extension}`;
	}

	return suggested;
}

export function buildQueuedFilesForUpload({
	files,
	existingFilenames,
	queuedFiles
}: QueueBuildParams): { queuedFiles: QueuedFile[]; firstRename: QueuedFile | null } {
	const batchFilenames = new Set<string>();
	const allKnownNames = collectFinalizedFilenames(existingFilenames, queuedFiles);

	const nextQueuedFiles = files.map((file) => {
		const extension = getFileExtension(file.name);
		let status: QueuedFile['status'] = 'valid';
		let error: string | undefined;
		let suggestedName: string | undefined;

		if (!ALLOWED_UPLOAD_EXTENSION_SET.has(extension)) {
			status = 'invalid';
			error = 'Invalid file type';
		} else if (file.size > MAX_UPLOAD_FILE_SIZE_MB * 1024 * 1024) {
			status = 'invalid';
			error = `Exceeds ${MAX_UPLOAD_FILE_SIZE_MB}MB limit`;
		} else if (allKnownNames.has(file.name) || batchFilenames.has(file.name)) {
			status = 'rename_pending';
			suggestedName = generateSuggestedFilename(file.name, allKnownNames);
			allKnownNames.add(suggestedName);
		}

		batchFilenames.add(file.name);
		if (status === 'valid') {
			allKnownNames.add(file.name);
		}

		return {
			id: crypto.randomUUID(),
			file,
			status,
			error,
			suggestedName
		};
	});

	const firstRename = nextQueuedFiles.find((file) => file.status === 'rename_pending');

	return {
		queuedFiles: nextQueuedFiles,
		firstRename: firstRename ?? null
	};
}

export function formatFileSize(bytes: number): string {
	if (bytes < 1024) return `${bytes} B`;
	if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
	return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
