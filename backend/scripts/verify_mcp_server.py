#!/usr/bin/env python3
"""Connect a real MCP client to a running graph-rag MCP server and exercise it.

Usage:
  # never pass the key as a CLI arg -- it would show up in shell history/ps
  export GRAPH_RAG_MCP_SERVICE_KEY="..."
  uv run python scripts/verify_mcp_server.py --tenant-key demo
  uv run python scripts/verify_mcp_server.py --tenant-key demo \
    --url http://localhost:8000/api/v1/mcp/
  uv run python scripts/verify_mcp_server.py --tenant-key chatwithdocs \
    --tool graphrag_query --question "What documents are available?"

This is a real MCP client (the official `mcp` SDK's streamable-HTTP transport),
not a mock -- it proves the server actually answers over the wire, not just
that the Python handler functions work in isolation. Requires the `mcp` extra
(`uv sync --extra mcp`) and MCP_ENABLED=true on the target server.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default=os.environ.get("GRAPH_RAG_MCP_URL", "https://api.chatwithdocs.org/api/v1/mcp/"),
        help="MCP endpoint (must end in a trailing slash). Default: production.",
    )
    parser.add_argument(
        "--tenant-key", help="X-Tenant-Key header (mutually exclusive with --tenant-id)"
    )
    parser.add_argument(
        "--tenant-id", help="X-Tenant-ID header (mutually exclusive with --tenant-key)"
    )
    parser.add_argument(
        "--tool",
        default="graphrag_query",
        help="Tool to call after listing tools. Pass --tool '' to only list tools.",
    )
    parser.add_argument("--question", default="What documents are available in this tenant?")
    parser.add_argument(
        "--document-id", help="Required by document-scoped tools (inspect/delete/reindex)."
    )
    return parser.parse_args()


TOOL_ARGS_BY_NAME = {
    "graphrag_query": lambda a: {"question": a.question},
    "graphrag_retrieve": lambda a: {"question": a.question},
    "graphrag_inspect_document": lambda a: {"document_id": a.document_id},
    "graphrag_show_run": lambda a: {"run_id": a.document_id},
}


async def main() -> None:
    args = parse_args()
    service_key = os.environ.get("GRAPH_RAG_MCP_SERVICE_KEY")
    if not service_key:
        print(
            "Set GRAPH_RAG_MCP_SERVICE_KEY in the environment (never as a CLI arg).",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if not args.tenant_key and not args.tenant_id:
        print("Pass --tenant-key or --tenant-id.", file=sys.stderr)
        raise SystemExit(1)

    headers = {"X-Api-Service-Key": service_key, "X-Principal": "verify-mcp-server-script"}
    if args.tenant_key:
        headers["X-Tenant-Key"] = args.tenant_key
    if args.tenant_id:
        headers["X-Tenant-ID"] = args.tenant_id

    async with (
        streamablehttp_client(args.url, headers=headers) as (read, write, _get_sid),
        ClientSession(read, write) as session,
    ):
        init_result = await session.initialize()
        print(f"connected: {init_result.serverInfo.name} {init_result.serverInfo.version}")

        tools = await session.list_tools()
        names = sorted(t.name for t in tools.tools)
        print(f"tools ({len(names)}): {names}")

        if not args.tool:
            return
        if args.tool not in names:
            print(f"'{args.tool}' not in tool list", file=sys.stderr)
            raise SystemExit(1)

        build_args = TOOL_ARGS_BY_NAME.get(args.tool)
        if build_args is None:
            print(
                f"No argument preset for '{args.tool}'; add one in TOOL_ARGS_BY_NAME.",
                file=sys.stderr,
            )
            raise SystemExit(1)

        result = await session.call_tool(args.tool, build_args(args))
        print(f"isError: {result.isError}")
        if result.structuredContent is not None:
            print(result.structuredContent)
        else:
            print([getattr(c, "text", str(c)) for c in result.content])


if __name__ == "__main__":
    asyncio.run(main())
