# ---- Builder stage: install dependencies ----
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---- Runtime stage: minimal image ----
FROM python:3.11-slim

WORKDIR /app

# Apply latest Debian security patches
RUN apt-get update && apt-get upgrade -y --no-install-recommends \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Upgrade packages with known CVEs (after COPY to avoid being overwritten)
# - setuptools: vendored copies of wheel and jaraco.context inside setuptools/_vendor/
# - cryptography: CVE-2026-26007
RUN pip install --no-cache-dir --upgrade pip setuptools wheel jaraco.context cryptography

# Copy application code
COPY . .

# Create symlink so "from orchestrator.xxx" imports resolve to /app/xxx
RUN mkdir -p /packages && ln -s /app /packages/orchestrator

# Add shared modules and orchestrator namespace to path
ENV PYTHONPATH=/app:/app/shared:/packages

EXPOSE 8003

# Use environment variable for worker count (default: 1 for backward compatibility)
ENV UVICORN_WORKERS=1

CMD uvicorn api.app:create_app --factory --host 0.0.0.0 --port 8003 --workers ${UVICORN_WORKERS}
