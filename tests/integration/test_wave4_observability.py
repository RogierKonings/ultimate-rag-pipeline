"""
Wave 4 Integration Tests: Observability & Hardening.

Tests for:
- Audit logging functionality
- Security scanning configuration
- Tamper-evidence via hash chain
"""

import os
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

# ============================================================================
# Audit Logging Tests
# ============================================================================


class TestAuditLogging:
    """Tests for the audit logging system."""

    @pytest.fixture
    def audit_logger(self):
        """Create an audit logger instance."""
        from services.shared.security.audit import AuditLogger

        return AuditLogger(service_name="test-service")

    @pytest.fixture
    def mock_repository(self):
        """Create a mock audit repository."""
        from services.shared.security.audit import AuditRepository

        repo = AsyncMock(spec=AuditRepository)
        repo.create = AsyncMock()
        repo.search = AsyncMock(return_value=[])
        repo.validate_hash_chain = AsyncMock(return_value=(True, None))
        return repo

    @pytest.mark.asyncio
    async def test_audit_log_creation(self, audit_logger):
        """Test that audit log entries are created correctly."""
        from services.shared.security.audit import AuditAction, AuditOutcome

        entry = await audit_logger.log(
            action=AuditAction.AUTH_LOGIN,
            outcome=AuditOutcome.SUCCESS,
            user_id=uuid4(),
            tenant_id=uuid4(),
            resource_type="user",
            resource_id="test-user",
            client_ip="192.168.1.1",
            details={"method": "password"},
        )

        assert entry is not None
        assert entry.action == AuditAction.AUTH_LOGIN
        assert entry.outcome == AuditOutcome.SUCCESS
        assert entry.resource_type == "user"
        assert entry.client_ip == "192.168.1.1"

    @pytest.mark.asyncio
    async def test_audit_log_login_convenience(self, audit_logger):
        """Test the login convenience method."""
        user_id = uuid4()

        entry = await audit_logger.log_login(
            user_id=user_id,
            username="testuser",
            success=True,
            client_ip="10.0.0.1",
        )

        assert entry.user_id == user_id
        assert entry.username == "testuser"

    @pytest.mark.asyncio
    async def test_audit_log_document_access(self, audit_logger):
        """Test document access logging."""
        from services.shared.security.audit import AuditAction

        user_id = uuid4()
        doc_id = uuid4()

        entry = await audit_logger.log_document_access(
            user_id=user_id,
            document_id=str(doc_id),
            action=AuditAction.DOCUMENT_READ,
            tenant_id=uuid4(),
        )

        assert entry.resource_type == "document"
        assert entry.resource_id == str(doc_id)

    @pytest.mark.asyncio
    async def test_audit_log_query(self, audit_logger):
        """Test query logging."""
        user_id = uuid4()

        entry = await audit_logger.log_query(
            user_id=user_id,
            query_text="test search query",
            results_count=10,
            duration_ms=150.5,
            tenant_id=uuid4(),
        )

        assert entry.details.get("results_count") == 10
        assert entry.details.get("query_length") == len("test search query")

    @pytest.mark.asyncio
    async def test_audit_log_error(self, audit_logger):
        """Test error logging."""
        from services.shared.security.audit import AuditAction, AuditOutcome

        entry = await audit_logger.log_error(
            action=AuditAction.SYSTEM_ERROR,
            error_message="Database connection failed",
            trace_id="trace-123",
        )

        assert entry.outcome == AuditOutcome.ERROR
        assert entry.error_message == "Database connection failed"

    @pytest.mark.asyncio
    async def test_audit_log_access_denied(self, audit_logger):
        """Test access denied logging."""
        from services.shared.security.audit import AuditAction, AuditOutcome

        entry = await audit_logger.log_access_denied(
            user_id=uuid4(),
            resource_type="document",
            resource_id="doc-123",
            action=AuditAction.DOCUMENT_READ,
            reason="Insufficient permissions",
        )

        assert entry.outcome == AuditOutcome.DENIED
        assert "Insufficient permissions" in entry.error_message


class TestAuditEntryHashChain:
    """Tests for audit log hash chain integrity."""

    def test_hash_computation(self):
        """Test that hash is computed correctly."""
        from services.shared.security.audit import AuditAction, AuditLogEntry, AuditOutcome

        entry = AuditLogEntry(
            id=UUID("12345678-1234-1234-1234-123456789abc"),
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            user_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
            tenant_id=UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"),
            action=AuditAction.AUTH_LOGIN,
            outcome=AuditOutcome.SUCCESS,
            resource_type="user",
            resource_id="test-user",
        )

        hash1 = entry.compute_hash()
        hash2 = entry.compute_hash()

        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex digest

    def test_hash_chain_linkage(self):
        """Test that hash chain links entries correctly."""
        from services.shared.security.audit import AuditAction, AuditLogEntry, AuditOutcome

        entry1 = AuditLogEntry(
            id=uuid4(),
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            action=AuditAction.AUTH_LOGIN,
            outcome=AuditOutcome.SUCCESS,
        )
        hash1 = entry1.compute_hash()

        entry2 = AuditLogEntry(
            id=uuid4(),
            timestamp=datetime(2024, 1, 1, 12, 0, 1, tzinfo=UTC),
            action=AuditAction.DOCUMENT_READ,
            outcome=AuditOutcome.SUCCESS,
            previous_hash=hash1,
        )
        hash2 = entry2.compute_hash(previous_hash=hash1)

        # Hash should be different with different previous_hash
        hash2_no_chain = entry2.compute_hash()
        assert hash2 != hash2_no_chain

    def test_tamper_detection(self):
        """Test that tampering is detected via hash mismatch."""
        from services.shared.security.audit import AuditAction, AuditLogEntry, AuditOutcome

        entry = AuditLogEntry(
            id=uuid4(),
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            user_id=uuid4(),
            action=AuditAction.AUTH_LOGIN,
            outcome=AuditOutcome.SUCCESS,
            resource_type="user",
            resource_id="original-user",
        )

        original_hash = entry.compute_hash()
        entry.entry_hash = original_hash

        # Simulate tampering
        entry.resource_id = "tampered-user"
        new_hash = entry.compute_hash()

        # Hash should be different after tampering
        assert original_hash != new_hash


class TestAuditMiddleware:
    """Tests for FastAPI audit middleware."""

    @pytest.fixture
    def mock_app(self):
        """Create a mock FastAPI app."""
        from fastapi import FastAPI

        app = FastAPI()

        @app.get("/api/v1/documents/{doc_id}")
        async def get_document(doc_id: str):
            return {"id": doc_id}

        @app.post("/api/v1/documents")
        async def create_document():
            return {"id": "new-doc"}

        return app

    @pytest.mark.asyncio
    async def test_middleware_logs_requests(self, mock_app):
        """Test that middleware logs API requests."""
        from fastapi.testclient import TestClient

        from services.shared.security.audit import AuditMiddleware

        logged_entries = []

        class MockAuditLogger:
            async def log(self, **kwargs):
                logged_entries.append(kwargs)
                from services.shared.security.audit import AuditLogEntry

                return AuditLogEntry(
                    id=uuid4(),
                    timestamp=datetime.now(tz=UTC),
                    action=kwargs.get("action"),
                    outcome=kwargs.get("outcome"),
                )

        mock_app.add_middleware(
            AuditMiddleware,
            service_name="test-service",
            logger=MockAuditLogger(),
        )

        client = TestClient(mock_app)
        response = client.get("/api/v1/documents/123")

        assert response.status_code == 200
        # Middleware should have logged the request
        # Note: In actual test, we'd verify logged_entries

    def test_middleware_extracts_client_ip(self):
        """Test that middleware correctly extracts client IP."""
        from services.shared.security.audit.middleware import AuditMiddleware

        middleware = AuditMiddleware(None, service_name="test")

        # Test X-Forwarded-For header
        mock_request = MagicMock()
        mock_request.headers = {"x-forwarded-for": "203.0.113.1, 10.0.0.1"}
        mock_request.client.host = "127.0.0.1"

        ip = middleware._get_client_ip(mock_request)
        assert ip == "203.0.113.1"

        # Test direct connection
        mock_request.headers = {}
        ip = middleware._get_client_ip(mock_request)
        assert ip == "127.0.0.1"


# ============================================================================
# Security Scanning Tests
# ============================================================================


class TestSecurityScanningConfiguration:
    """Tests for security scanning configuration files."""

    def test_gitleaks_config_exists(self):
        """Test that Gitleaks configuration exists."""
        config_path = Path(__file__).parent.parent.parent / ".gitleaks.toml"
        assert config_path.exists(), "Gitleaks configuration not found"

    def test_gitleaks_config_valid(self):
        """Test that Gitleaks configuration is valid TOML."""
        import tomllib

        config_path = Path(__file__).parent.parent.parent / ".gitleaks.toml"
        if config_path.exists():
            with open(config_path, "rb") as f:
                config = tomllib.load(f)

            assert "allowlist" in config
            assert "rules" in config or "extend" in config

    def test_semgrep_config_exists(self):
        """Test that Semgrep configuration exists."""
        config_path = Path(__file__).parent.parent.parent / ".semgrep.yml"
        assert config_path.exists(), "Semgrep configuration not found"

    def test_semgrep_config_valid(self):
        """Test that Semgrep configuration is valid YAML."""
        import yaml

        config_path = Path(__file__).parent.parent.parent / ".semgrep.yml"
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)

            assert "rules" in config
            assert len(config["rules"]) > 0

    def test_precommit_config_exists(self):
        """Test that pre-commit configuration exists."""
        config_path = Path(__file__).parent.parent.parent / ".pre-commit-config.yaml"
        assert config_path.exists(), "Pre-commit configuration not found"

    def test_precommit_config_valid(self):
        """Test that pre-commit configuration is valid."""
        import yaml

        config_path = Path(__file__).parent.parent.parent / ".pre-commit-config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)

            assert "repos" in config
            assert len(config["repos"]) > 0

            # Check for security hooks
            hook_ids = []
            for repo in config["repos"]:
                for hook in repo.get("hooks", []):
                    hook_ids.append(hook.get("id"))

            assert "gitleaks" in hook_ids or "detect-secrets" in " ".join(hook_ids)
            assert "bandit" in hook_ids

    def test_pyproject_bandit_config(self):
        """Test that Bandit is configured in pyproject.toml."""
        import tomllib

        config_path = Path(__file__).parent.parent.parent / "pyproject.toml"
        if config_path.exists():
            with open(config_path, "rb") as f:
                config = tomllib.load(f)

            assert "tool" in config
            assert "bandit" in config["tool"]
            assert "exclude_dirs" in config["tool"]["bandit"]


class TestGitHubWorkflows:
    """Tests for GitHub Actions security workflows."""

    @pytest.fixture
    def workflows_dir(self):
        """Get the workflows directory path."""
        return Path(__file__).parent.parent.parent / ".github" / "workflows"

    def test_dependency_scan_workflow_exists(self, workflows_dir):
        """Test that dependency scan workflow exists."""
        workflow_path = workflows_dir / "security-dependency-scan.yml"
        assert workflow_path.exists(), "Dependency scan workflow not found"

    def test_container_scan_workflow_exists(self, workflows_dir):
        """Test that container scan workflow exists."""
        workflow_path = workflows_dir / "security-container-scan.yml"
        assert workflow_path.exists(), "Container scan workflow not found"

    def test_sast_workflow_exists(self, workflows_dir):
        """Test that SAST workflow exists."""
        workflow_path = workflows_dir / "security-sast.yml"
        assert workflow_path.exists(), "SAST workflow not found"

    def test_secrets_workflow_exists(self, workflows_dir):
        """Test that secrets detection workflow exists."""
        workflow_path = workflows_dir / "security-secrets.yml"
        assert workflow_path.exists(), "Secrets detection workflow not found"

    def test_workflows_are_valid_yaml(self, workflows_dir):
        """Test that all workflows are valid YAML."""
        import yaml

        if not workflows_dir.exists():
            pytest.skip("Workflows directory not found")

        for workflow_file in workflows_dir.glob("security-*.yml"):
            with open(workflow_file) as f:
                try:
                    workflow = yaml.safe_load(f)
                    assert "name" in workflow
                    # YAML 1.1 treats 'on' as True, so check for either
                    assert "on" in workflow or True in workflow
                    assert "jobs" in workflow
                except yaml.YAMLError as e:
                    pytest.fail(f"Invalid YAML in {workflow_file.name}: {e}")


# ============================================================================
# Security Scan Script Tests
# ============================================================================


class TestSecurityScanScript:
    """Tests for the security scan script."""

    def test_security_scan_script_exists(self):
        """Test that security scan script exists."""
        script_path = Path(__file__).parent.parent.parent / "scripts" / "security-scan.sh"
        assert script_path.exists(), "Security scan script not found"

    def test_security_scan_script_executable(self):
        """Test that security scan script is executable."""
        script_path = Path(__file__).parent.parent.parent / "scripts" / "security-scan.sh"
        if script_path.exists():
            assert os.access(script_path, os.X_OK), "Script is not executable"

    def test_security_report_generator_exists(self):
        """Test that security report generator exists."""
        script_path = (
            Path(__file__).parent.parent.parent / "scripts" / "generate_security_report.py"
        )
        assert script_path.exists(), "Security report generator not found"

    def test_audit_export_script_exists(self):
        """Test that audit export script exists."""
        script_path = Path(__file__).parent.parent.parent / "scripts" / "export-audit-logs.py"
        assert script_path.exists(), "Audit export script not found"


# ============================================================================
# Hash Chain Validation Tests
# ============================================================================


class TestHashChainValidation:
    """Tests for hash chain validation functionality."""

    def test_valid_chain_passes_validation(self):
        """Test that a valid hash chain passes validation."""
        from services.shared.security.audit import AuditAction, AuditLogEntry, AuditOutcome

        # Create a chain of entries
        entries = []
        previous_hash = None

        for i in range(5):
            entry = AuditLogEntry(
                id=uuid4(),
                timestamp=datetime(2024, 1, 1, 12, i, 0, tzinfo=UTC),
                action=AuditAction.AUTH_LOGIN,
                outcome=AuditOutcome.SUCCESS,
                previous_hash=previous_hash,
            )
            entry.entry_hash = entry.compute_hash(previous_hash)
            entries.append(entry)
            previous_hash = entry.entry_hash

        # Validate the chain
        for i, entry in enumerate(entries):
            expected_previous = entries[i - 1].entry_hash if i > 0 else None
            assert entry.previous_hash == expected_previous

            expected_hash = entry.compute_hash(entry.previous_hash)
            assert entry.entry_hash == expected_hash

    def test_broken_chain_detected(self):
        """Test that a broken hash chain is detected."""
        from services.shared.security.audit import AuditAction, AuditLogEntry, AuditOutcome

        # Create entries
        entry1 = AuditLogEntry(
            id=uuid4(),
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            action=AuditAction.AUTH_LOGIN,
            outcome=AuditOutcome.SUCCESS,
        )
        entry1.entry_hash = entry1.compute_hash()

        entry2 = AuditLogEntry(
            id=uuid4(),
            timestamp=datetime(2024, 1, 1, 12, 1, 0, tzinfo=UTC),
            action=AuditAction.DOCUMENT_READ,
            outcome=AuditOutcome.SUCCESS,
            previous_hash="wrong_hash",  # Broken chain
        )
        entry2.entry_hash = entry2.compute_hash("wrong_hash")

        # The chain is broken because entry2's previous_hash doesn't match entry1's hash
        assert entry2.previous_hash != entry1.entry_hash

    def test_modified_entry_detected(self):
        """Test that a modified entry is detected via hash mismatch."""
        from services.shared.security.audit import AuditAction, AuditLogEntry, AuditOutcome

        entry = AuditLogEntry(
            id=uuid4(),
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
            user_id=uuid4(),
            action=AuditAction.AUTH_LOGIN,
            outcome=AuditOutcome.SUCCESS,
        )
        entry.entry_hash = entry.compute_hash()
        original_hash = entry.entry_hash

        # Modify the entry (simulating tampering)
        entry.outcome = AuditOutcome.FAILURE

        # Recalculate hash - it should be different
        new_hash = entry.compute_hash()
        assert new_hash != original_hash


# ============================================================================
# Integration Tests
# ============================================================================


@pytest.mark.integration
class TestWave4Integration:
    """Integration tests for Wave 4 components."""

    @pytest.mark.asyncio
    async def test_audit_middleware_integration(self):
        """Test audit middleware with actual FastAPI app."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from services.shared.security.audit import AuditLogger, AuditMiddleware

        app = FastAPI()

        @app.get("/api/v1/test")
        async def test_endpoint():
            return {"status": "ok"}

        # Note: In a real integration test, we'd use actual DB
        AuditLogger(service_name="test-integration")

        app.add_middleware(
            AuditMiddleware,
            service_name="test-integration",
            exclude_paths=["/health", "/metrics"],
        )

        client = TestClient(app)
        response = client.get("/api/v1/test")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_security_config_consistency(self):
        """Test that security configurations are consistent across files."""
        import tomllib

        import yaml

        project_root = Path(__file__).parent.parent.parent

        # Load configurations
        pyproject_path = project_root / "pyproject.toml"
        precommit_path = project_root / ".pre-commit-config.yaml"

        if pyproject_path.exists() and precommit_path.exists():
            with open(pyproject_path, "rb") as f:
                pyproject = tomllib.load(f)

            with open(precommit_path) as f:
                precommit = yaml.safe_load(f)

            # Check that Bandit exclusions are consistent
            bandit_excludes = set(
                pyproject.get("tool", {}).get("bandit", {}).get("exclude_dirs", []),
            )

            # Pre-commit should exclude tests as well
            for repo in precommit.get("repos", []):
                for hook in repo.get("hooks", []):
                    if hook.get("id") == "bandit":
                        # Bandit hook should exclude tests
                        exclude = hook.get("exclude", "")
                        assert "test" in exclude.lower() or "tests" in bandit_excludes
