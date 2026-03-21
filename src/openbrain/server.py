import contextlib
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .db import OpenBrainDB
from .index import index_repo as index_repository
from .search import search as search_repository


def _resolve_root(root: str | None) -> Path:
    return Path(root or ".").resolve()


def create_mcp_server(root: str | None = None) -> FastMCP:
    repo_root = _resolve_root(root)
    mcp = FastMCP(
        "OpenBrain",
        instructions="Repo-scoped memory for code indexing and search.",
        json_response=True,
        stateless_http=True,
        streamable_http_path="/",
    )

    @mcp.tool()
    def init() -> dict:
        """Initialize the repo-scoped SQLite memory store."""
        with OpenBrainDB(root=repo_root) as db:
            return {"status": "initialized", "db_path": str(db.db_path)}

    @mcp.tool()
    def index() -> dict:
        """Index supported text files from the repository into local memory."""
        return index_repository(root=str(repo_root))

    @mcp.tool()
    def search(query: str, limit: int = 20) -> list[dict]:
        """Search indexed repository content using normalized full-text terms."""
        return search_repository(query=query, root=str(repo_root), limit=limit)

    @mcp.tool()
    def list_documents() -> list[dict]:
        """List indexed documents by relative path."""
        with OpenBrainDB(root=repo_root) as db:
            return db.list_documents()

    return mcp


def create_app(root: str | None = None) -> Starlette:
    mcp = create_mcp_server(root=root)

    async def healthcheck(_request) -> JSONResponse:
        return JSONResponse({"status": "ok", "mcp_path": "/mcp/"})

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette):
        async with mcp.session_manager.run():
            yield

    return Starlette(
        routes=[
            Route("/", endpoint=healthcheck),
            Mount("/mcp", app=mcp.streamable_http_app()),
        ],
        lifespan=lifespan,
    )
