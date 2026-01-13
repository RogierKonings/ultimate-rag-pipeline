# Svelte Demo Frontend Design

> **Date:** 2026-01-13
> **Status:** Ready for implementation
> **Purpose:** Sales/marketing demo for Legal/Compliance domain

## Overview

A polished Svelte frontend demo application showcasing the RAG pipeline capabilities. Users can search across pre-loaded legal/compliance documents and upload their own, receiving AI-powered answers with cited sources.

**Name:** ComplianceAI Demo

**Tagline:** "Ask questions, get answers with sources"

**Core value proposition:** Demonstrate how the RAG pipeline instantly finds relevant information across legal documents and provides accurate, cited answers.

**Target demo audience:**
- Legal ops teams evaluating RAG solutions
- Compliance officers looking to modernize document search
- Technical decision-makers assessing the platform

---

## UI Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  Header: Logo | "ComplianceAI Demo" | Upload Button             │
├───────────────────────┬─────────────────────────────────────────┤
│                       │                                         │
│   Document Sidebar    │         Main Content Area               │
│   (240px)             │                                         │
│                       │   ┌─────────────────────────────────┐   │
│   ┌───────────────┐   │   │  Search Bar                     │   │
│   │ Your Documents│   │   └─────────────────────────────────┘   │
│   │ - uploaded.pdf│   │                                         │
│   │               │   │   ┌─────────────────────────────────┐   │
│   │ Sample Docs   │   │   │  Answer Card                    │   │
│   │ - GDPR.pdf    │   │   │  - AI Response with citations   │   │
│   │ - NDA.pdf     │   │   │  - Expandable source refs [1]   │   │
│   │ - Policy.pdf  │   │   └─────────────────────────────────┘   │
│   └───────────────┘   │                                         │
│                       │   ┌─────────────────────────────────┐   │
│   Processing Queue    │   │  Retrieved Sources Panel        │   │
│   - doc.pdf (75%)     │   │  - Source cards with snippets   │   │
│                       │   │  - Relevance scores             │   │
│                       │   │  - Click to expand              │   │
│                       │   └─────────────────────────────────┘   │
│                       │                                         │
└───────────────────────┴─────────────────────────────────────────┘
```

### Components

| Component | Purpose |
|-----------|---------|
| **Document Sidebar** | Shows uploaded + sample docs, processing status |
| **Search Bar** | Prominent input with placeholder examples |
| **Answer Card** | AI response with inline citation markers [1], [2] |
| **Sources Panel** | Retrieved chunks with scores, expandable details |
| **Upload Modal** | Drag-drop zone, file type validation, progress bar |
| **Document Viewer** | Modal/drawer to view full document context |

---

## Tech Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| **Framework** | SvelteKit | SSR-capable, fast, great DX |
| **Styling** | Tailwind CSS | Rapid styling, consistent design system |
| **Components** | shadcn-svelte | Polished, accessible UI primitives |
| **Icons** | Lucide | Clean, consistent icon set |
| **HTTP Client** | Native fetch | Simple, no dependencies needed |
| **State** | Svelte stores | Built-in reactivity, no extra library |

---

## Project Structure

```
frontend/
├── src/
│   ├── lib/
│   │   ├── components/
│   │   │   ├── ui/              # shadcn base components
│   │   │   ├── DocumentSidebar.svelte
│   │   │   ├── SearchBar.svelte
│   │   │   ├── AnswerCard.svelte
│   │   │   ├── SourcesPanel.svelte
│   │   │   ├── SourceCard.svelte
│   │   │   ├── UploadModal.svelte
│   │   │   ├── DocumentViewer.svelte
│   │   │   └── ProcessingIndicator.svelte
│   │   ├── api/
│   │   │   ├── client.ts        # API client wrapper
│   │   │   ├── orchestrator.ts  # Query endpoints
│   │   │   ├── ingestion.ts     # Upload/document endpoints
│   │   │   └── types.ts         # TypeScript interfaces
│   │   └── stores/
│   │       ├── documents.ts     # Document list state
│   │       ├── search.ts        # Search/answer state
│   │       └── upload.ts        # Upload progress state
│   ├── routes/
│   │   ├── +layout.svelte       # App shell with header
│   │   ├── +page.svelte         # Main demo page
│   │   └── api/                  # Optional: proxy endpoints
│   └── app.css                  # Tailwind imports + theme
├── static/
│   └── samples/                 # Pre-loaded sample docs
├── svelte.config.js
├── tailwind.config.js
├── package.json
└── Dockerfile
```

---

## User Flows

### Flow 1: Initial Load

1. Page loads -> Fetch document list from ingestion service
2. Display sample docs (pre-loaded) + any user-uploaded docs
3. Show empty state in main area with example questions

```typescript
GET /api/v1/documents?tenant_id={demo-tenant}
// Returns: { documents: [{ id, title, source_type, status, created_at }] }
```

### Flow 2: Search & Answer

1. User types question -> "What are the GDPR requirements for data deletion?"
2. Show loading state with skeleton
3. Call orchestrator query endpoint
4. Display answer with inline citations [1], [2]
5. Show retrieved sources below with relevance scores
6. User clicks citation -> Scrolls to/highlights source card

```typescript
POST /api/v1/query
{
  "query": "What are the GDPR requirements for data deletion?",
  "tenant_id": "demo-tenant",
  "options": { "include_citations": true }
}
// Returns: {
//   response: "Under GDPR Article 17, individuals have the right to erasure...[1]",
//   sources: [{ id, title, uri, score, snippet }],
//   latency_ms: 245
// }
```

### Flow 3: Document Upload

1. User clicks "Upload" -> Modal opens with drag-drop zone
2. User drops PDF/DOCX -> Validate file type, show preview
3. Click "Process" -> Upload to ingestion service
4. Modal closes -> Document appears in sidebar with progress indicator
5. Poll for status until processing complete
6. Document ready -> User can now query it

```typescript
// Step 1: Upload file
POST /api/v1/ingest
{
  "tenant_id": "demo-tenant",
  "source_type": "FILE",
  "source_uri": "uploaded://{filename}",
  "title": "User uploaded: contract.pdf",
  "file": <binary>  // multipart form
}
// Returns: { document_id, job_id, status: "queued" }

// Step 2: Poll status
GET /api/v1/documents/{document_id}
// Returns: { status: "processing" | "completed" | "failed" }
```

### Flow 4: View Source Context

1. User clicks source card -> Document viewer opens
2. Show full document with highlighted relevant section
3. User can scroll through, close to return

---

## Visual Design

### Color Palette (Light Theme)

| Element | Color | Usage |
|---------|-------|-------|
| Background | `#FAFAFA` | Page background |
| Surface | `#FFFFFF` | Cards, panels |
| Border | `#E5E7EB` | Subtle dividers |
| Text primary | `#111827` | Headings, body |
| Text secondary | `#6B7280` | Labels, metadata |
| Accent | `#2563EB` | Links, buttons, citations |
| Success | `#10B981` | Completed status |
| Warning | `#F59E0B` | Processing status |

### Typography

| Element | Style |
|---------|-------|
| Headings | Inter, 600 weight |
| Body | Inter, 400 weight |
| Code/scores | JetBrains Mono |

### Polish Elements

1. **Search bar** - Subtle shadow, animated focus ring, placeholder cycles through example questions
2. **Answer card** - Citation markers are clickable pills with hover states
3. **Source cards** - Relevance score as colored bar (green = high), smooth expand/collapse animation
4. **Upload** - Drag state with dashed border animation, progress bar with percentage
5. **Loading states** - Skeleton loaders that match content shape, subtle pulse animation
6. **Latency display** - Small badge showing "Answered in 245ms" to demonstrate speed
7. **Empty states** - Friendly illustrations with suggested example queries
8. **Transitions** - Smooth fade/slide for panels, no jarring jumps

### Responsive Behavior

| Breakpoint | Layout |
|------------|--------|
| Desktop (>1024px) | Sidebar + main (as designed) |
| Tablet (768-1024px) | Collapsible sidebar |
| Mobile (<768px) | Bottom sheet for sources, full-width search |

---

## Sample Documents

| File | Content | Purpose |
|------|---------|---------|
| `gdpr-article-17.pdf` | Right to erasure excerpt | Data deletion queries |
| `sample-nda.pdf` | Mutual NDA template | Confidentiality questions |
| `data-processing-agreement.pdf` | DPA template | Processor obligations |
| `employee-compliance-policy.pdf` | Internal policy doc | Policy lookup queries |
| `sox-compliance-checklist.pdf` | SOX controls summary | Audit/control queries |

### Example Queries

- "What are the requirements for data deletion under GDPR?"
- "How long is the confidentiality period in the NDA?"
- "What are the data processor's obligations?"
- "Who should employees contact to report compliance concerns?"
- "What controls are required for SOX compliance?"

---

## Configuration

### Environment Variables

```env
PUBLIC_ORCHESTRATOR_URL=http://localhost:8003
PUBLIC_INGESTION_URL=http://localhost:8001
PUBLIC_DEMO_TENANT_ID=demo-tenant-uuid
```

### Docker Integration

Add to existing `docker-compose.yml`:

```yaml
frontend:
  build: ./frontend
  ports:
    - "3000:3000"
  environment:
    - PUBLIC_ORCHESTRATOR_URL=http://orchestrator:8003
    - PUBLIC_INGESTION_URL=http://ingestion:8001
  depends_on:
    - orchestrator
    - ingestion
```

---

## Out of Scope (v1)

- User authentication (demo uses fixed tenant)
- Document deletion from UI
- Conversation history/sessions
- Mobile-optimized experience
- Analytics/usage tracking

---

## API Dependencies

The frontend depends on these existing endpoints:

| Service | Endpoint | Purpose |
|---------|----------|---------|
| Orchestrator | `POST /api/v1/query` | Search and answer |
| Ingestion | `POST /api/v1/ingest` | Document upload |
| Ingestion | `GET /api/v1/documents` | List documents |
| Ingestion | `GET /api/v1/documents/{id}` | Document status |
