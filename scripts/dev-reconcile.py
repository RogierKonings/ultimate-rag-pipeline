#!/usr/bin/env python3
"""CLI tool for triggering index reconciliation (US-10.6.3).

Usage:
    python scripts/dev-reconcile.py --tenant dev-tenant --dry-run
    python scripts/dev-reconcile.py --tenant dev-tenant
    python scripts/dev-reconcile.py --tenant dev-tenant --document <doc-id>
    python scripts/dev-reconcile.py status <job-id>
"""

import argparse
import asyncio
import json
import os
import sys

import httpx

try:
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.table import Table

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

INGESTION_HOST = os.getenv("INGESTION_HOST", "localhost")
INGESTION_PORT = os.getenv("INGESTION_PORT", "8001")
INGESTION_URL = os.getenv("INGESTION_SERVICE_URL", f"http://{INGESTION_HOST}:{INGESTION_PORT}")


async def trigger_reconciliation(
    tenant_id: str,
    document_id: str | None = None,
    dry_run: bool = True,
    token: str | None = None,
) -> dict:
    """Trigger index reconciliation."""
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    payload = {
        "tenant_id": tenant_id,
        "dry_run": dry_run,
    }
    if document_id:
        payload["document_id"] = document_id

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{INGESTION_URL}/api/v1/admin/reconcile",
            json=payload,
            headers=headers,
        )
        response.raise_for_status()
        return response.json()


async def get_reconciliation_status(job_id: str, token: str | None = None) -> dict:
    """Get reconciliation job status."""
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(
            f"{INGESTION_URL}/api/v1/admin/reconcile/{job_id}",
            headers=headers,
        )
        response.raise_for_status()
        return response.json()


async def wait_for_completion(
    job_id: str, token: str | None = None, poll_interval: float = 2.0
) -> dict:
    """Wait for reconciliation job to complete."""
    if RICH_AVAILABLE:
        console = Console()
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task(f"Reconciliation job {job_id}...", total=None)

            while True:
                status = await get_reconciliation_status(job_id, token)

                if status.get("status") in ("completed", "failed"):
                    progress.update(task, description=f"Job {status['status']}")
                    return status

                progress.update(task, description=f"Status: {status.get('status', 'unknown')}")
                await asyncio.sleep(poll_interval)
    else:
        while True:
            status = await get_reconciliation_status(job_id, token)

            if status.get("status") in ("completed", "failed"):
                return status

            print(f"Status: {status.get('status', 'unknown')}")
            await asyncio.sleep(poll_interval)


def display_result(result: dict, output_json: bool) -> None:
    """Display reconciliation result."""
    if output_json:
        print(json.dumps(result, indent=2, default=str))
        return

    if RICH_AVAILABLE:
        console = Console()

        status = result.get("status", "unknown")
        color = (
            "green" if status == "completed"
            else "yellow" if status in ("queued", "pending", "running")
            else "red"
        )

        console.print(f"[bold]Job ID:[/bold] {result.get('job_id', 'N/A')}")
        console.print(f"[bold]Status:[/bold] [{color}]{status}[/{color}]")

        if result.get("message"):
            console.print(f"[bold]Message:[/bold] {result['message']}")

        if result.get("error"):
            console.print(f"[bold red]Error:[/bold red] {result['error']}")

        # Display result details if available
        if result.get("result"):
            details = result["result"]
            console.print("\n[bold]Reconciliation Results:[/bold]")

            if details.get("issues_found") is not None:
                console.print(f"  Issues found: {details['issues_found']}")
            if details.get("issues_fixed") is not None:
                console.print(f"  Issues fixed: {details['issues_fixed']}")
            if details.get("orphans_cleaned") is not None:
                console.print(f"  Orphaned entries cleaned: {details['orphans_cleaned']}")
            if details.get("missing_reindexed") is not None:
                console.print(f"  Missing entries reindexed: {details['missing_reindexed']}")
            if details.get("dry_run"):
                console.print("\n[yellow]Note: This was a dry run. No changes were made.[/yellow]")

            # Display issue details if available
            if details.get("issues"):
                table = Table(title="Issues Found")
                table.add_column("Store")
                table.add_column("Type")
                table.add_column("Chunk ID")
                table.add_column("Action")

                for issue in details["issues"][:20]:  # Limit to 20
                    table.add_row(
                        issue.get("store", ""),
                        issue.get("issue_type", ""),
                        issue.get("chunk_id", "")[:8] if issue.get("chunk_id") else "",
                        issue.get("action_taken", ""),
                    )

                console.print(table)

                if len(details["issues"]) > 20:
                    console.print(f"  ... and {len(details['issues']) - 20} more issues")
    else:
        print(json.dumps(result, indent=2, default=str))


async def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Trigger index reconciliation between PostgreSQL and external stores"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Trigger reconciliation (default)
    trigger_parser = subparsers.add_parser("trigger", help="Trigger reconciliation")
    trigger_parser.add_argument(
        "--tenant", required=True, help="Tenant ID to reconcile"
    )
    trigger_parser.add_argument(
        "--document", help="Specific document ID (optional)"
    )
    trigger_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Report issues without making changes (default)",
    )
    trigger_parser.add_argument(
        "--no-dry-run",
        action="store_true",
        help="Actually repair issues",
    )
    trigger_parser.add_argument(
        "--wait", action="store_true", help="Wait for job completion"
    )
    trigger_parser.add_argument("--token", help="JWT token for authentication")

    # Get status
    status_parser = subparsers.add_parser("status", help="Get job status")
    status_parser.add_argument("job_id", help="Job ID to check")
    status_parser.add_argument("--token", help="JWT token for authentication")
    status_parser.add_argument(
        "--wait", action="store_true", help="Wait for job completion"
    )

    # Common options
    parser.add_argument("--json", action="store_true", help="Output in JSON format")

    # Also allow running without subcommand for backward compatibility
    parser.add_argument("--tenant", help="Tenant ID to reconcile")
    parser.add_argument("--document", help="Specific document ID")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Report issues without making changes",
    )
    parser.add_argument(
        "--no-dry-run",
        action="store_true",
        help="Actually repair issues",
    )
    parser.add_argument("--wait", action="store_true", help="Wait for job completion")
    parser.add_argument("--token", help="JWT token for authentication")

    args = parser.parse_args()

    try:
        if args.command == "status":
            result = await get_reconciliation_status(args.job_id, args.token)
            if args.wait and result.get("status") not in ("completed", "failed"):
                result = await wait_for_completion(args.job_id, args.token)

        elif args.command == "trigger" or args.tenant:
            # Handle both subcommand and direct invocation
            tenant_id = getattr(args, "tenant", None)
            if not tenant_id:
                print("Error: --tenant is required")
                return 1

            dry_run = not getattr(args, "no_dry_run", False)
            document_id = getattr(args, "document", None)
            token = getattr(args, "token", None)
            wait = getattr(args, "wait", False)

            result = await trigger_reconciliation(
                tenant_id=tenant_id,
                document_id=document_id,
                dry_run=dry_run,
                token=token,
            )

            if wait and result.get("job_id"):
                result = await wait_for_completion(result["job_id"], token)

        else:
            parser.print_help()
            return 1

        display_result(result, args.json)
        return 0

    except httpx.ConnectError:
        print(f"Error: Could not connect to ingestion service at {INGESTION_URL}")
        print("Make sure the service is running: make up-all")
        return 1
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            print("Error: Admin privileges required for this operation")
            print("Provide a valid admin JWT token with --token")
        else:
            print(f"Error: HTTP {e.response.status_code}")
            try:
                print(json.dumps(e.response.json(), indent=2))
            except json.JSONDecodeError:
                print(e.response.text)
        return 1
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
