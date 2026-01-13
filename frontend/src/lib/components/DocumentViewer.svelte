<script lang="ts">
	import { X, FileText, ExternalLink } from 'lucide-svelte';
	import type { SourceDocument } from '$lib/api/types';

	interface Props {
		source: SourceDocument;
		onClose: () => void;
	}

	let { source, onClose }: Props = $props();

	function handleBackdropClick(e: MouseEvent) {
		if (e.target === e.currentTarget) {
			onClose();
		}
	}
</script>

<!-- Backdrop -->
<div
	class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
	onclick={handleBackdropClick}
	role="dialog"
	aria-modal="true"
	aria-labelledby="viewer-title"
>
	<!-- Modal -->
	<div
		class="flex h-[80vh] w-full max-w-3xl flex-col rounded-xl bg-[var(--color-surface)] shadow-xl"
		onclick={(e) => e.stopPropagation()}
	>
		<!-- Header -->
		<div class="flex shrink-0 items-center justify-between border-b border-[var(--color-border)] px-6 py-4">
			<div class="flex items-center gap-3">
				<div class="flex h-10 w-10 items-center justify-center rounded-lg bg-[var(--color-accent)]/10">
					<FileText class="h-5 w-5 text-[var(--color-accent)]" />
				</div>
				<div>
					<h2 id="viewer-title" class="font-semibold text-[var(--color-text-primary)]">
						{source.title || 'Document'}
					</h2>
					{#if source.uri}
						<a
							href={source.uri}
							target="_blank"
							rel="noopener noreferrer"
							class="flex items-center gap-1 text-xs text-[var(--color-accent)] hover:underline"
						>
							<ExternalLink class="h-3 w-3" />
							View original
						</a>
					{/if}
				</div>
			</div>
			<button
				onclick={onClose}
				class="rounded-lg p-1 text-[var(--color-text-secondary)] hover:bg-gray-100 hover:text-[var(--color-text-primary)]"
			>
				<X class="h-5 w-5" />
			</button>
		</div>

		<!-- Content -->
		<div class="flex-1 overflow-y-auto p-6">
			{#if source.snippet}
				<div class="rounded-lg bg-gray-50 p-6">
					<p class="whitespace-pre-wrap text-[var(--color-text-primary)] leading-relaxed">
						{source.snippet}
					</p>
				</div>

				<!-- Relevance Score -->
				{#if source.score !== null}
					<div class="mt-6 flex items-center gap-3 text-sm">
						<span class="text-[var(--color-text-secondary)]">Relevance Score:</span>
						<div class="flex items-center gap-2">
							<div class="h-2 w-24 rounded-full bg-gray-200 overflow-hidden">
								<div
									class="h-full rounded-full bg-[var(--color-success)]"
									style="width: {(source.score * 100).toFixed(0)}%"
								></div>
							</div>
							<span class="font-mono text-[var(--color-text-primary)]">
								{(source.score * 100).toFixed(1)}%
							</span>
						</div>
					</div>
				{/if}
			{:else}
				<div class="flex h-full items-center justify-center">
					<p class="text-[var(--color-text-secondary)]">No content available</p>
				</div>
			{/if}
		</div>

		<!-- Footer -->
		<div class="shrink-0 border-t border-[var(--color-border)] px-6 py-4">
			<div class="flex items-center justify-between text-xs text-[var(--color-text-secondary)]">
				<span>Source ID: {source.id}</span>
				{#if source.score !== null}
					<span>Match: {(source.score * 100).toFixed(1)}%</span>
				{/if}
			</div>
		</div>
	</div>
</div>
