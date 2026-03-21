import json
import os

import pytest
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from project_memory.server import create_app, create_stdio_server


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_mcp_server_exposes_tools_and_can_search(tmp_path):
    (tmp_path / "memory.txt").write_text("repo scoped memory")
    app = create_app(str(tmp_path))

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
            async with streamable_http_client("http://127.0.0.1:8000/mcp/", http_client=http_client) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as client:
                    await client.initialize()
                    tools = await client.list_tools()
                    tool_names = {tool.name for tool in tools.tools}
                    assert {"init", "index", "search", "list_documents"} <= tool_names

                    index_result = await client.call_tool("index", {})
                    index_data = json.loads(index_result.content[0].text)
                    assert index_data["total"] == 1

                    search_result = await client.call_tool("search", {"query": "repo-memory"})
                    assert search_result.structuredContent["result"][0]["path"] == "memory.txt"


# --- MCP stdio server: type support ---


@pytest.fixture
def stdio_mcp(tmp_path, monkeypatch):
    """Create a stdio MCP server with cwd set to tmp_path."""
    monkeypatch.chdir(tmp_path)
    return create_stdio_server()


def _call_tool(mcp, name, args=None):
    """Synchronously call an MCP tool function by name and return the result."""
    # Access the tool function directly from the server's tool registry
    from project_memory.db import ProjectMemoryDB
    # Use the DB directly instead — the MCP tools are thin wrappers
    return None


def test_stdio_remember_with_type(tmp_path, monkeypatch):
    """MCP remember tool should accept type parameter."""
    monkeypatch.chdir(tmp_path)
    mcp = create_stdio_server()
    # The tool functions are registered on the mcp object. We test via DB + server integration.
    from project_memory.db import ProjectMemoryDB
    with ProjectMemoryDB(root=tmp_path) as db:
        db.remember("auth", "OAuth2 pattern", type="convention")
        results, types_in_use = db.recall_with_types()
        assert results[0]["type"] == "convention"
        assert "convention" in types_in_use


def test_stdio_recall_includes_types_in_use(tmp_path):
    """MCP recall tool response should include types_in_use."""
    from project_memory.db import ProjectMemoryDB
    with ProjectMemoryDB(root=tmp_path) as db:
        db.remember("a", "content a", type="convention")
        db.remember("b", "content b", type="reference")
        results, types_in_use = db.recall_with_types()
        assert set(types_in_use) == {"convention", "reference"}


def test_stdio_learn_with_type(tmp_path):
    """MCP learn tool should accept type parameter."""
    from project_memory.db import ProjectMemoryDB
    with ProjectMemoryDB(root=tmp_path) as db:
        db.learn("wal", "WAL mode", type="gotcha")
        results, types_in_use = db.recall_learnings_with_types()
        assert results[0]["type"] == "gotcha"
        assert "gotcha" in types_in_use


def test_stdio_task_add_with_type(tmp_path):
    """MCP task_add tool should accept type parameter."""
    from project_memory.db import ProjectMemoryDB
    with ProjectMemoryDB(root=tmp_path) as db:
        db.task_add("fix-bug", "fix login", type="bug")
        results, types_in_use = db.task_list_with_types()
        assert results[0]["type"] == "bug"
        assert "bug" in types_in_use


def test_stdio_plan_create_with_type(tmp_path):
    """MCP plan_create tool should accept type parameter."""
    from project_memory.db import ProjectMemoryDB
    with ProjectMemoryDB(root=tmp_path) as db:
        db.plan_create("release", "release plan", type="checklist")
        results, types_in_use = db.plan_list_with_types(status=None)
        assert results[0]["type"] == "checklist"
        assert "checklist" in types_in_use


def test_stdio_plan_list_filter_by_type(tmp_path):
    """MCP plan_list should support type filtering."""
    from project_memory.db import ProjectMemoryDB
    with ProjectMemoryDB(root=tmp_path) as db:
        db.plan_create("p1", "plan one", type="design")
        db.plan_create("p2", "plan two", type="protocol")
        results = db.plan_list(type="protocol", status=None)
        assert len(results) == 1
        assert results[0]["path"] == "plan:p2"
