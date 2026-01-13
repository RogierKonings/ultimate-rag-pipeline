<script lang="ts">
	import { onMount } from 'svelte';
	import { documents } from '$lib/stores/documents';
	import { search } from '$lib/stores/search';
	import { upload } from '$lib/stores/upload';
	import DocumentSidebar from '$lib/components/DocumentSidebar.svelte';
	import SearchBar from '$lib/components/SearchBar.svelte';
	import AnswerCard from '$lib/components/AnswerCard.svelte';
	import SourcesPanel from '$lib/components/SourcesPanel.svelte';
	import UploadModal from '$lib/components/UploadModal.svelte';

	onMount(() => {
		documents.fetch();
	});
</script>

<div class="flex h-[calc(100vh-4rem)]">
	<!-- Sidebar -->
	<DocumentSidebar />

	<!-- Main Content -->
	<div class="flex-1 overflow-y-auto">
		<div class="mx-auto max-w-4xl px-6 py-8">
			<!-- Search Bar -->
			<SearchBar />

			<!-- Results Area -->
			{#if $search.loading}
				<!-- Loading State -->
				<div class="mt-8 space-y-4">
					<div class="skeleton h-32 w-full"></div>
					<div class="skeleton h-24 w-full"></div>
					<div class="skeleton h-24 w-full"></div>
				</div>
			{:else if $search.error}
				<!-- Error State -->
				<div
					class="mt-8 rounded-lg border border-red-200 bg-red-50 p-6 text-center text-red-700"
				>
					<p class="font-medium">Search failed</p>
					<p class="mt-1 text-sm">{$search.error}</p>
				</div>
			{:else if $search.response}
				<!-- Results -->
				<div class="mt-8 space-y-6">
					<AnswerCard />
					<SourcesPanel />
				</div>
			{:else}
				<!-- Empty State -->
				<div class="mt-16 text-center">
					<div
						class="mx-auto flex h-16 w-16 items-center justify-center rounded-full bg-gray-100"
					>
						<svg
							class="h-8 w-8 text-gray-400"
							fill="none"
							stroke="currentColor"
							viewBox="0 0 24 24"
						>
							<path
								stroke-linecap="round"
								stroke-linejoin="round"
								stroke-width="2"
								d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
							></path>
						</svg>
					</div>
					<h2 class="mt-4 text-lg font-medium text-[var(--color-text-primary)]">
						Search your documents
					</h2>
					<p class="mt-2 text-sm text-[var(--color-text-secondary)]">
						Ask questions about your legal and compliance documents
					</p>

					<!-- Example Queries -->
					<div class="mt-8">
						<p class="mb-3 text-xs font-medium uppercase tracking-wide text-[var(--color-text-secondary)]">
							Try asking
						</p>
						<div class="flex flex-wrap justify-center gap-2">
							<button
								onclick={() => search.search('What are the GDPR requirements for data deletion?')}
								class="rounded-full border border-[var(--color-border)] bg-white px-4 py-2 text-sm text-[var(--color-text-primary)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
							>
								GDPR data deletion requirements
							</button>
							<button
								onclick={() => search.search('How long is the confidentiality period in the NDA?')}
								class="rounded-full border border-[var(--color-border)] bg-white px-4 py-2 text-sm text-[var(--color-text-primary)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
							>
								NDA confidentiality period
							</button>
							<button
								onclick={() => search.search("What are the data processor's obligations?")}
								class="rounded-full border border-[var(--color-border)] bg-white px-4 py-2 text-sm text-[var(--color-text-primary)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
							>
								Data processor obligations
							</button>
						</div>
					</div>
				</div>
			{/if}
		</div>
	</div>
</div>

<!-- Upload Modal -->
{#if $upload.modalOpen}
	<UploadModal />
{/if}
