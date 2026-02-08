import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// ---------------------------------------------------------------------------
// Mock SvelteKit env modules
// ---------------------------------------------------------------------------
vi.mock('$env/static/public', () => ({
	PUBLIC_DEMO_TENANT_ID: '00000000-0000-0000-0000-000000000001',
	PUBLIC_VIDEO_ENABLED: 'false'
}));

// ---------------------------------------------------------------------------
// Tests: VIDEO_ENABLED = false (default)
// ---------------------------------------------------------------------------
describe('video API with VIDEO_ENABLED=false', () => {
	let videoApi: typeof import('./video');

	beforeEach(async () => {
		vi.resetModules();

		// Ensure VIDEO_ENABLED is false
		vi.doMock('$env/static/public', () => ({
			PUBLIC_DEMO_TENANT_ID: '00000000-0000-0000-0000-000000000001',
			PUBLIC_VIDEO_ENABLED: 'false'
		}));

		// Re-mock config so it picks up the env value
		vi.doMock('$lib/config', () => ({
			VIDEO_ENABLED: false
		}));

		videoApi = await import('./video');
	});

	it('listVideos throws VideoFeatureDisabledError', async () => {
		await expect(videoApi.listVideos()).rejects.toThrow(videoApi.VideoFeatureDisabledError);
	});

	it('getVideo throws VideoFeatureDisabledError', async () => {
		await expect(videoApi.getVideo('test-id')).rejects.toThrow(
			videoApi.VideoFeatureDisabledError
		);
	});

	it('getVideoStatus throws VideoFeatureDisabledError', async () => {
		await expect(videoApi.getVideoStatus('test-id')).rejects.toThrow(
			videoApi.VideoFeatureDisabledError
		);
	});

	it('deleteVideo throws VideoFeatureDisabledError', async () => {
		await expect(videoApi.deleteVideo('test-id')).rejects.toThrow(
			videoApi.VideoFeatureDisabledError
		);
	});

	it('batchDeleteVideos throws VideoFeatureDisabledError', async () => {
		await expect(videoApi.batchDeleteVideos(['id-1', 'id-2'])).rejects.toThrow(
			videoApi.VideoFeatureDisabledError
		);
	});

	it('searchVideos throws VideoFeatureDisabledError', async () => {
		await expect(videoApi.searchVideos({ query: 'test' })).rejects.toThrow(
			videoApi.VideoFeatureDisabledError
		);
	});

	it('pollVideoStatus throws VideoFeatureDisabledError', async () => {
		await expect(videoApi.pollVideoStatus('test-id')).rejects.toThrow(
			videoApi.VideoFeatureDisabledError
		);
	});

	it('getClipUrl returns empty string', () => {
		expect(videoApi.getClipUrl('vid-1', 0, 5000)).toBe('');
	});

	it('getStreamUrl returns empty string', () => {
		expect(videoApi.getStreamUrl('vid-1')).toBe('');
	});

	it('error message mentions how to enable the feature', async () => {
		try {
			await videoApi.listVideos();
			expect.fail('Should have thrown');
		} catch (err) {
			expect((err as Error).message).toContain('PUBLIC_VIDEO_ENABLED=true');
		}
	});

	it('no fetch calls are made when video is disabled', async () => {
		const fetchSpy = vi.spyOn(globalThis, 'fetch');

		try {
			await videoApi.listVideos();
		} catch {
			// Expected to throw
		}
		try {
			await videoApi.searchVideos({ query: 'test' });
		} catch {
			// Expected to throw
		}

		expect(fetchSpy).not.toHaveBeenCalled();
		fetchSpy.mockRestore();
	});
});

// ---------------------------------------------------------------------------
// Tests: VIDEO_ENABLED = true
// ---------------------------------------------------------------------------
describe('video API with VIDEO_ENABLED=true', () => {
	let videoApi: typeof import('./video');
	let originalFetch: typeof globalThis.fetch;

	beforeEach(async () => {
		originalFetch = globalThis.fetch;
		vi.resetModules();

		vi.doMock('$env/static/public', () => ({
			PUBLIC_DEMO_TENANT_ID: '00000000-0000-0000-0000-000000000001',
			PUBLIC_VIDEO_ENABLED: 'true'
		}));

		vi.doMock('$lib/config', () => ({
			VIDEO_ENABLED: true
		}));

		videoApi = await import('./video');
	});

	afterEach(() => {
		globalThis.fetch = originalFetch;
	});

	it('getClipUrl returns a valid URL', () => {
		const url = videoApi.getClipUrl('vid-1', 1000, 5000);
		expect(url).toContain('/api/proxy/retrieval/videos/vid-1/clip');
		expect(url).toContain('start=1000');
		expect(url).toContain('end=5000');
		expect(url).toContain('tenant_id=');
	});

	it('getStreamUrl returns a valid URL', () => {
		const url = videoApi.getStreamUrl('vid-1');
		expect(url).toContain('/api/proxy/retrieval/videos/vid-1/stream');
		expect(url).toContain('tenant_id=');
	});

	it('listVideos makes a fetch call when enabled', async () => {
		const mockResponse = {
			videos: [],
			pagination: { page: 1, page_size: 50, total: 0, total_pages: 0 }
		};

		globalThis.fetch = vi.fn().mockResolvedValue({
			ok: true,
			status: 200,
			json: async () => mockResponse
		} as unknown as Response);

		const result = await videoApi.listVideos();
		expect(result).toEqual(mockResponse);
		expect(globalThis.fetch).toHaveBeenCalled();
	});

	it('searchVideos makes a fetch call when enabled', async () => {
		const mockResponse = {
			query: 'test',
			mode: 'hybrid',
			videos: [],
			total_videos: 0,
			total_matches: 0,
			metrics: { total_ms: 42 }
		};

		globalThis.fetch = vi.fn().mockResolvedValue({
			ok: true,
			status: 200,
			json: async () => mockResponse
		} as unknown as Response);

		const result = await videoApi.searchVideos({ query: 'test' });
		expect(result).toEqual(mockResponse);
		expect(globalThis.fetch).toHaveBeenCalled();
	});

	it.each([404, 405, 501])(
		'throws VideoBackendUnavailableError for backend unavailable status %s',
		async (status) => {
			globalThis.fetch = vi.fn().mockResolvedValue({
				ok: false,
				status,
				json: async () => ({
					error: 'not_available',
					message: 'Not available'
				})
			} as unknown as Response);

			await expect(videoApi.listVideos()).rejects.toThrow(videoApi.VideoBackendUnavailableError);
		}
	);

	it('preserves original API errors for non-capability statuses', async () => {
		globalThis.fetch = vi.fn().mockResolvedValue({
			ok: false,
			status: 500,
			json: async () => ({
				error: 'internal',
				message: 'Internal error'
			})
		} as unknown as Response);

		try {
			await videoApi.listVideos();
			expect.fail('Should have thrown');
		} catch (err) {
			expect(err).not.toBeInstanceOf(videoApi.VideoBackendUnavailableError);
			expect(err).toHaveProperty('status', 500);
		}
	});
});
