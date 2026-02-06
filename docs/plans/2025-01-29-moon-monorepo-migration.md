# Moon Monorepo Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.
>
> **Last Updated:** 2025-01-30 - Updated to reflect Rust rewrites (ingestion, embedding services now in Rust)

**Goal:** Migrate the ultimate-rag-pipeline repository to use Moon as a polyglot monorepo build system, enabling unified dev experience, proper dependency tracking across Rust/Python/TypeScript, and smart caching.

**Architecture:** Moon workspace at repo root with three project types: Rust crates (inherits from cargo workspace), Python orchestrator service (uv-based), and frontend (node/pnpm). Task dependencies flow: types → services → frontend. Shared schemas in `schemas/` generate types for all languages.

**Tech Stack:** Moon 1.x, Rust/Cargo workspace, Python/uv, Node/pnpm, JSON Schema for shared types

**Current Service Layout (as of 2025-01-30):**

- **Rust crates (17 total):** rag-types, rag-config, rag-cache, rag-auth, rag-telemetry, rag-search, rag-database, rag-storage, rag-vectorstore, rag-retrieval, rag-ingestion, rag-video, rag-embedding, rag-encryption, rag-tenant, rag-secrets, rag-llm-gateway
- **Python services (1):** orchestrator (with nested `shared/` module)
- **Frontend:** SvelteKit application

---

## Phase 1: Moon Foundation

### Task 1: Install Moon and Initialize Workspace

**Files:**

- Create: `.moon/workspace.yml`
- Create: `.moon/toolchain.yml`
- Create: `.prototools`

**Step 1: Install proto (Moon's toolchain manager)**

Run:

```bash
curl -fsSL https://moonrepo.dev/install/proto.sh | bash
```

Expected: proto installed to `~/.proto/bin`

**Step 2: Add proto to shell and verify**

Run:

```bash
export PATH="$HOME/.proto/bin:$PATH"
proto --version
```

Expected: Version output like `proto 0.x.x`

**Step 3: Install Moon via proto**

Run:

```bash
proto install moon
moon --version
```

Expected: Version output like `moon 1.x.x`

**Step 4: Create `.prototools` for pinned tool versions**

```toml
# Pinned tool versions for the workspace
moon = "1.31"
node = "22.11.0"
pnpm = "9.15.0"
python = "3.11.11"
```

**Step 5: Create `.moon/workspace.yml`**

```yaml
# Moon workspace configuration
# https://moonrepo.dev/docs/config/workspace

$schema: "https://moonrepo.dev/schemas/workspace.json"

# Projects are auto-discovered via globs
projects:
  # Rust crates - core libraries
  rag-types: "crates/rag-types"
  rag-config: "crates/rag-config"
  rag-cache: "crates/rag-cache"
  rag-auth: "crates/rag-auth"
  rag-telemetry: "crates/rag-telemetry"
  rag-search: "crates/rag-search"
  rag-database: "crates/rag-database"
  rag-storage: "crates/rag-storage"
  rag-vectorstore: "crates/rag-vectorstore"

  # Rust crates - services
  rag-retrieval: "crates/rag-retrieval"
  rag-ingestion: "crates/rag-ingestion"
  rag-video: "crates/rag-video"
  rag-embedding: "crates/rag-embedding"
  rag-llm-gateway: "crates/rag-llm-gateway"

  # Rust crates - security/tenant
  rag-encryption: "crates/rag-encryption"
  rag-tenant: "crates/rag-tenant"
  rag-secrets: "crates/rag-secrets"

  # Python services (orchestrator only - ingestion/embedding are now Rust)
  orchestrator-service: "services/orchestrator"

  # Frontend
  frontend: "frontend"

  # Shared schemas (for type generation)
  schemas: "schemas"

# Version control settings
vcs:
  manager: "git"
  defaultBranch: "main"

# Caching configuration
hasher:
  optimization: "performance"

# Telemetry (optional, can disable)
telemetry: false

# Extensions for additional functionality
extensions:
  rust: "https://moonrepo.dev/extensions/rust"
```

**Step 6: Create `.moon/toolchain.yml`**

```yaml
# Moon toolchain configuration
# https://moonrepo.dev/docs/config/toolchain

$schema: "https://moonrepo.dev/schemas/toolchain.json"

# Node.js for frontend
node:
  version: "22.11.0"
  packageManager: "pnpm"
  pnpm:
    version: "9.15.0"

# Python for services (using system python, managed by uv)
# Moon doesn't have native Python support yet, we use system tasks

# Rust configuration
rust:
  version: "1.75.0"
  syncToolchainConfig: true
  components:
    - "clippy"
    - "rustfmt"
```

**Step 7: Run moon setup to verify configuration**

Run:

```bash
moon setup
```

Expected: Moon downloads/verifies toolchain versions, no errors

**Step 8: Commit initial Moon configuration**

Run:

```bash
git add .moon/ .prototools
git commit -m "chore: initialize Moon monorepo workspace

- Add .moon/workspace.yml with all projects
- Add .moon/toolchain.yml for Node and Rust
- Add .prototools for pinned versions

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

### Task 2: Configure Rust Projects

**Files:**

- Create: `crates/rag-types/moon.yml`
- Create: `crates/rag-config/moon.yml`
- Create: `crates/rag-cache/moon.yml`
- Create: `crates/rag-auth/moon.yml`
- Create: `crates/rag-telemetry/moon.yml`
- Create: `crates/rag-search/moon.yml`
- Create: `crates/rag-database/moon.yml`
- Create: `crates/rag-storage/moon.yml`
- Create: `crates/rag-vectorstore/moon.yml`
- Create: `crates/rag-retrieval/moon.yml`
- Create: `crates/rag-ingestion/moon.yml`
- Create: `crates/rag-video/moon.yml`
- Create: `crates/rag-embedding/moon.yml`
- Create: `crates/rag-llm-gateway/moon.yml`
- Create: `crates/rag-encryption/moon.yml`
- Create: `crates/rag-tenant/moon.yml`
- Create: `crates/rag-secrets/moon.yml`

**Step 1: Create base Rust project template**

Create `crates/rag-types/moon.yml`:

```yaml
# Moon project configuration for rag-types
# https://moonrepo.dev/docs/config/project

$schema: "https://moonrepo.dev/schemas/project.json"

language: "rust"
type: "library"

# Project metadata
project:
  name: "rag-types"
  description: "Core type definitions for RAG pipeline"

# File groups for dependency tracking
fileGroups:
  sources:
    - "src/**/*"
    - "Cargo.toml"
  tests:
    - "tests/**/*"

# Tasks
tasks:
  build:
    command: "cargo build -p rag-types"
    inputs:
      - "@group(sources)"
    outputs:
      - "../target/debug/librag_types.rlib"

  check:
    command: "cargo check -p rag-types"
    inputs:
      - "@group(sources)"

  test:
    command: "cargo test -p rag-types"
    inputs:
      - "@group(sources)"
      - "@group(tests)"
    deps:
      - "~:build"

  lint:
    command: "cargo clippy -p rag-types -- -D warnings"
    inputs:
      - "@group(sources)"

  format:
    command: "cargo fmt -p rag-types"
    inputs:
      - "@group(sources)"
    local: true

  format-check:
    command: "cargo fmt -p rag-types -- --check"
    inputs:
      - "@group(sources)"
```

**Step 2: Create moon.yml for each Rust crate**

Create the following files with similar structure, adjusting `name`, `description`, and `deps` as needed:

`crates/rag-config/moon.yml`:

```yaml
$schema: "https://moonrepo.dev/schemas/project.json"
language: "rust"
type: "library"

project:
  name: "rag-config"
  description: "Configuration management for RAG pipeline"

fileGroups:
  sources:
    - "src/**/*"
    - "Cargo.toml"
  tests:
    - "tests/**/*"

tasks:
  build:
    command: "cargo build -p rag-config"
    inputs:
      - "@group(sources)"
    deps:
      - "rag-types:build"

  check:
    command: "cargo check -p rag-config"
    inputs:
      - "@group(sources)"

  test:
    command: "cargo test -p rag-config"
    inputs:
      - "@group(sources)"
      - "@group(tests)"
    deps:
      - "~:build"

  lint:
    command: "cargo clippy -p rag-config -- -D warnings"
    inputs:
      - "@group(sources)"

  format:
    command: "cargo fmt -p rag-config"
    local: true

  format-check:
    command: "cargo fmt -p rag-config -- --check"
```

`crates/rag-cache/moon.yml`:

```yaml
$schema: "https://moonrepo.dev/schemas/project.json"
language: "rust"
type: "library"

project:
  name: "rag-cache"
  description: "Caching layer for RAG pipeline"

fileGroups:
  sources:
    - "src/**/*"
    - "Cargo.toml"
  tests:
    - "tests/**/*"

tasks:
  build:
    command: "cargo build -p rag-cache"
    inputs:
      - "@group(sources)"
    deps:
      - "rag-types:build"
      - "rag-config:build"

  check:
    command: "cargo check -p rag-cache"
    inputs:
      - "@group(sources)"

  test:
    command: "cargo test -p rag-cache"
    inputs:
      - "@group(sources)"
      - "@group(tests)"
    deps:
      - "~:build"

  lint:
    command: "cargo clippy -p rag-cache -- -D warnings"
    inputs:
      - "@group(sources)"

  format:
    command: "cargo fmt -p rag-cache"
    local: true

  format-check:
    command: "cargo fmt -p rag-cache -- --check"
```

`crates/rag-auth/moon.yml`:

```yaml
$schema: "https://moonrepo.dev/schemas/project.json"
language: "rust"
type: "library"

project:
  name: "rag-auth"
  description: "Authentication and authorization for RAG pipeline"

fileGroups:
  sources:
    - "src/**/*"
    - "Cargo.toml"
  tests:
    - "tests/**/*"

tasks:
  build:
    command: "cargo build -p rag-auth"
    inputs:
      - "@group(sources)"
    deps:
      - "rag-types:build"
      - "rag-config:build"

  check:
    command: "cargo check -p rag-auth"
    inputs:
      - "@group(sources)"

  test:
    command: "cargo test -p rag-auth"
    inputs:
      - "@group(sources)"
      - "@group(tests)"
    deps:
      - "~:build"

  lint:
    command: "cargo clippy -p rag-auth -- -D warnings"
    inputs:
      - "@group(sources)"

  format:
    command: "cargo fmt -p rag-auth"
    local: true

  format-check:
    command: "cargo fmt -p rag-auth -- --check"
```

`crates/rag-telemetry/moon.yml`:

```yaml
$schema: "https://moonrepo.dev/schemas/project.json"
language: "rust"
type: "library"

project:
  name: "rag-telemetry"
  description: "Observability and telemetry for RAG pipeline"

fileGroups:
  sources:
    - "src/**/*"
    - "Cargo.toml"
  tests:
    - "tests/**/*"

tasks:
  build:
    command: "cargo build -p rag-telemetry"
    inputs:
      - "@group(sources)"
    deps:
      - "rag-types:build"
      - "rag-config:build"

  check:
    command: "cargo check -p rag-telemetry"
    inputs:
      - "@group(sources)"

  test:
    command: "cargo test -p rag-telemetry"
    inputs:
      - "@group(sources)"
      - "@group(tests)"
    deps:
      - "~:build"

  lint:
    command: "cargo clippy -p rag-telemetry -- -D warnings"
    inputs:
      - "@group(sources)"

  format:
    command: "cargo fmt -p rag-telemetry"
    local: true

  format-check:
    command: "cargo fmt -p rag-telemetry -- --check"
```

`crates/rag-search/moon.yml`:

```yaml
$schema: "https://moonrepo.dev/schemas/project.json"
language: "rust"
type: "library"

project:
  name: "rag-search"
  description: "OpenSearch integration for RAG pipeline"

fileGroups:
  sources:
    - "src/**/*"
    - "Cargo.toml"
  tests:
    - "tests/**/*"

tasks:
  build:
    command: "cargo build -p rag-search"
    inputs:
      - "@group(sources)"
    deps:
      - "rag-types:build"
      - "rag-config:build"
      - "rag-telemetry:build"

  check:
    command: "cargo check -p rag-search"
    inputs:
      - "@group(sources)"

  test:
    command: "cargo test -p rag-search"
    inputs:
      - "@group(sources)"
      - "@group(tests)"
    deps:
      - "~:build"

  lint:
    command: "cargo clippy -p rag-search -- -D warnings"
    inputs:
      - "@group(sources)"

  format:
    command: "cargo fmt -p rag-search"
    local: true

  format-check:
    command: "cargo fmt -p rag-search -- --check"
```

`crates/rag-database/moon.yml`:

```yaml
$schema: "https://moonrepo.dev/schemas/project.json"
language: "rust"
type: "library"

project:
  name: "rag-database"
  description: "PostgreSQL database layer for RAG pipeline"

fileGroups:
  sources:
    - "src/**/*"
    - "Cargo.toml"
  tests:
    - "tests/**/*"

tasks:
  build:
    command: "cargo build -p rag-database"
    inputs:
      - "@group(sources)"
    deps:
      - "rag-types:build"
      - "rag-config:build"
      - "rag-telemetry:build"

  check:
    command: "cargo check -p rag-database"
    inputs:
      - "@group(sources)"

  test:
    command: "cargo test -p rag-database"
    inputs:
      - "@group(sources)"
      - "@group(tests)"
    deps:
      - "~:build"

  lint:
    command: "cargo clippy -p rag-database -- -D warnings"
    inputs:
      - "@group(sources)"

  format:
    command: "cargo fmt -p rag-database"
    local: true

  format-check:
    command: "cargo fmt -p rag-database -- --check"
```

`crates/rag-storage/moon.yml`:

```yaml
$schema: "https://moonrepo.dev/schemas/project.json"
language: "rust"
type: "library"

project:
  name: "rag-storage"
  description: "MinIO/S3 storage layer for RAG pipeline"

fileGroups:
  sources:
    - "src/**/*"
    - "Cargo.toml"
  tests:
    - "tests/**/*"

tasks:
  build:
    command: "cargo build -p rag-storage"
    inputs:
      - "@group(sources)"
    deps:
      - "rag-types:build"
      - "rag-config:build"
      - "rag-telemetry:build"

  check:
    command: "cargo check -p rag-storage"
    inputs:
      - "@group(sources)"

  test:
    command: "cargo test -p rag-storage"
    inputs:
      - "@group(sources)"
      - "@group(tests)"
    deps:
      - "~:build"

  lint:
    command: "cargo clippy -p rag-storage -- -D warnings"
    inputs:
      - "@group(sources)"

  format:
    command: "cargo fmt -p rag-storage"
    local: true

  format-check:
    command: "cargo fmt -p rag-storage -- --check"
```

`crates/rag-vectorstore/moon.yml`:

```yaml
$schema: "https://moonrepo.dev/schemas/project.json"
language: "rust"
type: "library"

project:
  name: "rag-vectorstore"
  description: "Qdrant vector store integration for RAG pipeline"

fileGroups:
  sources:
    - "src/**/*"
    - "Cargo.toml"
  tests:
    - "tests/**/*"

tasks:
  build:
    command: "cargo build -p rag-vectorstore"
    inputs:
      - "@group(sources)"
    deps:
      - "rag-types:build"
      - "rag-config:build"
      - "rag-telemetry:build"

  check:
    command: "cargo check -p rag-vectorstore"
    inputs:
      - "@group(sources)"

  test:
    command: "cargo test -p rag-vectorstore"
    inputs:
      - "@group(sources)"
      - "@group(tests)"
    deps:
      - "~:build"

  lint:
    command: "cargo clippy -p rag-vectorstore -- -D warnings"
    inputs:
      - "@group(sources)"

  format:
    command: "cargo fmt -p rag-vectorstore"
    local: true

  format-check:
    command: "cargo fmt -p rag-vectorstore -- --check"
```

`crates/rag-retrieval/moon.yml`:

```yaml
$schema: "https://moonrepo.dev/schemas/project.json"
language: "rust"
type: "library"

project:
  name: "rag-retrieval"
  description: "Hybrid retrieval service for RAG pipeline"

fileGroups:
  sources:
    - "src/**/*"
    - "Cargo.toml"
  tests:
    - "tests/**/*"

tasks:
  build:
    command: "cargo build -p rag-retrieval"
    inputs:
      - "@group(sources)"
    deps:
      - "rag-types:build"
      - "rag-config:build"
      - "rag-telemetry:build"
      - "rag-vectorstore:build"
      - "rag-search:build"
      - "rag-cache:build"
      - "rag-auth:build"

  check:
    command: "cargo check -p rag-retrieval"
    inputs:
      - "@group(sources)"

  test:
    command: "cargo test -p rag-retrieval"
    inputs:
      - "@group(sources)"
      - "@group(tests)"
    deps:
      - "~:build"

  lint:
    command: "cargo clippy -p rag-retrieval -- -D warnings"
    inputs:
      - "@group(sources)"

  format:
    command: "cargo fmt -p rag-retrieval"
    local: true

  format-check:
    command: "cargo fmt -p rag-retrieval -- --check"
```

`crates/rag-ingestion/moon.yml`:

```yaml
$schema: "https://moonrepo.dev/schemas/project.json"
language: "rust"
type: "library"

project:
  name: "rag-ingestion-rust"
  description: "Document ingestion service (Rust implementation)"

fileGroups:
  sources:
    - "src/**/*"
    - "Cargo.toml"
  tests:
    - "tests/**/*"

tasks:
  build:
    command: "cargo build -p rag-ingestion"
    inputs:
      - "@group(sources)"
    deps:
      - "rag-types:build"
      - "rag-config:build"
      - "rag-telemetry:build"
      - "rag-vectorstore:build"
      - "rag-search:build"
      - "rag-storage:build"
      - "rag-database:build"

  check:
    command: "cargo check -p rag-ingestion"
    inputs:
      - "@group(sources)"

  test:
    command: "cargo test -p rag-ingestion"
    inputs:
      - "@group(sources)"
      - "@group(tests)"
    deps:
      - "~:build"

  lint:
    command: "cargo clippy -p rag-ingestion -- -D warnings"
    inputs:
      - "@group(sources)"

  format:
    command: "cargo fmt -p rag-ingestion"
    local: true

  format-check:
    command: "cargo fmt -p rag-ingestion -- --check"
```

`crates/rag-video/moon.yml`:

```yaml
$schema: "https://moonrepo.dev/schemas/project.json"
language: "rust"
type: "library"

project:
  name: "rag-video"
  description: "Video processing pipeline for RAG"

fileGroups:
  sources:
    - "src/**/*"
    - "Cargo.toml"
  tests:
    - "tests/**/*"

tasks:
  build:
    command: "cargo build -p rag-video"
    inputs:
      - "@group(sources)"
    deps:
      - "rag-types:build"
      - "rag-config:build"
      - "rag-telemetry:build"
      - "rag-vectorstore:build"
      - "rag-search:build"
      - "rag-storage:build"

  check:
    command: "cargo check -p rag-video"
    inputs:
      - "@group(sources)"

  test:
    command: "cargo test -p rag-video"
    inputs:
      - "@group(sources)"
      - "@group(tests)"
    deps:
      - "~:build"

  lint:
    command: "cargo clippy -p rag-video -- -D warnings"
    inputs:
      - "@group(sources)"

  format:
    command: "cargo fmt -p rag-video"
    local: true

  format-check:
    command: "cargo fmt -p rag-video -- --check"
```

`crates/rag-embedding/moon.yml`:

```yaml
$schema: "https://moonrepo.dev/schemas/project.json"
language: "rust"
type: "application"

project:
  name: "rag-embedding"
  description: "Embedding service with ONNX-based inference (Rust)"

fileGroups:
  sources:
    - "src/**/*"
    - "Cargo.toml"
  tests:
    - "tests/**/*"

tasks:
  build:
    command: "cargo build -p rag-embedding"
    inputs:
      - "@group(sources)"
    deps:
      - "rag-types:build"
      - "rag-config:build"
      - "rag-telemetry:build"

  check:
    command: "cargo check -p rag-embedding"
    inputs:
      - "@group(sources)"

  test:
    command: "cargo test -p rag-embedding"
    inputs:
      - "@group(sources)"
      - "@group(tests)"
    deps:
      - "~:build"

  lint:
    command: "cargo clippy -p rag-embedding -- -D warnings"
    inputs:
      - "@group(sources)"

  format:
    command: "cargo fmt -p rag-embedding"
    local: true

  format-check:
    command: "cargo fmt -p rag-embedding -- --check"
```

`crates/rag-llm-gateway/moon.yml`:

```yaml
$schema: "https://moonrepo.dev/schemas/project.json"
language: "rust"
type: "application"

project:
  name: "rag-llm-gateway"
  description: "Unified LLM Gateway with OpenAI-compatible API (Rust)"

fileGroups:
  sources:
    - "src/**/*"
    - "Cargo.toml"
  tests:
    - "tests/**/*"

tasks:
  build:
    command: "cargo build -p rag-llm-gateway"
    inputs:
      - "@group(sources)"
    deps:
      - "rag-types:build"
      - "rag-config:build"
      - "rag-telemetry:build"
      - "rag-auth:build"

  check:
    command: "cargo check -p rag-llm-gateway"
    inputs:
      - "@group(sources)"

  test:
    command: "cargo test -p rag-llm-gateway"
    inputs:
      - "@group(sources)"
      - "@group(tests)"
    deps:
      - "~:build"

  lint:
    command: "cargo clippy -p rag-llm-gateway -- -D warnings"
    inputs:
      - "@group(sources)"

  format:
    command: "cargo fmt -p rag-llm-gateway"
    local: true

  format-check:
    command: "cargo fmt -p rag-llm-gateway -- --check"
```

`crates/rag-encryption/moon.yml`:

```yaml
$schema: "https://moonrepo.dev/schemas/project.json"
language: "rust"
type: "library"

project:
  name: "rag-encryption"
  description: "Encryption utilities for RAG pipeline"

fileGroups:
  sources:
    - "src/**/*"
    - "Cargo.toml"
  tests:
    - "tests/**/*"

tasks:
  build:
    command: "cargo build -p rag-encryption"
    inputs:
      - "@group(sources)"
    deps:
      - "rag-types:build"
      - "rag-config:build"

  check:
    command: "cargo check -p rag-encryption"
    inputs:
      - "@group(sources)"

  test:
    command: "cargo test -p rag-encryption"
    inputs:
      - "@group(sources)"
      - "@group(tests)"
    deps:
      - "~:build"

  lint:
    command: "cargo clippy -p rag-encryption -- -D warnings"
    inputs:
      - "@group(sources)"

  format:
    command: "cargo fmt -p rag-encryption"
    local: true

  format-check:
    command: "cargo fmt -p rag-encryption -- --check"
```

`crates/rag-tenant/moon.yml`:

```yaml
$schema: "https://moonrepo.dev/schemas/project.json"
language: "rust"
type: "library"

project:
  name: "rag-tenant"
  description: "Multi-tenant management for RAG pipeline"

fileGroups:
  sources:
    - "src/**/*"
    - "Cargo.toml"
  tests:
    - "tests/**/*"

tasks:
  build:
    command: "cargo build -p rag-tenant"
    inputs:
      - "@group(sources)"
    deps:
      - "rag-types:build"
      - "rag-config:build"
      - "rag-database:build"

  check:
    command: "cargo check -p rag-tenant"
    inputs:
      - "@group(sources)"

  test:
    command: "cargo test -p rag-tenant"
    inputs:
      - "@group(sources)"
      - "@group(tests)"
    deps:
      - "~:build"

  lint:
    command: "cargo clippy -p rag-tenant -- -D warnings"
    inputs:
      - "@group(sources)"

  format:
    command: "cargo fmt -p rag-tenant"
    local: true

  format-check:
    command: "cargo fmt -p rag-tenant -- --check"
```

`crates/rag-secrets/moon.yml`:

```yaml
$schema: "https://moonrepo.dev/schemas/project.json"
language: "rust"
type: "library"

project:
  name: "rag-secrets"
  description: "Secrets management for RAG pipeline"

fileGroups:
  sources:
    - "src/**/*"
    - "Cargo.toml"
  tests:
    - "tests/**/*"

tasks:
  build:
    command: "cargo build -p rag-secrets"
    inputs:
      - "@group(sources)"
    deps:
      - "rag-types:build"
      - "rag-config:build"
      - "rag-encryption:build"

  check:
    command: "cargo check -p rag-secrets"
    inputs:
      - "@group(sources)"

  test:
    command: "cargo test -p rag-secrets"
    inputs:
      - "@group(sources)"
      - "@group(tests)"
    deps:
      - "~:build"

  lint:
    command: "cargo clippy -p rag-secrets -- -D warnings"
    inputs:
      - "@group(sources)"

  format:
    command: "cargo fmt -p rag-secrets"
    local: true

  format-check:
    command: "cargo fmt -p rag-secrets -- --check"
```

**Step 3: Verify Rust projects are recognized**

Run:

```bash
moon project-graph
```

Expected: Graph showing all rag-\* projects with their dependencies

**Step 4: Test running a Rust task**

Run:

```bash
moon run rag-types:check
```

Expected: Cargo check runs successfully for rag-types

**Step 5: Commit Rust project configurations**

Run:

```bash
git add crates/*/moon.yml
git commit -m "chore: add Moon project configs for all Rust crates

- Configure build, check, test, lint, format tasks
- Set up inter-crate dependencies
- Enable file group tracking for smart caching

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

### Task 3: Configure Python Orchestrator Service

> **Note:** The Python ingestion and embedding services have been rewritten in Rust.
> Only the orchestrator service remains as Python. The `shared/` module is now nested
> inside `services/orchestrator/shared/` rather than being a standalone service.

**Files:**

- Create: `services/orchestrator/moon.yml`

**Step 1: Create orchestrator service Moon config**

Create `services/orchestrator/moon.yml`:

```yaml
$schema: "https://moonrepo.dev/schemas/project.json"
language: "python"
type: "application"

project:
  name: "orchestrator-service"
  description: "RAG orchestration microservice with LangGraph"

fileGroups:
  sources:
    - "**/*.py"
    - "requirements.txt"
    - "!tests/**/*"
  tests:
    - "tests/**/*.py"
    - "pytest.ini"
  configs:
    - "Dockerfile"
    - "config.py"
  shared:
    - "shared/**/*.py"

tasks:
  install:
    command: "uv pip install -r requirements.txt"
    inputs:
      - "requirements.txt"

  dev:
    command: "uvicorn run:app --reload --host 0.0.0.0 --port 8003"
    local: true
    deps:
      - "~:install"

  test:
    command: "pytest tests/ -v"
    inputs:
      - "@group(sources)"
      - "@group(tests)"
    deps:
      - "~:install"

  lint:
    command: "ruff check ."
    inputs:
      - "@group(sources)"

  format:
    command: "ruff format ."
    local: true

  format-check:
    command: "ruff format --check ."

  typecheck:
    command: "mypy . --ignore-missing-imports"
    inputs:
      - "@group(sources)"
    deps:
      - "~:install"
```

**Step 2: Verify Python project**

Run:

```bash
moon project-graph
```

Expected: Graph shows orchestrator-service project

**Step 3: Test running a Python task**

Run:

```bash
moon run orchestrator-service:lint
```

Expected: Ruff runs on orchestrator service

**Step 4: Commit Python project configuration**

Run:

```bash
git add services/orchestrator/moon.yml
git commit -m "chore: add Moon project config for Python orchestrator service

- Configure install, dev, test, lint, format, typecheck tasks
- Include shared/ module in file groups
- Enable file group tracking for smart caching

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

### Task 4: Configure Frontend Project

**Files:**

- Create: `frontend/moon.yml`

**Step 1: Create frontend Moon config**

Create `frontend/moon.yml`:

```yaml
$schema: "https://moonrepo.dev/schemas/project.json"
language: "typescript"
type: "application"

project:
  name: "frontend"
  description: "SvelteKit frontend application"

fileGroups:
  sources:
    - "src/**/*"
    - "static/**/*"
    - "package.json"
    - "svelte.config.js"
    - "vite.config.ts"
    - "tsconfig.json"
  tests:
    - "tests/**/*"
  configs:
    - "tailwind.config.js"
    - "postcss.config.js"

tasks:
  install:
    command: "pnpm install"
    inputs:
      - "package.json"
      - "pnpm-lock.yaml"

  dev:
    command: "pnpm run dev"
    local: true
    deps:
      - "~:install"

  build:
    command: "pnpm run build"
    inputs:
      - "@group(sources)"
    outputs:
      - ".svelte-kit"
      - "build"
    deps:
      - "~:install"

  preview:
    command: "pnpm run preview"
    local: true
    deps:
      - "~:build"

  check:
    command: "pnpm run check"
    inputs:
      - "@group(sources)"
    deps:
      - "~:install"

  lint:
    command: "pnpm eslint src/"
    inputs:
      - "@group(sources)"
    deps:
      - "~:install"

  format:
    command: "pnpm prettier --write src/"
    local: true
    deps:
      - "~:install"

  format-check:
    command: "pnpm prettier --check src/"
    deps:
      - "~:install"
```

**Step 2: Verify frontend project**

Run:

```bash
moon project frontend
```

Expected: Shows frontend project details and available tasks

**Step 3: Commit frontend configuration**

Run:

```bash
git add frontend/moon.yml
git commit -m "chore: add Moon project config for SvelteKit frontend

- Configure install, dev, build, preview, check, lint, format tasks
- Set up file groups for smart caching
- Enable TypeScript checking

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Phase 2: Workspace Tasks and Developer Experience

### Task 5: Create Global Tasks

**Files:**

- Create: `.moon/tasks.yml`

**Step 1: Create workspace-level tasks**

Create `.moon/tasks.yml`:

```yaml
# Global tasks available across the workspace
# https://moonrepo.dev/docs/config/tasks

$schema: "https://moonrepo.dev/schemas/tasks.json"

tasks:
  # Development
  dev:
    command: 'echo "Use moon run <project>:dev to start a specific service"'
    local: true

  # Testing
  test-all:
    command: "moon run :test"

  # Linting
  lint-all:
    command: "moon run :lint"

  # Formatting
  format-all:
    command: "moon run :format"
    local: true

  format-check-all:
    command: "moon run :format-check"

  # Type checking
  check-all:
    command: "moon run :check"

  # CI pipeline
  ci:
    command: "moon ci"

  # Build everything
  build-all:
    command: "moon run :build"
```

**Step 2: Verify global tasks**

Run:

```bash
moon task --list
```

Expected: Shows global tasks like `test-all`, `lint-all`, etc.

**Step 3: Commit global tasks**

Run:

```bash
git add .moon/tasks.yml
git commit -m "chore: add global Moon tasks for workspace operations

- Add test-all, lint-all, format-all, check-all tasks
- Add ci task for CI pipeline
- Add build-all for complete builds

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

### Task 6: Update Makefile to Use Moon

**Files:**

- Modify: `Makefile`

**Step 1: Update Makefile with Moon commands**

Add the following section to `Makefile` after the help section:

```makefile
# =============================================================================
# Moon Monorepo Commands
# =============================================================================

.PHONY: moon-setup moon-check moon-test moon-lint moon-format moon-build moon-ci

moon-setup:
	@echo "Setting up Moon workspace..."
	moon setup

moon-check:
	@echo "Running type checks across all projects..."
	moon run :check

moon-test:
	@echo "Running tests across all projects..."
	moon run :test

moon-lint:
	@echo "Running linters across all projects..."
	moon run :lint

moon-format:
	@echo "Formatting all projects..."
	moon run :format

moon-format-check:
	@echo "Checking formatting across all projects..."
	moon run :format-check

moon-build:
	@echo "Building all projects..."
	moon run :build

moon-ci:
	@echo "Running CI pipeline..."
	moon ci

# Project-specific dev servers
dev-frontend:
	moon run frontend:dev

dev-orchestrator:
	moon run orchestrator-service:dev

# Run affected tasks only (useful for PRs)
affected-test:
	moon run :test --affected

affected-lint:
	moon run :lint --affected
```

**Step 2: Update the help target to include Moon commands**

Add to the help section in Makefile:

```makefile
	@echo ""
	@echo "Moon Monorepo:"
	@echo "  make moon-setup      - Initialize Moon workspace"
	@echo "  make moon-check      - Run type checks (all projects)"
	@echo "  make moon-test       - Run tests (all projects)"
	@echo "  make moon-lint       - Run linters (all projects)"
	@echo "  make moon-format     - Format code (all projects)"
	@echo "  make moon-build      - Build all projects"
	@echo "  make moon-ci         - Run full CI pipeline"
	@echo ""
	@echo "Dev Servers (via Moon):"
	@echo "  make dev-frontend    - Start frontend dev server"
	@echo "  make dev-orchestrator - Start orchestrator service"
```

**Step 3: Test the new Makefile commands**

Run:

```bash
make moon-lint
```

Expected: Moon runs lint task across all projects

**Step 4: Commit Makefile updates**

Run:

```bash
git add Makefile
git commit -m "chore: add Moon commands to Makefile

- Add moon-setup, moon-check, moon-test, moon-lint, moon-format
- Add moon-build, moon-ci for full pipeline
- Add dev-* targets for individual service dev servers
- Add affected-* targets for PR-scoped runs

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

### Task 7: Configure CI Integration

**Files:**

- Create: `.github/workflows/moon-ci.yml`

**Step 1: Create Moon CI workflow**

Create `.github/workflows/moon-ci.yml`:

```yaml
name: Moon CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

env:
  MOON_TOOLCHAIN_FORCE_GLOBALS: true

jobs:
  ci:
    name: CI Pipeline
    runs-on: ubuntu-latest

    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0 # Needed for affected detection

      - name: Setup proto
        uses: moonrepo/setup-toolchain@v0
        with:
          auto-install: true

      - name: Setup Rust
        uses: actions-rust-lang/setup-rust-toolchain@v1
        with:
          toolchain: stable
          components: clippy, rustfmt

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install uv
        uses: astral-sh/setup-uv@v4

      - name: Cache Moon
        uses: moonrepo/cache@v0

      - name: Run CI
        run: moon ci

  # Separate job for affected-only runs on PRs
  affected:
    name: Affected Check
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request'

    steps:
      - name: Checkout
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Setup proto
        uses: moonrepo/setup-toolchain@v0
        with:
          auto-install: true

      - name: Setup Rust
        uses: actions-rust-lang/setup-rust-toolchain@v1
        with:
          toolchain: stable
          components: clippy, rustfmt

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install uv
        uses: astral-sh/setup-uv@v4

      - name: Show affected projects
        run: moon query projects --affected

      - name: Run affected tests
        run: moon run :test --affected

      - name: Run affected lints
        run: moon run :lint --affected
```

**Step 2: Commit CI workflow**

Run:

```bash
git add .github/workflows/moon-ci.yml
git commit -m "ci: add Moon CI workflow

- Full CI pipeline on main branch pushes
- Affected-only checks on PRs for faster feedback
- Moon caching for faster builds
- Setup for Rust, Python, and Node toolchains

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Phase 3: Shared Schema Generation (Type Sync)

### Task 8: Set Up Shared Schema Directory

**Files:**

- Create: `schemas/README.md`
- Create: `schemas/moon.yml`
- Create: `schemas/document.schema.json`

**Step 1: Create schemas directory and README**

Create `schemas/README.md`:

```markdown
# Shared Schemas

This directory contains JSON Schema definitions that are the single source of truth for types shared across the Rust, Python, and TypeScript codebases.

## How It Works

1. Define types as JSON Schema in this directory
2. Run `moon run schemas:generate` to generate types for all languages
3. Generated types are placed in:
   - Rust: `crates/rag-types/src/generated/`
   - Python: `services/orchestrator/shared/generated/`
   - TypeScript: `frontend/src/lib/generated/`

## Adding a New Schema

1. Create a new `.schema.json` file in this directory
2. Run the generate task
3. Import the generated types in your code

## Schema Conventions

- Use `$id` to name the schema (e.g., `"document"`)
- Use `title` for the type name (e.g., `"SourceDocument"`)
- Prefer explicit types over `anyOf`/`oneOf` where possible
```

**Step 2: Create schemas Moon config**

Create `schemas/moon.yml`:

```yaml
$schema: "https://moonrepo.dev/schemas/project.json"
language: "other"
type: "library"

project:
  name: "schemas"
  description: "Shared JSON Schema definitions"

fileGroups:
  schemas:
    - "**/*.schema.json"
  scripts:
    - "scripts/**/*"

tasks:
  validate:
    command: 'npx ajv validate -s "*.schema.json"'
    inputs:
      - "@group(schemas)"

  generate-rust:
    command: "npx quicktype --src-lang schema --lang rust --out ../crates/rag-types/src/generated/mod.rs *.schema.json"
    inputs:
      - "@group(schemas)"
    outputs:
      - "../crates/rag-types/src/generated/mod.rs"

  generate-python:
    command: "npx quicktype --src-lang schema --lang python --out ../services/orchestrator/shared/generated/types.py *.schema.json"
    inputs:
      - "@group(schemas)"
    outputs:
      - "../services/orchestrator/shared/generated/types.py"

  generate-typescript:
    command: "npx quicktype --src-lang schema --lang typescript --out ../frontend/src/lib/generated/types.ts *.schema.json"
    inputs:
      - "@group(schemas)"
    outputs:
      - "../frontend/src/lib/generated/types.ts"

  generate:
    command: 'echo "Generating types for all languages..."'
    deps:
      - "~:generate-rust"
      - "~:generate-python"
      - "~:generate-typescript"
```

**Step 3: Create example schema**

Create `schemas/document.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "document",
  "title": "SourceDocument",
  "description": "A source document in the RAG pipeline",
  "type": "object",
  "properties": {
    "id": {
      "type": "string",
      "format": "uuid",
      "description": "Unique identifier for the document"
    },
    "tenant_id": {
      "type": "string",
      "format": "uuid",
      "description": "Tenant that owns this document"
    },
    "title": {
      "type": "string",
      "description": "Document title"
    },
    "source_uri": {
      "type": "string",
      "format": "uri",
      "description": "Original source location"
    },
    "source_type": {
      "type": "string",
      "enum": ["file", "web", "api", "database"],
      "description": "Type of source"
    },
    "content_hash": {
      "type": "string",
      "description": "SHA-256 hash of content for deduplication"
    },
    "visibility": {
      "type": "string",
      "enum": ["private", "group", "public"],
      "default": "private"
    },
    "allowed_groups": {
      "type": "array",
      "items": { "type": "string" },
      "default": []
    },
    "metadata": {
      "type": "object",
      "additionalProperties": true
    },
    "created_at": {
      "type": "string",
      "format": "date-time"
    },
    "updated_at": {
      "type": "string",
      "format": "date-time"
    }
  },
  "required": ["id", "tenant_id", "source_type", "content_hash"]
}
```

**Step 4: Install quicktype for schema generation**

Run:

```bash
cd schemas && pnpm init && pnpm install --save-dev quicktype ajv-cli
```

**Step 5: Create generated directories**

Run:

```bash
mkdir -p crates/rag-types/src/generated
mkdir -p services/orchestrator/shared/generated
mkdir -p frontend/src/lib/generated
touch crates/rag-types/src/generated/.gitkeep
touch services/orchestrator/shared/generated/.gitkeep
touch frontend/src/lib/generated/.gitkeep
```

**Step 6: Commit schema setup**

Run:

```bash
git add schemas/ crates/rag-types/src/generated/.gitkeep services/orchestrator/shared/generated/.gitkeep frontend/src/lib/generated/.gitkeep
git commit -m "chore: add shared schema infrastructure

- Add schemas directory with JSON Schema definitions
- Add Moon tasks for multi-language type generation
- Add quicktype for Rust, Python, TypeScript generation
- Add example document.schema.json

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

### Task 9: Update .gitignore and Documentation

**Files:**

- Modify: `.gitignore`
- Modify: `CLAUDE.md`

**Step 1: Update .gitignore for Moon**

Add to `.gitignore`:

```gitignore
# Moon
.moon/cache/
.moon/docker/

# Generated types (regenerate with moon run schemas:generate)
crates/rag-types/src/generated/*.rs
!crates/rag-types/src/generated/.gitkeep
services/orchestrator/shared/generated/*.py
!services/orchestrator/shared/generated/.gitkeep
frontend/src/lib/generated/*.ts
!frontend/src/lib/generated/.gitkeep
```

**Step 2: Update CLAUDE.md with Moon commands**

Add a new section to CLAUDE.md after "Essential Commands":

````markdown
### Moon Monorepo Commands

```bash
# Run all tests
moon run :test

# Run tests for specific project
moon run rag-types:test
moon run orchestrator-service:test

# Run all linters
moon run :lint

# Run affected tasks only (for PRs)
moon run :test --affected

# View project dependency graph
moon project-graph

# Run CI pipeline locally
moon ci

# Generate types from shared schemas
moon run schemas:generate
```
````

````

**Step 3: Commit documentation updates**

Run:
```bash
git add .gitignore CLAUDE.md
git commit -m "docs: update gitignore and CLAUDE.md for Moon

- Ignore Moon cache directories
- Ignore generated type files (with .gitkeep)
- Document Moon commands in CLAUDE.md

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
````

---

## Phase 4: Verification

### Task 10: End-to-End Verification

**Step 1: Clean and reinitialize**

Run:

```bash
rm -rf .moon/cache
moon setup
```

Expected: Moon reinitializes cleanly

**Step 2: Run full project graph**

Run:

```bash
moon project-graph --dot > project-graph.dot
```

Expected: Generates DOT file showing all project dependencies

**Step 3: Run lint on all projects**

Run:

```bash
moon run :lint
```

Expected: Linting runs on all Rust, Python, and TypeScript projects

**Step 4: Run tests on all projects**

Run:

```bash
moon run :test
```

Expected: Tests run on all projects with proper dependency ordering

**Step 5: Generate types from schemas**

Run:

```bash
moon run schemas:generate
```

Expected: Types generated in all three language directories

**Step 6: Verify caching works**

Run:

```bash
moon run :lint
```

Expected: Second run shows "cached" for unchanged projects

**Step 7: Final commit**

Run:

```bash
git add -A
git commit -m "feat: complete Moon monorepo migration

- All Rust crates configured with dependency tracking
- All Python services configured with uv integration
- Frontend configured with pnpm
- Shared schema generation working
- CI pipeline configured
- Makefile updated with Moon commands

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Summary

After completing this plan, you will have:

1. **Unified dev experience**: `moon run :test`, `moon run :lint`, individual `moon run <project>:dev`
2. **Shared types**: JSON Schema → Rust/Python/TypeScript via `moon run schemas:generate`
3. **Smart caching**: Moon tracks file changes and skips unchanged tasks
4. **CI integration**: GitHub Actions with affected-only runs for PRs
5. **Dependency graph**: `moon project-graph` shows all project relationships

The existing Makefile and docker-compose setup remain functional alongside Moon, allowing gradual adoption.

## Change Log

### 2025-01-30: Updated for Rust Rewrites

- **Removed Python services**: `services/ingestion` and `services/embedding` no longer exist (rewritten in Rust)
- **Added new Rust crates**: `rag-embedding`, `rag-llm-gateway`, `rag-encryption`, `rag-tenant`, `rag-secrets`
- **Updated shared module path**: Now at `services/orchestrator/shared/` instead of `services/shared/`
- **Updated project count**: 17 Rust crates, 1 Python service (orchestrator), 1 frontend
- **Removed defunct Makefile targets**: `dev-ingestion`, `dev-embedding`
