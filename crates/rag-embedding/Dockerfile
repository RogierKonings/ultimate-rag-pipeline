# Build stage
FROM rust:1.75-bookworm AS builder

WORKDIR /app

# Install dependencies for ML
RUN apt-get update && apt-get install -y \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy workspace files
COPY Cargo.toml Cargo.lock ./
COPY rag-types ./rag-types
COPY rag-config ./rag-config
COPY rag-embedding ./rag-embedding

# Build release binary
RUN cargo build --release -p rag-embedding

# Runtime stage
FROM debian:bookworm-slim

WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y \
    ca-certificates \
    libssl3 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy binary
COPY --from=builder /app/target/release/embedding-service /app/embedding-service

# Set environment variables
ENV EMBEDDING_HOST=0.0.0.0
ENV EMBEDDING_PORT=8080
ENV RUST_LOG=info

EXPOSE 8080

CMD ["/app/embedding-service"]
