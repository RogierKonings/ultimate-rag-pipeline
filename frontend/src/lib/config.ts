import { env } from '$env/dynamic/public';

/**
 * Feature flags for the frontend application.
 *
 * VIDEO_ENABLED gates all video-related UI and API calls.
 * It defaults to false because the backend video endpoints
 * (ingestion and retrieval) are not yet implemented.
 */
export const VIDEO_ENABLED: boolean = env.PUBLIC_VIDEO_ENABLED === 'true';
