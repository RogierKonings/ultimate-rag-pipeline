# Coding Conventions

**Analysis Date:** 2026-01-30

## Naming Patterns

**Files:**
- Rust: `snake_case` for modules, files, and functions (e.g., `hybrid_search.rs`, `input_validation_node.py`)
- Python: `snake_case` for files and functions (e.g., `input_validation.py`, `query_request.py`)
- Test files: `test_<module>.py` or `<module>_test.py` pattern
- Module files: Use descriptive plural/singular names matching content (e.g., `models/requests.py`, `models/responses.py`)

**Functions:**
- Rust: `snake_case` for all functions
  - Example: `build_rag_workflow()`, `format_context()`, `create_initial_state()`
  - Async functions: prefix `async` keyword, no naming suffix
  - Test functions: `#[test] fn test_<behavior>()` format
- Python: `snake_case` for all functions and methods
  - Example: `async def query()`, `def _transform_documents()`, `async def input_validation_node()`
  - Private functions: prefix with `_` (e.g., `_transform_documents`)
  - Test methods: `def test_<behavior>()` within test classes

**Variables:**
- Rust: `snake_case` for all bindings (e.g., `semantic_results`, `fusion_config`, `fused_score`)
- Python: `snake_case` for all variables and parameters
  - Type hints: Always include (e.g., `documents: list[dict[str, Any]]`)
  - Async contexts: Use descriptive names (e.g., `session_manager`, `model_gateway`)

**Types:**
- Rust: `PascalCase` for struct, enum, and trait names
  - Example: `FusionConfig`, `HybridSearchResponse`, `CircuitBreaker`
  - Error types: `Error` enum with variants in SCREAMING_SNAKE_CASE variants
  - Generics: Single letter capitals (e.g., `T`, `E`) or descriptive (e.g., `ScoredItem<T>`)
- Python: `PascalCase` for class names
  - Example: `QueryRequest`, `SourceDocument`, `GuardrailResult`
  - Enums: `PascalCase` for class, `SCREAMING_SNAKE_CASE` for values
  - Type aliases: `snake_case` at module level (e.g., `DbSessionDep = Annotated[AsyncSession, ...]`)

**Constants:**
- Rust: `SCREAMING_SNAKE_CASE` for compile-time constants
  - Example: `MAX_CHUNK_SIZE`, `DEFAULT_TIMEOUT_MS`
- Python: `SCREAMING_SNAKE_CASE` for module-level constants
  - Example: `MAX_INPUT_LENGTH = 4000`, `DEFAULT_BATCH_SIZE = 32`

## Code Style

**Formatting:**
- Rust: `cargo fmt` enforced via rustfmt.toml
  - Max width: 100 characters
  - Edition: 2021
  - Import reordering: enabled
  - Tab spaces: 4
- Python: Ruff formatter (configured in pyproject.toml)
  - Line length: 100 characters
  - Target: Python 3.11+

**Linting:**
- Rust: `cargo clippy` with workspace-level lint configuration
  - All clippy::all warnings enforced
  - clippy::pedantic warnings enforced
  - clippy::nursery warnings enforced
  - `unsafe_code` completely forbidden (see crates/Cargo.toml)
- Python: Ruff with 90+ rules enabled
  - Coverage requirement: 70% minimum (tool.coverage.run)
  - Linting rules: E, W, F, I, B, C4, UP, ARG, SIM, S, A, COM, DTZ, T10, EXE, ISC, ICN, PIE, PT, Q, RSE, RET, TCH, PTH
  - Per-file ignores for tests and scripts (see pyproject.toml)

## Import Organization

**Order:**
1. `__future__` imports (Rust: none; Python only)
2. Standard library imports
3. Third-party imports (organized by category)
4. First-party imports (`services`, `shared`)
5. Local relative imports (dot imports)

**Path Aliases:**
- Python: `known_first_party = ["services", "shared"]` in Ruff config
- Rust: Module tree organization in `lib.rs`
  - Use `pub mod <name>` for public modules
  - Use `mod <name>` for internal modules
  - Reexport key types in lib root: `pub use crate::fusion::{fuse, FusionConfig}`

**Import Style:**
- Rust: Use `use` statements at module/function scope
  - Group imports logically with blank lines
  - Example:
    ```rust
    use std::sync::Arc;
    use uuid::Uuid;

    use rag_types::{Error, Result};
    use rag_config::Config;
    ```
- Python: Use explicit imports, avoid wildcard `*` imports
  - Example:
    ```python
    from typing import Annotated, Any
    from uuid import UUID

    from pydantic import BaseModel, Field
    from sqlalchemy.ext.asyncio import AsyncSession
    ```

## Error Handling

**Patterns:**
- Rust:
  - Use `Result<T>` type alias with unified error enum (`rag_types::Error`)
  - Error variants use `#[error]` from thiserror crate with descriptive messages
  - Use `?` operator for error propagation
  - Example:
    ```rust
    pub type Result<T> = std::result::Result<T, Error>;

    #[derive(Error, Debug)]
    pub enum Error {
        #[error("Validation error: {message}")]
        Validation { message: String, field: Option<String> },
        #[error("Database error: {message}")]
        Database { message: String, #[source] source: Option<Box<dyn std::error::Error>> },
    }
    ```
- Python:
  - Use Pydantic exceptions for validation errors
  - Raise HTTPException in FastAPI routes (FastAPI automatic handling)
  - Use custom exception classes for domain errors
  - Example:
    ```python
    from fastapi import HTTPException, status

    if not query.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Query is empty or invalid"
        )
    ```

## Logging

**Framework:**
- Rust: `tracing` crate with `tracing_subscriber` for spans and events
  - Use `#[instrument]` macro on async functions for automatic span creation
  - Log levels: `trace!`, `debug!`, `info!`, `warn!`, `error!`
- Python: `structlog` for structured logging
  - Initialize logger: `logger = structlog.get_logger(__name__)`
  - Structured JSON output in production

**Patterns:**
- Rust:
  ```rust
  use tracing::{info, instrument};

  #[instrument(skip(state))]
  async fn process_query(state: &RAGState) -> Result<()> {
      info!("Processing query", query_length = state.query.len());
      // ...
  }
  ```
- Python:
  ```python
  import structlog

  logger = structlog.get_logger(__name__)

  async def query(request: Request, query_request: QueryRequest) -> QueryResponse:
      logger.info("query_received", query=query_request.query[:50])
      # ...
  ```

## Comments

**When to Comment:**
- Function documentation: Always include docstring with Args, Returns, Raises
- Complex algorithm logic: Explain the "why" not the "what"
- Workarounds: Document rationale for non-obvious implementation
- TODO/FIXME: Format as `# TODO: description` with optional ticket reference
- Module-level: Include summary of module purpose

**JSDoc/TSDoc:**
- Rust: Use `///` doc comments for public items
  - Include `# Examples` section for public functions
  - Example:
    ```rust
    /// Combines semantic and keyword search results using RRF.
    ///
    /// # Arguments
    /// * `semantic_results` - Results from semantic (vector) search
    /// * `keyword_results` - Results from keyword (BM25) search
    ///
    /// # Example
    /// ```
    /// let fused = fuse(&semantic, &keyword, &config)?;
    /// ```
    pub fn fuse(semantic: &[ScoredItem], keyword: &[ScoredItem], config: &FusionConfig) -> Result<Vec<FusedResult>> {
    ```
- Python: Use triple-quoted docstrings for functions and classes
  - Format: Google-style or NumPy-style (Google preferred)
  - Example:
    ```python
    async def query(
        request: Request,
        query_request: QueryRequest,
    ) -> QueryResponse:
        """Process a synchronous RAG query.

        This endpoint validates input, retrieves documents, and generates a response.

        Args:
            request: HTTP request object
            query_request: User's query with optional filters

        Returns:
            QueryResponse with generated answer and citations

        Raises:
            HTTPException: If guardrails reject input or service unavailable
        """
    ```

## Function Design

**Size:**
- Rust: Prefer single responsibility; typical range 10-50 lines
  - Break down complex logic into helper functions
  - Use private helper functions (`fn`) for internal logic
- Python: Similar range; aim for readability
  - Single async function per endpoint
  - Extract validation, transformation logic into helpers

**Parameters:**
- Rust:
  - Pass simple types by value (u32, bool, enums)
  - Pass complex types by `&` reference or `Arc<T>` for shared ownership
  - Use owned types (`String`, `Vec<T>`) when taking ownership
  - Example:
    ```rust
    fn fuse(semantic: &[ScoredItem], keyword: &[ScoredItem], config: &FusionConfig) -> Result<Vec<FusedResult>>
    ```
- Python:
  - Use type hints for all parameters
  - Dependency injection via FastAPI `Depends()`
  - Annotated types for clarity (e.g., `SessionManagerDep = Annotated[SessionManager, Depends(...)]`)
  - Example:
    ```python
    async def query(
        query_request: QueryRequest,
        session_manager: SessionManagerDep,
        model_gateway: ModelGatewayDep,
    ) -> QueryResponse:
    ```

**Return Values:**
- Rust:
  - Return `Result<T>` for fallible operations (error types must be unified)
  - Return owned values or `Arc<T>` for complex types
  - Example: `pub async fn retrieve(...) -> Result<HybridSearchResponse>`
- Python:
  - Always include return type hint
  - Async functions: `async def func(...) -> ReturnType`
  - Return Pydantic models for API responses
  - Example: `async def query(...) -> QueryResponse:`

## Module Design

**Exports:**
- Rust: Explicitly re-export key types and functions from module root
  - Use `pub use crate::<path>::<item>` in `lib.rs`
  - Hide implementation details behind module boundaries
  - Example (crates/rag-retrieval/src/lib.rs):
    ```rust
    pub use fusion::{fuse, FusionConfig, FusionMethod};
    pub use hybrid::{HybridSearcher, HybridSearchConfig};
    pub use query::QueryProcessor;
    ```
- Python: Define `__all__` in `__init__.py` to control public API
  - Example:
    ```python
    # api/__init__.py
    from api.routes.query import router as query_router
    from api.routes.sessions import router as sessions_router

    __all__ = ["query_router", "sessions_router"]
    ```

**Barrel Files:**
- Rust: `mod.rs` serves as barrel file
  - Group related modules logically
  - Re-export necessary types
- Python: `__init__.py` serves as barrel file
  - Import and re-export main classes/functions
  - Keep minimal initialization logic

**Internal Organization:**
- Rust:
  - `src/lib.rs`: Module tree and public exports
  - `src/bin/main.rs`: Application entry point
  - `src/api/`: HTTP routes and request/response types
  - `src/config.rs`: Configuration management
  - `src/error.rs`: Error type definitions
- Python:
  - `api/`: FastAPI app and routes
  - `api/models/`: Pydantic request/response schemas
  - `workflow/`: LangGraph nodes and graph definition
  - `services/`: Business logic modules
  - `config.py`: Configuration management
  - `tests/`: Test suite organized by module

---

*Convention analysis: 2026-01-30*
