import { writable } from 'svelte/store';
import type { VideoSearchResponse, VideoMatch, VideoSearchResult } from '$lib/api/types';
import { searchVideos } from '$lib/api/video';

interface VideoSearchState {
	query: string;
	loading: boolean;
	error: string | null;
	response: VideoSearchResponse | null;
}

function createVideoSearchStore() {
	const { subscribe, set, update } = writable<VideoSearchState>({
		query: '',
		loading: false,
		error: null,
		response: null
	});

	return {
		subscribe,

		setQuery(query: string) {
			update((state) => ({ ...state, query }));
		},

		async search(queryText: string) {
			if (!queryText.trim()) return;

			update((state) => ({
				...state,
				query: queryText,
				loading: true,
				error: null,
				response: null
			}));

			try {
				const response = await searchVideos({ query: queryText });
				update((state) => ({
					...state,
					loading: false,
					response
				}));
			} catch (error) {
				const message = error instanceof Error ? error.message : 'Search failed';
				update((state) => ({
					...state,
					loading: false,
					error: message
				}));
			}
		},

		clear() {
			set({
				query: '',
				loading: false,
				error: null,
				response: null
			});
		}
	};
}

export const videoSearch = createVideoSearchStore();

// Video player state
interface VideoPlayerState {
	selectedVideo: VideoSearchResult | null;
	selectedMatch: VideoMatch | null;
	isPlaying: boolean;
	currentTime: number;
	isPanelOpen: boolean;
}

function createVideoPlayerStore() {
	const { subscribe, set, update } = writable<VideoPlayerState>({
		selectedVideo: null,
		selectedMatch: null,
		isPlaying: false,
		currentTime: 0,
		isPanelOpen: false
	});

	return {
		subscribe,

		selectMatch(video: VideoSearchResult, match: VideoMatch) {
			update((state) => ({
				...state,
				selectedVideo: video,
				selectedMatch: match,
				isPanelOpen: true,
				isPlaying: false,
				currentTime: match.start_seconds
			}));
		},

		selectVideo(video: VideoSearchResult) {
			const firstMatch = video.matches[0] || null;
			update((state) => ({
				...state,
				selectedVideo: video,
				selectedMatch: firstMatch,
				isPanelOpen: true,
				isPlaying: false,
				currentTime: firstMatch?.start_seconds || 0
			}));
		},

		nextMatch() {
			update((state) => {
				if (!state.selectedVideo || !state.selectedMatch) return state;
				const matches = state.selectedVideo.matches;
				const currentIndex = matches.findIndex(
					(m) => m.chunk_id === state.selectedMatch?.chunk_id
				);
				const nextIndex = (currentIndex + 1) % matches.length;
				const nextMatch = matches[nextIndex];
				return {
					...state,
					selectedMatch: nextMatch,
					currentTime: nextMatch.start_seconds
				};
			});
		},

		previousMatch() {
			update((state) => {
				if (!state.selectedVideo || !state.selectedMatch) return state;
				const matches = state.selectedVideo.matches;
				const currentIndex = matches.findIndex(
					(m) => m.chunk_id === state.selectedMatch?.chunk_id
				);
				const prevIndex = currentIndex === 0 ? matches.length - 1 : currentIndex - 1;
				const prevMatch = matches[prevIndex];
				return {
					...state,
					selectedMatch: prevMatch,
					currentTime: prevMatch.start_seconds
				};
			});
		},

		setPlaying(isPlaying: boolean) {
			update((state) => ({ ...state, isPlaying }));
		},

		setCurrentTime(time: number) {
			update((state) => ({ ...state, currentTime: time }));
		},

		togglePanel() {
			update((state) => ({ ...state, isPanelOpen: !state.isPanelOpen }));
		},

		closePanel() {
			update((state) => ({ ...state, isPanelOpen: false }));
		},

		clear() {
			set({
				selectedVideo: null,
				selectedMatch: null,
				isPlaying: false,
				currentTime: 0,
				isPanelOpen: false
			});
		}
	};
}

export const videoPlayer = createVideoPlayerStore();

// Example queries for video search
export const videoExampleQueries = [
	'product demo features',
	'when the speaker mentions pricing',
	'slides about architecture',
	'introduction segment'
];
