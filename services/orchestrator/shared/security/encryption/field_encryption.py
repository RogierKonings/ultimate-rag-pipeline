"""
Field-level encryption using AES-256-GCM.

This module provides encryption/decryption for sensitive data fields
with authenticated encryption ensuring both confidentiality and integrity.
"""

import base64
import json
import secrets
from typing import Any

import structlog
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = structlog.get_logger(__name__)

# Constants
KEY_SIZE = 32  # 256 bits for AES-256
NONCE_SIZE = 12  # 96 bits recommended for GCM
TAG_SIZE = 16  # 128 bits authentication tag


class EncryptionError(Exception):
    """Base exception for encryption errors."""


class DecryptionError(EncryptionError):
    """Raised when decryption fails."""


class EncryptionKeyError(EncryptionError):
    """Raised when there's an issue with encryption keys."""


class FieldEncryption:
    """
    AES-256-GCM field encryption for sensitive data.

    Provides authenticated encryption ensuring both confidentiality
    and integrity of encrypted data. Each encryption operation uses
    a unique nonce, so the same plaintext produces different ciphertext.

    Example:
        ```python
        from shared.security.encryption import FieldEncryption

        # Initialize with key
        key = FieldEncryption.generate_key()
        encryptor = FieldEncryption(key)

        # Encrypt/decrypt strings
        ciphertext = encryptor.encrypt("sensitive data")
        plaintext = encryptor.decrypt(ciphertext)

        # Encrypt/decrypt dicts
        encrypted_dict = encryptor.encrypt_dict({"ssn": "123-45-6789"})
        decrypted_dict = encryptor.decrypt_dict(encrypted_dict)
        ```
    """

    def __init__(
        self,
        key: bytes | str,
        associated_data: bytes | None = None,
    ):
        """
        Initialize field encryption.

        Args:
            key: 32-byte encryption key (AES-256) as bytes or base64 string.
            associated_data: Optional additional authenticated data (AAD).
                            Not encrypted but authenticated with the ciphertext.
        """
        self._key = self._normalize_key(key)
        self._aesgcm = AESGCM(self._key)
        self._aad = associated_data

    @staticmethod
    def _normalize_key(key: bytes | str) -> bytes:
        """Normalize key to bytes."""
        if isinstance(key, str):
            try:
                key = base64.b64decode(key)
            except Exception:
                key = key.encode("utf-8")

        if len(key) != KEY_SIZE:
            raise EncryptionKeyError(
                f"Invalid key size: {len(key)} bytes. Expected {KEY_SIZE} bytes for AES-256.",
            )

        return key

    @staticmethod
    def generate_key() -> bytes:
        """
        Generate a cryptographically secure random key.

        Returns:
            32-byte random key for AES-256.
        """
        return secrets.token_bytes(KEY_SIZE)

    @staticmethod
    def key_to_base64(key: bytes) -> str:
        """Convert key to base64 string for storage."""
        return base64.b64encode(key).decode("utf-8")

    @staticmethod
    def key_from_base64(key_str: str) -> bytes:
        """Load key from base64 string."""
        return base64.b64decode(key_str)

    def encrypt(self, plaintext: str | bytes) -> str:
        """
        Encrypt plaintext data.

        Args:
            plaintext: Data to encrypt (string or bytes).

        Returns:
            Base64-encoded ciphertext (nonce + ciphertext + tag).

        Raises:
            EncryptionError: If encryption fails.
        """
        try:
            # Convert string to bytes
            if isinstance(plaintext, str):
                plaintext = plaintext.encode("utf-8")

            # Generate random nonce
            nonce = secrets.token_bytes(NONCE_SIZE)

            # Encrypt (includes authentication tag)
            ciphertext = self._aesgcm.encrypt(nonce, plaintext, self._aad)

            # Combine nonce + ciphertext and encode
            combined = nonce + ciphertext
            return base64.b64encode(combined).decode("utf-8")

        except Exception as e:
            raise EncryptionError(f"Encryption failed: {str(e)}") from e

    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt ciphertext data.

        Args:
            ciphertext: Base64-encoded ciphertext from encrypt().

        Returns:
            Decrypted plaintext as string.

        Raises:
            DecryptionError: If decryption fails (wrong key, tampered data, etc.).
        """
        try:
            # Decode base64
            combined = base64.b64decode(ciphertext)

            # Split nonce and ciphertext
            if len(combined) < NONCE_SIZE + TAG_SIZE:
                raise DecryptionError("Ciphertext too short")

            nonce = combined[:NONCE_SIZE]
            encrypted_data = combined[NONCE_SIZE:]

            # Decrypt and verify
            plaintext = self._aesgcm.decrypt(nonce, encrypted_data, self._aad)

            return plaintext.decode("utf-8")

        except DecryptionError:
            raise
        except Exception as e:
            raise DecryptionError(f"Decryption failed: {str(e)}") from e

    def encrypt_bytes(self, plaintext: bytes) -> bytes:
        """
        Encrypt bytes data, returning bytes.

        Args:
            plaintext: Data to encrypt.

        Returns:
            Raw ciphertext bytes (nonce + ciphertext + tag).
        """
        try:
            nonce = secrets.token_bytes(NONCE_SIZE)
            ciphertext = self._aesgcm.encrypt(nonce, plaintext, self._aad)
            return nonce + ciphertext
        except Exception as e:
            raise EncryptionError(f"Encryption failed: {str(e)}") from e

    def decrypt_bytes(self, ciphertext: bytes) -> bytes:
        """
        Decrypt bytes data.

        Args:
            ciphertext: Raw ciphertext bytes from encrypt_bytes().

        Returns:
            Decrypted plaintext bytes.
        """
        try:
            if len(ciphertext) < NONCE_SIZE + TAG_SIZE:
                raise DecryptionError("Ciphertext too short")

            nonce = ciphertext[:NONCE_SIZE]
            encrypted_data = ciphertext[NONCE_SIZE:]

            return self._aesgcm.decrypt(nonce, encrypted_data, self._aad)
        except DecryptionError:
            raise
        except Exception as e:
            raise DecryptionError(f"Decryption failed: {str(e)}") from e

    def encrypt_dict(
        self,
        data: dict[str, Any],
        fields_to_encrypt: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Encrypt specified fields in a dictionary.

        Args:
            data: Dictionary with data to encrypt.
            fields_to_encrypt: List of field names to encrypt.
                             If None, encrypts all string fields.

        Returns:
            Dictionary with specified fields encrypted.
        """
        result = data.copy()

        if fields_to_encrypt is None:
            # Encrypt all string fields
            fields_to_encrypt = [k for k, v in data.items() if isinstance(v, str)]

        for field in fields_to_encrypt:
            if field in result and result[field] is not None:
                value = result[field]
                if isinstance(value, str):
                    result[field] = self.encrypt(value)
                elif isinstance(value, (dict, list)):
                    # Serialize complex types
                    result[field] = self.encrypt(json.dumps(value))
                else:
                    # Convert to string first
                    result[field] = self.encrypt(str(value))

        return result

    def decrypt_dict(
        self,
        data: dict[str, Any],
        fields_to_decrypt: list[str] | None = None,
        json_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Decrypt specified fields in a dictionary.

        Args:
            data: Dictionary with encrypted fields.
            fields_to_decrypt: List of field names to decrypt.
                             If None, attempts to decrypt all string fields.
            json_fields: Fields that should be deserialized from JSON after decryption.

        Returns:
            Dictionary with specified fields decrypted.
        """
        result = data.copy()
        json_fields = json_fields or []

        if fields_to_decrypt is None:
            fields_to_decrypt = list(data.keys())

        for field in fields_to_decrypt:
            if field in result and result[field] is not None:
                value = result[field]
                if isinstance(value, str):
                    try:
                        decrypted = self.decrypt(value)
                        if field in json_fields:
                            result[field] = json.loads(decrypted)
                        else:
                            result[field] = decrypted
                    except DecryptionError:
                        # Field might not be encrypted, leave as-is
                        pass

        return result

    def rotate_key(
        self,
        new_key: bytes | str,
        ciphertext: str,
    ) -> str:
        """
        Re-encrypt data with a new key.

        Args:
            new_key: New encryption key.
            ciphertext: Data encrypted with current key.

        Returns:
            Data encrypted with new key.
        """
        # Decrypt with current key
        plaintext = self.decrypt(ciphertext)

        # Create new encryptor with new key
        new_encryptor = FieldEncryption(new_key, self._aad)

        # Encrypt with new key
        return new_encryptor.encrypt(plaintext)


class MultiKeyFieldEncryption:
    """
    Field encryption supporting multiple keys for key rotation.

    Maintains a primary key for encryption and a list of previous
    keys for decryption during rotation periods.

    Example:
        ```python
        encryptor = MultiKeyFieldEncryption(
            primary_key=current_key,
            previous_keys=[old_key_1, old_key_2],
        )

        # Always encrypts with primary key
        ciphertext = encryptor.encrypt("data")

        # Tries primary key first, then previous keys
        plaintext = encryptor.decrypt(ciphertext)
        ```
    """

    def __init__(
        self,
        primary_key: bytes | str,
        previous_keys: list[bytes | str] | None = None,
        associated_data: bytes | None = None,
    ):
        """
        Initialize multi-key encryption.

        Args:
            primary_key: Current key for encryption.
            previous_keys: Previous keys for decryption during rotation.
            associated_data: Optional AAD for authentication.
        """
        self._primary = FieldEncryption(primary_key, associated_data)
        self._previous = [FieldEncryption(k, associated_data) for k in (previous_keys or [])]

    def encrypt(self, plaintext: str | bytes) -> str:
        """Encrypt with primary key."""
        return self._primary.encrypt(plaintext)

    def decrypt(self, ciphertext: str) -> str:
        """
        Decrypt, trying primary key then previous keys.

        Args:
            ciphertext: Encrypted data.

        Returns:
            Decrypted plaintext.

        Raises:
            DecryptionError: If no key can decrypt the data.
        """
        # Try primary key first
        try:
            return self._primary.decrypt(ciphertext)
        except DecryptionError:
            pass

        # Try previous keys
        for encryptor in self._previous:
            try:
                return encryptor.decrypt(ciphertext)
            except DecryptionError:
                continue

        raise DecryptionError(
            "Failed to decrypt with primary key or any previous keys",
        )

    def encrypt_dict(
        self,
        data: dict[str, Any],
        fields_to_encrypt: list[str] | None = None,
    ) -> dict[str, Any]:
        """Encrypt dict fields with primary key."""
        return self._primary.encrypt_dict(data, fields_to_encrypt)

    def decrypt_dict(
        self,
        data: dict[str, Any],
        fields_to_decrypt: list[str] | None = None,
        json_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """Decrypt dict fields, trying all keys."""
        result = data.copy()
        json_fields = json_fields or []

        if fields_to_decrypt is None:
            fields_to_decrypt = list(data.keys())

        for field in fields_to_decrypt:
            if field in result and result[field] is not None:
                value = result[field]
                if isinstance(value, str):
                    try:
                        decrypted = self.decrypt(value)
                        if field in json_fields:
                            result[field] = json.loads(decrypted)
                        else:
                            result[field] = decrypted
                    except DecryptionError:
                        pass

        return result

    def re_encrypt_with_primary(self, ciphertext: str) -> str:
        """
        Re-encrypt data with the primary key.

        Useful for migrating data encrypted with old keys.

        Args:
            ciphertext: Data encrypted with any known key.

        Returns:
            Data encrypted with primary key.
        """
        plaintext = self.decrypt(ciphertext)
        return self._primary.encrypt(plaintext)
