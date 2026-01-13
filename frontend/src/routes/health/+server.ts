import { json } from '@sveltejs/kit';
import type { RequestHandler } from './$types';

export const GET: RequestHandler = async () => {
	return json({
		status: 'healthy',
		service: 'compliance-ai-demo',
		timestamp: new Date().toISOString()
	});
};
