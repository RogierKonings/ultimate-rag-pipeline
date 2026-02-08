# Rust Embedding Service Dockerfile
# Multi-stage build with cargo-chef for dependency caching
# and pre-baked ONNX model to avoid runtime download
# Build context: ./crates (the Rust workspace root)

# ============ Chef Stage ============
FROM rust:1.93-slim-bookworm AS chef
RUN cargo install cargo-chef
WORKDIR /app

# ============ Planner Stage ============
FROM chef AS planner

COPY Cargo.toml Cargo.lock ./
COPY rag-types ./rag-types
COPY rag-config ./rag-config
COPY rag-cache ./rag-cache
COPY rag-auth ./rag-auth
COPY rag-telemetry ./rag-telemetry
COPY rag-search ./rag-search
COPY rag-vectorstore ./rag-vectorstore
COPY rag-database ./rag-database
COPY rag-storage ./rag-storage
COPY rag-retrieval ./rag-retrieval
COPY rag-ingestion ./rag-ingestion
COPY rag-video ./rag-video
COPY rag-embedding ./rag-embedding
COPY rag-tenant ./rag-tenant
COPY rag-secrets ./rag-secrets
COPY rag-encryption ./rag-encryption
COPY rag-llm-gateway ./rag-llm-gateway

RUN cargo chef prepare --recipe-path recipe.json

# ============ Builder Stage ============
FROM chef AS builder

# Install dependencies for ML/ONNX (g++ needed for libstdc++ linking by ort-sys/fastembed)
RUN apt-get update && apt-get install -y \
    pkg-config \
    libssl-dev \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Cook dependencies (cached unless Cargo.toml/Cargo.lock change)
COPY --from=planner /app/recipe.json recipe.json
RUN cargo chef cook --release --recipe-path recipe.json

# Copy full source and build
COPY Cargo.toml Cargo.lock ./
COPY rag-types ./rag-types
COPY rag-config ./rag-config
COPY rag-cache ./rag-cache
COPY rag-auth ./rag-auth
COPY rag-telemetry ./rag-telemetry
COPY rag-search ./rag-search
COPY rag-vectorstore ./rag-vectorstore
COPY rag-database ./rag-database
COPY rag-storage ./rag-storage
COPY rag-retrieval ./rag-retrieval
COPY rag-ingestion ./rag-ingestion
COPY rag-video ./rag-video
COPY rag-embedding ./rag-embedding
COPY rag-tenant ./rag-tenant
COPY rag-secrets ./rag-secrets
COPY rag-encryption ./rag-encryption
COPY rag-llm-gateway ./rag-llm-gateway

RUN cargo build --release -p rag-embedding

# ============ Model Download Stage ============
# Runs in parallel with builder (BuildKit builds independent stages concurrently)
# Downloads the ONNX model during build so it's baked into the image
FROM python:3.11-slim AS model-downloader

RUN pip install --no-cache-dir huggingface_hub

# Download model to HF Hub cache format (same format fastembed expects)
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download('Qdrant/all-MiniLM-L6-v2-onnx', cache_dir='/model-cache')"

# ============ Runtime Stage ============
FROM debian:bookworm-slim

WORKDIR /app

# Install runtime dependencies (libstdc++6 needed for ONNX Runtime)
RUN apt-get update && apt-get install -y \
    ca-certificates \
    libssl3 \
    libstdc++6 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd -r -s /bin/false embedding

# Copy binary
COPY --from=builder /app/target/release/embedding-service /app/embedding-service

# Copy pre-downloaded model (avoids runtime download from HuggingFace)
COPY --from=model-downloader /model-cache /app/.fastembed_cache

# Set ownership
RUN chown -R embedding:embedding /app

# Switch to non-root user
USER embedding

# Set environment variables
ENV EMBEDDING_HOST=0.0.0.0
ENV EMBEDDING_PORT=8080
ENV RUST_LOG=info
# Tell fastembed where to find the pre-cached model
ENV FASTEMBED_CACHE_DIR=/app/.fastembed_cache

EXPOSE 8080

# Reduced start_period from 60s to 15s since model is pre-baked
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

CMD ["/app/embedding-service"]
