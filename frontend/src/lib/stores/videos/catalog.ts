import { derived, writable } from 'svelte/store';
import type { Video } from '$lib/api/types';
import { listVideos } from '$lib/api/video';

interface VideosState {
	videos: Video[];
	loading: boolean;
	error: string | null;
	lastFetched: Date | null;
}

function createVideosStore() {
	const { subscribe, set, update } = writable<VideosState>({
		videos: [],
		loading: false,
		error: null,
		lastFetched: null
	});

	return {
		subscribe,

		async fetch() {
			update((state) => ({ ...state, loading: true, error: null }));

			try {
				const response = await listVideos();
				update((state) => ({
					...state,
					videos: response.videos,
					loading: false,
					lastFetched: new Date()
				}));
			} catch (error) {
				const message = error instanceof Error ? error.message : 'Failed to fetch videos';
				update((state) => ({
					...state,
					loading: false,
					error: message
				}));
			}
		},

		addVideo(video: Video) {
			update((state) => ({
				...state,
				videos: [video, ...state.videos]
			}));
		},

		updateVideo(videoId: string, updates: Partial<Video>) {
			update((state) => ({
				...state,
				videos: state.videos.map((video) =>
					video.video_id === videoId ? { ...video, ...updates } : video
				)
			}));
		},

		removeVideo(videoId: string) {
			update((state) => ({
				...state,
				videos: state.videos.filter((video) => video.video_id !== videoId)
			}));
		},

		removeVideos(videoIds: string[]) {
			const idsSet = new Set(videoIds);
			update((state) => ({
				...state,
				videos: state.videos.filter((video) => !idsSet.has(video.video_id))
			}));
		},

		reset() {
			set({
				videos: [],
				loading: false,
				error: null,
				lastFetched: null
			});
		}
	};
}

export const videos = createVideosStore();

export const processingVideos = derived(videos, ($videos) =>
	$videos.videos.filter((video) => video.status === 'processing')
);

export const readyVideos = derived(videos, ($videos) =>
	$videos.videos.filter((video) => video.status === 'ready')
);
