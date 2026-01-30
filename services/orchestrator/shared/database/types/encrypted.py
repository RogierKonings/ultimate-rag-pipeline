"""
SQLAlchemy encrypted column types.

This module provides custom SQLAlchemy types that automatically
encrypt/decrypt data when storing/retrieving from the database.
"""

import json
import logging

from sqlalchemy import Text, TypeDecorator

logger = logging.getLogger(__name__)

# Module-level encryption instance
_field_encryption = None


def configure_encryption(encryption_instance) -> None:
    """
    Configure the encryption instance for encrypted types.

    Must be called before using encrypted column types.

    Args:
        encryption_instance: FieldEncryption or MultiKeyFieldEncryption instance.

    Example:
        ```python
        from shared.security.encryption import FieldEncryption
        from shared.database.types import configure_encryption

        key = FieldEncryption.generate_key()
        encryptor = FieldEncryption(key)
        configure_encryption(encryptor)
        ```
    """
    global _field_encryption
    _field_encryption = encryption_instance
    logger.info("Configured database field encryption")


def get_field_encryption():
    """Get the configured encryption instance."""
    if _field_encryption is None:
        raise RuntimeError(
            "Encryption not configured. Call configure_encryption() first.",
        )
    return _field_encryption


class EncryptedString(TypeDecorator):
    """
    SQLAlchemy type for encrypted string columns.

    Automatically encrypts values when storing and decrypts when
    retrieving. Stores ciphertext as Text in the database.

    Example:
        ```python
        from sqlalchemy import Column
        from shared.database.types import EncryptedString

        class User(Base):
            __tablename__ = "users"

            id = Column(Integer, primary_key=True)
            ssn = Column(EncryptedString(length=100))  # Encrypted at rest
        ```
    """

    impl = Text
    cache_ok = True

    def __init__(self, length: int | None = None, **kwargs):
        """
        Initialize encrypted string type.

        Args:
            length: Optional original string length (for documentation).
            **kwargs: Additional TypeDecorator arguments.
        """
        super().__init__(**kwargs)
        self.length = length

    def process_bind_param(self, value: str | None, dialect) -> str | None:
        """Encrypt value before storing in database."""
        if value is None:
            return None

        if not isinstance(value, str):
            value = str(value)

        try:
            encryption = get_field_encryption()
            return encryption.encrypt(value)
        except RuntimeError:
            # Encryption not configured, store as-is (for migrations, etc.)
            logger.warning(
                "Encryption not configured, storing value unencrypted",
            )
            return value

    def process_result_value(self, value: str | None, dialect) -> str | None:
        """Decrypt value when retrieving from database."""
        if value is None:
            return None

        try:
            encryption = get_field_encryption()
            return encryption.decrypt(value)
        except RuntimeError:
            # Encryption not configured
            logger.warning("Encryption not configured, returning raw value")
            return value
        except Exception as e:
            # Decryption failed - might be unencrypted legacy data
            logger.warning(f"Decryption failed, returning raw value: {e}")
            return value


class EncryptedText(EncryptedString):
    """
    Alias for EncryptedString for longer text content.

    Same as EncryptedString but semantically indicates larger content.
    """


class EncryptedJSON(TypeDecorator):
    """
    SQLAlchemy type for encrypted JSON columns.

    Serializes JSON data, encrypts it, and stores as Text.
    On retrieval, decrypts and deserializes back to Python objects.

    Example:
        ```python
        from sqlalchemy import Column
        from shared.database.types import EncryptedJSON

        class UserProfile(Base):
            __tablename__ = "user_profiles"

            id = Column(Integer, primary_key=True)
            sensitive_data = Column(EncryptedJSON)  # Dict/list encrypted at rest
        ```
    """

    impl = Text
    cache_ok = True

    def process_bind_param(
        self,
        value: dict | list | None,
        dialect,
    ) -> str | None:
        """Serialize and encrypt JSON value before storing."""
        if value is None:
            return None

        try:
            # Serialize to JSON
            json_str = json.dumps(value, default=str)

            # Encrypt
            try:
                encryption = get_field_encryption()
                return encryption.encrypt(json_str)
            except RuntimeError:
                logger.warning(
                    "Encryption not configured, storing JSON unencrypted",
                )
                return json_str

        except Exception as e:
            logger.error(f"Failed to serialize/encrypt JSON: {e}")
            raise

    def process_result_value(
        self,
        value: str | None,
        dialect,
    ) -> dict | list | None:
        """Decrypt and deserialize JSON value when retrieving."""
        if value is None:
            return None

        try:
            # Try to decrypt
            try:
                encryption = get_field_encryption()
                json_str = encryption.decrypt(value)
            except RuntimeError:
                # Not configured
                json_str = value
            except Exception:
                # Might be unencrypted legacy data
                json_str = value

            # Deserialize JSON
            return json.loads(json_str)

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON: {e}")
            # Return raw string if JSON parsing fails
            return value
        except Exception as e:
            logger.error(f"Failed to decrypt/deserialize JSON: {e}")
            return value


class EncryptedBytes(TypeDecorator):
    """
    SQLAlchemy type for encrypted binary data.

    Encrypts binary data and stores as base64-encoded Text.
    """

    impl = Text
    cache_ok = True

    def process_bind_param(
        self,
        value: bytes | None,
        dialect,
    ) -> str | None:
        """Encrypt bytes and encode as base64 for storage."""
        if value is None:
            return None

        import base64

        try:
            encryption = get_field_encryption()
            # Use bytes encryption
            encrypted = encryption.encrypt_bytes(value)
            return base64.b64encode(encrypted).decode("utf-8")
        except RuntimeError:
            # Not configured, store as base64
            return base64.b64encode(value).decode("utf-8")

    def process_result_value(
        self,
        value: str | None,
        dialect,
    ) -> bytes | None:
        """Decode base64 and decrypt bytes."""
        if value is None:
            return None

        import base64

        try:
            decoded = base64.b64decode(value)

            try:
                encryption = get_field_encryption()
                return encryption.decrypt_bytes(decoded)
            except RuntimeError:
                # Not configured
                return decoded
            except Exception:
                # Might be unencrypted legacy data
                return decoded

        except Exception as e:
            logger.error(f"Failed to decode/decrypt bytes: {e}")
            return value.encode("utf-8") if isinstance(value, str) else value
