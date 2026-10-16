"""Explicit stdio MCP service; fixed API origin/workspace and a private token file."""

import argparse
import asyncio
import logging
import os
import stat
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from agent_reach.utils.paths import read_small_text_no_follow
from mcp.server.stdio import stdio_server

from skriller.mcp_interface import ProductMCP, create_server


def read_token(path):
    try:
        info = os.stat(path, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077 or info.st_uid != os.getuid():
            raise ValueError
        token = (read_small_text_no_follow(Path(path), max_bytes=8192) or "").strip()
        if not token or any(not 33 <= ord(char) <= 126 for char in token):
            raise ValueError
        return token
    except Exception:  # noqa: BLE001 - never expose token content/path in errors
        raise ValueError("A private owner token file is required") from None


def validate_origin(value):
    parsed = urlsplit(value)
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
        or (
            parsed.scheme != "https"
            and not (
                parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
            )
        )
    ):
        raise ValueError("MCP requires a fixed HTTPS or local API origin")
    return value.rstrip("/")


async def serve(origin, workspace, token_file):
    # The SDK otherwise logs untrusted unknown tool names verbatim to stderr.
    logging.getLogger("mcp.server.lowlevel.server").setLevel(logging.ERROR)
    async with httpx.AsyncClient(
        base_url=validate_origin(origin),
        headers={"Authorization": "Bearer " + read_token(token_file)},
        timeout=15,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        server = create_server(ProductMCP(client, workspace))
        async with stdio_server() as (reader, writer):
            await server.run(reader, writer, server.create_initialization_options())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default="http://127.0.0.1:8000")
    parser.add_argument("--workspace-id", required=True, type=UUID)
    parser.add_argument("--token-file", required=True, type=Path)
    args = parser.parse_args()
    try:
        asyncio.run(serve(args.api_base, args.workspace_id, args.token_file))
    except (ValueError, OSError):
        parser.exit(2, "MCP configuration or authenticated API is unavailable\n")


if __name__ == "__main__":
    main()
