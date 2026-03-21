import contextlib
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .db import ProjectMemoryDB
from .index import index_repo as index_repository
from .search import search as search_repository


def _resolve_root(root: str | None) -> Path:
    return Path(root or ".").resolve()


def _cwd_root() -> Path:
    """Resolve repo root from current working directory."""
    return Path(os.getcwd()).resolve()


def create_mcp_server(root: str | None = None) -> FastMCP:
    repo_root = _resolve_root(root)
    mcp = FastMCP(
        "Project Memory",
        instructions="Repo-scoped memory for code indexing and search.",
        json_response=True,
        stateless_http=True,
        streamable_http_path="/",
    )

    @mcp.tool()
    def init() -> dict:
        """Initialize the repo-scoped SQLite memory store."""
        with ProjectMemoryDB(root=repo_root) as db:
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
        with ProjectMemoryDB(root=repo_root) as db:
            return db.list_documents()

    return mcp


def create_stdio_server() -> FastMCP:
    """Create an MCP server for stdio transport. Resolves repo root from cwd on each call."""
    mcp = FastMCP(
        "Project Memory",
        instructions="Repo-scoped memory for code indexing and search. Operates on the current working directory.",
        json_response=True,
    )

    def _ensure_db() -> ProjectMemoryDB:
        """Auto-init and return a database for cwd."""
        return ProjectMemoryDB(root=_cwd_root())

    @mcp.tool()
    def index() -> dict:
        """Index supported text files from the repository into local memory. Auto-initializes if needed."""
        root = _cwd_root()
        return index_repository(root=str(root))

    @mcp.tool()
    def search(query: str, limit: int = 20) -> list[dict]:
        """Search indexed repository content using full-text search with bm25 ranking."""
        root = _cwd_root()
        with ProjectMemoryDB(root=root) as db:
            return db.search(query, limit=limit)

    @mcp.tool()
    def list_documents() -> list[dict]:
        """List all indexed documents by relative path."""
        with _ensure_db() as db:
            return db.list_documents()

    @mcp.tool()
    def stats() -> dict:
        """Show database statistics: document count and database size."""
        root = _cwd_root()
        db_path = root / ".project-memory" / "project_memory.db"
        with _ensure_db() as db:
            count = db.document_count()
        if db_path.exists():
            size_bytes = db_path.stat().st_size
        else:
            size_bytes = 0
        return {"documents": count, "size_bytes": size_bytes}

    @mcp.tool()
    def remember(key: str, content: str, type: str = "") -> dict:
        """Store a note in project memory. Key is a short identifier (e.g. 'auth-pattern', 'deploy-steps'). Content is the text to remember. Provide a type to classify this note (e.g. 'convention', 'reference', 'decision'). Check existing types with recall first and reuse one if appropriate before introducing a new type."""
        with _ensure_db() as db:
            written = db.remember(key, content, type=type or None)
        return {"key": key, "written": written}

    @mcp.tool()
    def forget(key: str) -> dict:
        """Remove a note from project memory by key."""
        with _ensure_db() as db:
            deleted = db.forget(key)
        return {"key": key, "deleted": deleted}

    @mcp.tool()
    def recall(query: str = "", type: str = "", limit: int = 20) -> dict:
        """Retrieve notes from project memory. If query is given, search notes by content. If empty, list all notes. Filter by type if provided."""
        with _ensure_db() as db:
            results, types_in_use = db.recall_with_types(query=query or None, type=type or None, limit=limit)
        return {"results": results, "types_in_use": types_in_use}

    # --- Learnings ---

    @mcp.tool()
    def learn(key: str, content: str, type: str = "") -> dict:
        """Store a learning — knowledge discovered during development (e.g. 'sqlite-alter-limits', 'fts5-trigger-pattern'). Content is what was learned. Provide a type to classify this learning (e.g. 'gotcha', 'pattern', 'tool-tip'). Check existing types with recall_learnings first and reuse one if appropriate before introducing a new type."""
        with _ensure_db() as db:
            written = db.learn(key, content, type=type or None)
        return {"key": key, "written": written}

    @mcp.tool()
    def recall_learnings(query: str = "", type: str = "", limit: int = 20) -> dict:
        """Retrieve learnings. If query is given, search by content. If empty, list all learnings. Filter by type if provided."""
        with _ensure_db() as db:
            results, types_in_use = db.recall_learnings_with_types(query=query or None, type=type or None, limit=limit)
        return {"results": results, "types_in_use": types_in_use}

    @mcp.tool()
    def forget_learning(key: str) -> dict:
        """Remove a learning by key."""
        with _ensure_db() as db:
            deleted = db.forget_learning(key)
        return {"key": key, "deleted": deleted}

    # --- Tasks ---

    @mcp.tool()
    def task_add(key: str, content: str, group: str = "", type: str = "") -> dict:
        """Add a task with status 'pending'. Key is a short identifier. Group is optional (e.g. 'v0.2', 'auth-feature'). Provide a type to classify this task (e.g. 'bug', 'feature', 'chore', 'spike')."""
        with _ensure_db() as db:
            written = db.task_add(key, content, group=group or None, type=type or None)
        return {"key": key, "written": written}

    @mcp.tool()
    def task_update(key: str, status: str = "", content: str = "", group: str = "") -> dict:
        """Update a task. Status can be 'pending', 'in_progress', or 'done'. Only provided fields are changed."""
        with _ensure_db() as db:
            updated = db.task_update(
                key,
                status=status or None,
                content=content or None,
                group=group or None,
            )
        return {"key": key, "updated": updated}

    @mcp.tool()
    def task_list(status: str = "", group: str = "", type: str = "", query: str = "", limit: int = 50) -> dict:
        """List tasks. Filter by status ('pending', 'in_progress', 'done'), group, and/or type. Search by content with query."""
        with _ensure_db() as db:
            results, types_in_use = db.task_list_with_types(
                status=status or None,
                group=group or None,
                type=type or None,
                query=query or None,
                limit=limit,
            )
        return {"results": results, "types_in_use": types_in_use}

    @mcp.tool()
    def task_remove(key: str) -> dict:
        """Remove a task by key."""
        with _ensure_db() as db:
            deleted = db.task_remove(key)
        return {"key": key, "deleted": deleted}

    # --- Plans ---

    @mcp.tool()
    def plan_create(key: str, content: str, type: str = "") -> dict:
        """Create or update a plan. Content is markdown. Status starts as 'active'. Provide a type to classify this plan (e.g. 'protocol', 'design', 'checklist')."""
        with _ensure_db() as db:
            written = db.plan_create(key, content, type=type or None)
        return {"key": key, "written": written}

    @mcp.tool()
    def plan_get(key: str) -> dict:
        """Get a single plan by key. Returns the full plan content."""
        with _ensure_db() as db:
            plan = db.plan_get(key)
        return plan or {"error": f"No plan found with key '{key}'"}

    @mcp.tool()
    def plan_list(status: str = "active", type: str = "", query: str = "", limit: int = 20) -> dict:
        """List plans. Defaults to active plans. Set status to 'archived' or '' for all. Filter by type if provided."""
        with _ensure_db() as db:
            results, types_in_use = db.plan_list_with_types(
                status=status or None,
                type=type or None,
                query=query or None,
                limit=limit,
            )
        return {"results": results, "types_in_use": types_in_use}

    @mcp.tool()
    def plan_archive(key: str) -> dict:
        """Archive a plan (mark as done). Archived plans are hidden from default plan_list."""
        with _ensure_db() as db:
            archived = db.plan_archive(key)
        return {"key": key, "archived": archived}

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
