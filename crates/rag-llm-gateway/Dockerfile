# Rust LLM Gateway Service Dockerfile
# Multi-stage build with cargo-chef for dependency caching

# ============ Chef Stage ============
FROM rust:1.93-bookworm AS chef
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

# Install build dependencies
RUN apt-get update && apt-get install -y \
    pkg-config \
    libssl-dev \
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

RUN cargo build --release -p rag-llm-gateway

# ============ Runtime Stage ============
FROM debian:bookworm-slim

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    ca-certificates \
    libssl3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd -r -s /bin/false appuser

# Copy binary from builder
COPY --from=builder /app/target/release/llm-gateway /app/llm-gateway

# Set ownership
RUN chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Expose port
EXPOSE 8004

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8004/health || exit 1

# Environment defaults
ENV RUST_LOG=info
ENV LLM_GATEWAY_HOST=0.0.0.0
ENV LLM_GATEWAY_PORT=8004

# Run the service
CMD ["/app/llm-gateway"]
