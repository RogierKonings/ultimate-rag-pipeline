#!/usr/bin/env python3
"""CLI tool for document ingestion (US-10.6.3).

Usage:
    python scripts/dev-ingest.py file document.pdf
    python scripts/dev-ingest.py file document.pdf --tenant my-tenant
    python scripts/dev-ingest.py url https://example.com/doc.pdf
    python scripts/dev-ingest.py status <job-id>
    python scripts/dev-ingest.py list --tenant my-tenant
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

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


async def ingest_file(
    file_path: str,
    tenant_id: str = "dev-tenant",
    chunking_strategy: str = "recursive",
    wait: bool = False,
) -> dict[str, Any]:
    """Ingest a local file."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    async with httpx.AsyncClient(timeout=120.0) as client:
        # Upload file
        files = {"file": (path.name, path.read_bytes())}
        data = {
            "tenant_id": tenant_id,
            "chunking_strategy": chunking_strategy,
        }

        response = await client.post(
            f"{INGESTION_URL}/api/v1/ingest/file",
            files=files,
            data=data,
        )
        response.raise_for_status()
        result = response.json()

        if wait and result.get("job_id"):
            result = await wait_for_job(client, result["job_id"])

        return result


async def ingest_url(
    url: str,
    tenant_id: str = "dev-tenant",
    chunking_strategy: str = "recursive",
    wait: bool = False,
) -> dict[str, Any]:
    """Ingest a document from URL."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        payload = {
            "source_type": "web",
            "source_config": {
                "url": url,
            },
            "tenant_id": tenant_id,
            "options": {
                "chunking_strategy": chunking_strategy,
            },
        }

        response = await client.post(
            f"{INGESTION_URL}/api/v1/ingest/sync",
            json=payload,
        )
        response.raise_for_status()
        result = response.json()

        if wait and result.get("job_id"):
            result = await wait_for_job(client, result["job_id"])

        return result


async def wait_for_job(
    client: httpx.AsyncClient, job_id: str, poll_interval: float = 2.0
) -> dict[str, Any]:
    """Wait for a job to complete."""
    if RICH_AVAILABLE:
        console = Console()
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task(f"Processing job {job_id}...", total=None)

            while True:
                response = await client.get(f"{INGESTION_URL}/api/v1/ingest/jobs/{job_id}")
                response.raise_for_status()
                status = response.json()

                if status.get("status") in ("completed", "failed"):
                    progress.update(task, description=f"Job {status['status']}")
                    return status

                prog = status.get("progress", {})
                processed = prog.get("processed", 0)
                total = prog.get("total", 0)
                if total > 0:
                    progress.update(task, description=f"Processing: {processed}/{total}")

                await asyncio.sleep(poll_interval)
    else:
        while True:
            response = await client.get(f"{INGESTION_URL}/api/v1/ingest/jobs/{job_id}")
            response.raise_for_status()
            status = response.json()

            if status.get("status") in ("completed", "failed"):
                return status

            prog = status.get("progress", {})
            print(f"Processing: {prog.get('processed', 0)}/{prog.get('total', 0)}")
            await asyncio.sleep(poll_interval)


async def get_job_status(job_id: str) -> dict[str, Any]:
    """Get status of an ingestion job."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(f"{INGESTION_URL}/api/v1/ingest/jobs/{job_id}")
        response.raise_for_status()
        return response.json()


async def list_documents(
    tenant_id: str = "dev-tenant",
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """List ingested documents."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        params = {
            "tenant_id": tenant_id,
            "limit": limit,
            "offset": offset,
        }
        response = await client.get(
            f"{INGESTION_URL}/api/v1/documents",
            params=params,
        )
        response.raise_for_status()
        return response.json()


async def delete_document(document_id: str, tenant_id: str = "dev-tenant") -> dict[str, Any]:
    """Delete a document."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.delete(
            f"{INGESTION_URL}/api/v1/documents/{document_id}",
            params={"tenant_id": tenant_id},
        )
        response.raise_for_status()
        return {"status": "deleted", "document_id": document_id}


def display_result(result: dict[str, Any], output_json: bool) -> None:
    """Display result."""
    if output_json:
        print(json.dumps(result, indent=2, default=str))
        return

    if RICH_AVAILABLE:
        console = Console()

        if "documents" in result:
            # List documents
            table = Table(title="Documents")
            table.add_column("ID", style="cyan")
            table.add_column("Title")
            table.add_column("Source")
            table.add_column("Chunks")
            table.add_column("Status")

            for doc in result.get("documents", []):
                table.add_row(
                    doc.get("id", "")[:8],
                    doc.get("title", "")[:30],
                    doc.get("source_uri", "")[:40],
                    str(doc.get("chunk_count", "")),
                    doc.get("status", ""),
                )

            console.print(table)
            console.print(f"\nTotal: {result.get('total', len(result.get('documents', [])))}")

        elif "job_id" in result:
            # Job result
            status = result.get("status", "unknown")
            color = "green" if status == "completed" else "yellow" if status == "queued" else "red"
            console.print(f"[bold]Job ID:[/bold] {result['job_id']}")
            console.print(f"[bold]Status:[/bold] [{color}]{status}[/{color}]")

            if result.get("document_id"):
                console.print(f"[bold]Document ID:[/bold] {result['document_id']}")
            if result.get("chunks_created"):
                console.print(f"[bold]Chunks created:[/bold] {result['chunks_created']}")
            if result.get("progress"):
                prog = result["progress"]
                console.print(f"[bold]Progress:[/bold] {prog.get('processed', 0)}/{prog.get('total', 0)}")
            if result.get("error"):
                console.print(f"[bold red]Error:[/bold red] {result['error']}")

        else:
            console.print_json(data=result)
    else:
        print(json.dumps(result, indent=2, default=str))


async def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="CLI tool for document ingestion"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # File ingestion
    file_parser = subparsers.add_parser("file", help="Ingest a local file")
    file_parser.add_argument("path", help="Path to the file to ingest")
    file_parser.add_argument("--tenant", default="dev-tenant", help="Tenant ID")
    file_parser.add_argument(
        "--chunking",
        default="recursive",
        choices=["recursive", "semantic", "hierarchical"],
        help="Chunking strategy",
    )
    file_parser.add_argument("--wait", action="store_true", help="Wait for completion")

    # URL ingestion
    url_parser = subparsers.add_parser("url", help="Ingest from URL")
    url_parser.add_argument("url", help="URL to ingest")
    url_parser.add_argument("--tenant", default="dev-tenant", help="Tenant ID")
    url_parser.add_argument(
        "--chunking",
        default="recursive",
        choices=["recursive", "semantic", "hierarchical"],
        help="Chunking strategy",
    )
    url_parser.add_argument("--wait", action="store_true", help="Wait for completion")

    # Job status
    status_parser = subparsers.add_parser("status", help="Get job status")
    status_parser.add_argument("job_id", help="Job ID to check")

    # List documents
    list_parser = subparsers.add_parser("list", help="List documents")
    list_parser.add_argument("--tenant", default="dev-tenant", help="Tenant ID")
    list_parser.add_argument("--limit", type=int, default=20, help="Number of documents")
    list_parser.add_argument("--offset", type=int, default=0, help="Offset for pagination")

    # Delete document
    delete_parser = subparsers.add_parser("delete", help="Delete a document")
    delete_parser.add_argument("document_id", help="Document ID to delete")
    delete_parser.add_argument("--tenant", default="dev-tenant", help="Tenant ID")

    # Common options
    parser.add_argument("--json", action="store_true", help="Output in JSON format")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    try:
        if args.command == "file":
            result = await ingest_file(
                args.path,
                tenant_id=args.tenant,
                chunking_strategy=args.chunking,
                wait=args.wait,
            )
        elif args.command == "url":
            result = await ingest_url(
                args.url,
                tenant_id=args.tenant,
                chunking_strategy=args.chunking,
                wait=args.wait,
            )
        elif args.command == "status":
            result = await get_job_status(args.job_id)
        elif args.command == "list":
            result = await list_documents(
                tenant_id=args.tenant,
                limit=args.limit,
                offset=args.offset,
            )
        elif args.command == "delete":
            result = await delete_document(args.document_id, tenant_id=args.tenant)
        else:
            parser.print_help()
            return 1

        display_result(result, args.json)
        return 0

    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1
    except httpx.ConnectError:
        print(f"Error: Could not connect to ingestion service at {INGESTION_URL}")
        print("Make sure the service is running: make up-all")
        return 1
    except httpx.HTTPStatusError as e:
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
