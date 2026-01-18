"""Tests for configuration validation."""

import os
from importlib import reload
from unittest import mock

import pytest

from shared.config.validation import (
    ConfigurationError,
    validate_on_startup,
    validate_timeout_cascade,
)


class TestValidateTimeoutCascade:
    """Tests for validate_timeout_cascade function."""

    def test_default_config_is_valid(self) -> None:
        """Default timeout configuration should be valid."""
        errors = validate_timeout_cascade()
        assert len(errors) == 0

    def test_detects_retrieval_cascade_violation(self) -> None:
        """Should detect when retrieval inner > total."""
        # Mock env vars to create violation
        # Set reranker timeout higher than total
        with mock.patch.dict(
            os.environ,
            {
                "RETRIEVAL_RERANKER_TIMEOUT_MS": "20000",
                "RETRIEVAL_TOTAL_TIMEOUT_MS": "15000",
            },
        ):
            # Need to reimport to pick up env vars
            import shared.config.timeouts as timeouts_module
            import shared.config.validation as validation_module

            reload(timeouts_module)
            reload(validation_module)

            errors = validation_module.validate_timeout_cascade()

            assert len(errors) > 0
            assert any("Retrieval cascade violation" in e for e in errors)
            assert any("reranker" in e.lower() for e in errors)

            # Restore original values
            os.environ.pop("RETRIEVAL_RERANKER_TIMEOUT_MS", None)
            os.environ.pop("RETRIEVAL_TOTAL_TIMEOUT_MS", None)
            reload(timeouts_module)
            reload(validation_module)

    def test_detects_orchestrator_cascade_violation(self) -> None:
        """Should detect when orchestrator retrieval >= total."""
        with mock.patch.dict(
            os.environ,
            {
                "ORCHESTRATOR_RETRIEVAL_TIMEOUT_MS": "35000",
                "ORCHESTRATOR_TOTAL_TIMEOUT_MS": "30000",
            },
        ):
            import shared.config.timeouts as timeouts_module
            import shared.config.validation as validation_module

            reload(timeouts_module)
            reload(validation_module)

            errors = validation_module.validate_timeout_cascade()

            assert len(errors) > 0
            assert any("Orchestrator cascade violation" in e for e in errors)

            # Restore
            os.environ.pop("ORCHESTRATOR_RETRIEVAL_TIMEOUT_MS", None)
            os.environ.pop("ORCHESTRATOR_TOTAL_TIMEOUT_MS", None)
            reload(timeouts_module)
            reload(validation_module)

    def test_detects_cross_service_cascade_violation(self) -> None:
        """Should detect when retrieval_total >= orchestrator_retrieval."""
        with mock.patch.dict(
            os.environ,
            {
                "RETRIEVAL_TOTAL_TIMEOUT_MS": "25000",
                "ORCHESTRATOR_RETRIEVAL_TIMEOUT_MS": "20000",
            },
        ):
            import shared.config.timeouts as timeouts_module
            import shared.config.validation as validation_module

            reload(timeouts_module)
            reload(validation_module)

            errors = validation_module.validate_timeout_cascade()

            assert len(errors) > 0
            assert any("Cross-service cascade violation" in e for e in errors)

            # Restore
            os.environ.pop("RETRIEVAL_TOTAL_TIMEOUT_MS", None)
            os.environ.pop("ORCHESTRATOR_RETRIEVAL_TIMEOUT_MS", None)
            reload(timeouts_module)
            reload(validation_module)

    def test_detects_ingestion_cascade_violation(self) -> None:
        """Should detect when ingestion inner > document total."""
        with mock.patch.dict(
            os.environ,
            {
                "INGESTION_PARSING_TIMEOUT_MS": "350000",
                "INGESTION_DOCUMENT_TIMEOUT_MS": "300000",
            },
        ):
            import shared.config.timeouts as timeouts_module
            import shared.config.validation as validation_module

            reload(timeouts_module)
            reload(validation_module)

            errors = validation_module.validate_timeout_cascade()

            assert len(errors) > 0
            assert any("Ingestion cascade violation" in e for e in errors)

            # Restore
            os.environ.pop("INGESTION_PARSING_TIMEOUT_MS", None)
            os.environ.pop("INGESTION_DOCUMENT_TIMEOUT_MS", None)
            reload(timeouts_module)
            reload(validation_module)

    def test_detects_multiple_violations(self) -> None:
        """Should detect and report all cascade violations."""
        with mock.patch.dict(
            os.environ,
            {
                # Retrieval violation: inner > total
                "RETRIEVAL_RERANKER_TIMEOUT_MS": "20000",
                "RETRIEVAL_TOTAL_TIMEOUT_MS": "15000",
                # Orchestrator violation: retrieval >= total
                "ORCHESTRATOR_RETRIEVAL_TIMEOUT_MS": "35000",
                "ORCHESTRATOR_TOTAL_TIMEOUT_MS": "30000",
            },
        ):
            import shared.config.timeouts as timeouts_module
            import shared.config.validation as validation_module

            reload(timeouts_module)
            reload(validation_module)

            errors = validation_module.validate_timeout_cascade()

            # Should have at least 2 errors (retrieval + orchestrator + potentially cross-service)
            assert len(errors) >= 2
            assert any("Retrieval cascade violation" in e for e in errors)
            assert any("Orchestrator cascade violation" in e for e in errors)

            # Restore
            os.environ.pop("RETRIEVAL_RERANKER_TIMEOUT_MS", None)
            os.environ.pop("RETRIEVAL_TOTAL_TIMEOUT_MS", None)
            os.environ.pop("ORCHESTRATOR_RETRIEVAL_TIMEOUT_MS", None)
            os.environ.pop("ORCHESTRATOR_TOTAL_TIMEOUT_MS", None)
            reload(timeouts_module)
            reload(validation_module)

    def test_equal_values_are_violations(self) -> None:
        """Should detect violation when inner equals outer (not strictly less)."""
        with mock.patch.dict(
            os.environ,
            {
                "ORCHESTRATOR_RETRIEVAL_TIMEOUT_MS": "30000",
                "ORCHESTRATOR_TOTAL_TIMEOUT_MS": "30000",  # Equal, not less
            },
        ):
            import shared.config.timeouts as timeouts_module
            import shared.config.validation as validation_module

            reload(timeouts_module)
            reload(validation_module)

            errors = validation_module.validate_timeout_cascade()

            assert len(errors) > 0
            assert any("Orchestrator cascade violation" in e for e in errors)

            # Restore
            os.environ.pop("ORCHESTRATOR_RETRIEVAL_TIMEOUT_MS", None)
            os.environ.pop("ORCHESTRATOR_TOTAL_TIMEOUT_MS", None)
            reload(timeouts_module)
            reload(validation_module)


class TestValidateOnStartup:
    """Tests for validate_on_startup function."""

    def test_returns_empty_on_valid_config(self) -> None:
        """Should return empty list for valid config."""
        errors = validate_on_startup(fail_fast=False)
        assert errors == []

    def test_raises_on_invalid_with_fail_fast(self) -> None:
        """Should raise ConfigurationError with fail_fast=True."""
        with mock.patch.dict(
            os.environ,
            {
                "RETRIEVAL_RERANKER_TIMEOUT_MS": "20000",
                "RETRIEVAL_TOTAL_TIMEOUT_MS": "15000",
            },
        ):
            import shared.config.timeouts as timeouts_module
            import shared.config.validation as validation_module

            reload(timeouts_module)
            reload(validation_module)

            # Use the reloaded ConfigurationError class
            with pytest.raises(validation_module.ConfigurationError) as exc_info:
                validation_module.validate_on_startup(fail_fast=True)

            assert len(exc_info.value.errors) > 0
            assert any("Retrieval" in e for e in exc_info.value.errors)

            # Restore
            os.environ.pop("RETRIEVAL_RERANKER_TIMEOUT_MS", None)
            os.environ.pop("RETRIEVAL_TOTAL_TIMEOUT_MS", None)
            reload(timeouts_module)
            reload(validation_module)

    def test_returns_errors_without_fail_fast(self) -> None:
        """Should return errors without raising when fail_fast=False."""
        with mock.patch.dict(
            os.environ,
            {
                "RETRIEVAL_RERANKER_TIMEOUT_MS": "20000",
                "RETRIEVAL_TOTAL_TIMEOUT_MS": "15000",
            },
        ):
            import shared.config.timeouts as timeouts_module
            import shared.config.validation as validation_module

            reload(timeouts_module)
            reload(validation_module)

            # Should not raise
            errors = validation_module.validate_on_startup(fail_fast=False)

            assert len(errors) > 0
            assert any("Retrieval" in e for e in errors)

            # Restore
            os.environ.pop("RETRIEVAL_RERANKER_TIMEOUT_MS", None)
            os.environ.pop("RETRIEVAL_TOTAL_TIMEOUT_MS", None)
            reload(timeouts_module)
            reload(validation_module)

    def test_fail_fast_default_is_true(self) -> None:
        """Default fail_fast should be True (raises on error)."""
        with mock.patch.dict(
            os.environ,
            {
                "ORCHESTRATOR_RETRIEVAL_TIMEOUT_MS": "35000",
                "ORCHESTRATOR_TOTAL_TIMEOUT_MS": "30000",
            },
        ):
            import shared.config.timeouts as timeouts_module
            import shared.config.validation as validation_module

            reload(timeouts_module)
            reload(validation_module)

            # Should raise without explicit fail_fast argument
            # Use the reloaded ConfigurationError class
            with pytest.raises(validation_module.ConfigurationError):
                validation_module.validate_on_startup()

            # Restore
            os.environ.pop("ORCHESTRATOR_RETRIEVAL_TIMEOUT_MS", None)
            os.environ.pop("ORCHESTRATOR_TOTAL_TIMEOUT_MS", None)
            reload(timeouts_module)
            reload(validation_module)


class TestConfigurationError:
    """Tests for ConfigurationError exception class."""

    def test_configuration_error_stores_errors(self) -> None:
        """ConfigurationError should store list of errors."""
        errors = ["Error 1", "Error 2"]
        exc = ConfigurationError(errors)

        assert exc.errors == errors
        assert len(exc.errors) == 2

    def test_configuration_error_message(self) -> None:
        """ConfigurationError should have descriptive message."""
        errors = ["Timeout cascade violation"]
        exc = ConfigurationError(errors)

        assert "Configuration validation failed" in str(exc)
        assert "Timeout cascade violation" in str(exc)

    def test_configuration_error_empty_list(self) -> None:
        """ConfigurationError should handle empty error list."""
        exc = ConfigurationError([])

        assert exc.errors == []
        assert "Configuration validation failed" in str(exc)

    def test_configuration_error_is_exception(self) -> None:
        """ConfigurationError should be an Exception subclass."""
        exc = ConfigurationError(["error"])

        assert isinstance(exc, Exception)
