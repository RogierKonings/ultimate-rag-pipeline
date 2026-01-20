<script lang="ts">
	import { Loader2, CheckCircle, AlertCircle, Trash2, Play } from 'lucide-svelte';
	import type { Video } from '$lib/api/types';

	interface Props {
		video: Video;
		selected?: boolean;
		onSelect?: () => void;
		onDelete?: () => void;
	}

	let { video, selected = false, onSelect, onDelete }: Props = $props();

	let showDeleteButton = $state(false);

	function formatDuration(ms: number | null): string {
		if (!ms) return '--:--';
		const seconds = Math.floor(ms / 1000);
		const mins = Math.floor(seconds / 60);
		const secs = seconds % 60;
		return `${mins}:${secs.toString().padStart(2, '0')}`;
	}

	function getProcessingLabel(stage: string | null): string {
		if (!stage) return 'Processing...';
		const labels: Record<string, string> = {
			audio_extraction: 'Extracting audio...',
			transcription: 'Transcribing...',
			scene_detection: 'Detecting scenes...',
			visual_analysis: 'Analyzing visuals...',
			ocr: 'Reading text...',
			fusion: 'Combining content...',
			embedding: 'Indexing...'
		};
		return labels[stage] || 'Processing...';
	}
</script>

<button
	type="button"
	onclick={onSelect}
	onmouseenter={() => (showDeleteButton = true)}
	onmouseleave={() => (showDeleteButton = false)}
	class="group flex w-full items-center gap-3 rounded-lg p-2 text-left transition-colors {selected
		? 'bg-[var(--color-accent)]/10'
		: 'hover:bg-gray-50'}"
>
	<!-- Thumbnail -->
	<div
		class="relative h-10 w-16 shrink-0 overflow-hidden rounded bg-gray-100"
	>
		{#if video.thumbnail_url}
			<img
				src={video.thumbnail_url}
				alt=""
				class="h-full w-full object-cover"
			/>
		{:else}
			<div class="flex h-full w-full items-center justify-center">
				<Play class="h-4 w-4 text-gray-400" />
			</div>
		{/if}

		{#if video.status === 'processing'}
			<div class="absolute inset-0 flex items-center justify-center bg-black/50">
				<Loader2 class="h-4 w-4 animate-spin text-white" />
			</div>
		{/if}
	</div>

	<!-- Info -->
	<div class="min-w-0 flex-1">
		<p class="truncate text-sm font-medium text-[var(--color-text-primary)]">
			{video.title || video.filename}
		</p>

		{#if video.status === 'processing'}
			<p class="text-xs text-[var(--color-accent)]">
				{getProcessingLabel(video.processing_stage)}
			</p>
		{:else if video.status === 'failed'}
			<p class="flex items-center gap-1 text-xs text-red-600">
				<AlertCircle class="h-3 w-3" />
				Failed
			</p>
		{:else}
			<p class="text-xs text-[var(--color-text-secondary)]">
				{formatDuration(video.duration_ms)}
			</p>
		{/if}
	</div>

	<!-- Status/Actions -->
	<div class="shrink-0">
		{#if video.status === 'ready'}
			{#if showDeleteButton && onDelete}
				<button
					type="button"
					onclick={(e) => {
						e.stopPropagation();
						onDelete?.();
					}}
					class="rounded p-1 text-[var(--color-text-secondary)] hover:bg-red-50 hover:text-red-600"
				>
					<Trash2 class="h-4 w-4" />
				</button>
			{:else}
				<CheckCircle class="h-4 w-4 text-green-500" />
			{/if}
		{:else if video.status === 'processing'}
			<span class="text-xs text-[var(--color-text-secondary)]">
				{video.processing_progress}%
			</span>
		{/if}
	</div>
</button>
