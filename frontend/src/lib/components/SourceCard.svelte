<script lang="ts">
	import { ExternalLink, ChevronDown, ChevronUp } from 'lucide-svelte';
	import type { SourceDocument } from '$lib/api/types';
	import { search } from '$lib/stores/search';

	interface Props {
		source: SourceDocument;
		index: number;
	}

	let { source, index }: Props = $props();
	let expanded = $state(false);

	const isHighlighted = $derived($search.highlightedSourceId === source.id);

	// Calculate score bar width and color
	const scorePercent = $derived(source.score ? Math.min(source.score * 100, 100) : 0);
	const scoreColor = $derived(() => {
		if (!source.score) return 'bg-gray-300';
		if (source.score >= 0.8) return 'bg-[var(--color-success)]';
		if (source.score >= 0.5) return 'bg-[var(--color-warning)]';
		return 'bg-[var(--color-error)]';
	});

	function toggleExpanded() {
		expanded = !expanded;
	}
</script>

<div
	id="source-{index}"
	class={`rounded-lg border bg-[var(--color-surface)] transition-all ${
		isHighlighted
			? 'border-[var(--color-accent)] ring-2 ring-[var(--color-accent)]/20'
			: 'border-[var(--color-border)]'
	}`}
>
	<!-- Header -->
	<button
		onclick={toggleExpanded}
		class="flex w-full items-start gap-3 p-4 text-left"
	>
		<!-- Citation Number -->
		<div
			class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-[var(--color-accent)]/10 text-xs font-medium text-[var(--color-accent)]"
		>
			{index + 1}
		</div>

		<div class="min-w-0 flex-1">
			<!-- Title -->
			<div class="flex items-start justify-between gap-2">
				<h4 class="font-medium text-[var(--color-text-primary)]">
					{source.title || 'Untitled Document'}
				</h4>

				<div class="flex shrink-0 items-center gap-2">
					<!-- Score -->
					{#if source.score !== null}
						<div class="flex items-center gap-2">
							<div class="w-16 score-bar">
								<div
									class={`score-bar-fill ${scoreColor()}`}
									style="width: {scorePercent}%"
								></div>
							</div>
							<span class="text-xs font-mono text-[var(--color-text-secondary)]">
								{(source.score * 100).toFixed(0)}%
							</span>
						</div>
					{/if}

					<!-- Expand Icon -->
					{#if expanded}
						<ChevronUp class="h-4 w-4 text-[var(--color-text-secondary)]" />
					{:else}
						<ChevronDown class="h-4 w-4 text-[var(--color-text-secondary)]" />
					{/if}
				</div>
			</div>

			<!-- Snippet Preview (when collapsed) -->
			{#if !expanded && source.snippet}
				<p class="mt-1 line-clamp-2 text-sm text-[var(--color-text-secondary)]">
					{source.snippet}
				</p>
			{/if}
		</div>
	</button>

	<!-- Expanded Content -->
	{#if expanded}
		<div class="border-t border-[var(--color-border)] px-4 py-3">
			<!-- Full Snippet -->
			{#if source.snippet}
				<div class="rounded-lg bg-gray-50 p-3">
					<p class="text-sm text-[var(--color-text-primary)] whitespace-pre-wrap">
						{source.snippet}
					</p>
				</div>
			{/if}

			<!-- Source URI -->
			{#if source.uri}
				<div class="mt-3 flex items-center gap-2">
					<ExternalLink class="h-3 w-3 text-[var(--color-text-secondary)]" />
					<a
						href={source.uri}
						target="_blank"
						rel="noopener noreferrer"
						class="text-xs text-[var(--color-accent)] hover:underline truncate"
					>
						{source.uri}
					</a>
				</div>
			{/if}
		</div>
	{/if}
</div>
