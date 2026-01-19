# E2E Test Runner Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install test dependencies
RUN pip install --no-cache-dir \
    pytest==7.4.3 \
    pytest-asyncio==0.23.2 \
    httpx==0.26.0

# Tests are mounted as a volume
CMD ["pytest", "/tests/e2e/", "-v", "--e2e", "--tb=short"]
