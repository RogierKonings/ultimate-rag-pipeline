#!/usr/bin/env python3
"""CLI tool for testing RAG queries with debug output (US-10.6.3).

Usage:
    python scripts/dev-query.py "What is RAG?"
    python scripts/dev-query.py "How does chunking work?" --debug
    python scripts/dev-query.py "Explain embeddings" --tenant my-tenant --top-k 5
"""

import argparse
import asyncio
import json
import os
import sys
from typing import Any

import httpx

try:
    from rich.console import Console
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.table import Table

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

ORCHESTRATOR_HOST = os.getenv("ORCHESTRATOR_HOST", "localhost")
ORCHESTRATOR_PORT = os.getenv("ORCHESTRATOR_PORT", "8003")
ORCHESTRATOR_URL = os.getenv("ORCHESTRATOR_SERVICE_URL", f"http://{ORCHESTRATOR_HOST}:{ORCHESTRATOR_PORT}")


async def execute_query(
    query_text: str,
    tenant_id: str = "dev-tenant",
    top_k: int = 10,
    debug: bool = False,
    stream: bool = False,
    semantic_weight: float = 0.7,
) -> dict[str, Any]:
    """Execute a RAG query against the orchestrator service."""
    url = f"{ORCHESTRATOR_URL}/api/v1/query"

    payload = {
        "query": query_text,
        "tenant_id": tenant_id,
        "options": {
            "top_k": top_k,
            "debug": debug,
            "semantic_weight": semantic_weight,
            "use_reranker": True,
        },
    }

    async with httpx.AsyncClient(timeout=60.0) as client:
        if stream:
            # Handle streaming response
            chunks = []
            async with client.stream("POST", url, json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        data = json.loads(line[6:])
                        if data.get("type") == "chunk":
                            chunks.append(data.get("content", ""))
                        elif data.get("type") == "done":
                            return {
                                "response": "".join(chunks),
                                "citations": data.get("citations", []),
                                "debug": data.get("debug"),
                            }
            return {"response": "".join(chunks), "citations": [], "debug": None}

        response = await client.post(url, json=payload)
        response.raise_for_status()
        return response.json()


def display_with_rich(data: dict[str, Any], show_debug: bool) -> None:
    """Display results using rich formatting."""
    console = Console()

    # Display response
    response_text = data.get("response", "No response")
    console.print(Panel(Markdown(response_text), title="[bold green]Response[/bold green]"))

    # Display citations
    citations = data.get("citations", [])
    if citations:
        console.print("\n[bold blue]Citations:[/bold blue]")
        for i, cite in enumerate(citations, 1):
            source = cite.get("source", cite.get("source_uri", "Unknown"))
            title = cite.get("title", "")
            score = cite.get("score", cite.get("relevance_score"))
            score_str = f" (score: {score:.3f})" if score else ""
            display = f"[dim]{title}[/dim] " if title else ""
            console.print(f"  [{i}] {display}{source}{score_str}")

    # Display debug info
    if show_debug and data.get("debug"):
        debug_info = data["debug"]
        console.print("\n[bold yellow]Debug Info:[/bold yellow]")

        # Timing table
        if debug_info.get("timing"):
            table = Table(title="Timing Breakdown")
            table.add_column("Component", style="cyan")
            table.add_column("Latency (ms)", justify="right")

            total = 0
            for component, latency in debug_info["timing"].items():
                table.add_row(component, f"{latency:.1f}")
                total += latency

            table.add_row("[bold]Total[/bold]", f"[bold]{total:.1f}[/bold]")
            console.print(table)

        # Retrieval info
        if debug_info.get("retrieval"):
            retrieval = debug_info["retrieval"]
            console.print(f"\n[dim]Retrieval strategy:[/dim] {retrieval.get('strategy', 'hybrid')}")
            console.print(f"[dim]Semantic results:[/dim] {retrieval.get('semantic_count', 'N/A')}")
            console.print(f"[dim]Keyword results:[/dim] {retrieval.get('keyword_count', 'N/A')}")
            console.print(f"[dim]After fusion:[/dim] {retrieval.get('fused_count', 'N/A')}")
            console.print(f"[dim]After reranking:[/dim] {retrieval.get('reranked_count', 'N/A')}")

        # Token usage
        if debug_info.get("tokens"):
            tokens = debug_info["tokens"]
            console.print(f"\n[dim]Prompt tokens:[/dim] {tokens.get('prompt', 'N/A')}")
            console.print(f"[dim]Completion tokens:[/dim] {tokens.get('completion', 'N/A')}")

        # Intent classification
        if debug_info.get("intent"):
            console.print(f"\n[dim]Intent:[/dim] {debug_info['intent']}")


def display_plain(data: dict[str, Any], show_debug: bool) -> None:
    """Display results without rich formatting."""
    print("\n=== Response ===")
    print(data.get("response", "No response"))

    citations = data.get("citations", [])
    if citations:
        print("\n=== Citations ===")
        for i, cite in enumerate(citations, 1):
            source = cite.get("source", cite.get("source_uri", "Unknown"))
            print(f"  [{i}] {source}")

    if show_debug and data.get("debug"):
        debug_info = data["debug"]
        print("\n=== Debug Info ===")

        if debug_info.get("timing"):
            print("\nTiming:")
            for component, latency in debug_info["timing"].items():
                print(f"  {component}: {latency:.1f}ms")

        if debug_info.get("retrieval"):
            print(f"\nRetrieval: {debug_info['retrieval']}")


def display_json(data: dict[str, Any]) -> None:
    """Display results as JSON."""
    print(json.dumps(data, indent=2, default=str))


async def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Test RAG queries against the orchestrator service"
    )
    parser.add_argument("query", help="Query text to send")
    parser.add_argument(
        "--tenant", default="dev-tenant", help="Tenant ID (default: dev-tenant)"
    )
    parser.add_argument(
        "--top-k", type=int, default=10, help="Number of results to retrieve (default: 10)"
    )
    parser.add_argument(
        "--debug", action="store_true", help="Enable debug output"
    )
    parser.add_argument(
        "--stream", action="store_true", help="Stream response (SSE)"
    )
    parser.add_argument(
        "--semantic-weight",
        type=float,
        default=0.7,
        help="Semantic vs keyword weight (default: 0.7)",
    )
    parser.add_argument(
        "--json", action="store_true", help="Output in JSON format"
    )

    args = parser.parse_args()

    try:
        data = await execute_query(
            query_text=args.query,
            tenant_id=args.tenant,
            top_k=args.top_k,
            debug=args.debug,
            stream=args.stream,
            semantic_weight=args.semantic_weight,
        )

        if args.json:
            display_json(data)
        elif RICH_AVAILABLE:
            display_with_rich(data, args.debug)
        else:
            display_plain(data, args.debug)

        return 0

    except httpx.ConnectError:
        print("Error: Could not connect to orchestrator service at", ORCHESTRATOR_URL)
        print("Make sure the service is running: make up-all")
        return 1
    except httpx.HTTPStatusError as e:
        print(f"Error: HTTP {e.response.status_code}")
        try:
            print(e.response.json())
        except json.JSONDecodeError:
            print(e.response.text)
        return 1
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
