<script lang="ts">
	import { FileText, Loader2, AlertCircle, FolderOpen } from 'lucide-svelte';
	import { documents, sampleDocuments, userDocuments } from '$lib/stores/documents';
	import { activeJobs } from '$lib/stores/upload';
	import DocumentItem from './DocumentItem.svelte';
	import ProcessingIndicator from './ProcessingIndicator.svelte';
</script>

<aside
	class="w-[var(--spacing-sidebar)] shrink-0 overflow-y-auto border-r border-[var(--color-border)] bg-[var(--color-surface)]"
>
	<div class="p-4">
		<!-- Active Processing Jobs -->
		{#if $activeJobs.length > 0}
			<div class="mb-6">
				<h3
					class="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-[var(--color-text-secondary)]"
				>
					<Loader2 class="h-3 w-3 animate-spin" />
					Processing
				</h3>
				<div class="space-y-2">
					{#each $activeJobs as job (job.id)}
						<ProcessingIndicator {job} />
					{/each}
				</div>
			</div>
		{/if}

		<!-- User Documents -->
		{#if $userDocuments.length > 0}
			<div class="mb-6">
				<h3
					class="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-[var(--color-text-secondary)]"
				>
					<FolderOpen class="h-3 w-3" />
					Your Documents
				</h3>
				<div class="space-y-1">
					{#each $userDocuments as doc (doc.document_id)}
						<DocumentItem document={doc} />
					{/each}
				</div>
			</div>
		{/if}

		<!-- Sample Documents -->
		<div>
			<h3
				class="mb-2 flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-[var(--color-text-secondary)]"
			>
				<FileText class="h-3 w-3" />
				Sample Documents
			</h3>

			{#if $documents.loading}
				<div class="space-y-2">
					{#each Array(5) as _}
						<div class="skeleton h-10 w-full rounded-lg"></div>
					{/each}
				</div>
			{:else if $documents.error}
				<div
					class="flex items-center gap-2 rounded-lg bg-red-50 p-3 text-sm text-red-700"
				>
					<AlertCircle class="h-4 w-4 shrink-0" />
					<span>{$documents.error}</span>
				</div>
			{:else if $sampleDocuments.length > 0}
				<div class="space-y-1">
					{#each $sampleDocuments as doc (doc.document_id)}
						<DocumentItem document={doc} />
					{/each}
				</div>
			{:else}
				<p class="text-sm text-[var(--color-text-secondary)] italic">
					No sample documents loaded
				</p>
			{/if}
		</div>
	</div>
</aside>
