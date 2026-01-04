# Task Completion Checklist

## Before Completing a Task

1. **Code Quality**
   - Run linting: `make lint` or `ruff check .`
   - Ensure code follows project conventions
   - Add appropriate type hints

2. **Testing**
   - Run tests: `make test` or `pytest`
   - Add tests for new functionality

3. **Documentation**
   - Update relevant docs if needed
   - Add docstrings to new functions/classes

4. **Kubernetes Changes**
   - Validate YAML syntax
   - Test with `kubectl apply --dry-run=client`
   - Update kustomization.yaml if adding new resources

## Code Style Conventions
- Python 3.11+ with type hints
- FastAPI + Pydantic v2 for APIs
- Use async/await for I/O operations
- Follow PEP 8 naming conventions
- Use `ruff` for linting
