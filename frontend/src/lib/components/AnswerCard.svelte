<script lang="ts">
	import { Clock, Sparkles, ThumbsUp, ThumbsDown, X, RotateCcw, Loader2 } from 'lucide-svelte';
	import { search, parseCitations } from '$lib/stores/search';
	import { submitFeedback } from '$lib/api/orchestrator';

	let feedbackGiven = $state<'up' | 'down' | null>(null);
	let feedbackSubmitting = $state(false);

	const response = $derived($search.response);
	const streamingState = $derived($search.streamingState);
	const partialResponse = $derived($search.partialResponse);
	const isStreaming = $derived(streamingState === 'streaming' || streamingState === 'connecting');
	const isCancelled = $derived(streamingState === 'cancelled');

	// Use the completed response text, or the partial text while streaming
	const displayText = $derived(response?.response || partialResponse);

	const citations = $derived(displayText ? parseCitations(displayText) : []);

	// Split response into parts with citations
	const responseParts = $derived(() => {
		if (!displayText) return [];

		const text = displayText;
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
		const sources = response?.sources || $search.streamSources;
		search.highlightSource(sources[index]?.id || null);

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

	function handleCancel() {
		search.cancel();
	}

	function handleRetry() {
		feedbackGiven = null;
		search.retry();
	}
</script>

{#if displayText || isStreaming}
	<div class="rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6 shadow-sm">
		<!-- Header -->
		<div class="mb-4 flex items-center justify-between">
			<div class="flex items-center gap-2 text-[var(--color-accent)]">
				{#if isStreaming}
					<Loader2 class="h-4 w-4 animate-spin" />
				{:else}
					<Sparkles class="h-4 w-4" />
				{/if}
				<span class="text-sm font-medium">
					{#if streamingState === 'connecting'}
						Connecting...
					{:else if streamingState === 'streaming'}
						AI is responding...
					{:else if isCancelled}
						AI Answer (cancelled)
					{:else}
						AI Answer
					{/if}
				</span>
			</div>

			<div class="flex items-center gap-3">
				<!-- Cancel Button (during streaming) -->
				{#if isStreaming}
					<button
						onclick={handleCancel}
						class="flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs text-[var(--color-text-secondary)] transition-colors hover:bg-gray-100 hover:text-[var(--color-text-primary)]"
					>
						<X class="h-3 w-3" />
						<span>Cancel</span>
					</button>
				{/if}

				<!-- Retry Button (after error or cancel) -->
				{#if isCancelled || streamingState === 'error'}
					<button
						onclick={handleRetry}
						class="flex items-center gap-1 rounded-lg px-2.5 py-1 text-xs text-[var(--color-accent)] transition-colors hover:bg-[var(--color-accent)]/10"
					>
						<RotateCcw class="h-3 w-3" />
						<span>Retry</span>
					</button>
				{/if}

				<!-- Latency Badge (only when done) -->
				{#if response?.latency_ms}
					<div
						class="flex items-center gap-1 rounded-full bg-gray-100 px-2.5 py-1 text-xs text-[var(--color-text-secondary)]"
					>
						<Clock class="h-3 w-3" />
						<span>{response.latency_ms.toFixed(0)}ms</span>
					</div>
				{/if}

				<!-- Feedback Buttons (only when response is complete) -->
				{#if response && streamingState === 'done'}
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
				{/if}
			</div>
		</div>

		<!-- Response Content -->
		<div class="prose prose-sm max-w-none text-[var(--color-text-primary)]">
			{#if displayText}
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
					{#if isStreaming}
						<span class="inline-block h-4 w-1 animate-pulse bg-[var(--color-accent)]"></span>
					{/if}
				</p>
			{:else if streamingState === 'connecting'}
				<p class="text-[var(--color-text-secondary)]">Waiting for response...</p>
			{/if}
		</div>

		<!-- Model Info (only when fully done) -->
		{#if response && streamingState === 'done'}
			<div class="mt-4 flex items-center gap-4 border-t border-[var(--color-border)] pt-4 text-xs text-[var(--color-text-secondary)]">
				<span>Model: {response.model}</span>
				<span>Tokens: {response.usage.total_tokens}</span>
				{#if response.strategy_used}
					<span>Strategy: {response.strategy_used}</span>
				{/if}
			</div>
		{/if}
	</div>
{/if}
