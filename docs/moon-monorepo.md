# Moon Monorepo Guide

This document describes the Moon monorepo setup for the Ultimate RAG Pipeline project.

## Overview

Moon is a polyglot build system that provides:
- **Unified dev experience** across Rust, Python, and TypeScript
- **Smart caching** - skips unchanged tasks
- **Dependency tracking** - rebuilds only what's needed
- **Affected detection** - run tasks only for changed projects in PRs

## Quick Start

```bash
# Install proto (Moon's toolchain manager)
curl -fsSL https://moonrepo.dev/install/proto.sh | bash

# Install Moon
proto install moon

# Setup workspace (downloads toolchains)
moon setup

# Run all tests
moon run :test

# Run all linters
moon run :lint
```

## Project Structure

Moon manages 20 projects in this workspace:

### Rust Crates (17)

| Project | Path | Description |
|---------|------|-------------|
| rag-types | crates/rag-types | Core type definitions |
| rag-config | crates/rag-config | Configuration management |
| rag-cache | crates/rag-cache | Caching layer |
| rag-auth | crates/rag-auth | Authentication/authorization |
| rag-telemetry | crates/rag-telemetry | Observability |
| rag-search | crates/rag-search | OpenSearch integration |
| rag-database | crates/rag-database | PostgreSQL layer |
| rag-storage | crates/rag-storage | MinIO/S3 storage |
| rag-vectorstore | crates/rag-vectorstore | Qdrant integration |
| rag-retrieval | crates/rag-retrieval | Hybrid retrieval service |
| rag-ingestion | crates/rag-ingestion | Document ingestion |
| rag-video | crates/rag-video | Video processing |
| rag-embedding | crates/rag-embedding | Embedding service |
| rag-llm-gateway | crates/rag-llm-gateway | LLM Gateway |
| rag-encryption | crates/rag-encryption | Encryption utilities |
| rag-tenant | crates/rag-tenant | Multi-tenant management |
| rag-secrets | crates/rag-secrets | Secrets management |

### Python Services (1)

| Project | Path | Description |
|---------|------|-------------|
| orchestrator-service | services/orchestrator | RAG orchestration with LangGraph |

### Frontend (1)

| Project | Path | Description |
|---------|------|-------------|
| frontend | frontend | SvelteKit application |

### Utilities (1)

| Project | Path | Description |
|---------|------|-------------|
| schemas | schemas | Shared JSON Schema definitions |

## Common Commands

### Workspace-Wide Tasks

```bash
# Run all tests
moon run :test

# Run all linters
moon run :lint

# Run all type checks
moon run :check

# Build everything
moon run :build

# Format all code
moon run :format

# Check formatting (CI)
moon run :format-check

# Run CI pipeline
moon ci
```

### Project-Specific Tasks

```bash
# Rust crate
moon run rag-types:check
moon run rag-types:test
moon run rag-types:lint
moon run rag-types:build

# Python service
moon run orchestrator-service:test
moon run orchestrator-service:lint
moon run orchestrator-service:typecheck

# Frontend
moon run frontend:dev
moon run frontend:build
moon run frontend:check
```

### Affected Tasks (for PRs)

```bash
# Run tests only for changed projects
moon run :test --affected

# Run lints only for changed projects
moon run :lint --affected

# Show which projects are affected
moon query projects --affected
```

### Dev Servers

```bash
# Start frontend dev server
moon run frontend:dev

# Start orchestrator service
moon run orchestrator-service:dev
```

## Makefile Integration

For convenience, Moon commands are also available via Make:

```bash
make moon-setup        # Initialize workspace
make moon-test         # Run all tests
make moon-lint         # Run all linters
make moon-check        # Run type checks
make moon-format       # Format all code
make moon-build        # Build everything
make moon-ci           # Run CI pipeline

make dev-frontend      # Start frontend dev server
make dev-orchestrator  # Start orchestrator service

make affected-test     # Test affected projects only
make affected-lint     # Lint affected projects only
```

## Configuration Files

### Workspace Configuration

**.moon/workspace.yml** - Defines all projects and workspace settings:
- Project paths
- VCS settings
- Caching configuration
- Extensions

**.moon/toolchain.yml** - Defines toolchain versions:
- Node.js 22.11.0
- pnpm 9.15.0
- Rust 1.93.0

**.moon/tasks.yml** - Global tasks inherited by all projects

**.prototools** - Pinned tool versions for proto

### Project Configuration

Each project has a `moon.yml` file defining:
- Language and type
- File groups for input tracking
- Tasks (build, test, lint, format, etc.)
- Dependencies on other projects

Example (`crates/rag-types/moon.yml`):
```yaml
$schema: 'https://moonrepo.dev/schemas/project.json'
language: 'rust'
type: 'library'

project:
  name: 'rag-types'
  description: 'Core type definitions for RAG pipeline'

fileGroups:
  sources:
    - 'src/**/*'
    - 'Cargo.toml'
  tests:
    - 'tests/**/*'

tasks:
  build:
    command: 'cargo build -p rag-types'
    inputs:
      - '@group(sources)'

  check:
    command: 'cargo check -p rag-types'
    inputs:
      - '@group(sources)'

  test:
    command: 'cargo test -p rag-types'
    inputs:
      - '@group(sources)'
      - '@group(tests)'
    deps:
      - '~:build'

  lint:
    command: 'cargo clippy -p rag-types -- -D warnings'
    inputs:
      - '@group(sources)'

  format:
    command: 'cargo fmt -p rag-types'
    local: true

  format-check:
    command: 'cargo fmt -p rag-types -- --check'
```

## Shared Schema Generation

The `schemas/` directory contains JSON Schema definitions that generate types for all languages.

### Adding a New Schema

1. Create a `.schema.json` file in `schemas/`:
```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "my-type",
  "title": "MyType",
  "type": "object",
  "properties": {
    "id": { "type": "string" }
  }
}
```

2. Generate types:
```bash
moon run schemas:generate
```

3. Generated files appear in:
   - `crates/rag-types/src/generated/` (Rust)
   - `services/orchestrator/shared/generated/` (Python)
   - `frontend/src/lib/generated/` (TypeScript)

## Caching

Moon caches task outputs based on file inputs. When you run a task twice without changing files, the second run uses the cache:

```
$ moon run rag-types:check
▪▪▪▪ rag-types:check (cached, 1ec53c21)

Tasks: 1 completed (1 cached)
Time: 393ms
```

### Cache Location

- Local cache: `.moon/cache/` (gitignored)
- Remote cache: Can be configured for CI sharing

### Invalidating Cache

```bash
# Clear all caches
rm -rf .moon/cache

# Re-run setup
moon setup
```

## CI Integration

The `.github/workflows/moon-ci.yml` workflow provides:

1. **Full CI on main branch** - runs `moon ci` for complete validation
2. **Affected checks on PRs** - runs only changed project tasks for faster feedback

### CI Pipeline

```yaml
# Full CI
moon ci

# Affected only (PRs)
moon run :test --affected
moon run :lint --affected
```

## Dependency Graph

View the project dependency graph:

```bash
# Interactive graph (opens browser)
moon project-graph

# List all projects
moon query projects

# Show project details
moon project rag-retrieval
```

Example output:
```
Project: rag-retrieval
Depends on: rag-types, rag-config, rag-telemetry, rag-vectorstore,
            rag-search, rag-cache, rag-auth
```

## Troubleshooting

### Moon Not Found

```bash
# Add proto to PATH
export PATH="$HOME/.proto/bin:$PATH"

# Or add to shell profile
echo 'export PATH="$HOME/.proto/bin:$PATH"' >> ~/.zshrc
```

### Rust Version Issues

If you see errors about Rust version requirements:
1. Check `.moon/toolchain.yml` for the configured version
2. Run `moon setup` to install the correct version

### Task Failures

```bash
# Run with verbose output
moon run rag-types:check --log debug

# Check task configuration
moon project rag-types
```

### Cache Issues

```bash
# Clear cache and retry
rm -rf .moon/cache
moon setup
moon run :check
```

## Further Reading

- [Moon Documentation](https://moonrepo.dev/docs)
- [Moon Configuration](https://moonrepo.dev/docs/config/workspace)
- [Proto Documentation](https://moonrepo.dev/docs/proto)
