<script lang="ts">
	import { Clock, Sparkles, ThumbsUp, ThumbsDown } from 'lucide-svelte';
	import { search, parseCitations } from '$lib/stores/search';
	import { submitFeedback } from '$lib/api/orchestrator';

	let feedbackGiven = $state<'up' | 'down' | null>(null);
	let feedbackSubmitting = $state(false);

	const response = $derived($search.response);
	const citations = $derived(response ? parseCitations(response.response) : []);

	// Split response into parts with citations
	const responseParts = $derived(() => {
		if (!response) return [];

		const text = response.response;
		const parts: Array<{ type: 'text' | 'citation'; content: string; index?: number }> = [];
		let lastIndex = 0;

		for (const citation of citations) {
			// Add text before citation
			if (citation.position > lastIndex) {
				parts.push({
					type: 'text',
					content: text.slice(lastIndex, citation.position)
				});
			}

			// Add citation
			parts.push({
				type: 'citation',
				content: `[${citation.index + 1}]`,
				index: citation.index
			});

			// Update lastIndex to after the citation marker
			const citationMatch = text.slice(citation.position).match(/^\[\d+\]/);
			if (citationMatch) {
				lastIndex = citation.position + citationMatch[0].length;
			}
		}

		// Add remaining text
		if (lastIndex < text.length) {
			parts.push({
				type: 'text',
				content: text.slice(lastIndex)
			});
		}

		return parts;
	});

	function handleCitationClick(index: number) {
		search.highlightSource(response?.sources[index]?.id || null);

		// Scroll to source card
		const sourceElement = document.getElementById(`source-${index}`);
		if (sourceElement) {
			sourceElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
		}
	}

	async function handleFeedback(type: 'up' | 'down') {
		if (!response || feedbackSubmitting) return;

		feedbackSubmitting = true;
		try {
			await submitFeedback(
				response.request_id,
				type === 'up' ? 5 : 1,
				type === 'up' ? 'helpful' : 'unhelpful'
			);
			feedbackGiven = type;
		} catch {
			// Silently fail feedback
		} finally {
			feedbackSubmitting = false;
		}
	}
</script>

{#if response}
	<div class="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6 shadow-sm">
		<!-- Header -->
		<div class="mb-4 flex items-center justify-between">
			<div class="flex items-center gap-2 text-[var(--color-accent)]">
				<Sparkles class="h-4 w-4" />
				<span class="text-sm font-medium">AI Answer</span>
			</div>

			<div class="flex items-center gap-3">
				<!-- Latency Badge -->
				<div
					class="flex items-center gap-1 rounded-full bg-gray-100 px-2.5 py-1 text-xs text-[var(--color-text-secondary)]"
				>
					<Clock class="h-3 w-3" />
					<span>{response.latency_ms.toFixed(0)}ms</span>
				</div>

				<!-- Feedback Buttons -->
				<div class="flex items-center gap-1">
					<button
						onclick={() => handleFeedback('up')}
						disabled={feedbackGiven !== null || feedbackSubmitting}
						class={`rounded-lg p-1.5 transition-colors ${
							feedbackGiven === 'up'
								? 'bg-green-100 text-green-600'
								: 'text-[var(--color-text-secondary)] hover:bg-gray-100 hover:text-[var(--color-text-primary)]'
						} disabled:cursor-not-allowed disabled:opacity-50`}
					>
						<ThumbsUp class="h-4 w-4" />
					</button>
					<button
						onclick={() => handleFeedback('down')}
						disabled={feedbackGiven !== null || feedbackSubmitting}
						class={`rounded-lg p-1.5 transition-colors ${
							feedbackGiven === 'down'
								? 'bg-red-100 text-red-600'
								: 'text-[var(--color-text-secondary)] hover:bg-gray-100 hover:text-[var(--color-text-primary)]'
						} disabled:cursor-not-allowed disabled:opacity-50`}
					>
						<ThumbsDown class="h-4 w-4" />
					</button>
				</div>
			</div>
		</div>

		<!-- Response Content -->
		<div class="prose prose-sm max-w-none text-[var(--color-text-primary)]">
			<p class="whitespace-pre-wrap leading-relaxed">
				{#each responseParts() as part}
					{#if part.type === 'text'}
						{part.content}
					{:else}
						<button
							onclick={() => handleCitationClick(part.index!)}
							class="citation-pill mx-0.5"
						>
							{part.content}
						</button>
					{/if}
				{/each}
			</p>
		</div>

		<!-- Model Info -->
		<div class="mt-4 flex items-center gap-4 border-t border-[var(--color-border)] pt-4 text-xs text-[var(--color-text-secondary)]">
			<span>Model: {response.model}</span>
			<span>Tokens: {response.usage.total_tokens}</span>
			{#if response.strategy_used}
				<span>Strategy: {response.strategy_used}</span>
			{/if}
		</div>
	</div>
{/if}
