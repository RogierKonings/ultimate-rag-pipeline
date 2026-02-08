import { createProxyHandlers } from '$lib/server/proxy';
import { ORCHESTRATOR_URL } from '$env/static/private';

const config = {
	baseUrl: ORCHESTRATOR_URL || 'http://localhost:8003',
	pathPrefix: '/api/v1',
	serviceName: 'orchestrator',
	streamPaths: ['query/stream']
};

export const { GET, POST } = createProxyHandlers(config);
