<script lang="ts">
	import { Search, Loader2 } from 'lucide-svelte';
	import { search, exampleQueries } from '$lib/stores/search';

	let inputValue = $state($search.query);
	let placeholderIndex = $state(0);

	// Cycle through example queries for placeholder
	$effect(() => {
		const interval = setInterval(() => {
			placeholderIndex = (placeholderIndex + 1) % exampleQueries.length;
		}, 4000);

		return () => clearInterval(interval);
	});

	function handleSubmit(e: Event) {
		e.preventDefault();
		if (inputValue.trim()) {
			search.search(inputValue.trim());
		}
	}

	function handleKeyDown(e: KeyboardEvent) {
		if (e.key === 'Enter' && !e.shiftKey) {
			handleSubmit(e);
		}
	}
</script>

<form onsubmit={handleSubmit} class="relative">
	<div class="relative">
		<div class="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-4">
			{#if $search.loading}
				<Loader2 class="h-5 w-5 animate-spin text-[var(--color-accent)]" />
			{:else}
				<Search class="h-5 w-5 text-[var(--color-text-secondary)]" />
			{/if}
		</div>

		<input
			type="text"
			bind:value={inputValue}
			onkeydown={handleKeyDown}
			placeholder={exampleQueries[placeholderIndex]}
			disabled={$search.loading}
			class="w-full rounded-xl border border-[var(--color-border)] bg-[var(--color-surface)] py-4 pl-12 pr-4 text-[var(--color-text-primary)] shadow-sm transition-all placeholder:text-[var(--color-text-secondary)]/60 focus:border-[var(--color-accent)] focus:outline-none focus:ring-2 focus:ring-[var(--color-accent)]/20 disabled:cursor-not-allowed disabled:opacity-60"
		/>

		{#if inputValue.trim()}
			<button
				type="submit"
				disabled={$search.loading}
				class="absolute inset-y-0 right-0 flex items-center pr-4 text-[var(--color-accent)] hover:text-[var(--color-accent-hover)] disabled:cursor-not-allowed disabled:opacity-60"
			>
				<span class="text-sm font-medium">Search</span>
			</button>
		{/if}
	</div>

	<p class="mt-2 text-center text-xs text-[var(--color-text-secondary)]">
		Ask questions about your legal and compliance documents
	</p>
</form>
