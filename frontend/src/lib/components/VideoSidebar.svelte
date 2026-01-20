<script lang="ts">
	import { Loader2, FolderOpen, Video, AlertCircle } from 'lucide-svelte';
	import { videos, processingVideos, readyVideos, activeVideoJobs } from '$lib/stores/videos';
	import { deleteVideo } from '$lib/api/video';
	import VideoItem from './VideoItem.svelte';

	interface Props {
		selectedVideoId?: string | null;
		onSelectVideo?: (videoId: string) => void;
	}

	let { selectedVideoId = null, onSelectVideo }: Props = $props();

	let deleteConfirmId = $state<string | null>(null);
	let isDeleting = $state(false);
	let deleteError = $state<string | null>(null);

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
		{#if $readyVideos.length > 0}
			<div class="mb-6">
				<h3
					class="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-[var(--color-text-secondary)]"
				>
					<FolderOpen class="h-3 w-3" />
					Your Videos
				</h3>
				<div class="space-y-1">
					{#each $readyVideos as video (video.video_id)}
						<VideoItem
							{video}
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
				<p class="mt-1 text-xs text-[var(--color-text-secondary)]">
					Upload a video to get started
				</p>
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

<!-- Delete Confirmation Modal -->
{#if deleteConfirmId}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
		onclick={() => (deleteConfirmId = null)}
		onkeydown={(e) => e.key === 'Escape' && (deleteConfirmId = null)}
		role="dialog"
		aria-modal="true"
		tabindex="-1"
	>
		<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
		<div
			class="mx-4 w-full max-w-sm rounded-lg bg-white p-6 shadow-xl"
			onclick={(e) => e.stopPropagation()}
			role="document"
		>
			<h3 class="text-lg font-semibold text-[var(--color-text-primary)]">Delete Video</h3>
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
					class="rounded-lg px-4 py-2 text-sm font-medium text-[var(--color-text-secondary)] hover:bg-gray-100 disabled:opacity-50"
				>
					Cancel
				</button>
				<button
					type="button"
					onclick={() => deleteConfirmId && handleDelete(deleteConfirmId)}
					disabled={isDeleting}
					class="flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
				>
					{#if isDeleting}
						<Loader2 class="h-4 w-4 animate-spin" />
						Deleting...
					{:else}
						Delete Video
					{/if}
				</button>
			</div>
		</div>
	</div>
{/if}
