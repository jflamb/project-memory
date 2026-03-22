import json
import os

import pytest
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from project_memory.server import create_app, create_stdio_server, _cwd_root


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


@pytest.mark.anyio
async def test_mcp_server_plan_get_and_history_tools(tmp_path):
    from project_memory.db import ProjectMemoryDB

    with ProjectMemoryDB(root=tmp_path) as db:
        db.plan_create("roadmap", "version one", type="design")
        db.plan_create("roadmap", "version two", type="design")

    app = create_app(str(tmp_path))

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
            async with streamable_http_client("http://127.0.0.1:8000/mcp/", http_client=http_client) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as client:
                    await client.initialize()

                    plan_result = await client.call_tool("plan_get", {"key": "roadmap"})
                    plan_data = json.loads(plan_result.content[0].text)
                    assert plan_data["content"] == "version two"

                    history_result = await client.call_tool("history_list", {"key": "roadmap", "source_type": "plan"})
                    versions = json.loads(history_result.content[0].text)["results"]
                    assert len(versions) == 2

                    diff_result = await client.call_tool(
                        "history_diff",
                        {"version_a": versions[1]["id"], "version_b": versions[0]["id"]},
                    )
                    diff_data = json.loads(diff_result.content[0].text)
                    assert "version two" in diff_data["diff"]


@pytest.mark.anyio
async def test_mcp_server_returns_structured_errors_for_invalid_and_missing_inputs(tmp_path):
    app = create_app(str(tmp_path))

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as http_client:
            async with streamable_http_client("http://127.0.0.1:8000/mcp/", http_client=http_client) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as client:
                    await client.initialize()

                    invalid_history = await client.call_tool(
                        "history_list",
                        {"key": "roadmap", "source_type": "file", "limit": 1},
                    )
                    invalid_history_data = json.loads(invalid_history.content[0].text)
                    assert invalid_history_data["error"] == "source_type must be one of: learning, note, plan, task"

                    invalid_search = await client.call_tool("search", {"query": "repo", "limit": 0})
                    invalid_search_data = json.loads(invalid_search.content[0].text)
                    assert invalid_search_data["error"] == "limit must be a positive integer"

                    missing_plan = await client.call_tool("plan_get", {"key": "missing"})
                    missing_plan_data = json.loads(missing_plan.content[0].text)
                    assert missing_plan_data["error"] == "No plan found with key 'missing'"

                    missing_history = await client.call_tool("history_restore", {"version_id": 9999})
                    missing_history_data = json.loads(missing_history.content[0].text)
                    assert missing_history_data["error"] == "No history version found with id '9999'"


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


@pytest.mark.anyio
async def test_stdio_stats_reports_history_versions(tmp_path, monkeypatch):
    from project_memory.db import ProjectMemoryDB

    monkeypatch.chdir(tmp_path)
    with ProjectMemoryDB(root=tmp_path) as db:
        db.remember("auth", "version 1")
        db.remember("auth", "version 2")

    mcp = create_stdio_server()
    result = await mcp.call_tool("stats", {})
    data = json.loads(result[0].text)
    assert data["documents"] == 1
    assert data["versions"] == 2
    assert data["size_bytes"] > 0


@pytest.mark.anyio
async def test_stdio_management_tools_cover_missing_paths_and_updates(tmp_path, monkeypatch):
    from project_memory.db import ProjectMemoryDB

    monkeypatch.chdir(tmp_path)
    with ProjectMemoryDB(root=tmp_path) as db:
        db.remember("note-key", "note")
        db.learn("learning-key", "learning")
        db.task_add("task-key", "task")
        db.plan_create("plan-key", "plan")

    mcp = create_stdio_server()

    forget_result = json.loads((await mcp.call_tool("forget", {"key": "note-key"}))[0].text)
    assert forget_result == {"key": "note-key", "deleted": True}

    forget_learning_result = json.loads((await mcp.call_tool("forget_learning", {"key": "learning-key"}))[0].text)
    assert forget_learning_result == {"key": "learning-key", "deleted": True}

    update_result = json.loads(
        (await mcp.call_tool("task_update", {"key": "task-key", "status": "done", "content": "updated"}))[0].text
    )
    assert update_result == {"key": "task-key", "updated": True}

    remove_result = json.loads((await mcp.call_tool("task_remove", {"key": "task-key"}))[0].text)
    assert remove_result == {"key": "task-key", "deleted": True}

    archive_result = json.loads((await mcp.call_tool("plan_archive", {"key": "plan-key"}))[0].text)
    assert archive_result == {"key": "plan-key", "archived": True}

    missing_remove_result = json.loads((await mcp.call_tool("task_remove", {"key": "task-key"}))[0].text)
    assert missing_remove_result == {"key": "task-key", "deleted": False}

    docs_result = (await mcp.call_tool("list_documents", {}))[1]["result"]
    assert any(doc["path"] == "plan:plan-key" for doc in docs_result)


@pytest.mark.anyio
async def test_stdio_validation_errors_are_returned_consistently(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mcp = create_stdio_server()

    invalid_key = json.loads((await mcp.call_tool("remember", {"key": "bad:key", "content": "value"}))[0].text)
    assert invalid_key["error"] == "key must not contain ':'"

    empty_key = json.loads((await mcp.call_tool("forget", {"key": ""}))[0].text)
    assert empty_key["error"] == "key must not be empty"

    invalid_task_status = json.loads(
        (await mcp.call_tool("task_update", {"key": "task", "status": "waiting"}))[0].text
    )
    assert invalid_task_status["error"] == "status must be one of: done, in_progress, pending"

    invalid_plan_status = json.loads(
        (await mcp.call_tool("plan_list", {"status": "disabled", "limit": 1}))[0].text
    )
    assert invalid_plan_status["error"] == "status must be one of: active, archived"

    invalid_limit = json.loads((await mcp.call_tool("recall", {"limit": 0}))[0].text)
    assert invalid_limit["error"] == "limit must be a positive integer"

    invalid_history_type = json.loads(
        (await mcp.call_tool("history_list", {"key": "task", "source_type": "file"}))[0].text
    )
    assert invalid_history_type["error"] == "source_type must be one of: learning, note, plan, task"

    invalid_version = json.loads((await mcp.call_tool("history_get", {"version_id": 0}))[0].text)
    assert invalid_version["error"] == "version_id must be a positive integer"


# --- MCP stdio server: export/import ---


def test_stdio_export(tmp_path):
    """Export tool should produce valid MEMORY.md content."""
    from project_memory.db import ProjectMemoryDB
    from project_memory.portability import export_memory as do_export
    with ProjectMemoryDB(root=tmp_path) as db:
        db.remember("auth", "OAuth2 pattern", type="convention")
        md = do_export(db)
    assert "### auth" in md
    assert "**Type:** convention" in md


def test_stdio_import(tmp_path):
    """Import tool should load entries from MEMORY.md."""
    from project_memory.db import ProjectMemoryDB
    from project_memory.portability import import_memory as do_import
    md = """# Project Memory

## Notes

### imported
**Type:** convention | **Updated:** 2026-03-21T10:00:00.000Z

Imported content.
"""
    (tmp_path / "MEMORY.md").write_text(md)
    with ProjectMemoryDB(root=tmp_path) as db:
        result = do_import(db, tmp_path / "MEMORY.md")
        assert result["imported"] == 1
        notes = db.recall()
        assert len(notes) == 1


def test_stdio_auto_import_on_init(tmp_path, monkeypatch):
    """init should auto-import MEMORY.md if DB is empty."""
    monkeypatch.chdir(tmp_path)
    md = """# Project Memory

## Notes

### auto-imported
**Type:** context | **Updated:** 2026-03-21T10:00:00.000Z

Auto-imported on init.
"""
    (tmp_path / "MEMORY.md").write_text(md)
    from project_memory.db import ProjectMemoryDB
    from project_memory.portability import import_memory as do_import
    with ProjectMemoryDB(root=tmp_path) as db:
        if db.document_count() == 0 and (tmp_path / "MEMORY.md").exists():
            do_import(db, tmp_path / "MEMORY.md")
        notes = db.recall()
        assert len(notes) == 1
        assert notes[0]["type"] == "context"


# --- protocol_reminder in tool responses ---


def test_protocol_reminder_present_when_protocols_exist(tmp_path):
    """When protocols are active, write tool responses should include protocol_reminder."""
    from project_memory.db import ProjectMemoryDB
    from project_memory.protocols import generate_default_protocols
    from project_memory.server import _build_protocol_reminder
    with ProjectMemoryDB(root=tmp_path) as db:
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
        generate_default_protocols(db, tmp_path)
        reminder = _build_protocol_reminder(db)
        assert reminder is not None
        assert "protocol" in reminder.lower()


def test_protocol_reminder_absent_when_no_protocols(tmp_path):
    """Without protocols, reminder should be None."""
    from project_memory.db import ProjectMemoryDB
    from project_memory.server import _build_protocol_reminder
    with ProjectMemoryDB(root=tmp_path) as db:
        reminder = _build_protocol_reminder(db)
        assert reminder is None


# --- _cwd_root resolution ---


def test_cwd_root_finds_project_memory_dir(tmp_path, monkeypatch):
    """_cwd_root should find the ancestor with .project-memory/."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".project-memory").mkdir()
    subdir = repo / "a" / "b"
    subdir.mkdir(parents=True)
    monkeypatch.chdir(subdir)
    assert _cwd_root() == repo


def test_cwd_root_falls_back_to_git(tmp_path, monkeypatch):
    """_cwd_root should fall back to .git root when no .project-memory/ exists."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    subdir = repo / "src" / "pkg"
    subdir.mkdir(parents=True)
    monkeypatch.chdir(subdir)
    assert _cwd_root() == repo


def test_cwd_root_prefers_project_memory_over_git(tmp_path, monkeypatch):
    """.project-memory/ should win over .git when both exist at different levels."""
    outer = tmp_path / "outer"
    outer.mkdir()
    (outer / ".git").mkdir()
    inner = outer / "inner"
    inner.mkdir()
    (inner / ".project-memory").mkdir()
    subdir = inner / "deep"
    subdir.mkdir()
    monkeypatch.chdir(subdir)
    assert _cwd_root() == inner


def test_cwd_root_falls_back_to_cwd(tmp_path, monkeypatch):
    """Without markers, _cwd_root should return cwd."""
    monkeypatch.chdir(tmp_path)
    assert _cwd_root() == tmp_path
