<script lang="ts">
	import { FileText } from 'lucide-svelte';
	import { search } from '$lib/stores/search';
	import SourceCard from './SourceCard.svelte';

	const response = $derived($search.response);
	const streamSources = $derived($search.streamSources);
	// Show completed response sources, or stream sources if available
	const sources = $derived(response?.sources || (streamSources.length > 0 ? streamSources : []));
</script>

{#if sources.length > 0}
	<div>
		<div class="mb-4 flex items-center gap-2">
			<FileText class="h-4 w-4 text-[var(--color-text-secondary)]" />
			<h3 class="text-sm font-medium text-[var(--color-text-primary)]">
				Sources ({sources.length})
			</h3>
		</div>

		<div class="space-y-3">
			{#each sources as source, index (source.id)}
				<SourceCard {source} {index} />
			{/each}
		</div>
	</div>
{/if}
