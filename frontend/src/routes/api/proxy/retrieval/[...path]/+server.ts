import { createProxyHandlers } from '$lib/server/proxy';
import { RETRIEVAL_URL } from '$env/static/private';

const config = {
	baseUrl: RETRIEVAL_URL || 'http://localhost:8002',
	pathPrefix: '/api/v1',
	serviceName: 'retrieval'
};

export const { GET, POST } = createProxyHandlers(config);
