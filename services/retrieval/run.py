"""Entry point for the Retrieval Service."""

import uvicorn

from config import RetrievalConfig


def main():
    """Start the Retrieval Service."""
    config = RetrievalConfig()

    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=config.service_port,
        reload=config.debug,
        log_level="debug" if config.debug else "info",
    )


if __name__ == "__main__":
    main()
