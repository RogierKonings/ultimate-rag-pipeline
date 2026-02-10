export interface ApiError {
	error: string;
	message: string;
	request_id?: string;
	details?: Array<{
		field: string | null;
		message: string;
		code: string | null;
	}>;
}
