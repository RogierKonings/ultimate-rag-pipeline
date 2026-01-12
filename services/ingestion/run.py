#!/usr/bin/env python
"""Run the ingestion service."""

import uvicorn

from config import get_settings

if __name__ == "__main__":
    settings = get_settings()

    uvicorn.run(
        "api.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="info",
    )
