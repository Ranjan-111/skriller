"""Actual MCP SDK protocol through authenticated API and real tenant job ledger."""

import asyncio
import json
from uuid import UUID, uuid4

import httpx
import pytest
import sqlalchemy as sa
from mcp.shared.memory import create_connected_server_and_client_session
from test_research_workflow import Provider, run

from skriller.api import create_app
from skriller.db import ConversationRepository
from skriller.entitlements import admissions, policies, policy_for
from skriller.mcp_interface import ProductMCP, create_server
from skriller.settings import Settings

pytestmark = pytest.mark.integration_db


def setup(database, monkeypatch):
    actor = "mcp-" + str(uuid4())
    workspace = database.create_workspace(actor, "MCP tenant")["id"]
    with database.tenant(actor, workspace) as session:
        conversation = ConversationRepository.create(session, "MCP existing research")
    app = create_app(
        Settings(_env_file=None, environment="test", firebase_project_id="mcp-fixture")
    )
    app.state.database = database
    app.state.search_provider = Provider()
    app.state.identity_verifier = lambda token, project: {
        "sub": token,
        "aud": project,
        "iss": f"https://securetoken.google.com/{project}",
    }
    monkeypatch.setattr("skriller.research.router.safe_dispatch", lambda *args: True)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://fixture.invalid",
        headers={"Authorization": "Bearer " + actor},
    )
    return actor, workspace, conversation["id"], app, client


def data(result):
    assert not result.isError, result
    return json.loads(result.content[0].text)["data"]


async def test_real_sdk_research_uses_api_scope_idempotency_costs_and_worker(database, monkeypatch):
    actor, workspace, conversation, _app, client = setup(database, monkeypatch)
    async with client:
        adapter = ProductMCP(client, UUID(workspace))
        async with create_connected_server_and_client_session(create_server(adapter)) as mcp:
            tools = await mcp.list_tools()
            assert {item.name for item in tools.tools} == {
                "list_conversations",
                "submit_research",
                "get_research",
                "list_saved_lists",
                "read_saved_snapshot",
                "read_evidence",
            }
            assert data(await mcp.call_tool("list_conversations", {}))[0]["id"] == conversation
            arguments = {
                "conversation_id": conversation,
                "prompt": "Find software companies",
                "sources": ["web"],
                "result_limit": 5,
                "request_key": "first-research",
            }
            accepted = data(await mcp.call_tool("submit_research", arguments))
            assert accepted["workspace_id"] == workspace
            duplicate = data(await mcp.call_tool("submit_research", arguments))
            assert duplicate["job_id"] == accepted["job_id"]
            provider = Provider()
            _payload, outcome = await asyncio.to_thread(
                run, database, actor, accepted, provider, monkeypatch
            )
            assert outcome["status"] == "checkpointed" and provider.calls > 0
            result = data(await mcp.call_tool("get_research", {"job_id": accepted["job_id"]}))
            normal = await client.get(
                f"/v1/jobs/{accepted['job_id']}/results", params={"workspace_id": workspace}
            )
            assert result == normal.json() and result["state"] == "completed"
            assert result["results"][0]["qualification"] == "unverified"
            usage = data(
                await mcp.call_tool("get_research", {"job_id": accepted["job_id"], "view": "usage"})
            )
            assert (
                usage
                == (
                    await client.get(
                        f"/v1/jobs/{accepted['job_id']}/usage", params={"workspace_id": workspace}
                    )
                ).json()
            )
            with database.tenant(actor, workspace) as session:
                assert (
                    session.execute(sa.select(sa.func.count()).select_from(admissions)).scalar_one()
                    == 1
                )


async def test_workspace_and_unsupported_tool_input_cannot_escape_api(database, monkeypatch):
    actor, workspace, _conversation, _app, client = setup(database, monkeypatch)
    other = database.create_workspace(actor, "Other owned workspace")["id"]
    with database.tenant(actor, other) as session:
        foreign = ConversationRepository.create(session, "Private foreign conversation")["id"]
    async with (
        client,
        create_connected_server_and_client_session(
            create_server(ProductMCP(client, UUID(workspace)))
        ) as mcp,
    ):
        result = await mcp.call_tool(
            "submit_research",
            {
                "conversation_id": foreign,
                "prompt": "Find companies",
                "sources": ["web"],
                "request_key": "foreign",
            },
        )
        assert result.isError and foreign not in result.content[0].text
        for name, arguments in [
            ("run_shell", {"command": "SENTINEL"}),
            ("list_conversations", {"workspace_id": other}),
            ("read_saved_snapshot", {"list_id": str(uuid4()), "revision": True}),
            ("list_saved_lists", {"token": "SENTINEL"}),
        ]:
            rejected = await mcp.call_tool(name, arguments)
            assert rejected.isError and "SENTINEL" not in rejected.content[0].text
        visible = data(await mcp.call_tool("list_conversations", {}))
        assert foreign not in {item["id"] for item in visible}


async def test_disabled_entitlement_and_invalid_auth_have_no_mcp_bypass(database, monkeypatch):
    actor, workspace, conversation, _app, client = setup(database, monkeypatch)
    with database.tenant(actor, workspace) as session:
        policy_for(session)
        session.execute(
            sa.update(policies).where(policies.c.workspace_id == workspace).values(enabled=False)
        )
    async with client:
        adapter = ProductMCP(client, UUID(workspace))
        result = await adapter.call_tool(
            "submit_research",
            {
                "conversation_id": conversation,
                "prompt": "Find software companies",
                "sources": ["web"],
                "request_key": "disabled",
            },
        )
        assert result.isError
        with database.tenant(actor, workspace) as session:
            assert (
                session.execute(sa.select(sa.func.count()).select_from(admissions)).scalar_one()
                == 0
            )
        client.headers.pop("Authorization")
        unauthenticated = await adapter.call_tool("list_conversations", {})
        assert unauthenticated.isError


async def test_copied_server_product_hook_never_constructs_host_doctor_config(
    database, monkeypatch
):
    import agent_reach.integrations.mcp_server as copied

    monkeypatch.setattr(
        copied, "Config", lambda **_: pytest.fail("No host-wide configuration may be loaded")
    )
    _actor, workspace, _conversation, _app, client = setup(database, monkeypatch)
    async with (
        client,
        create_connected_server_and_client_session(
            create_server(ProductMCP(client, UUID(workspace)))
        ) as mcp,
    ):
        assert data(await mcp.call_tool("list_saved_lists", {})) == []
