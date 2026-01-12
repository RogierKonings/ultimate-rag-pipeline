"""
Encryption module for the RAG Pipeline.

This module provides field-level encryption with AES-256-GCM,
key management, and SQLAlchemy type integration.
"""

from .field_encryption import (
    FieldEncryption,
    EncryptionError,
    DecryptionError,
    KeyError as EncryptionKeyError,
)
from .key_manager import (
    EncryptionKeyManager,
    KeyProvider,
    EnvironmentKeyProvider,
    VaultKeyProvider,
    FileKeyProvider,
)

__all__ = [
    # Field encryption
    "FieldEncryption",
    "EncryptionError",
    "DecryptionError",
    "EncryptionKeyError",
    # Key management
    "EncryptionKeyManager",
    "KeyProvider",
    "EnvironmentKeyProvider",
    "VaultKeyProvider",
    "FileKeyProvider",
]
