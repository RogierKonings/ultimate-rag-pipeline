# ComplianceAI Demo Frontend

A polished Svelte demo application showcasing the RAG pipeline capabilities for legal/compliance document search.

## Features

- **Search & Answer**: Ask questions about legal documents and get AI-powered answers with citations
- **Document Upload**: Upload your own PDF, DOCX, TXT, or MD files for processing
- **Source Attribution**: See exactly which document chunks informed each answer
- **Real-time Processing**: Track document ingestion progress in real-time
- **Pre-loaded Samples**: Includes sample legal/compliance documents for immediate demo

## Quick Start

### Prerequisites

- Node.js 22.x (use `nvm use 22`)
- pnpm (`npm install -g pnpm`)
- Backend services running (see main README)

### Development

```bash
# Install dependencies
pnpm install

# Start development server
pnpm run dev

# Open http://localhost:5173
```

### Production Build

```bash
# Build
pnpm run build

# Preview production build
pnpm run preview
```

### Docker

```bash
# Build and run with Docker
docker build -t compliance-ai-demo .
docker run -p 3000:3000 compliance-ai-demo

# Or use docker-compose from project root
docker-compose --profile app up frontend
```

## Seed Sample Documents

To load the sample legal documents into the RAG pipeline:

```bash
# Ensure backend services are running first
make up

# Seed documents
pnpm run seed
```

## Environment Variables

Create a `.env` file based on `.env.example`:

```env
# Public (exposed to client)
PUBLIC_ORCHESTRATOR_URL=http://localhost:8003
PUBLIC_INGESTION_URL=http://localhost:8001
PUBLIC_DEMO_TENANT_ID=00000000-0000-0000-0000-000000000001

# Private (server-side only)
MINIO_ENDPOINT=http://localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=rag-documents
INGESTION_URL=http://localhost:8001
DEMO_TENANT_ID=00000000-0000-0000-0000-000000000001
```

## Tech Stack

- **Framework**: SvelteKit 2.x with Svelte 5
- **Styling**: Tailwind CSS 4.x
- **Icons**: Lucide Svelte
- **State**: Svelte stores
- **File Upload**: AWS SDK for S3 (MinIO compatible)

## Project Structure

```
frontend/
├── src/
│   ├── lib/
│   │   ├── api/           # API client layer
│   │   ├── components/    # Svelte components
│   │   └── stores/        # State management
│   ├── routes/
│   │   ├── api/upload/    # Server-side upload handler
│   │   ├── health/        # Health check endpoint
│   │   ├── +layout.svelte
│   │   └── +page.svelte
│   ├── app.css
│   └── app.html
├── static/
│   └── samples/           # Sample legal documents
├── scripts/
│   └── seed-demo-documents.ts
└── Dockerfile
```

## Sample Documents

The demo includes these pre-loaded legal/compliance documents:

1. **GDPR Article 17** - Right to erasure requirements
2. **Sample NDA** - Mutual non-disclosure agreement template
3. **Data Processing Agreement** - GDPR-compliant DPA
4. **Employee Compliance Policy** - Internal ethics and compliance
5. **SOX Compliance Checklist** - Sarbanes-Oxley requirements

## API Dependencies

| Service | Endpoint | Purpose |
|---------|----------|---------|
| Orchestrator | `POST /api/v1/query` | Search and answer |
| Ingestion | `POST /api/v1/ingest` | Document ingestion |
| Ingestion | `GET /api/v1/documents` | List documents |
| MinIO | S3 API | File storage |
