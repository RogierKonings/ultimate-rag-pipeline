#!/usr/bin/env python3
"""Check health of all RAG pipeline services (US-10.6.3).

Usage:
    python scripts/dev-health.py
    python scripts/dev-health.py --json
    python scripts/dev-health.py --watch --interval 5
"""

import argparse
import asyncio
import json
import os
import sys
from datetime import UTC, datetime

import httpx

try:
    from rich.console import Console
    from rich.live import Live
    from rich.table import Table

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False


def get_service_url(env_var: str, host_env: str, port_env: str, default_host: str, default_port: str) -> str:
    """Get service URL from environment variables."""
    if url := os.getenv(env_var):
        return url
    host = os.getenv(host_env, default_host)
    port = os.getenv(port_env, default_port)
    return f"http://{host}:{port}"


SERVICES = {
    "Ingestion": {
        "url": f"{get_service_url('INGESTION_SERVICE_URL', 'INGESTION_HOST', 'INGESTION_PORT', 'localhost', '8001')}/health",
        "description": "Document ingestion service",
    },
    "Retrieval": {
        "url": f"{get_service_url('RETRIEVAL_SERVICE_URL', 'RETRIEVAL_HOST', 'RETRIEVAL_PORT', 'localhost', '8002')}/health",
        "description": "Hybrid search service",
    },
    "Orchestrator": {
        "url": f"{get_service_url('ORCHESTRATOR_SERVICE_URL', 'ORCHESTRATOR_HOST', 'ORCHESTRATOR_PORT', 'localhost', '8003')}/health",
        "description": "RAG orchestration service",
    },
    "Embedding": {
        "url": f"{get_service_url('EMBEDDING_SERVICE_URL', 'EMBEDDING_HOST', 'EMBEDDING_PORT', 'localhost', '8080')}/health",
        "description": "Embedding model service",
    },
    "Qdrant": {
        "url": f"{get_service_url('QDRANT_URL', 'QDRANT_HOST', 'QDRANT_PORT', 'localhost', '6333')}/healthz",
        "description": "Vector database",
    },
    "OpenSearch": {
        "url": f"{get_service_url('OPENSEARCH_URL', 'OPENSEARCH_HOST', 'OPENSEARCH_PORT', 'localhost', '9200')}/_cluster/health",
        "description": "Keyword search engine",
    },
    "Redis": {
        "url": f"{os.getenv('REDIS_HOST', 'localhost')}:{os.getenv('REDIS_PORT', '6379')}",
        "description": "Cache and task queue",
        "check_type": "tcp",
    },
    "PostgreSQL": {
        "url": f"{os.getenv('POSTGRES_HOST', 'localhost')}:{os.getenv('POSTGRES_PORT', '5432')}",
        "description": "Metadata database",
        "check_type": "tcp",
    },
    "MinIO": {
        "url": f"http://{os.getenv('MINIO_ENDPOINT', 'localhost:9000')}/minio/health/live",
        "description": "Object storage",
    },
}


async def check_http_health(
    client: httpx.AsyncClient, name: str, config: dict
) -> dict:
    """Check health via HTTP endpoint."""
    url = config["url"]
    try:
        response = await client.get(url)
        if response.status_code == 200:
            try:
                data = response.json()
                details = data.get("version", data.get("cluster_name", data.get("status", "OK")))
            except (json.JSONDecodeError, ValueError):
                details = "OK"
            return {
                "name": name,
                "status": "healthy",
                "details": str(details)[:50],
                "latency_ms": response.elapsed.total_seconds() * 1000,
            }

        return {
            "name": name,
            "status": "degraded",
            "details": f"HTTP {response.status_code}",
            "latency_ms": response.elapsed.total_seconds() * 1000,
        }
    except httpx.ConnectError:
        return {"name": name, "status": "unhealthy", "details": "Connection refused"}
    except httpx.TimeoutException:
        return {"name": name, "status": "unhealthy", "details": "Timeout"}
    except Exception as e:
        return {"name": name, "status": "unhealthy", "details": str(e)[:50]}


async def check_tcp_health(name: str, config: dict) -> dict:
    """Check health via TCP connection."""
    url = config["url"]
    try:
        if "://" in url:
            url = url.split("://")[1]
        host, port = url.split(":")
        port = int(port)

        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=5.0
        )
        writer.close()
        await writer.wait_closed()
        return {"name": name, "status": "healthy", "details": "TCP OK"}
    except TimeoutError:
        return {"name": name, "status": "unhealthy", "details": "Timeout"}
    except ConnectionRefusedError:
        return {"name": name, "status": "unhealthy", "details": "Connection refused"}
    except Exception as e:
        return {"name": name, "status": "unhealthy", "details": str(e)[:50]}


async def check_all_services() -> list[dict]:
    """Check health of all services."""
    results = []

    async with httpx.AsyncClient(timeout=5.0) as client:
        tasks = []
        for name, config in SERVICES.items():
            check_type = config.get("check_type", "http")
            if check_type == "tcp":
                tasks.append(check_tcp_health(name, config))
            else:
                tasks.append(check_http_health(client, name, config))

        results = await asyncio.gather(*tasks)

    return list(results)


def create_table(results: list[dict], timestamp: datetime | None = None) -> Table:
    """Create rich table from results."""
    title = "RAG Pipeline Service Health"
    if timestamp:
        title += f" ({timestamp.strftime('%H:%M:%S')})"

    table = Table(title=title)
    table.add_column("Service", style="cyan")
    table.add_column("Status")
    table.add_column("Details")
    table.add_column("Latency", justify="right")

    for result in results:
        status = result["status"]
        if status == "healthy":
            status_str = "[green]● Healthy[/green]"
        elif status == "degraded":
            status_str = "[yellow]◐ Degraded[/yellow]"
        else:
            status_str = "[red]○ Unhealthy[/red]"

        latency = result.get("latency_ms")
        latency_str = f"{latency:.0f}ms" if latency else "-"

        table.add_row(
            result["name"],
            status_str,
            result.get("details", ""),
            latency_str,
        )

    return table


def print_json(results: list[dict]) -> None:
    """Print results as JSON."""
    output = {
        "timestamp": datetime.now(tz=UTC).isoformat(),
        "services": results,
        "summary": {
            "total": len(results),
            "healthy": sum(1 for r in results if r["status"] == "healthy"),
            "degraded": sum(1 for r in results if r["status"] == "degraded"),
            "unhealthy": sum(1 for r in results if r["status"] == "unhealthy"),
        },
    }
    print(json.dumps(output, indent=2))


def print_plain(results: list[dict]) -> None:
    """Print results without rich formatting."""
    print("\nRAG Pipeline Service Health")
    print("=" * 60)
    for result in results:
        status = result["status"].upper()
        latency = result.get("latency_ms")
        latency_str = f" ({latency:.0f}ms)" if latency else ""
        print(f"{result['name']:15} [{status:9}] {result.get('details', '')}{latency_str}")

    healthy = sum(1 for r in results if r["status"] == "healthy")
    print(f"\nSummary: {healthy}/{len(results)} services healthy")


async def watch_health(interval: float, use_json: bool) -> None:
    """Continuously watch service health."""
    if use_json:
        while True:
            results = await check_all_services()
            print_json(results)
            await asyncio.sleep(interval)
    elif RICH_AVAILABLE:
        console = Console()
        with Live(console=console, refresh_per_second=1) as live:
            while True:
                results = await check_all_services()
                table = create_table(results, datetime.now(tz=UTC))
                live.update(table)
                await asyncio.sleep(interval)
    else:
        while True:
            results = await check_all_services()
            print("\033[2J\033[H")  # Clear screen
            print_plain(results)
            await asyncio.sleep(interval)


async def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Check health of all RAG pipeline services"
    )
    parser.add_argument(
        "--json", action="store_true", help="Output in JSON format"
    )
    parser.add_argument(
        "--watch", action="store_true", help="Continuously watch health"
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="Watch interval in seconds (default: 5)",
    )

    args = parser.parse_args()

    if args.watch:
        try:
            await watch_health(args.interval, args.json)
        except KeyboardInterrupt:
            print("\nStopped watching.")
            return 0
    else:
        results = await check_all_services()

        if args.json:
            print_json(results)
        elif RICH_AVAILABLE:
            console = Console()
            table = create_table(results)
            console.print(table)
        else:
            print_plain(results)

        # Return non-zero if any service is unhealthy
        unhealthy = sum(1 for r in results if r["status"] == "unhealthy")
        return 1 if unhealthy > 0 else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
