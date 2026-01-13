<script lang="ts">
	import { FileText, FileCheck, AlertCircle, Clock } from 'lucide-svelte';
	import type { Document } from '$lib/api/types';

	interface Props {
		document: Document;
	}

	let { document }: Props = $props();

	const StatusIcon = $derived.by(() => {
		switch (document.status) {
			case 'indexed':
				return FileCheck;
			case 'pending':
				return Clock;
			case 'failed':
				return AlertCircle;
			default:
				return FileText;
		}
	});

	const statusColor = $derived.by(() => {
		switch (document.status) {
			case 'indexed':
				return 'text-[var(--color-success)]';
			case 'pending':
				return 'text-[var(--color-warning)]';
			case 'failed':
				return 'text-[var(--color-error)]';
			default:
				return 'text-[var(--color-text-secondary)]';
		}
	});

	const displayName = $derived.by(() => {
		return document.title || document.filename || document.source_id.split('/').pop() || 'Document';
	});
</script>

<div
	class="group flex items-center gap-3 rounded-lg px-3 py-2 transition-colors hover:bg-gray-50 cursor-pointer"
>
	<div class={`shrink-0 ${statusColor}`}>
		<StatusIcon class="h-4 w-4" />
	</div>

	<div class="min-w-0 flex-1">
		<p
			class="truncate text-sm font-medium text-[var(--color-text-primary)] group-hover:text-[var(--color-accent)]"
		>
			{displayName}
		</p>
		{#if document.chunk_count > 0}
			<p class="text-xs text-[var(--color-text-secondary)]">
				{document.chunk_count} chunks
			</p>
		{/if}
	</div>
</div>
