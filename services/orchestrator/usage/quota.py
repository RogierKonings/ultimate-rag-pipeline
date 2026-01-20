"""Quota enforcement exceptions.

Reference: US-10.5.4 - Token Usage Accounting
"""


class QuotaExceededError(Exception):
    """Raised when a tenant exceeds their token quota."""

    def __init__(self, tenant_id: str, limit: int, used: int):
        self.tenant_id = tenant_id
        self.limit = limit
        self.used = used
        self.remaining = max(0, limit - used)
        super().__init__(f"Quota exceeded for tenant {tenant_id}: {used:,}/{limit:,} tokens used")
