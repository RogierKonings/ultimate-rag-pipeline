"""Orchestrator Service Configuration.

This module re-exports OrchestratorConfig and get_config from config.settings
for backward compatibility.
"""

# Re-export from settings for backward compatibility
from orchestrator.config.settings import OrchestratorConfig, get_config

__all__ = ["OrchestratorConfig", "get_config"]
