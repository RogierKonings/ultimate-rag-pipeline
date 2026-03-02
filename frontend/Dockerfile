# Build stage
FROM node:22-alpine AS builder

WORKDIR /app

# Install pnpm
RUN corepack enable && corepack prepare pnpm@latest --activate

# Copy package files
COPY package.json pnpm-lock.yaml* ./

# Install dependencies
RUN pnpm install --frozen-lockfile

# Copy source files
COPY . .

# Build-time environment variables for SvelteKit static env
# These are required for $env/static/private and $env/static/public imports
ARG PUBLIC_ORCHESTRATOR_URL=http://orchestrator-service:8003
ARG PUBLIC_INGESTION_URL=http://ingestion-service:8001
ARG PUBLIC_DEMO_TENANT_ID=00000000-0000-0000-0000-000000000001
ARG MINIO_ENDPOINT=http://minio:9000
ARG MINIO_ACCESS_KEY=minioadmin
ARG MINIO_SECRET_KEY=minioadmin123
ARG MINIO_BUCKET=rag-documents
ARG INGESTION_URL=http://ingestion-service:8001
ARG ORCHESTRATOR_URL=http://orchestrator-service:8003
ARG RETRIEVAL_URL=http://retrieval-service:8002
ARG DEMO_TENANT_ID=00000000-0000-0000-0000-000000000001

# Set environment variables from build args
ENV PUBLIC_ORCHESTRATOR_URL=$PUBLIC_ORCHESTRATOR_URL
ENV PUBLIC_INGESTION_URL=$PUBLIC_INGESTION_URL
ENV PUBLIC_DEMO_TENANT_ID=$PUBLIC_DEMO_TENANT_ID
ENV MINIO_ENDPOINT=$MINIO_ENDPOINT
ENV MINIO_ACCESS_KEY=$MINIO_ACCESS_KEY
ENV MINIO_SECRET_KEY=$MINIO_SECRET_KEY
ENV MINIO_BUCKET=$MINIO_BUCKET
ENV INGESTION_URL=$INGESTION_URL
ENV ORCHESTRATOR_URL=$ORCHESTRATOR_URL
ENV RETRIEVAL_URL=$RETRIEVAL_URL
ENV DEMO_TENANT_ID=$DEMO_TENANT_ID

# Build the application
RUN pnpm run build

# Production stage
FROM node:22-alpine AS runner

WORKDIR /app

# Upgrade npm to patch bundled vulnerabilities (minimatch, tar, glob)
RUN npm install -g npm@latest

# Install pnpm
RUN corepack enable && corepack prepare pnpm@latest --activate

# Copy package files
COPY package.json pnpm-lock.yaml* ./

# Install production dependencies only
RUN pnpm install --prod --frozen-lockfile

# Copy built application from builder
COPY --from=builder /app/build ./build
COPY --from=builder /app/static ./static

# Set environment variables
ENV NODE_ENV=production
ENV PORT=3000
ENV HOST=0.0.0.0

# Expose port
EXPOSE 3000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://127.0.0.1:3000/health || exit 1

# Start the application
CMD ["node", "build"]
