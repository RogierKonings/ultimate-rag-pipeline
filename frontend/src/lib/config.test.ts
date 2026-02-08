import { describe, it, expect, vi, beforeEach } from 'vitest';

describe('VIDEO_ENABLED config', () => {
	beforeEach(() => {
		vi.resetModules();
	});

	it('defaults to false when PUBLIC_VIDEO_ENABLED is not set', async () => {
		vi.doMock('$env/static/public', () => ({
			PUBLIC_VIDEO_ENABLED: ''
		}));

		const config = await import('./config');
		expect(config.VIDEO_ENABLED).toBe(false);
	});

	it('is false when PUBLIC_VIDEO_ENABLED is "false"', async () => {
		vi.doMock('$env/static/public', () => ({
			PUBLIC_VIDEO_ENABLED: 'false'
		}));

		const config = await import('./config');
		expect(config.VIDEO_ENABLED).toBe(false);
	});

	it('is true only when PUBLIC_VIDEO_ENABLED is exactly "true"', async () => {
		vi.doMock('$env/static/public', () => ({
			PUBLIC_VIDEO_ENABLED: 'true'
		}));

		const config = await import('./config');
		expect(config.VIDEO_ENABLED).toBe(true);
	});

	it('is false for truthy-but-not-"true" values like "1" or "yes"', async () => {
		vi.doMock('$env/static/public', () => ({
			PUBLIC_VIDEO_ENABLED: '1'
		}));

		const config = await import('./config');
		expect(config.VIDEO_ENABLED).toBe(false);
	});

	it('is false for undefined', async () => {
		vi.doMock('$env/static/public', () => ({
			PUBLIC_VIDEO_ENABLED: undefined
		}));

		const config = await import('./config');
		expect(config.VIDEO_ENABLED).toBe(false);
	});
});
