# Rust Retrieval Service Dockerfile
# Multi-stage build for minimal production image
# Build context: ./crates (the Rust workspace root)

# ============ Builder Stage ============
FROM rust:1.87-slim-bookworm AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy workspace files
COPY Cargo.toml Cargo.lock ./

# Copy all workspace members
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

# Build release binary
RUN cargo build --release -p rag-retrieval --bin retrieval-service

# ============ Runtime Stage ============
FROM debian:bookworm-slim AS runtime

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    ca-certificates \
    libssl3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN useradd -r -s /bin/false retrieval

WORKDIR /app

# Copy the built binary
COPY --from=builder /app/target/release/retrieval-service /app/retrieval-service

# Set ownership
RUN chown -R retrieval:retrieval /app

# Switch to non-root user
USER retrieval

# Expose port
EXPOSE 8002

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8002/health/live || exit 1

# Environment defaults
ENV RUST_LOG=info
ENV RETRIEVAL_HOST=0.0.0.0
ENV RETRIEVAL_PORT=8002

# Run the service
CMD ["/app/retrieval-service"]
