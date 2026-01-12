"""
TLS/SSL configuration for secure communication.

This module provides SSL context configuration for TLS 1.3 enforcement,
mTLS support, and integration with various services.
"""

import logging
import ssl
from enum import Enum

from pydantic import Field
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class TLSMode(str, Enum):
    """TLS operation mode."""

    DISABLED = "disabled"  # No TLS
    OPTIONAL = "optional"  # TLS if available
    REQUIRED = "required"  # TLS required
    MTLS = "mtls"  # Mutual TLS required


class TLSSettings(BaseSettings):
    """
    TLS configuration settings.

    Can be configured via environment variables with TLS_ prefix.
    """

    mode: TLSMode = Field(
        default=TLSMode.OPTIONAL,
        description="TLS operation mode",
    )

    # Certificate paths
    cert_file: str | None = Field(
        default=None,
        alias="TLS_CERT_FILE",
        description="Path to certificate file (PEM)",
    )
    key_file: str | None = Field(
        default=None,
        alias="TLS_KEY_FILE",
        description="Path to private key file (PEM)",
    )
    ca_file: str | None = Field(
        default=None,
        alias="TLS_CA_FILE",
        description="Path to CA certificate file (for verification)",
    )
    ca_path: str | None = Field(
        default=None,
        alias="TLS_CA_PATH",
        description="Path to directory of CA certificates",
    )

    # TLS version constraints
    min_version: str = Field(
        default="TLSv1.2",
        description="Minimum TLS version (TLSv1.2 or TLSv1.3)",
    )
    prefer_tls13: bool = Field(
        default=True,
        description="Prefer TLS 1.3 when available",
    )

    # Cipher configuration
    ciphers: str | None = Field(
        default=None,
        description="Cipher suite string (OpenSSL format)",
    )

    # Hostname verification
    verify_hostname: bool = Field(
        default=True,
        description="Verify server hostname matches certificate",
    )
    verify_cert: bool = Field(
        default=True,
        description="Verify server certificate",
    )

    # Client certificate (for mTLS)
    client_cert_file: str | None = Field(
        default=None,
        alias="TLS_CLIENT_CERT_FILE",
        description="Path to client certificate for mTLS",
    )
    client_key_file: str | None = Field(
        default=None,
        alias="TLS_CLIENT_KEY_FILE",
        description="Path to client private key for mTLS",
    )

    model_config = {"env_prefix": "TLS_", "extra": "ignore"}

    @property
    def is_enabled(self) -> bool:
        """Check if TLS is enabled."""
        return self.mode != TLSMode.DISABLED

    @property
    def requires_mtls(self) -> bool:
        """Check if mutual TLS is required."""
        return self.mode == TLSMode.MTLS


# Strong cipher suites for TLS 1.2 and 1.3
DEFAULT_CIPHERS = (
    # TLS 1.3 ciphers (automatically selected)
    "TLS_AES_256_GCM_SHA384:"
    "TLS_CHACHA20_POLY1305_SHA256:"
    "TLS_AES_128_GCM_SHA256:"
    # TLS 1.2 ciphers (ECDHE for forward secrecy)
    "ECDHE-ECDSA-AES256-GCM-SHA384:"
    "ECDHE-RSA-AES256-GCM-SHA384:"
    "ECDHE-ECDSA-CHACHA20-POLY1305:"
    "ECDHE-RSA-CHACHA20-POLY1305:"
    "ECDHE-ECDSA-AES128-GCM-SHA256:"
    "ECDHE-RSA-AES128-GCM-SHA256"
)


def _get_ssl_version(version_str: str) -> int:
    """Convert version string to ssl constant."""
    versions = {
        "TLSv1.2": ssl.TLSVersion.TLSv1_2,
        "TLSv1.3": ssl.TLSVersion.TLSv1_3,
    }
    return versions.get(version_str, ssl.TLSVersion.TLSv1_2)


def create_server_ssl_context(
    settings: TLSSettings | None = None,
    cert_file: str | None = None,
    key_file: str | None = None,
    ca_file: str | None = None,
    require_client_cert: bool = False,
) -> ssl.SSLContext | None:
    """
    Create SSL context for server-side TLS.

    Args:
        settings: TLS settings (optional, creates from env if None).
        cert_file: Override certificate file path.
        key_file: Override private key file path.
        ca_file: Override CA file path (for client verification).
        require_client_cert: Require client certificate (mTLS).

    Returns:
        SSLContext configured for server use, or None if disabled.

    Example:
        ```python
        from services.shared.security.tls import create_server_ssl_context

        ssl_context = create_server_ssl_context(
            cert_file="/etc/certs/server.crt",
            key_file="/etc/certs/server.key",
        )

        # Use with uvicorn
        uvicorn.run(app, ssl=ssl_context)
        ```
    """
    settings = settings or TLSSettings()

    if not settings.is_enabled:
        return None

    # Get certificate paths
    cert = cert_file or settings.cert_file
    key = key_file or settings.key_file

    if not cert or not key:
        logger.warning(
            "TLS enabled but no certificate/key provided. "
            "Set TLS_CERT_FILE and TLS_KEY_FILE.",
        )
        return None

    # Create context
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)

    # Set minimum TLS version
    context.minimum_version = _get_ssl_version(settings.min_version)

    # Prefer TLS 1.3 if requested
    if settings.prefer_tls13:
        try:
            context.minimum_version = ssl.TLSVersion.TLSv1_3
        except AttributeError:
            # TLS 1.3 not available in this Python version
            pass

    # Set cipher suites
    ciphers = settings.ciphers or DEFAULT_CIPHERS
    context.set_ciphers(ciphers)

    # Load server certificate
    try:
        context.load_cert_chain(cert, key)
        logger.info(f"Loaded server certificate from {cert}")
    except Exception as e:
        logger.error(f"Failed to load server certificate: {e}")
        raise

    # Configure client certificate verification for mTLS
    if require_client_cert or settings.requires_mtls:
        ca = ca_file or settings.ca_file
        if ca:
            context.verify_mode = ssl.CERT_REQUIRED
            context.load_verify_locations(ca)
            logger.info(f"Configured mTLS with CA from {ca}")
        else:
            logger.warning("mTLS requested but no CA file provided")

    return context


def create_client_ssl_context(
    settings: TLSSettings | None = None,
    ca_file: str | None = None,
    client_cert_file: str | None = None,
    client_key_file: str | None = None,
    verify: bool = True,
    check_hostname: bool = True,
) -> ssl.SSLContext | None:
    """
    Create SSL context for client-side TLS.

    Args:
        settings: TLS settings.
        ca_file: CA certificate file for server verification.
        client_cert_file: Client certificate for mTLS.
        client_key_file: Client private key for mTLS.
        verify: Whether to verify server certificate.
        check_hostname: Whether to verify server hostname.

    Returns:
        SSLContext configured for client use, or None if disabled.

    Example:
        ```python
        import httpx
        from services.shared.security.tls import create_client_ssl_context

        ssl_context = create_client_ssl_context(
            ca_file="/etc/certs/ca.crt",
        )

        async with httpx.AsyncClient(verify=ssl_context) as client:
            response = await client.get("https://api.example.com")
        ```
    """
    settings = settings or TLSSettings()

    if not settings.is_enabled:
        return None

    # Create context
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)

    # Set minimum TLS version
    context.minimum_version = _get_ssl_version(settings.min_version)

    # Set cipher suites
    ciphers = settings.ciphers or DEFAULT_CIPHERS
    context.set_ciphers(ciphers)

    # Configure verification
    if verify and settings.verify_cert:
        context.verify_mode = ssl.CERT_REQUIRED
        context.check_hostname = check_hostname and settings.verify_hostname

        # Load CA certificates
        ca = ca_file or settings.ca_file
        if ca:
            context.load_verify_locations(ca)
        elif settings.ca_path:
            context.load_verify_locations(capath=settings.ca_path)
        else:
            # Use system CA certificates
            context.load_default_certs()
    else:
        context.verify_mode = ssl.CERT_NONE
        context.check_hostname = False

    # Load client certificate for mTLS
    client_cert = client_cert_file or settings.client_cert_file
    client_key = client_key_file or settings.client_key_file

    if client_cert and client_key:
        context.load_cert_chain(client_cert, client_key)
        logger.info("Loaded client certificate for mTLS")

    return context


def create_postgres_ssl_context(
    settings: TLSSettings | None = None,
    ca_file: str | None = None,
    client_cert_file: str | None = None,
    client_key_file: str | None = None,
) -> ssl.SSLContext | None:
    """
    Create SSL context for PostgreSQL connections.

    Args:
        settings: TLS settings.
        ca_file: CA certificate file.
        client_cert_file: Client certificate for mTLS.
        client_key_file: Client private key for mTLS.

    Returns:
        SSLContext for PostgreSQL, or None if disabled.

    Example:
        ```python
        from services.shared.security.tls import create_postgres_ssl_context
        from sqlalchemy.ext.asyncio import create_async_engine

        ssl_context = create_postgres_ssl_context(
            ca_file="/etc/certs/postgres-ca.crt",
        )

        engine = create_async_engine(
            database_url,
            connect_args={"ssl": ssl_context},
        )
        ```
    """
    return create_client_ssl_context(
        settings=settings,
        ca_file=ca_file,
        client_cert_file=client_cert_file,
        client_key_file=client_key_file,
        verify=True,
        check_hostname=True,
    )


def create_redis_ssl_context(
    settings: TLSSettings | None = None,
    ca_file: str | None = None,
    client_cert_file: str | None = None,
    client_key_file: str | None = None,
) -> ssl.SSLContext | None:
    """
    Create SSL context for Redis connections.

    Args:
        settings: TLS settings.
        ca_file: CA certificate file.
        client_cert_file: Client certificate for mTLS.
        client_key_file: Client private key for mTLS.

    Returns:
        SSLContext for Redis, or None if disabled.

    Example:
        ```python
        from redis.asyncio import Redis
        from services.shared.security.tls import create_redis_ssl_context

        ssl_context = create_redis_ssl_context()

        redis = Redis(
            host="redis.example.com",
            port=6379,
            ssl=ssl_context,
        )
        ```
    """
    return create_client_ssl_context(
        settings=settings,
        ca_file=ca_file,
        client_cert_file=client_cert_file,
        client_key_file=client_key_file,
        verify=True,
        # Redis often uses IP addresses
        check_hostname=settings.verify_hostname if settings else True,
    )


def get_ssl_info(ssl_object) -> dict:
    """
    Get information about an SSL connection.

    Args:
        ssl_object: SSL socket or SSLObject.

    Returns:
        Dict with SSL connection details.
    """
    try:
        cipher = ssl_object.cipher()
        return {
            "version": ssl_object.version(),
            "cipher_name": cipher[0] if cipher else None,
            "cipher_bits": cipher[2] if cipher else None,
            "server_hostname": getattr(ssl_object, "server_hostname", None),
        }
    except Exception as e:
        return {"error": str(e)}
