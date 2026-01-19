"""
PII (Personally Identifiable Information) detection and handling.

This module provides comprehensive PII detection and processing
capabilities using Microsoft Presidio.

Features:
- Detection of standard PII (emails, SSN, credit cards, etc.)
- Custom recognizers for enterprise patterns (API keys, tokens, etc.)
- Multiple handling modes (redact, mask, flag, reject, encrypt)
- Response filtering for search results and LLM outputs
- Query filtering to prevent PII leakage

Example:
    ```python
    from services.shared.security.pii import (
        PIIDetector,
        PIISettings,
        PIIHandlingMode,
        PIIResponseFilter,
    )

    # Configure PII detection
    settings = PIISettings(
        default_handling_mode=PIIHandlingMode.REDACT,
        confidence_threshold=0.7,
        reject_on_high_sensitivity=True,
    )

    # Create detector
    detector = PIIDetector(settings)

    # Detect PII
    result = await detector.detect("Contact john@example.com")
    print(result.entity_counts)  # {'EMAIL_ADDRESS': 1}

    # Redact PII
    redacted = await detector.redact("SSN: 123-45-6789")
    print(redacted)  # "SSN: [US_SSN]"

    # Filter search results
    filter = PIIResponseFilter(settings)
    filtered = await filter.filter_search_results(results)
    ```
"""

from .config import (
    PIIEntityConfig,
    PIIEntityType,
    PIIHandlingMode,
    PIISensitivity,
    PIISettings,
    create_pii_settings_from_env,
)
from .detector import (
    PIIDetectionError,
    PIIDetector,
    detect_pii,
    get_detector,
    redact_pii,
)
from .models import (
    PIIAnalysisRequest,
    PIIAnalysisResponse,
    PIIChunkResult,
    PIIDocumentResult,
    PIIEntity,
    PIIProcessedText,
    PIIResult,
)
from .response_filter import (
    PIIQueryFilter,
    PIIResponseFilter,
)
from .tenant_config import (
    TenantPIIConfigService,
    get_tenant_pii_config_service,
    reset_tenant_pii_config_service,
)

__all__ = [
    # Config
    "PIIHandlingMode",
    "PIIEntityType",
    "PIISensitivity",
    "PIIEntityConfig",
    "PIISettings",
    "create_pii_settings_from_env",
    # Detector
    "PIIDetector",
    "PIIDetectionError",
    "get_detector",
    "detect_pii",
    "redact_pii",
    # Models
    "PIIEntity",
    "PIIResult",
    "PIIProcessedText",
    "PIIChunkResult",
    "PIIDocumentResult",
    "PIIAnalysisRequest",
    "PIIAnalysisResponse",
    # Filters
    "PIIResponseFilter",
    "PIIQueryFilter",
    # Tenant config
    "TenantPIIConfigService",
    "get_tenant_pii_config_service",
    "reset_tenant_pii_config_service",
]
