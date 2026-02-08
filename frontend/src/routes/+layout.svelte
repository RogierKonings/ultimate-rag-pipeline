<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { Upload, Scale } from 'lucide-svelte';
	import { page } from '$app/stores';
	import { upload } from '$lib/stores/upload';
	import { videoUpload } from '$lib/stores/videos';
	import { capabilities } from '$lib/stores/capabilities';

	let { children } = $props();

	// Determine active tab from URL
	const activeTab = $derived($page.url.searchParams.get('tab') || 'documents');

	// Fetch capabilities on app startup
	onMount(() => {
		capabilities.fetch();
	});

	// Only show video upload if video_search is enabled
	const videoSearchEnabled = $derived($capabilities.capabilities.features.video_search ?? false);

	function handleUploadClick() {
		if (activeTab === 'videos' && videoSearchEnabled) {
			videoUpload.openModal();
		} else {
			upload.openModal();
		}
	}
</script>

<div class="min-h-screen bg-[var(--color-background)]">
	<!-- Header -->
	<header class="sticky top-0 z-50 border-b border-[var(--color-border)] bg-[var(--color-surface)]">
		<div class="flex h-16 items-center justify-between px-6">
			<!-- Logo & Title -->
			<div class="flex items-center gap-3">
				<div
					class="flex h-9 w-9 items-center justify-center rounded-lg bg-[var(--color-accent)] text-white"
				>
					<Scale class="h-5 w-5" />
				</div>
				<div>
					<h1 class="text-lg font-semibold text-[var(--color-text-primary)]">ComplianceAI</h1>
					<p class="text-xs text-[var(--color-text-secondary)]">Demo</p>
				</div>
			</div>

			<!-- Upload Button -->
			<button
				onclick={handleUploadClick}
				class="flex items-center gap-2 rounded-lg bg-[var(--color-accent)] px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-[var(--color-accent-hover)]"
			>
				<Upload class="h-4 w-4" />
				{#if activeTab === 'videos' && videoSearchEnabled}
					Upload Video
				{:else}
					Upload Document
				{/if}
			</button>
		</div>
	</header>

	<!-- Main Content -->
	<main>
		{@render children()}
	</main>
</div>
