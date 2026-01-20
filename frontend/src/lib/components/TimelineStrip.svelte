<script lang="ts">
	import type { VideoMatch } from '$lib/api/types';

	interface Props {
		durationMs: number;
		matches: VideoMatch[];
		selectedMatchId?: string | null;
		onSelectMatch: (match: VideoMatch) => void;
	}

	let { durationMs, matches, selectedMatchId = null, onSelectMatch }: Props = $props();

	let containerRef: HTMLDivElement;
	let hoveredMatch = $state<VideoMatch | null>(null);
	let tooltipX = $state(0);

	function formatTime(ms: number): string {
		const seconds = Math.floor(ms / 1000);
		const mins = Math.floor(seconds / 60);
		const secs = seconds % 60;
		return `${mins}:${secs.toString().padStart(2, '0')}`;
	}

	function getMarkerPosition(match: VideoMatch): number {
		if (!durationMs) return 0;
		const midpoint = (match.start_time_ms + match.end_time_ms) / 2;
		return (midpoint / durationMs) * 100;
	}

	function getMarkerOpacity(match: VideoMatch): number {
		// Map score (0-1) to opacity (0.4-1)
		return 0.4 + match.fused_score * 0.6;
	}

	function handleMarkerHover(match: VideoMatch, event: MouseEvent) {
		hoveredMatch = match;
		const rect = containerRef.getBoundingClientRect();
		tooltipX = event.clientX - rect.left;
	}

	function handleMarkerLeave() {
		hoveredMatch = null;
	}
</script>

<div bind:this={containerRef} class="relative">
	<!-- Timeline bar -->
	<div class="relative h-6 rounded-full bg-gray-100">
		<!-- Match markers -->
		{#each matches as match (match.chunk_id)}
			<button
				type="button"
				onclick={() => onSelectMatch(match)}
				onmouseenter={(e) => handleMarkerHover(match, e)}
				onmouseleave={handleMarkerLeave}
				class="absolute top-0 h-full w-1 -translate-x-1/2 cursor-pointer rounded-full transition-all hover:w-1.5 {selectedMatchId ===
				match.chunk_id
					? 'bg-[var(--color-accent)] ring-2 ring-[var(--color-accent)] ring-offset-1'
					: 'bg-[var(--color-accent)]'}"
				style="left: {getMarkerPosition(match)}%; opacity: {getMarkerOpacity(match)}"
				aria-label="Match at {formatTime(match.start_time_ms)}"
			></button>
		{/each}
	</div>

	<!-- Time labels -->
	<div class="mt-1 flex justify-between text-xs text-[var(--color-text-secondary)]">
		<span>0:00</span>
		<span>{formatTime(durationMs)}</span>
	</div>

	<!-- Tooltip -->
	{#if hoveredMatch}
		<div
			class="pointer-events-none absolute bottom-full mb-2 -translate-x-1/2 rounded-lg bg-gray-900 px-3 py-2 text-xs text-white shadow-lg"
			style="left: {tooltipX}px"
		>
			<p class="font-medium">{formatTime(hoveredMatch.start_time_ms)}</p>
			<p class="mt-1 max-w-48 truncate opacity-80">
				{hoveredMatch.fused_text_preview}
			</p>
			<p class="mt-1 opacity-60">Score: {(hoveredMatch.fused_score * 100).toFixed(0)}%</p>
		</div>
	{/if}
</div>
