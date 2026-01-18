"""Exceptions for rate limiting module."""


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded in hard limit mode.

    Attributes:
        tenant_id: The tenant that exceeded their limit.
        current_jobs: Number of currently active jobs.
        max_jobs: Maximum allowed concurrent jobs.
    """

    def __init__(
        self,
        tenant_id: str,
        current_jobs: int,
        max_jobs: int,
    ) -> None:
        self.tenant_id = tenant_id
        self.current_jobs = current_jobs
        self.max_jobs = max_jobs
        super().__init__(
            f"Rate limit exceeded for tenant {tenant_id}: "
            f"{current_jobs}/{max_jobs} concurrent jobs"
        )
