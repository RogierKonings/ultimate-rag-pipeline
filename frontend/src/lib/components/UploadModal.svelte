<script lang="ts">
	import { X, Upload, FileText, AlertCircle, Loader2, AlertTriangle, Pencil } from 'lucide-svelte';
	import { upload } from '$lib/stores/upload';
	import { documents } from '$lib/stores/documents';
	import {
		ALLOWED_UPLOAD_EXTENSIONS,
		MAX_UPLOAD_FILE_SIZE_MB,
		buildQueuedFilesForUpload,
		collectFinalizedFilenames,
		formatFileSize,
		generateSuggestedFilename,
		getFileExtension,
		stripFileExtension
	} from '$lib/utils/uploadQueue';

	let dragOver = $state(false);
	let inputElement: HTMLInputElement;
	let renameInputElement: HTMLInputElement | undefined = $state(undefined);

	const existingFilenames = $derived(new Set($documents.documents.map((doc) => doc.filename)));

	const validFiles = $derived($upload.queuedFiles.filter((f) => f.status === 'valid'));
	const hasRenamePending = $derived($upload.queuedFiles.some((f) => f.status === 'rename_pending'));
	const hasValidFiles = $derived(validFiles.length > 0 && !hasRenamePending);

	// Track the file currently being renamed via inline dialog
	let renamingFileId = $state<string | null>(null);
	let renameValue = $state('');

	function handleClose() {
		upload.closeModal();
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			if (renamingFileId) {
				// Cancel rename on Escape
				handleCancelRename(renamingFileId);
			} else {
				handleClose();
			}
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
		// Reset input so same files can be selected again
		target.value = '';
	}

	function processFiles(files: File[]) {
		const { queuedFiles, firstRename } = buildQueuedFilesForUpload({
			files,
			existingFilenames,
			queuedFiles: $upload.queuedFiles
		});

		upload.addFiles(queuedFiles);

		if (firstRename) {
			openRenameDialog(firstRename.id, firstRename.suggestedName || firstRename.file.name);
		}
	}

	function openRenameDialog(fileId: string, suggested: string) {
		renamingFileId = fileId;
		renameValue = stripFileExtension(suggested);
		setTimeout(() => renameInputElement?.focus(), 50);
	}

	function openNextRenameDialog(skipFileId?: string) {
		const nextRename = $upload.queuedFiles.find(
			(file) => file.status === 'rename_pending' && file.id !== skipFileId
		);
		if (nextRename) {
			openRenameDialog(nextRename.id, nextRename.suggestedName || nextRename.file.name);
		}
	}

	function handleConfirmRename(fileId: string) {
		const qf = $upload.queuedFiles.find((f) => f.id === fileId);
		if (!qf) return;

		const renameBase = renameValue.trim();
		if (!renameBase) return;

		const extension = getFileExtension(qf.file.name);
		const newName = `${renameBase}${extension}`;

		const allKnownNames = collectFinalizedFilenames(existingFilenames, $upload.queuedFiles, fileId);

		if (allKnownNames.has(newName)) {
			const better = generateSuggestedFilename(newName, allKnownNames);
			renameValue = stripFileExtension(better);
			return;
		}

		upload.confirmRename(fileId, newName);
		renamingFileId = null;
		renameValue = '';
		openNextRenameDialog(fileId);
	}

	function handleCancelRename(fileId: string) {
		upload.removeQueuedFile(fileId);
		renamingFileId = null;
		renameValue = '';
		openNextRenameDialog();
	}

	function handleRenameKeydown(e: KeyboardEvent, fileId: string) {
		if (e.key === 'Enter') {
			e.preventDefault();
			handleConfirmRename(fileId);
		} else if (e.key === 'Escape') {
			e.preventDefault();
			handleCancelRename(fileId);
		}
	}

	function handleUploadAll() {
		const filesToUpload = validFiles.map((qf) => ({
			file: qf.file,
			customName: qf.customName
		}));
		upload.uploadBatch(filesToUpload);
	}

	function handleBrowseClick() {
		inputElement?.click();
	}
</script>

<!-- Backdrop -->
<div
	class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
	onclick={handleBackdropClick}
	onkeydown={handleKeydown}
	role="dialog"
	aria-modal="true"
	aria-labelledby="upload-title"
	tabindex="-1"
>
	<!-- Modal -->
	<div class="w-full max-w-lg rounded-xl bg-[var(--color-surface)] shadow-xl" role="document">
		<!-- Header -->
		<div
			class="flex items-center justify-between border-b border-[var(--color-border)] px-6 py-4"
		>
			<h2 id="upload-title" class="text-lg font-semibold text-[var(--color-text-primary)]">
				Upload Documents
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
			{#if $upload.queuedFiles.length > 0}
				<div class="mb-4 max-h-48 overflow-y-auto rounded-lg border border-[var(--color-border)]">
					{#each $upload.queuedFiles as queuedFile (queuedFile.id)}
						<div
							class="border-b border-[var(--color-border)] last:border-b-0"
						>
							<!-- Normal file row -->
							{#if queuedFile.status !== 'rename_pending' || renamingFileId !== queuedFile.id}
								<div class="flex items-center gap-3 px-3 py-2">
									{#if queuedFile.status === 'valid'}
										<FileText class="h-4 w-4 shrink-0 text-[var(--color-accent)]" />
									{:else if queuedFile.status === 'rename_pending'}
										<Pencil class="h-4 w-4 shrink-0 text-amber-500" />
									{:else}
										<AlertTriangle class="h-4 w-4 shrink-0 text-amber-500" />
									{/if}

									<div class="min-w-0 flex-1">
										<p
											class="truncate text-sm font-medium {queuedFile.status === 'invalid'
												? 'text-[var(--color-text-secondary)]'
												: queuedFile.status === 'rename_pending'
													? 'text-amber-700'
													: 'text-[var(--color-text-primary)]'}"
										>
											{queuedFile.customName || queuedFile.file.name}
										</p>
										{#if queuedFile.status === 'valid' && queuedFile.customName}
											<p class="text-xs text-[var(--color-text-secondary)]">
												Originally: {queuedFile.file.name} · {formatFileSize(queuedFile.file.size)}
											</p>
										{:else if queuedFile.error}
											<p class="text-xs text-amber-600">{queuedFile.error}</p>
										{:else if queuedFile.status === 'rename_pending'}
											<p class="text-xs text-amber-600">Duplicate name — waiting for rename</p>
										{:else}
											<p class="text-xs text-[var(--color-text-secondary)]">
												{formatFileSize(queuedFile.file.size)}
											</p>
										{/if}
									</div>

									<button
										onclick={() => upload.removeQueuedFile(queuedFile.id)}
										class="shrink-0 rounded p-1 text-[var(--color-text-secondary)] hover:bg-gray-100 hover:text-[var(--color-text-primary)]"
										aria-label="Remove file"
									>
										<X class="h-4 w-4" />
									</button>
								</div>
							{/if}

							<!-- Inline rename dialog -->
							{#if queuedFile.status === 'rename_pending' && renamingFileId === queuedFile.id}
								<div class="bg-amber-50 px-3 py-3">
									<div class="mb-2 flex items-center gap-2">
										<AlertTriangle class="h-4 w-4 shrink-0 text-amber-500" />
										<p class="text-sm font-medium text-amber-800">
											"{queuedFile.file.name}" already exists
										</p>
									</div>
									<p class="mb-2 text-xs text-amber-700">
										Please choose a new name for this document:
									</p>
									<div class="flex items-center gap-2">
										<div class="relative flex-1">
											<input
												bind:this={renameInputElement}
												type="text"
												bind:value={renameValue}
												onkeydown={(e) => handleRenameKeydown(e, queuedFile.id)}
												class="w-full rounded-md border border-amber-300 bg-white px-3 py-1.5 text-sm text-[var(--color-text-primary)] outline-none focus:border-[var(--color-accent)] focus:ring-1 focus:ring-[var(--color-accent)]"
												aria-label="New filename"
											/>
											<span class="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-[var(--color-text-secondary)]">
												{getFileExtension(queuedFile.file.name)}
											</span>
										</div>
									</div>
									<div class="mt-2 flex justify-end gap-2">
										<button
											onclick={() => handleCancelRename(queuedFile.id)}
											class="rounded-md px-3 py-1 text-xs font-medium text-[var(--color-text-secondary)] hover:bg-amber-100"
										>
											Cancel
										</button>
										<button
											onclick={() => handleConfirmRename(queuedFile.id)}
											class="rounded-md bg-[var(--color-accent)] px-3 py-1 text-xs font-medium text-white hover:bg-[var(--color-accent-hover)]"
										>
											OK
										</button>
									</div>
								</div>
							{/if}
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
				aria-label="File drop zone"
			>
				<input
					bind:this={inputElement}
					type="file"
					accept={ALLOWED_UPLOAD_EXTENSIONS.join(',')}
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
						PDF, DOCX, TXT, or MD (max {MAX_UPLOAD_FILE_SIZE_MB}MB each)
					</p>
				</div>
			</div>

			<!-- Error Message -->
			{#if $upload.uploadError}
				<div
					class="mt-4 flex items-center gap-2 rounded-lg bg-red-50 p-3 text-sm text-red-700"
					role="alert"
				>
					<AlertCircle class="h-4 w-4 shrink-0" />
					<span>{$upload.uploadError}</span>
				</div>
			{/if}
		</div>

		<!-- Footer -->
		<div class="flex justify-end gap-3 border-t border-[var(--color-border)] px-6 py-4">
			<button
				onclick={handleClose}
				disabled={$upload.uploading}
				class="rounded-lg px-4 py-2 text-sm font-medium text-[var(--color-text-secondary)] hover:bg-gray-100 disabled:opacity-50"
			>
				Cancel
			</button>
			<button
				onclick={handleUploadAll}
				disabled={!hasValidFiles || $upload.uploading}
				class="flex items-center gap-2 rounded-lg bg-[var(--color-accent)] px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-[var(--color-accent-hover)] disabled:cursor-not-allowed disabled:opacity-50"
			>
				{#if $upload.uploading}
					<Loader2 class="h-4 w-4 animate-spin" />
					Uploading...
				{:else}
					<Upload class="h-4 w-4" />
					{#if validFiles.length === 1}
						Upload File
					{:else if validFiles.length > 1}
						Upload {validFiles.length} Files
					{:else}
						Upload
					{/if}
				{/if}
			</button>
		</div>
	</div>
</div>
