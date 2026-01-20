<script lang="ts">
	import { Search, Loader2 } from 'lucide-svelte';
	import { videoSearch } from '$lib/stores/videoSearch';

	let inputValue = $state($videoSearch.query);

	function handleSubmit(e: Event) {
		e.preventDefault();
		if (inputValue.trim()) {
			videoSearch.search(inputValue.trim());
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Enter') {
			handleSubmit(e);
		}
	}
</script>

<form onsubmit={handleSubmit} class="relative">
	<div class="relative">
		<input
			type="text"
			bind:value={inputValue}
			onkeydown={handleKeydown}
			placeholder="Search within your videos..."
			class="w-full rounded-xl border border-[var(--color-border)] bg-white py-3 pl-12 pr-4 text-[var(--color-text-primary)] placeholder-[var(--color-text-secondary)] outline-none transition-shadow focus:border-[var(--color-accent)] focus:ring-2 focus:ring-[var(--color-accent)]/20"
		/>
		<div class="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2">
			{#if $videoSearch.loading}
				<Loader2 class="h-5 w-5 animate-spin text-[var(--color-accent)]" />
			{:else}
				<Search class="h-5 w-5 text-[var(--color-text-secondary)]" />
			{/if}
		</div>
	</div>
</form>
