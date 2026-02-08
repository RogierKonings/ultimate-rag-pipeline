import { writable } from 'svelte/store';
import type { QueryResponse, SourceDocument, StreamCitationsData, StreamDoneData } from '$lib/api/types';
import { query as apiQuery, queryStream } from '$lib/api/orchestrator';

/**
 * Streaming state represents the current phase of an SSE stream.
 * - 'idle': No stream active
 * - 'connecting': Request sent, waiting for first event
 * - 'streaming': Receiving delta tokens
 * - 'done': Stream completed successfully
 * - 'error': Stream failed
 * - 'cancelled': Stream was cancelled by user
 */
export type StreamingState = 'idle' | 'connecting' | 'streaming' | 'done' | 'error' | 'cancelled';

interface SearchState {
	query: string;
	loading: boolean;
	error: string | null;
	response: QueryResponse | null;
	highlightedSourceId: string | null;
	// Streaming state
	streamingState: StreamingState;
	partialResponse: string;
	streamSources: SourceDocument[];
	streamRequestId: string | null;
	streamModel: string | null;
	streamUsage: { prompt_tokens: number; completion_tokens: number; total_tokens: number } | null;
	streamLatencyMs: number | null;
}

function createSearchStore() {
	const { subscribe, set, update } = writable<SearchState>({
		query: '',
		loading: false,
		error: null,
		response: null,
		highlightedSourceId: null,
		streamingState: 'idle',
		partialResponse: '',
		streamSources: [],
		streamRequestId: null,
		streamModel: null,
		streamUsage: null,
		streamLatencyMs: null
	});

	// Active AbortController for cancelling in-flight streams
	let activeController: AbortController | null = null;

	/**
	 * Cancel any active stream without clearing display state.
	 */
	function cancelStream() {
		if (activeController) {
			activeController.abort();
			activeController = null;
		}
	}

	return {
		subscribe,

		setQuery(query: string) {
			update((state) => ({ ...state, query }));
		},

		/**
		 * Execute a streaming search. Falls back to synchronous query if the
		 * stream fails with a recoverable/network error.
		 */
		async search(queryText: string) {
			if (!queryText.trim()) return;

			// Cancel any in-flight stream
			cancelStream();

			update((state) => ({
				...state,
				query: queryText,
				loading: true,
				error: null,
				response: null,
				highlightedSourceId: null,
				streamingState: 'connecting',
				partialResponse: '',
				streamSources: [],
				streamRequestId: null,
				streamModel: null,
				streamUsage: null,
				streamLatencyMs: null
			}));

			try {
				activeController = queryStream({ query: queryText }, {
					onStart(data) {
						update((state) => ({
							...state,
							streamingState: 'streaming',
							streamRequestId: data.request_id,
							streamModel: data.model
						}));
					},

					onDelta(data) {
						update((state) => ({
							...state,
							partialResponse: state.partialResponse + data.token
						}));
					},

					onCitations(data: StreamCitationsData) {
						const sources: SourceDocument[] = data.sources.map((s, i) => ({
							id: s.chunk_id || `source-${i}`,
							title: s.title || null,
							uri: s.uri || null,
							score: null,
							snippet: null
						}));
						update((state) => ({
							...state,
							streamSources: sources
						}));
					},

					onDone(data: StreamDoneData) {
						update((state) => {
							// Build a complete QueryResponse from the accumulated stream data
							const completeResponse: QueryResponse = {
								request_id: data.request_id,
								response: state.partialResponse,
								sources: state.streamSources,
								session_id: null,
								model: state.streamModel || 'unknown',
								usage: data.usage,
								latency_ms: data.latency_ms,
								strategy_used: null
							};
							return {
								...state,
								loading: false,
								streamingState: 'done',
								response: completeResponse,
								streamUsage: data.usage,
								streamLatencyMs: data.latency_ms
							};
						});
						activeController = null;
					},

					onError(data) {
						// If the error is recoverable, fall back to sync query
						if (data.recoverable) {
							fallbackToSync(queryText);
						} else {
							update((state) => ({
								...state,
								loading: false,
								streamingState: 'error',
								error: data.error || 'Stream failed'
							}));
							activeController = null;
						}
					}
				});
			} catch {
				// If queryStream itself throws (unlikely), fall back to sync
				fallbackToSync(queryText);
			}
		},

		/**
		 * Cancel the active stream. The partial response remains visible.
		 */
		cancel() {
			cancelStream();
			update((state) => ({
				...state,
				loading: false,
				streamingState: state.partialResponse ? 'cancelled' : 'idle'
			}));
		},

		/**
		 * Retry the last query using streaming.
		 */
		retry() {
			let currentQuery = '';
			const unsub = subscribe((state) => {
				currentQuery = state.query;
			});
			unsub();
			if (currentQuery.trim()) {
				this.search(currentQuery);
			}
		},

		highlightSource(sourceId: string | null) {
			update((state) => ({
				...state,
				highlightedSourceId: sourceId
			}));
		},

		clear() {
			cancelStream();
			set({
				query: '',
				loading: false,
				error: null,
				response: null,
				highlightedSourceId: null,
				streamingState: 'idle',
				partialResponse: '',
				streamSources: [],
				streamRequestId: null,
				streamModel: null,
				streamUsage: null,
				streamLatencyMs: null
			});
		}
	};

	/**
	 * Fallback: run the synchronous query endpoint when streaming fails.
	 */
	async function fallbackToSync(queryText: string) {
		activeController = null;
		update((state) => ({
			...state,
			streamingState: 'idle',
			partialResponse: '',
			streamSources: []
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
	}
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
