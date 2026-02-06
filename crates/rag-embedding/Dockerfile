# Rust Embedding Service Dockerfile
# Build context: ./crates (the Rust workspace root)

# ============ Builder Stage ============
FROM rust:1.93-slim-bookworm AS builder

WORKDIR /app

# Install dependencies for ML/ONNX (g++ needed for libstdc++ linking by ort-sys/fastembed)
RUN apt-get update && apt-get install -y \
    pkg-config \
    libssl-dev \
    g++ \
    && rm -rf /var/lib/apt/lists/*

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
RUN cargo build --release -p rag-embedding

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

# Copy binary
COPY --from=builder /app/target/release/embedding-service /app/embedding-service

# Set environment variables
ENV EMBEDDING_HOST=0.0.0.0
ENV EMBEDDING_PORT=8080
ENV RUST_LOG=info

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

CMD ["/app/embedding-service"]
