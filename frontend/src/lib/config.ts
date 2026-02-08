import { PUBLIC_VIDEO_ENABLED } from '$env/static/public';

/**
 * Feature flags for the frontend application.
 *
 * VIDEO_ENABLED gates all video-related UI and API calls.
 * It defaults to false because the backend video endpoints
 * (ingestion and retrieval) are not yet implemented.
 */
export const VIDEO_ENABLED: boolean = PUBLIC_VIDEO_ENABLED === 'true';
