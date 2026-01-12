"""
Tests for encryption module.

This module tests field encryption, key management,
and SQLAlchemy encrypted types.
"""

import base64
import json
import os
import tempfile
from pathlib import Path

import pytest

from services.shared.security.encryption import (
    DecryptionError,
    EncryptionError,
    EncryptionKeyManager,
    EnvironmentKeyProvider,
    FieldEncryption,
    FileKeyProvider,
)
from services.shared.security.encryption.field_encryption import (
    MultiKeyFieldEncryption,
)


class TestFieldEncryption:
    """Tests for FieldEncryption class."""

    @pytest.fixture
    def key(self):
        """Generate a test encryption key."""
        return FieldEncryption.generate_key()

    @pytest.fixture
    def encryptor(self, key):
        """Create an encryptor with test key."""
        return FieldEncryption(key)

    def test_generate_key(self):
        """Test key generation."""
        key = FieldEncryption.generate_key()
        assert len(key) == 32  # 256 bits
        assert isinstance(key, bytes)

    def test_key_uniqueness(self):
        """Test that generated keys are unique."""
        keys = [FieldEncryption.generate_key() for _ in range(100)]
        assert len(set(keys)) == 100

    def test_key_to_base64_roundtrip(self):
        """Test key serialization/deserialization."""
        key = FieldEncryption.generate_key()
        key_b64 = FieldEncryption.key_to_base64(key)
        restored = FieldEncryption.key_from_base64(key_b64)
        assert restored == key

    def test_encrypt_decrypt_string(self, encryptor):
        """Test basic string encryption/decryption."""
        plaintext = "Hello, World!"
        ciphertext = encryptor.encrypt(plaintext)
        decrypted = encryptor.decrypt(ciphertext)
        assert decrypted == plaintext

    def test_encrypt_produces_different_ciphertext(self, encryptor):
        """Test that same plaintext produces different ciphertext (nonce)."""
        plaintext = "Same text"
        ciphertexts = [encryptor.encrypt(plaintext) for _ in range(10)]
        # All ciphertexts should be different due to random nonce
        assert len(set(ciphertexts)) == 10

    def test_decrypt_with_wrong_key(self, key):
        """Test that wrong key fails decryption."""
        encryptor1 = FieldEncryption(key)
        encryptor2 = FieldEncryption(FieldEncryption.generate_key())

        ciphertext = encryptor1.encrypt("secret")

        with pytest.raises(DecryptionError):
            encryptor2.decrypt(ciphertext)

    def test_tampered_ciphertext_fails(self, encryptor):
        """Test that tampered ciphertext is rejected."""
        ciphertext = encryptor.encrypt("original")

        # Decode, tamper, re-encode
        decoded = base64.b64decode(ciphertext)
        tampered = bytes([decoded[0] ^ 0xFF]) + decoded[1:]
        tampered_b64 = base64.b64encode(tampered).decode()

        with pytest.raises(DecryptionError):
            encryptor.decrypt(tampered_b64)

    def test_unicode_content(self, encryptor):
        """Test encryption of unicode content."""
        unicode_text = "Hello 世界 🔒 Привет"
        ciphertext = encryptor.encrypt(unicode_text)
        decrypted = encryptor.decrypt(ciphertext)
        assert decrypted == unicode_text

    def test_empty_string(self, encryptor):
        """Test encryption of empty string."""
        ciphertext = encryptor.encrypt("")
        decrypted = encryptor.decrypt(ciphertext)
        assert decrypted == ""

    def test_long_content(self, encryptor):
        """Test encryption of long content."""
        long_text = "x" * 100000  # 100KB
        ciphertext = encryptor.encrypt(long_text)
        decrypted = encryptor.decrypt(ciphertext)
        assert decrypted == long_text

    def test_encrypt_bytes(self, encryptor):
        """Test byte encryption."""
        data = b"\x00\x01\x02\x03\xff\xfe\xfd"
        encrypted = encryptor.encrypt_bytes(data)
        decrypted = encryptor.decrypt_bytes(encrypted)
        assert decrypted == data

    def test_invalid_key_size(self):
        """Test that invalid key size raises error."""
        with pytest.raises(Exception):  # KeyError from encryption module
            FieldEncryption(b"too-short")

    def test_key_from_base64_string(self):
        """Test creating encryptor from base64 key string."""
        key = FieldEncryption.generate_key()
        key_b64 = FieldEncryption.key_to_base64(key)

        encryptor = FieldEncryption(key_b64)
        plaintext = "test"
        ciphertext = encryptor.encrypt(plaintext)
        decrypted = encryptor.decrypt(ciphertext)
        assert decrypted == plaintext

    def test_associated_data(self):
        """Test encryption with associated data (AAD)."""
        key = FieldEncryption.generate_key()
        aad = b"context-data"

        encryptor_with_aad = FieldEncryption(key, associated_data=aad)
        encryptor_without_aad = FieldEncryption(key)

        ciphertext = encryptor_with_aad.encrypt("secret")

        # Same AAD works
        decrypted = encryptor_with_aad.decrypt(ciphertext)
        assert decrypted == "secret"

        # Different/no AAD fails
        with pytest.raises(DecryptionError):
            encryptor_without_aad.decrypt(ciphertext)


class TestFieldEncryptionDict:
    """Tests for dictionary encryption."""

    @pytest.fixture
    def encryptor(self):
        """Create an encryptor."""
        return FieldEncryption(FieldEncryption.generate_key())

    def test_encrypt_dict_all_fields(self, encryptor):
        """Test encrypting all string fields in dict."""
        data = {
            "name": "John Doe",
            "ssn": "123-45-6789",
            "age": 30,  # Not encrypted (not a string)
        }

        encrypted = encryptor.encrypt_dict(data)

        # String fields should be encrypted (different from original)
        assert encrypted["name"] != data["name"]
        assert encrypted["ssn"] != data["ssn"]
        # Non-string fields unchanged
        assert encrypted["age"] == 30

    def test_encrypt_dict_specific_fields(self, encryptor):
        """Test encrypting specific fields only."""
        data = {
            "name": "John Doe",
            "ssn": "123-45-6789",
            "email": "john@example.com",
        }

        encrypted = encryptor.encrypt_dict(data, fields_to_encrypt=["ssn"])

        # Only ssn should be encrypted
        assert encrypted["name"] == data["name"]
        assert encrypted["ssn"] != data["ssn"]
        assert encrypted["email"] == data["email"]

    def test_decrypt_dict(self, encryptor):
        """Test decrypting dict fields."""
        data = {"name": "John", "ssn": "123-45-6789"}

        encrypted = encryptor.encrypt_dict(data)
        decrypted = encryptor.decrypt_dict(encrypted)

        assert decrypted["name"] == data["name"]
        assert decrypted["ssn"] == data["ssn"]

    def test_encrypt_dict_with_json(self, encryptor):
        """Test encrypting complex objects as JSON."""
        data = {
            "profile": {"address": "123 Main St", "phone": "555-1234"},
        }

        encrypted = encryptor.encrypt_dict(data, fields_to_encrypt=["profile"])
        decrypted = encryptor.decrypt_dict(
            encrypted,
            fields_to_decrypt=["profile"],
            json_fields=["profile"],
        )

        assert decrypted["profile"] == data["profile"]


class TestMultiKeyFieldEncryption:
    """Tests for multi-key encryption (key rotation)."""

    def test_encrypt_with_primary_key(self):
        """Test encryption uses primary key."""
        primary = FieldEncryption.generate_key()
        previous = FieldEncryption.generate_key()

        multi = MultiKeyFieldEncryption(primary, [previous])
        single_primary = FieldEncryption(primary)

        ciphertext = multi.encrypt("test")

        # Should be decryptable with just the primary key
        decrypted = single_primary.decrypt(ciphertext)
        assert decrypted == "test"

    def test_decrypt_with_previous_key(self):
        """Test decryption tries previous keys."""
        old_key = FieldEncryption.generate_key()
        new_key = FieldEncryption.generate_key()

        # Encrypt with old key
        old_encryptor = FieldEncryption(old_key)
        ciphertext = old_encryptor.encrypt("old data")

        # Decrypt with multi-key (new primary, old as previous)
        multi = MultiKeyFieldEncryption(new_key, [old_key])
        decrypted = multi.decrypt(ciphertext)

        assert decrypted == "old data"

    def test_re_encrypt_with_primary(self):
        """Test re-encrypting data with primary key."""
        old_key = FieldEncryption.generate_key()
        new_key = FieldEncryption.generate_key()

        # Encrypt with old key
        old_encryptor = FieldEncryption(old_key)
        old_ciphertext = old_encryptor.encrypt("migrate me")

        # Re-encrypt with new key
        multi = MultiKeyFieldEncryption(new_key, [old_key])
        new_ciphertext = multi.re_encrypt_with_primary(old_ciphertext)

        # Verify new ciphertext works with just new key
        new_encryptor = FieldEncryption(new_key)
        decrypted = new_encryptor.decrypt(new_ciphertext)
        assert decrypted == "migrate me"

    def test_decrypt_fails_with_unknown_key(self):
        """Test decryption fails if no key works."""
        key1 = FieldEncryption.generate_key()
        key2 = FieldEncryption.generate_key()
        key3 = FieldEncryption.generate_key()

        encryptor = FieldEncryption(key1)
        ciphertext = encryptor.encrypt("secret")

        # key1 is not in multi's keys
        multi = MultiKeyFieldEncryption(key2, [key3])

        with pytest.raises(DecryptionError):
            multi.decrypt(ciphertext)


class TestEnvironmentKeyProvider:
    """Tests for environment-based key provider."""

    def test_get_set_key(self):
        """Test getting and setting keys via environment."""
        provider = EnvironmentKeyProvider(prefix="TEST")

        key = FieldEncryption.generate_key()
        provider.set_key("encryption", key)

        retrieved = provider.get_key("encryption")
        assert retrieved == key

        # Cleanup
        provider.delete_key("encryption")

    def test_get_nonexistent_key(self):
        """Test getting a key that doesn't exist."""
        provider = EnvironmentKeyProvider(prefix="NONEXISTENT")
        assert provider.get_key("missing") is None


class TestFileKeyProvider:
    """Tests for file-based key provider."""

    def test_get_set_key(self):
        """Test getting and setting keys via files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = FileKeyProvider(tmpdir)

            key = FieldEncryption.generate_key()
            provider.set_key("test-key", key)

            retrieved = provider.get_key("test-key")
            assert retrieved == key

            # Check file permissions (Unix only)
            key_path = Path(tmpdir) / "test-key.key"
            if os.name != "nt":  # Not Windows
                assert key_path.stat().st_mode & 0o777 == 0o600

    def test_list_keys(self):
        """Test listing keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = FileKeyProvider(tmpdir)

            provider.set_key("key1", FieldEncryption.generate_key())
            provider.set_key("key2", FieldEncryption.generate_key())

            keys = provider.list_keys()
            assert "key1" in keys
            assert "key2" in keys

    def test_delete_key(self):
        """Test deleting a key."""
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = FileKeyProvider(tmpdir)

            provider.set_key("to-delete", FieldEncryption.generate_key())
            provider.delete_key("to-delete")

            assert provider.get_key("to-delete") is None


class TestEncryptionKeyManager:
    """Tests for the key manager."""

    def test_get_or_create_key(self):
        """Test automatic key generation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = FileKeyProvider(tmpdir)
            manager = EncryptionKeyManager(provider)

            # First call creates key
            key1 = manager.get_or_create_key("new-key")
            assert key1 is not None
            assert len(key1) == 32

            # Second call returns same key
            key2 = manager.get_or_create_key("new-key")
            assert key2 == key1

    def test_rotate_key(self):
        """Test key rotation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = FileKeyProvider(tmpdir)
            manager = EncryptionKeyManager(provider)

            # Create initial key
            original = manager.get_or_create_key("rotate-me")

            # Rotate
            new_key, old_key = manager.rotate_key("rotate-me")

            # Old key should be stored
            assert old_key == original
            assert manager.get_previous_key("rotate-me") == original

            # New key should be different
            assert new_key != original
            assert manager.get_key("rotate-me") == new_key

    def test_caching(self):
        """Test key caching."""
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = FileKeyProvider(tmpdir)
            manager = EncryptionKeyManager(provider, cache_keys=True)

            key = manager.get_or_create_key("cached")

            # Delete from provider
            provider.delete_key("cached")

            # Should still get from cache
            cached = manager.get_key("cached")
            assert cached == key

            # Clear cache
            manager.clear_cache()
            assert manager.get_key("cached") is None


class TestEncryptionIntegration:
    """Integration tests for encryption workflow."""

    def test_full_encryption_workflow(self):
        """Test complete encryption workflow with key management."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Setup key manager
            provider = FileKeyProvider(tmpdir)
            manager = EncryptionKeyManager(provider)

            # Get encryption key
            key = manager.get_or_create_key("field-encryption")

            # Create encryptor
            encryptor = FieldEncryption(key)

            # Encrypt sensitive data
            user_data = {
                "name": "John Doe",
                "ssn": "123-45-6789",
                "email": "john@example.com",
            }

            encrypted = encryptor.encrypt_dict(
                user_data,
                fields_to_encrypt=["ssn"],
            )

            # Verify encryption
            assert encrypted["ssn"] != user_data["ssn"]
            assert encrypted["name"] == user_data["name"]

            # Decrypt
            decrypted = encryptor.decrypt_dict(
                encrypted,
                fields_to_decrypt=["ssn"],
            )
            assert decrypted["ssn"] == user_data["ssn"]

    def test_key_rotation_workflow(self):
        """Test key rotation with data migration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            provider = FileKeyProvider(tmpdir)
            manager = EncryptionKeyManager(provider)

            # Initial encryption
            old_key = manager.get_or_create_key("rotate-test")
            old_encryptor = FieldEncryption(old_key)
            ciphertext = old_encryptor.encrypt("sensitive")

            # Rotate key
            new_key, _ = manager.rotate_key("rotate-test")
            previous_key = manager.get_previous_key("rotate-test")

            # Create multi-key encryptor for migration
            multi = MultiKeyFieldEncryption(new_key, [previous_key])

            # Can still decrypt old data
            decrypted = multi.decrypt(ciphertext)
            assert decrypted == "sensitive"

            # Re-encrypt with new key
            new_ciphertext = multi.re_encrypt_with_primary(ciphertext)

            # Verify with new key only
            new_encryptor = FieldEncryption(new_key)
            assert new_encryptor.decrypt(new_ciphertext) == "sensitive"
