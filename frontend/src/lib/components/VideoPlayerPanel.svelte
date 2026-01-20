<script lang="ts">
	import {
		ChevronLeft,
		ChevronRight,
		X,
		Play,
		MessageSquare,
		Eye,
		Type,
		Maximize2
	} from 'lucide-svelte';
	import { videoPlayer } from '$lib/stores/videoSearch';
	import { getClipUrl, getStreamUrl } from '$lib/api/video';

	type ContentTab = 'transcript' | 'scene' | 'ocr';
	let activeTab = $state<ContentTab>('transcript');

	let videoElement = $state<HTMLVideoElement | null>(null);

	function formatTimestamp(seconds: number): string {
		const mins = Math.floor(seconds / 60);
		const secs = Math.floor(seconds % 60);
		return `${mins}:${secs.toString().padStart(2, '0')}`;
	}

	function formatTimeRange(startSec: number, endSec: number): string {
		return `${formatTimestamp(startSec)} - ${formatTimestamp(endSec)}`;
	}

	const clipUrl = $derived(
		$videoPlayer.selectedVideo && $videoPlayer.selectedMatch
			? getClipUrl(
					$videoPlayer.selectedVideo.video_id,
					$videoPlayer.selectedMatch.start_time_ms,
					$videoPlayer.selectedMatch.end_time_ms
				)
			: null
	);

	const fullVideoUrl = $derived(
		$videoPlayer.selectedVideo ? getStreamUrl($videoPlayer.selectedVideo.video_id) : null
	);

	function handleTimeUpdate() {
		if (videoElement) {
			videoPlayer.setCurrentTime(videoElement.currentTime);
		}
	}

	function handlePlay() {
		videoPlayer.setPlaying(true);
	}

	function handlePause() {
		videoPlayer.setPlaying(false);
	}
</script>

{#if $videoPlayer.isPanelOpen}
	<div
		class="flex w-[400px] shrink-0 flex-col border-l border-[var(--color-border)] bg-[var(--color-surface)]"
	>
		<!-- Header -->
		<div class="flex items-center justify-between border-b border-[var(--color-border)] px-4 py-3">
			<h3 class="font-medium text-[var(--color-text-primary)]">Video Preview</h3>
			<button
				type="button"
				onclick={() => videoPlayer.closePanel()}
				class="rounded p-1 text-[var(--color-text-secondary)] hover:bg-gray-100"
				aria-label="Close panel"
			>
				<X class="h-4 w-4" />
			</button>
		</div>

		{#if $videoPlayer.selectedVideo && $videoPlayer.selectedMatch}
			<!-- Video Player -->
			<div class="relative aspect-video bg-black">
				{#if clipUrl}
					<video
						bind:this={videoElement}
						src={clipUrl}
						class="h-full w-full"
						controls
						ontimeupdate={handleTimeUpdate}
						onplay={handlePlay}
						onpause={handlePause}
					>
						<track kind="captions" />
					</video>
				{:else}
					<div class="flex h-full w-full items-center justify-center">
						<Play class="h-12 w-12 text-gray-400" />
					</div>
				{/if}
			</div>

			<!-- Video Info -->
			<div class="border-b border-[var(--color-border)] p-4">
				<h4 class="font-medium text-[var(--color-text-primary)]">
					{$videoPlayer.selectedVideo.title || 'Untitled Video'}
				</h4>
				<div class="mt-2 flex items-center gap-3 text-sm text-[var(--color-text-secondary)]">
					<span>
						{formatTimeRange(
							$videoPlayer.selectedMatch.start_seconds,
							$videoPlayer.selectedMatch.end_seconds
						)}
					</span>
					<span
						class="rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-700"
					>
						{($videoPlayer.selectedMatch.fused_score * 100).toFixed(0)}% match
					</span>
				</div>

				<!-- Navigation -->
				{#if $videoPlayer.selectedVideo.matches.length > 1}
					<div class="mt-3 flex items-center justify-between">
						<button
							type="button"
							onclick={() => videoPlayer.previousMatch()}
							class="flex items-center gap-1 rounded px-2 py-1 text-xs text-[var(--color-text-secondary)] hover:bg-gray-100"
						>
							<ChevronLeft class="h-3 w-3" />
							Previous
						</button>
						<span class="text-xs text-[var(--color-text-secondary)]">
							{$videoPlayer.selectedVideo.matches.findIndex(
								(m) => m.chunk_id === $videoPlayer.selectedMatch?.chunk_id
							) + 1} of {$videoPlayer.selectedVideo.matches.length}
						</span>
						<button
							type="button"
							onclick={() => videoPlayer.nextMatch()}
							class="flex items-center gap-1 rounded px-2 py-1 text-xs text-[var(--color-text-secondary)] hover:bg-gray-100"
						>
							Next
							<ChevronRight class="h-3 w-3" />
						</button>
					</div>
				{/if}
			</div>

			<!-- Content Tabs -->
			<div class="flex border-b border-[var(--color-border)]">
				<button
					type="button"
					onclick={() => (activeTab = 'transcript')}
					class="flex flex-1 items-center justify-center gap-1.5 py-2 text-xs font-medium transition-colors {activeTab ===
					'transcript'
						? 'border-b-2 border-[var(--color-accent)] text-[var(--color-accent)]'
						: 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]'}"
				>
					<MessageSquare class="h-3 w-3" />
					Transcript
				</button>
				<button
					type="button"
					onclick={() => (activeTab = 'scene')}
					class="flex flex-1 items-center justify-center gap-1.5 py-2 text-xs font-medium transition-colors {activeTab ===
					'scene'
						? 'border-b-2 border-[var(--color-accent)] text-[var(--color-accent)]'
						: 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]'}"
				>
					<Eye class="h-3 w-3" />
					Scene
				</button>
				<button
					type="button"
					onclick={() => (activeTab = 'ocr')}
					class="flex flex-1 items-center justify-center gap-1.5 py-2 text-xs font-medium transition-colors {activeTab ===
					'ocr'
						? 'border-b-2 border-[var(--color-accent)] text-[var(--color-accent)]'
						: 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]'}"
				>
					<Type class="h-3 w-3" />
					OCR
				</button>
			</div>

			<!-- Tab Content -->
			<div class="flex-1 overflow-y-auto p-4">
				{#if activeTab === 'transcript'}
					{#if $videoPlayer.selectedMatch.transcript_text}
						<p class="text-sm leading-relaxed text-[var(--color-text-primary)]">
							{$videoPlayer.selectedMatch.transcript_text}
						</p>
					{:else}
						<p class="text-sm text-[var(--color-text-secondary)]">No transcript available</p>
					{/if}
				{:else if activeTab === 'scene'}
					{#if $videoPlayer.selectedMatch.scene_description}
						<p class="text-sm leading-relaxed text-[var(--color-text-primary)]">
							{$videoPlayer.selectedMatch.scene_description}
						</p>
					{:else}
						<p class="text-sm text-[var(--color-text-secondary)]">No scene description available</p>
					{/if}
				{:else if activeTab === 'ocr'}
					{#if $videoPlayer.selectedMatch.source_modalities.includes('ocr')}
						<p class="text-sm leading-relaxed text-[var(--color-text-primary)]">
							{$videoPlayer.selectedMatch.fused_text_preview}
						</p>
					{:else}
						<p class="text-sm text-[var(--color-text-secondary)]">No on-screen text detected</p>
					{/if}
				{/if}
			</div>

			<!-- Footer -->
			{#if fullVideoUrl}
				<div class="border-t border-[var(--color-border)] p-4">
					<a
						href={fullVideoUrl}
						target="_blank"
						rel="noopener noreferrer"
						class="flex items-center justify-center gap-2 rounded-lg border border-[var(--color-border)] py-2 text-sm font-medium text-[var(--color-text-primary)] hover:bg-gray-50"
					>
						<Maximize2 class="h-4 w-4" />
						Open full video
					</a>
				</div>
			{/if}
		{:else}
			<!-- Empty State -->
			<div class="flex flex-1 flex-col items-center justify-center p-8 text-center">
				<Play class="h-12 w-12 text-gray-300" />
				<p class="mt-4 text-sm text-[var(--color-text-secondary)]">
					Select a video or click a timeline marker to preview
				</p>
			</div>
		{/if}
	</div>
{/if}
