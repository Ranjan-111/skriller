# -*- coding: utf-8 -*-
"""
Agent Reach MCP Server — expose doctor/status as MCP tool.

Run: python -m agent_reach.integrations.mcp_server

Agent Reach is an installer + doctor tool. For actual reading/searching,
agents should call upstream tools directly (twitter-cli, yt-dlp, mcporter, etc.).
"""

import asyncio
import json
import sys

from agent_reach.config import Config
from agent_reach.core import AgentReach
from agent_reach.utils.text import scrub_url_credentials

try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import TextContent, Tool

    HAS_MCP = True
except ImportError:
    HAS_MCP = False


def create_server(*, tool_handlers=None):
    if not HAS_MCP:
        print(
            "MCP not installed. Install: python -m pip install "
            "'agent-reach[mcp] @ "
            "https://github.com/Panniantong/agent-reach/archive/main.zip'",
            file=sys.stderr,
        )
        sys.exit(1)

    server = Server("skriller" if tool_handlers is not None else "agent-reach")
    # Product adapters supply a fixed trusted tool surface. They must not read
    # host-wide source configuration or run the upstream diagnostic tools.
    if tool_handlers is None:
        config = Config(read_only=True)
        eyes = AgentReach(config)

    @server.list_tools()
    async def list_tools():
        if tool_handlers is not None:
            return await tool_handlers[0]()
        return [
            Tool(name="get_status",
                 description="Get Agent Reach status: which channels are installed and active.",
                 inputSchema={"type": "object", "properties": {}}),
        ]

    @server.call_tool(validate_input=False) if tool_handlers is not None else server.call_tool()
    async def call_tool(name: str, arguments: dict):
        try:
            if tool_handlers is not None:
                return await tool_handlers[1](name, arguments)
            if name == "get_status":
                result = eyes.doctor_report()
            else:
                result = f"Unknown tool: {name}"

            text = json.dumps(result, ensure_ascii=False, indent=2) if isinstance(result, (dict, list)) else str(result)
            return [TextContent(type="text", text=text)]
        except Exception as e:
            if tool_handlers is not None:
                return [TextContent(type="text", text="Product tool is unavailable")]
            return [
                TextContent(
                    type="text",
                    text=f"Error: {scrub_url_credentials(e)}",
                )
            ]

    return server


async def main():
    server = create_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
