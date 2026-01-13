<script lang="ts">
	import { FileText, Loader2, AlertCircle, FolderOpen, Trash2, CheckSquare, Square, X } from 'lucide-svelte';
	import { documents, sampleDocuments, userDocuments, selectedDocuments, selectedCount } from '$lib/stores/documents';
	import { activeJobs } from '$lib/stores/upload';
	import { batchDeleteDocuments } from '$lib/api/ingestion';
	import DocumentItem from './DocumentItem.svelte';
	import ProcessingIndicator from './ProcessingIndicator.svelte';

	let selectionMode = $state(false);
	let isDeleting = $state(false);
	let showBatchConfirm = $state(false);
	let batchDeleteError = $state<string | null>(null);

	const allUserDocumentIds = $derived($userDocuments.map((doc) => doc.document_id));
	const allSelected = $derived(
		$userDocuments.length > 0 && $userDocuments.every((doc) => $selectedDocuments.has(doc.document_id))
	);
	const someSelected = $derived($selectedCount > 0);

	function toggleSelectionMode() {
		selectionMode = !selectionMode;
		if (!selectionMode) {
			selectedDocuments.deselectAll();
		}
	}

	function toggleSelectAll() {
		if (allSelected) {
			selectedDocuments.deselectAll();
		} else {
			selectedDocuments.selectAll(allUserDocumentIds);
		}
	}

	function openBatchDeleteConfirm() {
		batchDeleteError = null;
		showBatchConfirm = true;
	}

	function closeBatchDeleteConfirm() {
		showBatchConfirm = false;
		batchDeleteError = null;
	}

	async function confirmBatchDelete() {
		const idsToDelete = Array.from($selectedDocuments);
		if (idsToDelete.length === 0) return;

		isDeleting = true;
		batchDeleteError = null;

		try {
			const result = await batchDeleteDocuments(idsToDelete);

			// Remove successfully deleted documents from store
			const deletedIds = result.results
				.filter((r) => r.deleted)
				.map((r) => r.document_id);

			documents.removeDocuments(deletedIds);
			selectedDocuments.deselectAll();

			if (result.failed_count > 0) {
				batchDeleteError = `${result.deleted_count} deleted, ${result.failed_count} failed`;
			} else {
				showBatchConfirm = false;
				selectionMode = false;
			}
		} catch (error) {
			batchDeleteError = error instanceof Error ? error.message : 'Failed to delete documents';
		} finally {
			isDeleting = false;
		}
	}
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
				<div class="mb-2 flex items-center justify-between">
					<h3
						class="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-[var(--color-text-secondary)]"
					>
						<FolderOpen class="h-3 w-3" />
						Your Documents
					</h3>
					<button
						type="button"
						onclick={toggleSelectionMode}
						class="rounded p-1 text-xs text-[var(--color-text-secondary)] transition-colors hover:bg-gray-100 hover:text-[var(--color-text-primary)]"
						title={selectionMode ? 'Exit selection mode' : 'Select documents'}
					>
						{#if selectionMode}
							<X class="h-4 w-4" />
						{:else}
							<CheckSquare class="h-4 w-4" />
						{/if}
					</button>
				</div>

				{#if selectionMode}
					<div class="mb-2 flex items-center gap-2">
						<button
							type="button"
							onclick={toggleSelectAll}
							class="flex items-center gap-1 rounded px-2 py-1 text-xs text-[var(--color-text-secondary)] transition-colors hover:bg-gray-100"
						>
							{#if allSelected}
								<CheckSquare class="h-3 w-3" />
								Deselect all
							{:else}
								<Square class="h-3 w-3" />
								Select all
							{/if}
						</button>

						{#if someSelected}
							<button
								type="button"
								onclick={openBatchDeleteConfirm}
								class="flex items-center gap-1 rounded bg-red-50 px-2 py-1 text-xs text-red-600 transition-colors hover:bg-red-100"
							>
								<Trash2 class="h-3 w-3" />
								Delete ({$selectedCount})
							</button>
						{/if}
					</div>
				{/if}

				<div class="space-y-1">
					{#each $userDocuments as doc (doc.document_id)}
						<DocumentItem document={doc} {selectionMode} />
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

{#if showBatchConfirm}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
		onclick={closeBatchDeleteConfirm}
		onkeydown={(e) => e.key === 'Escape' && closeBatchDeleteConfirm()}
		role="dialog"
		aria-modal="true"
		aria-labelledby="batch-delete-dialog-title"
		tabindex="-1"
	>
		<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
		<div
			class="mx-4 w-full max-w-sm rounded-lg bg-white p-6 shadow-xl"
			onclick={(e) => e.stopPropagation()}
			role="document"
		>
			<h3 id="batch-delete-dialog-title" class="text-lg font-semibold text-[var(--color-text-primary)]">
				Delete {$selectedCount} Document{$selectedCount === 1 ? '' : 's'}
			</h3>
			<p class="mt-2 text-sm text-[var(--color-text-secondary)]">
				Are you sure you want to delete {$selectedCount} selected document{$selectedCount === 1 ? '' : 's'}?
				This will remove all documents and their chunks from the database. This action cannot be undone.
			</p>

			{#if batchDeleteError}
				<div class="mt-3 flex items-center gap-2 rounded-lg bg-red-50 p-3 text-sm text-red-700">
					<AlertCircle class="h-4 w-4 shrink-0" />
					<span>{batchDeleteError}</span>
				</div>
			{/if}

			<div class="mt-4 flex justify-end gap-3">
				<button
					type="button"
					onclick={closeBatchDeleteConfirm}
					disabled={isDeleting}
					class="rounded-lg px-4 py-2 text-sm font-medium text-[var(--color-text-secondary)] transition-colors hover:bg-gray-100 disabled:opacity-50"
				>
					Cancel
				</button>
				<button
					type="button"
					onclick={confirmBatchDelete}
					disabled={isDeleting}
					class="flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-red-700 disabled:opacity-50"
				>
					{#if isDeleting}
						<Loader2 class="h-4 w-4 animate-spin" />
						Deleting...
					{:else}
						Delete {$selectedCount} Document{$selectedCount === 1 ? '' : 's'}
					{/if}
				</button>
			</div>
		</div>
	</div>
{/if}
