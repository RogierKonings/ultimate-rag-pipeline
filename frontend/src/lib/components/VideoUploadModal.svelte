<script lang="ts">
	import { X, Upload, Video, AlertCircle, Loader2, AlertTriangle } from 'lucide-svelte';
	import { videoUpload, videos } from '$lib/stores/videos';
	import {
		ALLOWED_VIDEO_UPLOAD_EXTENSIONS,
		MAX_VIDEO_UPLOAD_SIZE_GB,
		buildQueuedVideoFilesForUpload,
		formatVideoFileSize
	} from '$lib/utils/videoUploadQueue';

	let dragOver = $state(false);
	let inputElement: HTMLInputElement;

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
		const queuedFiles = buildQueuedVideoFilesForUpload({
			files,
			existingFilenames,
			queuedFiles: $videoUpload.queuedFiles
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
										{formatVideoFileSize(queuedFile.file.size)}
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
					accept={ALLOWED_VIDEO_UPLOAD_EXTENSIONS.join(',')}
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
						MP4, MOV, AVI, MKV, or WebM (max {MAX_VIDEO_UPLOAD_SIZE_GB}GB)
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
