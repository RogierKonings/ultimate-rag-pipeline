#!/usr/bin/env python3
"""
Initialize MinIO buckets with lifecycle policies.

This script creates the required buckets for the RAG pipeline:
- documents: Primary storage for raw documents (no expiration)
- temp-uploads: Temporary upload staging (expires after 1 day)
- backups: Database and system backups (expires after 30 days)

Usage:
    python scripts/init-minio-buckets.py

Environment Variables:
    MINIO_ENDPOINT: MinIO server endpoint (default: localhost:9000)
    MINIO_ACCESS_KEY: Access key (default: minioadmin)
    MINIO_SECRET_KEY: Secret key (default: minioadmin123)
"""

from minio import Minio
from minio.error import S3Error
from minio.lifecycleconfig import LifecycleConfig, Rule, Expiration
from minio.commonconfig import Filter
import os
import sys

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin123")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"

# Bucket configurations
BUCKETS = [
    {
        "name": "documents",
        "policy": "private",
        "lifecycle_days": None,  # No expiration for primary documents
    },
    {
        "name": "temp-uploads",
        "policy": "private",
        "lifecycle_days": 1,  # Expire after 1 day
    },
    {
        "name": "backups",
        "policy": "private",
        "lifecycle_days": 30,  # Expire after 30 days
    },
]


def create_lifecycle_config(days: int) -> LifecycleConfig:
    """Create a lifecycle configuration with expiration rule."""
    return LifecycleConfig(
        [
            Rule(
                "Enabled",
                rule_filter=Filter(prefix=""),
                rule_id="expire-rule",
                expiration=Expiration(days=days),
            )
        ]
    )


def init_buckets() -> bool:
    """
    Initialize all required buckets.

    Returns:
        True if all buckets were created/verified successfully
    """
    print(f"Connecting to MinIO at {MINIO_ENDPOINT}...")

    try:
        client = Minio(
            MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=MINIO_SECURE,
        )

        # Verify connection
        client.list_buckets()
        print("✓ Connected to MinIO successfully")

    except Exception as e:
        print(f"✗ Failed to connect to MinIO: {e}")
        return False

    success = True

    for bucket_config in BUCKETS:
        bucket_name = bucket_config["name"]
        lifecycle_days = bucket_config["lifecycle_days"]

        try:
            # Create bucket if it doesn't exist
            if not client.bucket_exists(bucket_name):
                client.make_bucket(bucket_name)
                print(f"✓ Created bucket: {bucket_name}")
            else:
                print(f"○ Bucket already exists: {bucket_name}")

            # Set lifecycle policy if specified
            if lifecycle_days:
                lifecycle_config = create_lifecycle_config(lifecycle_days)
                client.set_bucket_lifecycle(bucket_name, lifecycle_config)
                print(f"  ↳ Lifecycle policy set: expire after {lifecycle_days} day(s)")

        except S3Error as e:
            print(f"✗ Error with bucket {bucket_name}: {e}")
            success = False

    return success


def main():
    """Main entry point."""
    print("=" * 50)
    print("MinIO Bucket Initialization")
    print("=" * 50)
    print()

    if init_buckets():
        print()
        print("=" * 50)
        print("✓ All buckets initialized successfully!")
        print("=" * 50)
        sys.exit(0)
    else:
        print()
        print("=" * 50)
        print("✗ Some buckets failed to initialize")
        print("=" * 50)
        sys.exit(1)


if __name__ == "__main__":
    main()
