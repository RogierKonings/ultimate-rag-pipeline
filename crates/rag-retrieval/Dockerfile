# Rust Retrieval Service Dockerfile
# Multi-stage build for minimal production image

# ============ Builder Stage ============
FROM rust:1.81-slim-bookworm AS builder

# Install build dependencies
RUN apt-get update && apt-get install -y \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Copy workspace Cargo files for dependency caching
COPY Cargo.toml Cargo.lock ./
COPY crates/Cargo.toml ./crates/

# Copy all crate manifests to allow dependency resolution
COPY crates/rag-types/Cargo.toml ./crates/rag-types/
COPY crates/rag-auth/Cargo.toml ./crates/rag-auth/
COPY crates/rag-cache/Cargo.toml ./crates/rag-cache/
COPY crates/rag-config/Cargo.toml ./crates/rag-config/
COPY crates/rag-database/Cargo.toml ./crates/rag-database/
COPY crates/rag-search/Cargo.toml ./crates/rag-search/
COPY crates/rag-storage/Cargo.toml ./crates/rag-storage/
COPY crates/rag-telemetry/Cargo.toml ./crates/rag-telemetry/
COPY crates/rag-vectorstore/Cargo.toml ./crates/rag-vectorstore/
COPY crates/rag-retrieval/Cargo.toml ./crates/rag-retrieval/

# Create dummy source files to cache dependencies
RUN mkdir -p crates/rag-types/src && echo "pub fn dummy() {}" > crates/rag-types/src/lib.rs
RUN mkdir -p crates/rag-auth/src && echo "pub fn dummy() {}" > crates/rag-auth/src/lib.rs
RUN mkdir -p crates/rag-cache/src && echo "pub fn dummy() {}" > crates/rag-cache/src/lib.rs
RUN mkdir -p crates/rag-config/src && echo "pub fn dummy() {}" > crates/rag-config/src/lib.rs
RUN mkdir -p crates/rag-database/src && echo "pub fn dummy() {}" > crates/rag-database/src/lib.rs
RUN mkdir -p crates/rag-search/src && echo "pub fn dummy() {}" > crates/rag-search/src/lib.rs
RUN mkdir -p crates/rag-storage/src && echo "pub fn dummy() {}" > crates/rag-storage/src/lib.rs
RUN mkdir -p crates/rag-telemetry/src && echo "pub fn dummy() {}" > crates/rag-telemetry/src/lib.rs
RUN mkdir -p crates/rag-vectorstore/src && echo "pub fn dummy() {}" > crates/rag-vectorstore/src/lib.rs
RUN mkdir -p crates/rag-retrieval/src && echo "pub fn dummy() {}" > crates/rag-retrieval/src/lib.rs
RUN mkdir -p crates/rag-retrieval/src/bin && echo "fn main() {}" > crates/rag-retrieval/src/bin/main.rs

# Build dependencies only (this layer will be cached)
RUN cargo build --release -p rag-retrieval --bin retrieval-service 2>/dev/null || true

# Copy actual source code
COPY crates/ ./crates/

# Touch source files to invalidate cache and rebuild with real code
RUN touch crates/*/src/lib.rs crates/rag-retrieval/src/bin/main.rs

# Build the actual binary
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
COPY --from=builder /build/target/release/retrieval-service /app/retrieval-service

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
