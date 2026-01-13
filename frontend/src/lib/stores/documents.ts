import { writable, derived } from 'svelte/store';
import type { Document } from '$lib/api/types';
import { listDocuments } from '$lib/api/ingestion';

interface DocumentsState {
	documents: Document[];
	loading: boolean;
	error: string | null;
	lastFetched: Date | null;
}

function createDocumentsStore() {
	const { subscribe, set, update } = writable<DocumentsState>({
		documents: [],
		loading: false,
		error: null,
		lastFetched: null
	});

	return {
		subscribe,

		async fetch() {
			update((state) => ({ ...state, loading: true, error: null }));

			try {
				const response = await listDocuments();
				update((state) => ({
					...state,
					documents: response.documents,
					loading: false,
					lastFetched: new Date()
				}));
			} catch (error) {
				const message = error instanceof Error ? error.message : 'Failed to fetch documents';
				update((state) => ({
					...state,
					loading: false,
					error: message
				}));
			}
		},

		addDocument(doc: Document) {
			update((state) => ({
				...state,
				documents: [doc, ...state.documents]
			}));
		},

		updateDocument(documentId: string, updates: Partial<Document>) {
			update((state) => ({
				...state,
				documents: state.documents.map((doc) =>
					doc.document_id === documentId ? { ...doc, ...updates } : doc
				)
			}));
		},

		removeDocument(documentId: string) {
			update((state) => ({
				...state,
				documents: state.documents.filter((doc) => doc.document_id !== documentId)
			}));
		},

		removeDocuments(documentIds: string[]) {
			const idsSet = new Set(documentIds);
			update((state) => ({
				...state,
				documents: state.documents.filter((doc) => !idsSet.has(doc.document_id))
			}));
		},

		reset() {
			set({
				documents: [],
				loading: false,
				error: null,
				lastFetched: null
			});
		}
	};
}

export const documents = createDocumentsStore();

// Selection store for batch operations
function createSelectionStore() {
	const { subscribe, set, update } = writable<Set<string>>(new Set());

	return {
		subscribe,

		toggle(documentId: string) {
			update((selected) => {
				const newSelected = new Set(selected);
				if (newSelected.has(documentId)) {
					newSelected.delete(documentId);
				} else {
					newSelected.add(documentId);
				}
				return newSelected;
			});
		},

		select(documentId: string) {
			update((selected) => {
				const newSelected = new Set(selected);
				newSelected.add(documentId);
				return newSelected;
			});
		},

		deselect(documentId: string) {
			update((selected) => {
				const newSelected = new Set(selected);
				newSelected.delete(documentId);
				return newSelected;
			});
		},

		selectAll(documentIds: string[]) {
			set(new Set(documentIds));
		},

		deselectAll() {
			set(new Set());
		},

		isSelected(documentId: string): boolean {
			let result = false;
			subscribe((selected) => {
				result = selected.has(documentId);
			})();
			return result;
		}
	};
}

export const selectedDocuments = createSelectionStore();

// Derived stores for filtering
export const sampleDocuments = derived(documents, ($docs) =>
	$docs.documents.filter((doc) => doc.source_id.startsWith('sample/'))
);

export const userDocuments = derived(documents, ($docs) =>
	$docs.documents.filter((doc) => !doc.source_id.startsWith('sample/'))
);

export const processingDocuments = derived(documents, ($docs) =>
	$docs.documents.filter((doc) => doc.status === 'pending')
);

// Derived store for selection count
export const selectedCount = derived(selectedDocuments, ($selected) => $selected.size);
