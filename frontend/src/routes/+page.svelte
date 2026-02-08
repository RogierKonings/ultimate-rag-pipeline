<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { goto } from '$app/navigation';
	import { VIDEO_ENABLED } from '$lib/config';
	import { documents } from '$lib/stores/documents';
	import { videos, videoUpload } from '$lib/stores/videos';
	import { search } from '$lib/stores/search';
	import { videoSearch, videoPlayer, videoExampleQueries } from '$lib/stores/videoSearch';
	import { upload } from '$lib/stores/upload';
	// Document components
	import DocumentSidebar from '$lib/components/DocumentSidebar.svelte';
	import SearchBar from '$lib/components/SearchBar.svelte';
	import AnswerCard from '$lib/components/AnswerCard.svelte';
	import SourcesPanel from '$lib/components/SourcesPanel.svelte';
	import UploadModal from '$lib/components/UploadModal.svelte';

	// Video components (only rendered when VIDEO_ENABLED)
	import ContentTabs from '$lib/components/ContentTabs.svelte';
	import VideoSidebar from '$lib/components/VideoSidebar.svelte';
	import VideoSearchBar from '$lib/components/VideoSearchBar.svelte';
	import VideoResultCard from '$lib/components/VideoResultCard.svelte';
	import VideoPlayerPanel from '$lib/components/VideoPlayerPanel.svelte';
	import VideoUploadModal from '$lib/components/VideoUploadModal.svelte';

	type Tab = 'documents' | 'videos';

	// Get tab from URL or default to documents.
	// When video is disabled, always force 'documents' even if ?tab=videos is in the URL.
	let activeTab = $derived<Tab>(
		VIDEO_ENABLED ? (($page.url.searchParams.get('tab') as Tab) || 'documents') : 'documents'
	);

	function handleTabChange(tab: Tab) {
		if (!VIDEO_ENABLED && tab === 'videos') return;
		const url = new URL($page.url);
		if (tab === 'documents') {
			url.searchParams.delete('tab');
		} else {
			url.searchParams.set('tab', tab);
		}
		goto(url.toString(), { replaceState: true });
	}

	onMount(() => {
		documents.fetch();
		if (VIDEO_ENABLED) {
			videos.fetch();
		}
	});

	function handleVideoMatchSelect(
		video: (typeof $videoSearch.response)['videos'][number],
		match: (typeof $videoSearch.response)['videos'][number]['matches'][number]
	) {
		videoPlayer.selectMatch(video, match);
	}
</script>

<div class="flex h-[calc(100vh-4rem)]">
	<!-- Sidebar -->
	{#if activeTab === 'documents'}
		<DocumentSidebar />
	{:else}
		<VideoSidebar
			selectedVideoId={$videoPlayer.selectedVideo?.video_id}
			onSelectVideo={(id: string) => {
				const video = $videoSearch.response?.videos.find((v: { video_id: string }) => v.video_id === id);
				if (video) {
					videoPlayer.selectVideo(video);
				}
			}}
		/>
	{/if}

	<!-- Main Content -->
	<div class="flex flex-1 flex-col overflow-hidden">
		<!-- Tabs -->
		<ContentTabs {activeTab} onTabChange={handleTabChange} />

		{#if activeTab === 'documents'}
			<!-- Documents View -->
			<div class="flex-1 overflow-y-auto">
				<div class="mx-auto max-w-4xl px-6 py-8">
					<SearchBar />

					{#if $search.streamingState === 'streaming' || $search.streamingState === 'connecting' || $search.streamingState === 'cancelled'}
						<!-- Streaming: show incremental answer and sources as they arrive -->
						<div class="mt-8 space-y-6">
							<AnswerCard />
							<SourcesPanel />
						</div>
					{:else if $search.loading && $search.streamingState === 'idle'}
						<!-- Sync fallback loading: show skeleton placeholders -->
						<div class="mt-8 space-y-4">
							<div class="skeleton h-32 w-full"></div>
							<div class="skeleton h-24 w-full"></div>
							<div class="skeleton h-24 w-full"></div>
						</div>
					{:else if $search.error}
						<div
							class="mt-8 rounded-lg border border-red-200 bg-red-50 p-6 text-center text-red-700"
						>
							<p class="font-medium">Search failed</p>
							<p class="mt-1 text-sm">{$search.error}</p>
							<button
								onclick={() => search.retry()}
								class="mt-3 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-red-700"
							>
								Retry
							</button>
						</div>
					{:else if $search.response}
						<div class="mt-8 space-y-6">
							<AnswerCard />
							<SourcesPanel />
						</div>
					{:else}
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

							<div class="mt-8">
								<p
									class="mb-3 text-xs font-medium uppercase tracking-wide text-[var(--color-text-secondary)]"
								>
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
		{:else}
			<!-- Videos View -->
			<div class="flex flex-1 overflow-hidden">
				<!-- Search Results -->
				<div class="flex-1 overflow-y-auto">
					<div class="mx-auto max-w-3xl px-6 py-8">
						<VideoSearchBar />

						{#if $videoSearch.loading}
							<div class="mt-8 space-y-4">
								<div class="skeleton h-40 w-full rounded-lg"></div>
								<div class="skeleton h-40 w-full rounded-lg"></div>
							</div>
						{:else if $videoSearch.error}
							<div
								class="mt-8 rounded-lg border border-red-200 bg-red-50 p-6 text-center text-red-700"
							>
								<p class="font-medium">Search failed</p>
								<p class="mt-1 text-sm">{$videoSearch.error}</p>
							</div>
						{:else if $videoSearch.response && $videoSearch.response.videos.length > 0}
							<div class="mt-8 space-y-4">
								<p class="text-sm text-[var(--color-text-secondary)]">
									Found {$videoSearch.response.total_matches} matches in {$videoSearch.response
										.total_videos} videos
								</p>
								{#each $videoSearch.response.videos as result (result.video_id)}
									<VideoResultCard
										{result}
										selectedMatchId={$videoPlayer.selectedMatch?.chunk_id}
										onSelectMatch={(match) => handleVideoMatchSelect(result, match)}
									/>
								{/each}
							</div>
						{:else if $videoSearch.response && $videoSearch.response.videos.length === 0}
							<div class="mt-16 text-center">
								<p class="text-[var(--color-text-secondary)]">
									No matches found. Try different search terms.
								</p>
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
											d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"
										></path>
									</svg>
								</div>
								<h2 class="mt-4 text-lg font-medium text-[var(--color-text-primary)]">
									Search your videos
								</h2>
								<p class="mt-2 text-sm text-[var(--color-text-secondary)]">
									Find specific moments by searching transcripts, scene descriptions, and on-screen
									text
								</p>

								<div class="mt-8">
									<p
										class="mb-3 text-xs font-medium uppercase tracking-wide text-[var(--color-text-secondary)]"
									>
										Try searching
									</p>
									<div class="flex flex-wrap justify-center gap-2">
										{#each videoExampleQueries as query}
											<button
												onclick={() => videoSearch.search(query)}
												class="rounded-full border border-[var(--color-border)] bg-white px-4 py-2 text-sm text-[var(--color-text-primary)] transition-colors hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
											>
												{query}
											</button>
										{/each}
									</div>
								</div>
							</div>
						{/if}
					</div>
				</div>

				<!-- Video Player Panel -->
				<VideoPlayerPanel />
			</div>
		{/if}
	</div>
</div>

<!-- Upload Modals -->
{#if $upload.modalOpen}
	<UploadModal />
{/if}

{#if $videoUpload.modalOpen}
	<VideoUploadModal />
{/if}
