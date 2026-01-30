# Testing Patterns

**Analysis Date:** 2026-01-30

## Test Framework

**Runner:**
- Python: pytest 7.0+ (config: `pyproject.toml` and `services/orchestrator/pytest.ini`)
  - Async support: `pytest-asyncio` with `asyncio_mode = "auto"`
  - Test discovery: `test_*.py` and `*_test.py` files
  - Test classes: `Test*` prefix; test functions: `test_*` prefix
- Rust: Built-in test framework (`#[test]`)
  - Integration tests in `tests/` directory (e.g., `crates/rag-retrieval/tests/`)
  - Unit tests inline with code using `#[cfg(test)]` modules
  - Async tests use `#[tokio::test]` macro

**Assertion Library:**
- Python: pytest built-in assertions with clear failure messages
- Rust: Built-in `assert!` and `assert_eq!` macros

**Run Commands:**
```bash
# Python - All tests
cd /Users/rogierkonings/Projects/ultimate-rag-pipeline
pytest tests/ -v                    # Run all tests with verbose output
pytest tests/ -m "not slow"         # Skip slow tests
pytest tests/security/ -v           # Run specific test module
pytest services/orchestrator/tests/ -v  # Run orchestrator tests

# Python - Watch mode / Coverage
pytest tests/ --cov=services --cov-report=html  # Generate coverage report
pytest tests/ -s                    # Show print output during tests

# Rust - All tests
cd /Users/rogierkonings/Projects/ultimate-rag-pipeline/crates
cargo test                          # Run all tests
cargo test -p rag-retrieval         # Run specific package
cargo test --test integration       # Run only integration tests
cargo test -- --test-threads 1      # Run single-threaded (for state-dependent tests)

# Rust - Specific test
cargo test test_rrf_fusion_combines_results  # Run test by name
```

## Test File Organization

**Location:**
- Python: `tests/` directory at root or `tests/` within service directory
  - Mirrors source structure: `tests/security/`, `tests/integration/`, `tests/e2e/`
  - Orchestrator tests: `services/orchestrator/tests/`
  - Shared tests: `tests/` for cross-service functionality
- Rust: `tests/` directory within crate (e.g., `crates/rag-retrieval/tests/`)
  - Parallel mirror of `src/` structure when possible
  - Integration tests as separate files (not in `src/`)

**Naming:**
- Python: `test_<module>.py` (e.g., `test_pii_detection.py`)
  - Test class: `TestClassName` (e.g., `TestPIISettings`)
  - Test method: `test_<behavior_being_tested>` (e.g., `test_default_settings()`)
- Rust: `#[test] fn test_<behavior>()` (e.g., `#[test] fn test_rrf_fusion_combines_results()`)
  - Integration test files: `tests/integration/hybrid_search.rs`

**Structure:**
```
tests/
├── security/
│   ├── test_pii_detection.py
│   ├── test_jwt_authentication.py
│   └── conftest.py
├── integration/
│   ├── test_rag_pipeline.py
│   └── test_audit_end_to_end.py
├── e2e/
│   └── test_rag_pipeline.py
├── conftest.py  # Shared fixtures
└── __init__.py

crates/rag-retrieval/tests/
├── integration/
│   ├── hybrid_search.rs
│   ├── mocks.rs
│   └── mod.rs
└── property_tests.rs
```

## Test Structure

**Suite Organization:**
```python
# Python pattern - from tests/security/test_pii_detection.py
"""Tests for PII detection module.

This module tests PII detection, handling modes,
and response filtering capabilities.
"""

from uuid import uuid4
import pytest

from services.shared.security.pii import (
    PIIChunkResult,
    PIIDetector,
    PIIDocumentResult,
    PIIEntityType,
    PIIHandlingMode,
    PIIQueryFilter,
    PIIResponseFilter,
    PIIResult,
    PIISettings,
)


class TestPIISettings:
    """Tests for PII settings configuration."""

    def test_default_settings(self):
        """Test default settings values."""
        settings = PIISettings()
        assert settings.enabled is True
        assert settings.default_handling_mode == PIIHandlingMode.FLAG
        assert settings.confidence_threshold == 0.7
        assert "en" in settings.languages

    @pytest.mark.asyncio
    async def test_async_operation(self, mock_detector):
        """Test async detector behavior."""
        result = await mock_detector.detect(text="Contact: john@example.com")
        assert result.found_pii is True
```

**Patterns:**
- Rust: Test function with descriptive name and documentation comment
  ```rust
  /// Test that RRF fusion correctly combines results from both search methods.
  #[test]
  fn test_rrf_fusion_combines_results() {
      let (semantic_results, keyword_results) = generate_overlapping_results(10, 10, 5);

      let semantic_scored = to_scored_items(&semantic_results);
      let keyword_scored = to_scored_items(&keyword_results);

      let config = FusionConfig::new(FusionMethod::Rrf)
          .with_weights(0.7, 0.3)
          .with_rrf_k(60.0);

      let fused = fuse(&semantic_scored, &keyword_scored, &config).unwrap();

      // Assertions
      assert_eq!(fused.len(), 15);
      for i in 1..fused.len() {
          assert!(
              fused[i - 1].fused_score >= fused[i].fused_score,
              "Results should be sorted by fused score in descending order"
          );
      }
  }
  ```

- Python: Test class grouping related tests with fixtures
  ```python
  class TestInputGuardrail:
      """Tests for the InputGuardrail class."""

      @pytest.fixture
      def guardrail(self):
          """Create an InputGuardrail with default config."""
          return InputGuardrail()

      @pytest.mark.asyncio
      async def test_valid_input_passes(self, guardrail):
          """Test that valid input passes all checks."""
          text = "What is the weather like today?"
          result = await guardrail.check(text)

          assert result.passed is True
          assert len(result.violations) == 0
          assert result.processing_time_ms > 0
  ```

## Mocking

**Framework:**
- Python: `unittest.mock` (AsyncMock, MagicMock) for test isolation
- Rust: Custom mock implementations or integration tests without mocking

**Patterns:**
- Python mocking from `services/orchestrator/tests/conftest.py`:
  ```python
  @pytest.fixture
  def mock_redis():
      """Create a mock Redis client."""
      redis = AsyncMock()
      redis.get = AsyncMock(return_value=None)
      redis.set = AsyncMock(return_value=True)
      redis.delete = AsyncMock(return_value=1)
      redis.expire = AsyncMock(return_value=True)
      redis.ping = AsyncMock(return_value=True)
      redis.close = AsyncMock()
      return redis

  @pytest.fixture
  def mock_llm_response():
      """Create a mock LLM response."""
      return {
          "id": "chatcmpl-test",
          "object": "chat.completion",
          "created": int(datetime.now(tz=UTC).timestamp()),
          "model": "meta-llama/Llama-3.1-8B-Instruct",
          "choices": [
              {
                  "index": 0,
                  "message": {"role": "assistant", "content": "This is a test response."},
                  "finish_reason": "stop",
              },
          ],
          "usage": {"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
      }

  @pytest.fixture
  def mock_httpx_client(mock_llm_response):
      """Create a mock httpx AsyncClient."""
      client = AsyncMock()
      response = AsyncMock()
      response.status_code = 200
      response.json = MagicMock(return_value=mock_llm_response)
      response.raise_for_status = MagicMock()
      client.post = AsyncMock(return_value=response)
      client.get = AsyncMock(return_value=response)
      client.aclose = AsyncMock()
      return client
  ```

- Rust helper modules for testing (example: `crates/rag-retrieval/tests/integration/mocks.rs`)
  ```rust
  pub fn generate_overlapping_results(
      semantic_count: usize,
      keyword_count: usize,
      overlap: usize,
  ) -> (Vec<MockSearchResult>, Vec<MockSearchResult>) {
      // Creates test data with overlapping results
  }

  pub fn to_scored_items(results: &[MockSearchResult]) -> Vec<ScoredItem<Uuid>> {
      // Converts mock results to ScoredItem format
  }
  ```

**What to Mock:**
- External services: Redis, HTTP clients, LLM gateway
- Infrastructure: Database connections (in Python orchestrator tests)
- Complex dependencies: Session managers, model gateways
- **Don't mock:** Core business logic that should be tested, validation rules, fusion algorithms

**What NOT to Mock:**
- Error handling logic
- Core computation functions
- Fusion algorithms (test with real inputs)
- Pydantic models
- Enums and simple types

## Fixtures and Factories

**Test Data:**
- Python pattern (from `services/orchestrator/tests/conftest.py`):
  ```python
  @pytest.fixture
  def config():
      """Create test configuration."""
      from config import OrchestratorConfig

      return OrchestratorConfig(
          service_name="orchestrator-service-test",
          service_port=8003,
          debug=True,
          redis_url="redis://localhost:6379/1",  # Use different DB for tests
          llm_gateway_url="http://localhost:8004",
          retrieval_url="http://localhost:8002",
      )
  ```

- Python async fixture pattern:
  ```python
  @pytest.fixture
  async def session_manager(config, mock_redis):
      """Create a session manager with mocked Redis."""
      manager = SessionManager(config=config, redis_client=mock_redis)
      yield manager
      await manager.cleanup()
  ```

**Location:**
- Python: `tests/conftest.py` for project-wide fixtures
  - Module-specific: `tests/<module>/conftest.py` for localized fixtures
  - Orchestrator: `services/orchestrator/tests/conftest.py`
  - Shared security: `tests/security/conftest.py` if common fixtures
- Rust: Mock modules in `tests/integration/mocks.rs`

## Coverage

**Requirements:**
- Python: Minimum 70% coverage (enforced by `tool.coverage.run fail_under = 70`)
- Rust: No enforced minimum, but high coverage expected for critical modules

**View Coverage:**
```bash
# Python
pytest tests/ --cov=services --cov-report=html
open htmlcov/index.html  # View HTML report

# View specific module
pytest tests/security/ --cov=services.shared.security --cov-report=term-missing
```

**Excluded Lines:**
```python
# pyproject.toml - tool.coverage.report exclude_lines
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise AssertionError",
    "raise NotImplementedError",
    "if __name__ == .__main__.:",
    "if TYPE_CHECKING:",
    "if typing.TYPE_CHECKING:",
    "@abstractmethod",
]
```

## Test Types

**Unit Tests:**
- Scope: Single function/module in isolation
- Mocking: Heavy use of mocks for dependencies
- Speed: <100ms per test
- Examples:
  - `tests/security/test_pii_detection.py::TestPIISettings::test_default_settings`
  - `crates/rag-retrieval/tests/integration/hybrid_search.rs::test_rrf_fusion_combines_results`

**Integration Tests:**
- Scope: Multiple components working together
- Mocking: Some mocks (external services), but real internal components
- Speed: 100ms-2s per test
- Examples:
  - `tests/integration/test_rag_pipeline.py` - Full RAG workflow
  - `crates/rag-retrieval/tests/integration/hybrid_search.rs` - Fusion + search components

**E2E Tests:**
- Scope: Full system through HTTP API
- Mocking: Minimal (only external APIs if needed)
- Speed: 1-10s per test
- Examples:
  - `tests/e2e/test_rag_pipeline.py` - Complete query lifecycle
  - Run against real services via docker-compose

**Markers (Python):**
```python
# From pyproject.toml pytest markers
markers = [
    "slow: marks tests as slow (deselect with '-m \"not slow\"')",
    "integration: marks tests as integration tests",
    "security: marks security-related tests",
    "unit: marks unit tests",
    "requires_spacy: marks tests requiring spacy availability",
]

# Usage in tests
@pytest.mark.slow
def test_expensive_operation():
    pass

@pytest.mark.asyncio
async def test_async_operation():
    pass
```

## Common Patterns

**Async Testing:**
- Python: Use `@pytest.mark.asyncio` decorator
  ```python
  class TestInputGuardrail:
      @pytest.fixture
      def guardrail(self):
          return InputGuardrail()

      @pytest.mark.asyncio
      async def test_valid_input_passes(self, guardrail):
          """Test that valid input passes all checks."""
          text = "What is the weather like today?"
          result = await guardrail.check(text)

          assert result.passed is True
          assert len(result.violations) == 0
  ```

- Rust: Use `#[tokio::test]` macro
  ```rust
  #[tokio::test]
  async fn test_retrieval_with_context() {
      let client = HybridSearcher::new(&config).await.unwrap();
      let query = "What is Python?";
      let results = client.search(query).await.unwrap();

      assert!(!results.is_empty());
  }
  ```

**Error Testing:**
- Python: Use `pytest.raises` context manager
  ```python
  def test_length_violation(self):
      """Test that overly long input is flagged."""
      config = GuardrailConfig(max_input_length=50)
      guardrail = InputGuardrail(config)

      text = "a" * 100
      result = await guardrail.check(text)

      assert result.passed is False
      assert len(result.violations) == 1
      assert result.violations[0].type == ViolationType.CONTENT_TOO_LONG
  ```

- Rust: Test error variants
  ```rust
  #[test]
  fn test_fusion_invalid_weights() {
      let config = FusionConfig::new(FusionMethod::Linear)
          .with_weights(1.5, 0.3);  // Invalid: sum > 1.0

      let semantic = vec![ScoredItem::new(Uuid::new_v4(), 0.9)];
      let keyword = vec![ScoredItem::new(Uuid::new_v4(), 0.6)];

      let result = fuse(&semantic, &keyword, &config);
      assert!(result.is_err());
      assert!(matches!(result.err().unwrap(), Error::Validation { .. }));
  }
  ```

**Parameterized Tests:**
- Python: Use `@pytest.mark.parametrize`
  ```python
  @pytest.mark.parametrize(
      "input_text,expected_entity_type",
      [
          ("john@example.com", PIIEntityType.EMAIL_ADDRESS),
          ("555-123-4567", PIIEntityType.PHONE_NUMBER),
          ("123-45-6789", PIIEntityType.US_SSN),
      ],
  )
  def test_pii_detection_patterns(self, input_text, expected_entity_type):
      """Test detection of various PII patterns."""
      result = detect_pii(input_text)
      assert len(result) > 0
      assert result[0].entity_type == expected_entity_type
  ```

- Rust: Use loop within test or separate test per case
  ```rust
  #[test]
  fn test_fusion_methods_consistency() {
      for (semantic, keyword) in test_cases {
          for method in [FusionMethod::Rrf, FusionMethod::Linear, FusionMethod::Dbsf] {
              let config = FusionConfig::new(method);
              let result = fuse(&semantic, &keyword, &config);

              assert!(result.is_ok());
              assert!(!result.unwrap().is_empty());
          }
      }
  }
  ```

## Test Configuration

**Pytest Configuration:**
- File: `pyproject.toml` (primary) and `services/orchestrator/pytest.ini` (orchestrator-specific)
- Settings:
  ```toml
  [tool.pytest.ini_options]
  minversion = "7.0"
  testpaths = ["tests"]
  python_files = ["test_*.py", "*_test.py"]
  python_classes = ["Test*"]
  python_functions = ["test_*"]
  addopts = ["-v", "--strict-markers", "--tb=short", "-ra"]
  asyncio_mode = "auto"
  filterwarnings = [
      "ignore::DeprecationWarning",
      "ignore::PendingDeprecationWarning",
  ]
  ```

**Skip Conditions:**
- Python: Custom skip for spacy availability (tests/conftest.py)
  ```python
  def pytest_collection_modifyitems(config, items):
      """Skip tests that require spacy if it's not available."""
      if not SPACY_AVAILABLE:
          skip_spacy = pytest.mark.skip(
              reason=f"spacy not available on Python {sys.version_info.major}.{sys.version_info.minor}"
          )
          for item in items:
              if "test_pii_detection" in str(item.fspath):
                  item.add_marker(skip_spacy)
  ```

## Test Isolation

**Database Isolation:**
- Python: Use separate Redis DB for tests (`redis://localhost:6379/1`)
- Rust: Mock databases or use in-memory alternatives
- Cleanup: Fixture teardown (Python `yield`, Rust `drop`)

**Async Event Loop:**
- Python: `pytest-asyncio` with `asyncio_mode = "auto"` handles event loop management
- No manual loop creation needed with pytest async markers

**Environment:**
- Isolate using `.env.test` or fixture-based configuration
- Never depend on system environment variables in tests

---

*Testing analysis: 2026-01-30*
