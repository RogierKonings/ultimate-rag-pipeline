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
