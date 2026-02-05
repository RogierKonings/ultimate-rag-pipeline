<script lang="ts">
	import { FileText, FileCheck, AlertCircle, Clock, Trash2, Loader2 } from 'lucide-svelte';
	import type { Document } from '$lib/api/types';
	import { deleteDocument } from '$lib/api/ingestion';
	import { documents, selectedDocuments } from '$lib/stores/documents';

	interface Props {
		document: Document;
		selectionMode?: boolean;
	}

	let { document, selectionMode = false }: Props = $props();
	const isSelected = $derived($selectedDocuments.has(document.document_id));
	let showConfirm = $state(false);
	let isDeleting = $state(false);
	let deleteError = $state<string | null>(null);

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
		if (document.filename) {
			return document.filename;
		}
		if (document.title) {
			return document.title;
		}
		// Extract original filename from source_id (format: uploads/{tenant}/{timestamp}-{filename})
		const lastSegment = document.source_id.split('/').pop() || 'Document';
		const dashIndex = lastSegment.indexOf('-');
		if (dashIndex > 0 && /^\d+$/.test(lastSegment.substring(0, dashIndex))) {
			return lastSegment.substring(dashIndex + 1);
		}
		return lastSegment;
	});

	function handleDeleteClick(e: MouseEvent) {
		e.stopPropagation();
		showConfirm = true;
		deleteError = null;
	}

	function cancelDelete() {
		showConfirm = false;
		deleteError = null;
	}

	async function confirmDelete() {
		isDeleting = true;
		deleteError = null;

		try {
			await deleteDocument(document.document_id);
			documents.removeDocument(document.document_id);
			showConfirm = false;
		} catch (error) {
			deleteError = error instanceof Error ? error.message : 'Failed to delete document';
		} finally {
			isDeleting = false;
		}
	}
</script>

<div
	class="group flex items-center gap-2 rounded-lg px-3 py-2 transition-colors hover:bg-gray-50 cursor-pointer"
	class:bg-blue-50={isSelected}
	class:hover:bg-blue-100={isSelected}
>
	{#if selectionMode}
		<input
			type="checkbox"
			checked={isSelected}
			onchange={() => selectedDocuments.toggle(document.document_id)}
			onclick={(e) => e.stopPropagation()}
			class="h-4 w-4 shrink-0 cursor-pointer rounded border-gray-300 text-blue-600 focus:ring-blue-500"
		/>
	{/if}

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

	{#if !selectionMode}
		<button
			type="button"
			onclick={handleDeleteClick}
			class="shrink-0 rounded p-1 text-[var(--color-text-secondary)] opacity-0 transition-all hover:bg-red-50 hover:text-red-600 group-hover:opacity-100"
			title="Delete document"
		>
			<Trash2 class="h-4 w-4" />
		</button>
	{/if}
</div>

{#if showConfirm}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
		onclick={cancelDelete}
		onkeydown={(e) => e.key === 'Escape' && cancelDelete()}
		role="dialog"
		aria-modal="true"
		aria-labelledby="delete-dialog-title"
		tabindex="-1"
	>
			<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
		<div
			class="mx-4 w-full max-w-sm rounded-lg bg-white p-6 shadow-xl"
			onclick={(e) => e.stopPropagation()}
			onkeydown={(e) => e.stopPropagation()}
			role="document"
		>
			<h3 id="delete-dialog-title" class="text-lg font-semibold text-[var(--color-text-primary)]">
				Delete Document
			</h3>
			<p class="mt-2 text-sm text-[var(--color-text-secondary)]">
				Are you sure you want to delete "{displayName}"? This will remove the document and all its chunks from the database. This action cannot be undone.
			</p>

			{#if deleteError}
				<div class="mt-3 flex items-center gap-2 rounded-lg bg-red-50 p-3 text-sm text-red-700">
					<AlertCircle class="h-4 w-4 shrink-0" />
					<span>{deleteError}</span>
				</div>
			{/if}

			<div class="mt-4 flex justify-end gap-3">
				<button
					type="button"
					onclick={cancelDelete}
					disabled={isDeleting}
					class="rounded-lg px-4 py-2 text-sm font-medium text-[var(--color-text-secondary)] transition-colors hover:bg-gray-100 disabled:opacity-50"
				>
					Cancel
				</button>
				<button
					type="button"
					onclick={confirmDelete}
					disabled={isDeleting}
					class="flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-red-700 disabled:opacity-50"
				>
					{#if isDeleting}
						<Loader2 class="h-4 w-4 animate-spin" />
						Deleting...
					{:else}
						Delete
					{/if}
				</button>
			</div>
		</div>
	</div>
{/if}
