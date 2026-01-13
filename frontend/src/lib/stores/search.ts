import { writable } from 'svelte/store';
import type { QueryResponse, SourceDocument } from '$lib/api/types';
import { query as apiQuery } from '$lib/api/orchestrator';

interface SearchState {
	query: string;
	loading: boolean;
	error: string | null;
	response: QueryResponse | null;
	highlightedSourceId: string | null;
}

function createSearchStore() {
	const { subscribe, set, update } = writable<SearchState>({
		query: '',
		loading: false,
		error: null,
		response: null,
		highlightedSourceId: null
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
				response: null,
				highlightedSourceId: null
			}));

			try {
				const response = await apiQuery({ query: queryText });
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

		highlightSource(sourceId: string | null) {
			update((state) => ({
				...state,
				highlightedSourceId: sourceId
			}));
		},

		clear() {
			set({
				query: '',
				loading: false,
				error: null,
				response: null,
				highlightedSourceId: null
			});
		}
	};
}

export const search = createSearchStore();

// Example queries for the demo
export const exampleQueries = [
	'What are the GDPR requirements for data deletion?',
	'How long is the confidentiality period in the NDA?',
	"What are the data processor's obligations?",
	'Who should employees contact to report compliance concerns?',
	'What controls are required for SOX compliance?'
];

// Helper to parse citations from response text
export function parseCitations(text: string): Array<{ index: number; position: number }> {
	const citations: Array<{ index: number; position: number }> = [];
	const regex = /\[(\d+)\]/g;
	let match;

	while ((match = regex.exec(text)) !== null) {
		citations.push({
			index: parseInt(match[1], 10) - 1, // Convert to 0-indexed
			position: match.index
		});
	}

	return citations;
}

// Helper to get source by citation index
export function getSourceByCitation(
	sources: SourceDocument[],
	citationIndex: number
): SourceDocument | undefined {
	return sources[citationIndex];
}
