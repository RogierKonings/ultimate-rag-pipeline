<script lang="ts">
	import { Play, ChevronDown, ChevronUp } from 'lucide-svelte';
	import type { VideoSearchResult, VideoMatch } from '$lib/api/types';
	import TimelineStrip from './TimelineStrip.svelte';

	interface Props {
		result: VideoSearchResult;
		selectedMatchId?: string | null;
		onSelectMatch: (match: VideoMatch) => void;
	}

	let { result, selectedMatchId = null, onSelectMatch }: Props = $props();

	let expanded = $state(false);
	const MAX_VISIBLE_MATCHES = 3;

	function formatDuration(ms: number | null): string {
		if (!ms) return '--:--';
		const seconds = Math.floor(ms / 1000);
		const mins = Math.floor(seconds / 60);
		const secs = seconds % 60;
		return `${mins}:${secs.toString().padStart(2, '0')}`;
	}

	function formatTimestamp(seconds: number): string {
		const mins = Math.floor(seconds / 60);
		const secs = Math.floor(seconds % 60);
		return `${mins}:${secs.toString().padStart(2, '0')}`;
	}

	const visibleMatches = $derived(
		expanded ? result.matches : result.matches.slice(0, MAX_VISIBLE_MATCHES)
	);

	const hasMoreMatches = $derived(result.matches.length > MAX_VISIBLE_MATCHES);
</script>

<div class="rounded-lg border border-[var(--color-border)] bg-white p-4">
	<!-- Header -->
	<div class="flex items-start gap-3">
		<!-- Thumbnail -->
		<div class="relative h-16 w-24 shrink-0 overflow-hidden rounded bg-gray-100">
			{#if result.thumbnail_url}
				<img src={result.thumbnail_url} alt="" class="h-full w-full object-cover" />
			{:else}
				<div class="flex h-full w-full items-center justify-center">
					<Play class="h-6 w-6 text-gray-400" />
				</div>
			{/if}
		</div>

		<!-- Title and meta -->
		<div class="min-w-0 flex-1">
			<h3 class="font-medium text-[var(--color-text-primary)]">
				{result.title || 'Untitled Video'}
			</h3>
			<div class="mt-1 flex items-center gap-3 text-xs text-[var(--color-text-secondary)]">
				<span>{formatDuration(result.duration_ms)}</span>
				<span
					class="rounded-full bg-[var(--color-accent)]/10 px-2 py-0.5 text-[var(--color-accent)]"
				>
					{result.match_count} match{result.match_count === 1 ? '' : 'es'}
				</span>
			</div>
		</div>
	</div>

	<!-- Timeline Strip -->
	{#if result.duration_ms}
		<div class="mt-4">
			<TimelineStrip
				durationMs={result.duration_ms}
				matches={result.matches}
				{selectedMatchId}
				{onSelectMatch}
			/>
		</div>
	{/if}

	<!-- Match List -->
	<div class="mt-4 space-y-2">
		{#each visibleMatches as match (match.chunk_id)}
			<button
				type="button"
				onclick={() => onSelectMatch(match)}
				class="flex w-full items-start gap-2 rounded-lg p-2 text-left transition-colors hover:bg-gray-50 {selectedMatchId ===
				match.chunk_id
					? 'bg-[var(--color-accent)]/5 ring-1 ring-[var(--color-accent)]'
					: ''}"
			>
				<span
					class="shrink-0 rounded bg-gray-100 px-1.5 py-0.5 text-xs font-medium text-[var(--color-text-secondary)]"
				>
					{formatTimestamp(match.start_seconds)}
				</span>
				<p class="line-clamp-2 flex-1 text-sm text-[var(--color-text-primary)]">
					{match.fused_text_preview}
				</p>
			</button>
		{/each}
	</div>

	<!-- Show more/less -->
	{#if hasMoreMatches}
		<button
			type="button"
			onclick={() => (expanded = !expanded)}
			class="mt-2 flex w-full items-center justify-center gap-1 rounded-lg py-2 text-xs font-medium text-[var(--color-accent)] hover:bg-gray-50"
		>
			{#if expanded}
				<ChevronUp class="h-3 w-3" />
				Show less
			{:else}
				<ChevronDown class="h-3 w-3" />
				Show all {result.match_count} matches
			{/if}
		</button>
	{/if}
</div>
