<script lang="ts">
	import { FileText, Video } from 'lucide-svelte';
	import { capabilities } from '$lib/stores/capabilities';

	interface Props {
		activeTab: 'documents' | 'videos';
		onTabChange: (tab: 'documents' | 'videos') => void;
	}

	let { activeTab, onTabChange }: Props = $props();

	const videoSearchEnabled = $derived($capabilities.capabilities.features.video_search ?? false);
</script>

<div class="flex border-b border-[var(--color-border)]">
	<button
		type="button"
		onclick={() => onTabChange('documents')}
		class="flex items-center gap-2 px-4 py-3 text-sm font-medium transition-colors {activeTab ===
		'documents'
			? 'border-b-2 border-[var(--color-accent)] text-[var(--color-accent)]'
			: 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]'}"
	>
		<FileText class="h-4 w-4" />
		Documents
	</button>
	{#if videoSearchEnabled}
		<button
			type="button"
			onclick={() => onTabChange('videos')}
			class="flex items-center gap-2 px-4 py-3 text-sm font-medium transition-colors {activeTab ===
			'videos'
				? 'border-b-2 border-[var(--color-accent)] text-[var(--color-accent)]'
				: 'text-[var(--color-text-secondary)] hover:text-[var(--color-text-primary)]'}"
		>
			<Video class="h-4 w-4" />
			Videos
		</button>
	{:else}
		<span
			class="flex cursor-default items-center gap-2 px-4 py-3 text-sm font-medium text-[var(--color-text-secondary)]/50"
			title="Video features coming soon"
		>
			<Video class="h-4 w-4" />
			Videos
			<span
				class="rounded-full bg-gray-100 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-[var(--color-text-secondary)]"
				>Soon</span
			>
		</span>
	{/if}
</div>
