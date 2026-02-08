import { writable, derived } from 'svelte/store';
import type { ServiceCapabilities } from '$lib/api/types';
import { fetchCapabilities, DEFAULT_CAPABILITIES } from '$lib/api/capabilities';

interface CapabilitiesState {
	loaded: boolean;
	loading: boolean;
	capabilities: ServiceCapabilities;
}

function createCapabilitiesStore() {
	const { subscribe, set, update } = writable<CapabilitiesState>({
		loaded: false,
		loading: false,
		capabilities: DEFAULT_CAPABILITIES
	});

	return {
		subscribe,

		/**
		 * Fetch capabilities from the backend. Safe to call multiple
		 * times -- subsequent calls are no-ops while a fetch is in flight.
		 */
		async fetch() {
			// Optimistic guard: skip if already loaded or loading
			let skip = false;
			const unsub = subscribe((state) => {
				skip = state.loaded || state.loading;
			});
			unsub();
			if (skip) return;

			update((state) => ({ ...state, loading: true }));

			const capabilities = await fetchCapabilities();

			set({
				loaded: true,
				loading: false,
				capabilities
			});
		},

		/**
		 * Force a refresh of capabilities (e.g. after a reconnection).
		 */
		async refresh() {
			update((state) => ({ ...state, loading: true }));
			const capabilities = await fetchCapabilities();
			set({
				loaded: true,
				loading: false,
				capabilities
			});
		}
	};
}

export const capabilities = createCapabilitiesStore();

/**
 * Convenience derived store: is a specific feature enabled?
 *
 * Usage:
 *   import { hasFeature } from '$lib/stores/capabilities';
 *   const videoEnabled = hasFeature('video_search');
 *   {#if $videoEnabled} ... {/if}
 */
export function hasFeature(name: string) {
	return derived(capabilities, ($caps) => $caps.capabilities.features[name] ?? false);
}
