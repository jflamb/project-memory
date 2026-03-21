import json

import pytest
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from project_memory.server import create_app


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
