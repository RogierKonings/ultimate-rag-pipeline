#!/usr/bin/env python3
"""
Audit Log Export Script.

Exports audit logs from the database with optional filtering and hash chain validation.
Supports JSON and CSV output formats.

Usage:
    python scripts/export-audit-logs.py --start-date 2024-01-01 --end-date 2024-01-31 --output audit-export.json
    python scripts/export-audit-logs.py --tenant-id <uuid> --format csv --output audit-export.csv
    python scripts/export-audit-logs.py --validate-chain --start-id <uuid>

Requirements:
    - Database connection configured via environment variables
    - User must have audit:export permission
"""

import argparse
import asyncio
import csv
import hashlib
import json
import os
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent.parent))


async def get_database_session():
    """Get database session."""
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker

    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://raguser:ragpassword@localhost:5432/ragpipeline",
    )

    engine = create_async_engine(database_url, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    return async_session()


async def fetch_audit_logs(
    session,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    tenant_id: UUID | None = None,
    user_id: UUID | None = None,
    action: str | None = None,
    limit: int = 10000,
    offset: int = 0,
) -> list[dict]:
    """Fetch audit logs from database with filters."""
    from sqlalchemy import and_, select

    try:
        from services.shared.database.models.audit_log import AuditLog
    except ImportError:
        # Fallback for when running standalone
        print("Warning: Could not import AuditLog model, using raw SQL")
        return await fetch_audit_logs_raw(
            session,
            start_date,
            end_date,
            tenant_id,
            user_id,
            action,
            limit,
            offset,
        )

    conditions = []

    if start_date:
        conditions.append(AuditLog.timestamp >= start_date)
    if end_date:
        conditions.append(AuditLog.timestamp <= end_date)
    if tenant_id:
        conditions.append(AuditLog.tenant_id == tenant_id)
    if user_id:
        conditions.append(AuditLog.user_id == user_id)
    if action:
        conditions.append(AuditLog.action == action)

    query = select(AuditLog)
    if conditions:
        query = query.where(and_(*conditions))

    query = query.order_by(AuditLog.timestamp.asc()).limit(limit).offset(offset)

    result = await session.execute(query)
    logs = result.scalars().all()

    return [
        {
            "id": str(log.id),
            "trace_id": log.trace_id,
            "timestamp": log.timestamp.isoformat() if log.timestamp else None,
            "user_id": str(log.user_id) if log.user_id else None,
            "tenant_id": str(log.tenant_id) if log.tenant_id else None,
            "action": log.action,
            "outcome": log.outcome,
            "severity": log.severity,
            "resource_type": log.resource_type,
            "resource_id": log.resource_id,
            "client_ip": log.client_ip,
            "user_agent": log.user_agent,
            "request_path": log.request_path,
            "request_method": log.request_method,
            "response_status": log.response_status,
            "error_message": log.error_message,
            "details": log.details,
            "previous_hash": log.previous_hash,
            "entry_hash": log.entry_hash,
        }
        for log in logs
    ]


async def fetch_audit_logs_raw(
    session,
    start_date: datetime | None = None,
    end_date: datetime | None = None,
    tenant_id: UUID | None = None,
    user_id: UUID | None = None,
    action: str | None = None,
    limit: int = 10000,
    offset: int = 0,
) -> list[dict]:
    """Fetch audit logs using raw SQL (fallback)."""
    from sqlalchemy import text

    conditions = ["1=1"]
    params = {"limit": limit, "offset": offset}

    if start_date:
        conditions.append("timestamp >= :start_date")
        params["start_date"] = start_date
    if end_date:
        conditions.append("timestamp <= :end_date")
        params["end_date"] = end_date
    if tenant_id:
        conditions.append("tenant_id = :tenant_id")
        params["tenant_id"] = str(tenant_id)
    if user_id:
        conditions.append("user_id = :user_id")
        params["user_id"] = str(user_id)
    if action:
        conditions.append("action = :action")
        params["action"] = action

    query = text(
        f"""
        SELECT * FROM audit_logs
        WHERE {" AND ".join(conditions)}
        ORDER BY timestamp ASC
        LIMIT :limit OFFSET :offset
    """,
    )

    result = await session.execute(query, params)
    rows = result.fetchall()

    return [dict(row._mapping) for row in rows]


def compute_hash(entry: dict, previous_hash: str | None = None) -> str:
    """Compute SHA-256 hash of an audit entry."""
    hash_input = json.dumps(
        {
            "id": entry.get("id"),
            "timestamp": entry.get("timestamp"),
            "user_id": entry.get("user_id"),
            "tenant_id": entry.get("tenant_id"),
            "action": entry.get("action"),
            "outcome": entry.get("outcome"),
            "resource_type": entry.get("resource_type"),
            "resource_id": entry.get("resource_id"),
            "previous_hash": previous_hash,
        },
        sort_keys=True,
    )

    return hashlib.sha256(hash_input.encode()).hexdigest()


async def validate_hash_chain(
    session,
    start_id: UUID | None = None,
    limit: int = 1000,
) -> tuple[bool, str | None, int]:
    """
    Validate the hash chain of audit logs.

    Returns:
        Tuple of (is_valid, error_message, entries_validated)
    """
    from sqlalchemy import select, text

    try:
        from services.shared.database.models.audit_log import AuditLog

        query = select(AuditLog).order_by(AuditLog.timestamp.asc()).limit(limit)
        if start_id:
            query = query.where(AuditLog.id >= start_id)

        result = await session.execute(query)
        logs = result.scalars().all()
    except ImportError:
        # Fallback to raw SQL
        sql = text(
            """
            SELECT * FROM audit_logs
            ORDER BY timestamp ASC
            LIMIT :limit
        """,
        )
        result = await session.execute(sql, {"limit": limit})
        logs = [dict(row._mapping) for row in result.fetchall()]

    if not logs:
        return True, None, 0

    previous_hash = None
    entries_validated = 0

    for log in logs:
        if hasattr(log, "__dict__"):
            entry = {
                "id": str(log.id),
                "timestamp": log.timestamp.isoformat() if log.timestamp else None,
                "user_id": str(log.user_id) if log.user_id else None,
                "tenant_id": str(log.tenant_id) if log.tenant_id else None,
                "action": log.action,
                "outcome": log.outcome,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "previous_hash": log.previous_hash,
                "entry_hash": log.entry_hash,
            }
        else:
            entry = log

        stored_previous = entry.get("previous_hash")
        stored_hash = entry.get("entry_hash")

        # Validate previous hash matches
        if previous_hash is not None and stored_previous != previous_hash:
            return (
                False,
                f"Hash chain broken at entry {entry['id']}: "
                f"expected previous_hash {previous_hash}, found {stored_previous}",
                entries_validated,
            )

        # Validate entry hash
        expected_hash = compute_hash(entry, stored_previous)
        if stored_hash and stored_hash != expected_hash:
            return (
                False,
                f"Hash mismatch at entry {entry['id']}: "
                f"expected {expected_hash}, found {stored_hash}",
                entries_validated,
            )

        previous_hash = stored_hash
        entries_validated += 1

    return True, None, entries_validated


def export_to_json(logs: list[dict], output_path: Path) -> None:
    """Export logs to JSON format."""
    export_data = {
        "metadata": {
            "exported_at": datetime.now(tz=UTC).isoformat(),
            "total_entries": len(logs),
            "format_version": "1.0",
        },
        "audit_logs": logs,
    }

    with open(output_path, "w") as f:
        json.dump(export_data, f, indent=2, default=str)


def export_to_csv(logs: list[dict], output_path: Path) -> None:
    """Export logs to CSV format."""
    if not logs:
        print("No logs to export")
        return

    fieldnames = [
        "id",
        "trace_id",
        "timestamp",
        "user_id",
        "tenant_id",
        "action",
        "outcome",
        "severity",
        "resource_type",
        "resource_id",
        "client_ip",
        "request_path",
        "request_method",
        "response_status",
        "error_message",
        "previous_hash",
        "entry_hash",
    ]

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(logs)


def parse_date(date_str: str) -> datetime:
    """Parse date string to datetime."""
    formats = [
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%d %H:%M:%S",
    ]

    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue

    raise ValueError(f"Could not parse date: {date_str}")


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Export audit logs from the RAG Pipeline database",
    )

    parser.add_argument(
        "--start-date",
        type=str,
        help="Start date for export (YYYY-MM-DD or ISO format)",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        help="End date for export (YYYY-MM-DD or ISO format)",
    )
    parser.add_argument(
        "--tenant-id",
        type=str,
        help="Filter by tenant ID (UUID)",
    )
    parser.add_argument(
        "--user-id",
        type=str,
        help="Filter by user ID (UUID)",
    )
    parser.add_argument(
        "--action",
        type=str,
        help="Filter by action (e.g., auth.login, document.read)",
    )
    parser.add_argument(
        "--format",
        choices=["json", "csv"],
        default="json",
        help="Output format (default: json)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output file path",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10000,
        help="Maximum number of records to export (default: 10000)",
    )
    parser.add_argument(
        "--validate-chain",
        action="store_true",
        help="Validate hash chain integrity instead of exporting",
    )
    parser.add_argument(
        "--start-id",
        type=str,
        help="Start validation from this entry ID",
    )
    parser.add_argument(
        "--last-days",
        type=int,
        help="Export logs from the last N days",
    )

    args = parser.parse_args()

    # Handle date shortcuts
    if args.last_days:
        args.end_date = datetime.now(tz=UTC).isoformat()
        args.start_date = (datetime.now(tz=UTC) - timedelta(days=args.last_days)).isoformat()

    print("Connecting to database...")
    session = await get_database_session()

    try:
        if args.validate_chain:
            print("Validating hash chain...")
            start_id = UUID(args.start_id) if args.start_id else None
            is_valid, error, count = await validate_hash_chain(
                session,
                start_id,
                args.limit,
            )

            if is_valid:
                print(f"Hash chain is valid. Validated {count} entries.")
                sys.exit(0)
            else:
                print(f"Hash chain validation FAILED: {error}")
                print(f"Validated {count} entries before failure.")
                sys.exit(1)

        # Parse dates
        start_date = parse_date(args.start_date) if args.start_date else None
        end_date = parse_date(args.end_date) if args.end_date else None
        tenant_id = UUID(args.tenant_id) if args.tenant_id else None
        user_id = UUID(args.user_id) if args.user_id else None

        print("Fetching audit logs...")
        logs = await fetch_audit_logs(
            session,
            start_date=start_date,
            end_date=end_date,
            tenant_id=tenant_id,
            user_id=user_id,
            action=args.action,
            limit=args.limit,
        )

        print(f"Found {len(logs)} audit log entries")

        if not logs:
            print("No logs match the specified criteria")
            sys.exit(0)

        # Determine output path
        if args.output:
            output_path = args.output
        else:
            timestamp = datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")
            output_path = Path(f"audit-export-{timestamp}.{args.format}")

        # Export
        if args.format == "json":
            export_to_json(logs, output_path)
        else:
            export_to_csv(logs, output_path)

        print(f"Exported {len(logs)} entries to {output_path}")

        # Validate exported data
        print("Validating exported hash chain...")
        previous_hash = None
        for i, log in enumerate(logs):
            if log.get("previous_hash") and log.get("previous_hash") != previous_hash:
                if i > 0:  # First entry might not have previous
                    print(f"Warning: Hash chain may be incomplete at entry {i}")
            previous_hash = log.get("entry_hash")

        print("Export complete!")

    finally:
        await session.close()


if __name__ == "__main__":
    asyncio.run(main())
