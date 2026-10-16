from uuid import uuid4

import httpx
import pytest

from skriller.mcp_interface import ProductMCP
from skriller.mcp_runtime import read_token, validate_origin


async def test_actual_stdio_runtime_initializes_without_source_configuration(tmp_path):
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    token = tmp_path / "fixture-token"
    token.write_text("EXPLICIT_SYNTHETIC_TOKEN")
    token.chmod(0o600)
    parameters = StdioServerParameters(
        command=sys.executable,
        args=[
            "-m",
            "skriller.mcp_runtime",
            "--workspace-id",
            str(uuid4()),
            "--token-file",
            str(token),
            "--api-base",
            "http://127.0.0.1:1",
        ],
        env={"PATH": "/usr/bin:/bin", "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
    )
    async with (
        stdio_client(parameters) as (reader, writer),
        ClientSession(reader, writer) as client,
    ):
        initialized = await client.initialize()
        assert initialized.serverInfo.name == "skriller"
        tools = await client.list_tools()
        assert {item.name for item in tools.tools} == {
            "list_conversations",
            "submit_research",
            "get_research",
            "list_saved_lists",
            "read_saved_snapshot",
            "read_evidence",
        }


def test_token_file_must_be_private_regular_owned_and_bounded(tmp_path):
    private = tmp_path / "token"
    private.write_text("SYNTHETIC_TOKEN\n")
    private.chmod(0o600)
    assert read_token(private) == "SYNTHETIC_TOKEN"
    private.chmod(0o644)
    with pytest.raises(ValueError, match="private owner token"):
        read_token(private)
    private.chmod(0o600)
    link = tmp_path / "link"
    link.symlink_to(private)
    with pytest.raises(ValueError):
        read_token(link)
    private.write_text("x" * 8193)
    with pytest.raises(ValueError):
        read_token(private)


@pytest.mark.parametrize(
    "origin",
    [
        "http://remote.example",
        "https://user:secret@example.org",
        "https://example.org/?token=secret",
        "https://example.org/path",
        "file:///tmp/api",
    ],
)
def test_fixed_api_origin_has_no_credentials_or_arbitrary_http_target(origin):
    with pytest.raises(ValueError):
        validate_origin(origin)


async def test_redirect_error_body_output_bound_and_workspace_mismatch_are_not_echoed():
    workspace = uuid4()
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(302, headers={"Location": "https://evil.invalid/SENTINEL"})
        if len(calls) == 2:
            return httpx.Response(401, json={"secret": "SENTINEL"})
        if len(calls) == 3:
            return httpx.Response(200, content=b"x" * 262145)
        return httpx.Response(200, json=[{"workspace_id": str(uuid4()), "secret": "SENTINEL"}])

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://localhost", follow_redirects=False
    ) as client:
        adapter = ProductMCP(client, workspace)
        for _ in range(4):
            result = await adapter.call_tool("list_conversations", {})
            assert result.isError and "SENTINEL" not in result.content[0].text
    assert len(calls) == 4
