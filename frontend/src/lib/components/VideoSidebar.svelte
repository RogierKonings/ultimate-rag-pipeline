<script lang="ts">
	import {
		Loader2,
		FolderOpen,
		Video,
		AlertCircle,
		Trash2,
		CheckSquare,
		Square,
		X
	} from 'lucide-svelte';
	import { videos, activeVideoJobs, selectedVideos, selectedVideoCount } from '$lib/stores/videos';
	import { deleteVideo, batchDeleteVideos } from '$lib/api/video';
	import VideoItem from './VideoItem.svelte';

	interface Props {
		selectedVideoId?: string | null;
		onSelectVideo?: (videoId: string) => void;
	}

	let { selectedVideoId = null, onSelectVideo }: Props = $props();

	let selectionMode = $state(false);
	let deleteConfirmId = $state<string | null>(null);
	let isDeleting = $state(false);
	let deleteError = $state<string | null>(null);
	let showBatchConfirm = $state(false);
	let batchDeleteError = $state<string | null>(null);

	const allVideoIds = $derived($videos.videos.map((v) => v.video_id));
	const allSelected = $derived(
		$videos.videos.length > 0 && $videos.videos.every((v) => $selectedVideos.has(v.video_id))
	);
	const someSelected = $derived($selectedVideoCount > 0);

	function toggleSelectionMode() {
		selectionMode = !selectionMode;
		if (!selectionMode) {
			selectedVideos.deselectAll();
		}
	}

	function toggleSelectAll() {
		if (allSelected) {
			selectedVideos.deselectAll();
		} else {
			selectedVideos.selectAll(allVideoIds);
		}
	}

	function openBatchDeleteConfirm() {
		batchDeleteError = null;
		showBatchConfirm = true;
	}

	function closeBatchDeleteConfirm() {
		showBatchConfirm = false;
		batchDeleteError = null;
	}

	async function confirmBatchDelete() {
		const idsToDelete = Array.from($selectedVideos);
		if (idsToDelete.length === 0) return;

		isDeleting = true;
		batchDeleteError = null;

		try {
			const result = await batchDeleteVideos(idsToDelete);

			// Remove successfully deleted videos from store
			const deletedIds = result.results.filter((r) => r.deleted).map((r) => r.video_id);

			videos.removeVideos(deletedIds);
			selectedVideos.deselectAll();

			if (result.failed_count > 0) {
				batchDeleteError = `${result.deleted_count} deleted, ${result.failed_count} failed`;
			} else {
				showBatchConfirm = false;
				selectionMode = false;
			}
		} catch (error) {
			batchDeleteError = error instanceof Error ? error.message : 'Failed to delete videos';
		} finally {
			isDeleting = false;
		}
	}

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
		{#if $videos.videos.length > 0}
			<div class="mb-6">
				<div class="mb-2 flex items-center justify-between">
					<h3
						class="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-[var(--color-text-secondary)]"
					>
						<FolderOpen class="h-3 w-3" />
						Your Videos
					</h3>
					<button
						type="button"
						onclick={toggleSelectionMode}
						class="rounded p-1 text-xs text-[var(--color-text-secondary)] transition-colors hover:bg-gray-100 hover:text-[var(--color-text-primary)]"
						title={selectionMode ? 'Exit selection mode' : 'Select videos'}
					>
						{#if selectionMode}
							<X class="h-4 w-4" />
						{:else}
							<CheckSquare class="h-4 w-4" />
						{/if}
					</button>
				</div>

				{#if selectionMode}
					<div class="mb-2 flex items-center gap-2">
						<button
							type="button"
							onclick={toggleSelectAll}
							class="flex items-center gap-1 rounded px-2 py-1 text-xs text-[var(--color-text-secondary)] transition-colors hover:bg-gray-100"
						>
							{#if allSelected}
								<CheckSquare class="h-3 w-3" />
								Deselect all
							{:else}
								<Square class="h-3 w-3" />
								Select all
							{/if}
						</button>

						{#if someSelected}
							<button
								type="button"
								onclick={openBatchDeleteConfirm}
								class="flex items-center gap-1 rounded bg-red-50 px-2 py-1 text-xs text-red-600 transition-colors hover:bg-red-100"
							>
								<Trash2 class="h-3 w-3" />
								Delete ({$selectedVideoCount})
							</button>
						{/if}
					</div>
				{/if}

				<div class="space-y-1">
					{#each $videos.videos as video (video.video_id)}
						<VideoItem
							{video}
							{selectionMode}
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
				<p class="mt-1 text-xs text-[var(--color-text-secondary)]">Upload a video to get started</p>
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

<!-- Single Delete Confirmation Modal -->
{#if deleteConfirmId}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
		onclick={() => (deleteConfirmId = null)}
		onkeydown={(e) => e.key === 'Escape' && (deleteConfirmId = null)}
		role="dialog"
		aria-modal="true"
		aria-labelledby="delete-dialog-title"
		tabindex="-1"
	>
		<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
		<div
			class="mx-4 w-full max-w-sm rounded-lg bg-white p-6 shadow-xl"
			onclick={(e) => e.stopPropagation()}
			onkeydown={(e) => e.stopPropagation()}
			role="document"
		>
			<h3 id="delete-dialog-title" class="text-lg font-semibold text-[var(--color-text-primary)]">
				Delete Video
			</h3>
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
					class="rounded-lg px-4 py-2 text-sm font-medium text-[var(--color-text-secondary)] transition-colors hover:bg-gray-100 disabled:opacity-50"
				>
					Cancel
				</button>
				<button
					type="button"
					onclick={() => deleteConfirmId && handleDelete(deleteConfirmId)}
					disabled={isDeleting}
					class="flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-red-700 disabled:opacity-50"
				>
					{#if isDeleting}
						<Loader2 class="h-4 w-4 animate-spin" />
						Deleting...
					{:else}
						Delete
					{/if}
				</button>
			</div>
		</div>
	</div>
{/if}

<!-- Batch Delete Confirmation Modal -->
{#if showBatchConfirm}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
		onclick={closeBatchDeleteConfirm}
		onkeydown={(e) => e.key === 'Escape' && closeBatchDeleteConfirm()}
		role="dialog"
		aria-modal="true"
		aria-labelledby="batch-delete-dialog-title"
		tabindex="-1"
	>
		<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
		<div
			class="mx-4 w-full max-w-sm rounded-lg bg-white p-6 shadow-xl"
			onclick={(e) => e.stopPropagation()}
			onkeydown={(e) => e.stopPropagation()}
			role="document"
		>
			<h3
				id="batch-delete-dialog-title"
				class="text-lg font-semibold text-[var(--color-text-primary)]"
			>
				Delete {$selectedVideoCount} Video{$selectedVideoCount === 1 ? '' : 's'}
			</h3>
			<p class="mt-2 text-sm text-[var(--color-text-secondary)]">
				Are you sure you want to delete {$selectedVideoCount} selected video{$selectedVideoCount ===
				1
					? ''
					: 's'}? All associated data including transcripts, keyframes, and search index will be
				removed. This action cannot be undone.
			</p>

			{#if batchDeleteError}
				<div class="mt-3 flex items-center gap-2 rounded-lg bg-red-50 p-3 text-sm text-red-700">
					<AlertCircle class="h-4 w-4 shrink-0" />
					<span>{batchDeleteError}</span>
				</div>
			{/if}

			<div class="mt-4 flex justify-end gap-3">
				<button
					type="button"
					onclick={closeBatchDeleteConfirm}
					disabled={isDeleting}
					class="rounded-lg px-4 py-2 text-sm font-medium text-[var(--color-text-secondary)] transition-colors hover:bg-gray-100 disabled:opacity-50"
				>
					Cancel
				</button>
				<button
					type="button"
					onclick={confirmBatchDelete}
					disabled={isDeleting}
					class="flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-red-700 disabled:opacity-50"
				>
					{#if isDeleting}
						<Loader2 class="h-4 w-4 animate-spin" />
						Deleting...
					{:else}
						Delete {$selectedVideoCount} Video{$selectedVideoCount === 1 ? '' : 's'}
					{/if}
				</button>
			</div>
		</div>
	</div>
{/if}
