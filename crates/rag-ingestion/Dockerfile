# Rust Ingestion Service Dockerfile
# Multi-stage build with cargo-chef for dependency caching
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
COPY rag-retrieval ./rag-retrieval
COPY rag-auth ./rag-auth
COPY rag-telemetry ./rag-telemetry
COPY rag-storage ./rag-storage
COPY rag-vectorstore ./rag-vectorstore
COPY rag-search ./rag-search
COPY rag-database ./rag-database
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
COPY rag-retrieval ./rag-retrieval
COPY rag-auth ./rag-auth
COPY rag-telemetry ./rag-telemetry
COPY rag-storage ./rag-storage
COPY rag-vectorstore ./rag-vectorstore
COPY rag-search ./rag-search
COPY rag-database ./rag-database
COPY rag-ingestion ./rag-ingestion
COPY rag-video ./rag-video
COPY rag-embedding ./rag-embedding
COPY rag-tenant ./rag-tenant
COPY rag-secrets ./rag-secrets
COPY rag-encryption ./rag-encryption
COPY rag-llm-gateway ./rag-llm-gateway

RUN cargo build --release -p rag-ingestion --bin ingestion-api

# ============ Runtime Stage ============
FROM debian:bookworm-slim AS runtime

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    ca-certificates \
    libssl3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd -r -s /bin/false ingestion

WORKDIR /app

# Copy the built binary
COPY --from=builder /app/target/release/ingestion-api /app/ingestion-api

# Set ownership
RUN chown -R ingestion:ingestion /app

# Switch to non-root user
USER ingestion

# Expose port
EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8001/health/live || exit 1

# Environment defaults
ENV RUST_LOG=info
ENV INGESTION_HOST=0.0.0.0
ENV INGESTION_PORT=8001

# Run the service
CMD ["/app/ingestion-api"]
