# Rust LLM Gateway Service Dockerfile
# Multi-stage build for minimal production image

# ============ Build Stage ============
FROM rust:1.75-bookworm AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy workspace files
COPY Cargo.toml Cargo.lock ./
COPY rag-types ./rag-types
COPY rag-config ./rag-config
COPY rag-embedding ./rag-embedding
COPY rag-telemetry ./rag-telemetry
COPY rag-llm-gateway ./rag-llm-gateway

# Build release binary
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
