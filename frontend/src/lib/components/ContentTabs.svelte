<script lang="ts">
	import { FileText, Video } from 'lucide-svelte';

	interface Props {
		activeTab: 'documents' | 'videos';
		onTabChange: (tab: 'documents' | 'videos') => void;
	}

	let { activeTab, onTabChange }: Props = $props();
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
</div>
