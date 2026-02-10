import { derived, writable } from 'svelte/store';

function createVideoSelectionStore() {
	const { subscribe, set, update } = writable<Set<string>>(new Set());

	return {
		subscribe,

		toggle(videoId: string) {
			update((selected) => {
				const nextSelected = new Set(selected);
				if (nextSelected.has(videoId)) {
					nextSelected.delete(videoId);
				} else {
					nextSelected.add(videoId);
				}
				return nextSelected;
			});
		},

		select(videoId: string) {
			update((selected) => {
				const nextSelected = new Set(selected);
				nextSelected.add(videoId);
				return nextSelected;
			});
		},

		deselect(videoId: string) {
			update((selected) => {
				const nextSelected = new Set(selected);
				nextSelected.delete(videoId);
				return nextSelected;
			});
		},

		selectAll(videoIds: string[]) {
			set(new Set(videoIds));
		},

		deselectAll() {
			set(new Set());
		},

		isSelected(videoId: string): boolean {
			let result = false;
			subscribe((selected) => {
				result = selected.has(videoId);
			})();
			return result;
		}
	};
}

export const selectedVideos = createVideoSelectionStore();

export const selectedVideoCount = derived(selectedVideos, ($selected) => $selected.size);
