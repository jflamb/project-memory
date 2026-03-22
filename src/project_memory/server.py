import contextlib
import logging
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from typing import Optional

from .db import ProjectMemoryDB
from .index import index_repo as index_repository
from .portability import export_memory as do_export, import_memory as do_import
from .search import search as search_repository

VALID_HISTORY_SOURCE_TYPES = {"note", "learning", "task", "plan"}
VALID_TASK_STATUSES = {"pending", "in_progress", "done"}
VALID_PLAN_STATUSES = {"active", "archived"}
logger = logging.getLogger(__name__)


def _resolve_root(root: str | None) -> Path:
    return Path(root or ".").resolve()


def _cwd_root() -> Path:
    """Resolve repo root from current working directory.

    Walks up from cwd looking for an existing ``.project-memory/`` directory
    (preferred) or ``.git`` marker.  Falls back to cwd if neither is found.
    """
    cwd = Path(os.getcwd()).resolve()
    # First pass: look for an existing .project-memory directory
    cur = cwd
    while True:
        if (cur / ".project-memory").is_dir():
            return cur
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    # Second pass: fall back to .git root
    cur = cwd
    while True:
        if (cur / ".git").exists():
            return cur
        parent = cur.parent
        if parent == cur:
            break
        cur = parent
    return cwd


def _build_protocol_reminder(db: ProjectMemoryDB) -> Optional[str]:
    """Return a protocol reminder string if any active protocols exist, else None."""
    protocols = db.plan_list(type="protocol", status="active", limit=10)
    if not protocols:
        return None
    names = [p["path"].split(":", 1)[1] for p in protocols]
    return f"Active protocols: {', '.join(names)}. Check protocols for blast radius requirements before committing."


def _validate_key(key: str) -> Optional[str]:
    if not key or not key.strip():
        return "key must not be empty"
    if ":" in key:
        return "key must not contain ':'"
    return None


def _validate_limit(limit: int) -> Optional[str]:
    if limit <= 0:
        return "limit must be a positive integer"
    return None


def _validate_history_source_type(source_type: str) -> Optional[str]:
    if source_type not in VALID_HISTORY_SOURCE_TYPES:
        return "source_type must be one of: learning, note, plan, task"
    return None


def _validate_task_status(status: str) -> Optional[str]:
    if status and status not in VALID_TASK_STATUSES:
        return "status must be one of: done, in_progress, pending"
    return None


def _validate_plan_status(status: str) -> Optional[str]:
    if status and status not in VALID_PLAN_STATUSES:
        return "status must be one of: active, archived"
    return None


def _validate_version_id(version_id: int) -> Optional[str]:
    if version_id <= 0:
        return "version_id must be a positive integer"
    return None


class _BearerAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, token: str):
        super().__init__(app)
        self._expected = f"Bearer {token}"

    async def dispatch(self, request: Request, call_next):
        if request.url.path.startswith("/mcp"):
            if request.headers.get("authorization") != self._expected:
                logger.warning("Rejected unauthorized HTTP MCP request for %s", request.url.path)
                return JSONResponse({"error": "Unauthorized"}, status_code=401)
        return await call_next(request)


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
        if error := _validate_limit(limit):
            return [{"error": error}]
        return search_repository(query=query, root=str(repo_root), limit=limit)

    @mcp.tool()
    def list_documents() -> list[dict]:
        """List indexed documents by relative path."""
        with ProjectMemoryDB(root=repo_root) as db:
            return db.list_documents()

    @mcp.tool()
    def plan_get(key: str) -> dict:
        """Get a single plan by key. Returns the full plan content."""
        if error := _validate_key(key):
            return {"error": error}
        with ProjectMemoryDB(root=repo_root) as db:
            plan = db.plan_get(key)
        return plan or {"error": f"No plan found with key '{key}'"}

    @mcp.tool()
    def history_list(key: str, source_type: str, limit: int = 20) -> dict:
        """List immutable history snapshots for a typed memory entry."""
        if error := _validate_key(key):
            return {"error": error}
        if error := _validate_history_source_type(source_type):
            return {"error": error}
        if error := _validate_limit(limit):
            return {"error": error}
        with ProjectMemoryDB(root=repo_root) as db:
            results = db.history_list(key=key, source_type=source_type, limit=limit)
        return {"results": results}

    @mcp.tool()
    def history_get(version_id: int) -> dict:
        """Get a single history snapshot by version id."""
        if error := _validate_version_id(version_id):
            return {"error": error}
        with ProjectMemoryDB(root=repo_root) as db:
            version = db.history_get(version_id)
        return version or {"error": f"No history version found with id '{version_id}'"}

    @mcp.tool()
    def history_diff(version_a: int, version_b: int) -> dict:
        """Return a unified diff between two history snapshots."""
        if error := _validate_version_id(version_a):
            return {"error": error}
        if error := _validate_version_id(version_b):
            return {"error": error}
        with ProjectMemoryDB(root=repo_root) as db:
            diff = db.history_diff(version_a, version_b)
        return diff or {"error": "One or both history versions were not found"}

    @mcp.tool()
    def history_restore(version_id: int) -> dict:
        """Restore a history snapshot as the latest current state."""
        if error := _validate_version_id(version_id):
            return {"error": error}
        with ProjectMemoryDB(root=repo_root) as db:
            restored = db.history_restore(version_id)
        return restored or {"error": f"No history version found with id '{version_id}'"}

    return mcp


def create_stdio_server(root: str | None = None) -> FastMCP:
    """Create an MCP server for stdio transport.

    When *root* is given it is used directly as the repo root.  Otherwise
    the root is resolved from the current working directory on each tool
    call via ``_cwd_root()``.
    """
    resolved_root = Path(root).resolve() if root else None
    mcp = FastMCP(
        "Project Memory",
        instructions="Repo-scoped memory for code indexing and search. Operates on the current working directory.",
        json_response=True,
    )

    def _get_root() -> Path:
        return resolved_root or _cwd_root()

    def _ensure_db() -> ProjectMemoryDB:
        """Auto-init and return a database for the repo root."""
        return ProjectMemoryDB(root=_get_root())

    @mcp.tool()
    def index() -> dict:
        """Index supported text files from the repository into local memory. Auto-initializes if needed."""
        root = _get_root()
        return index_repository(root=str(root))

    @mcp.tool()
    def search(query: str, limit: int = 20) -> dict:
        """Search indexed repository content using keyword search (FTS5 bm25)."""
        if error := _validate_limit(limit):
            return {"error": error}
        root = _get_root()
        with ProjectMemoryDB(root=root) as db:
            results = db.search(query, limit=limit)
            search_mode = "keyword"
            for r in results:
                r["search_mode"] = search_mode
        response = {"results": results, "search_mode": search_mode}
        return response

    @mcp.tool()
    def list_documents() -> list[dict]:
        """List all indexed documents by relative path."""
        with _ensure_db() as db:
            return db.list_documents()

    @mcp.tool()
    def stats() -> dict:
        """Show database statistics: document count and database size."""
        root = _get_root()
        db_path = root / ".project-memory" / "project_memory.db"
        with _ensure_db() as db:
            count = db.document_count()
            version_count = db.history_version_count()
        if db_path.exists():
            size_bytes = db_path.stat().st_size
        else:
            size_bytes = 0
        return {"documents": count, "versions": version_count, "size_bytes": size_bytes}

    @mcp.tool()
    def remember(key: str, content: str, type: str = "") -> dict:
        """Store a note in project memory. Key is a short identifier (e.g. 'auth-pattern', 'deploy-steps'). Content is the text to remember. Provide a type to classify this note (e.g. 'convention', 'reference', 'decision'). Check existing types with recall first and reuse one if appropriate before introducing a new type."""
        if error := _validate_key(key):
            return {"error": error}
        with _ensure_db() as db:
            written = db.remember(key, content, type=type or None)
            reminder = _build_protocol_reminder(db)
        result = {"key": key, "written": written}
        if reminder:
            result["protocol_reminder"] = reminder
        return result

    @mcp.tool()
    def forget(key: str) -> dict:
        """Remove a note from project memory by key."""
        if error := _validate_key(key):
            return {"error": error}
        with _ensure_db() as db:
            deleted = db.forget(key)
        return {"key": key, "deleted": deleted}

    @mcp.tool()
    def recall(query: str = "", type: str = "", limit: int = 20) -> dict:
        """Retrieve notes from project memory. If query is given, search notes by content. If empty, list all notes. Filter by type if provided."""
        if error := _validate_limit(limit):
            return {"error": error}
        with _ensure_db() as db:
            results, types_in_use = db.recall_with_types(query=query or None, type=type or None, limit=limit)
        return {"results": results, "types_in_use": types_in_use}

    # --- Learnings ---

    @mcp.tool()
    def learn(key: str, content: str, type: str = "") -> dict:
        """Store a learning — knowledge discovered during development (e.g. 'sqlite-alter-limits', 'fts5-trigger-pattern'). Content is what was learned. Provide a type to classify this learning (e.g. 'gotcha', 'pattern', 'tool-tip'). Check existing types with recall_learnings first and reuse one if appropriate before introducing a new type."""
        if error := _validate_key(key):
            return {"error": error}
        with _ensure_db() as db:
            written = db.learn(key, content, type=type or None)
            reminder = _build_protocol_reminder(db)
        result = {"key": key, "written": written}
        if reminder:
            result["protocol_reminder"] = reminder
        return result

    @mcp.tool()
    def recall_learnings(query: str = "", type: str = "", limit: int = 20) -> dict:
        """Retrieve learnings. If query is given, search by content. If empty, list all learnings. Filter by type if provided."""
        if error := _validate_limit(limit):
            return {"error": error}
        with _ensure_db() as db:
            results, types_in_use = db.recall_learnings_with_types(query=query or None, type=type or None, limit=limit)
        return {"results": results, "types_in_use": types_in_use}

    @mcp.tool()
    def forget_learning(key: str) -> dict:
        """Remove a learning by key."""
        if error := _validate_key(key):
            return {"error": error}
        with _ensure_db() as db:
            deleted = db.forget_learning(key)
        return {"key": key, "deleted": deleted}

    # --- Tasks ---

    @mcp.tool()
    def task_add(key: str, content: str, group: str = "", type: str = "") -> dict:
        """Add a task with status 'pending'. Key is a short identifier. Group is optional (e.g. 'v0.2', 'auth-feature'). Provide a type to classify this task (e.g. 'bug', 'feature', 'chore', 'spike'). After adding, assess blast radius per project protocols."""
        if error := _validate_key(key):
            return {"error": error}
        with _ensure_db() as db:
            written = db.task_add(key, content, group=group or None, type=type or None)
            reminder = _build_protocol_reminder(db)
        result = {"key": key, "written": written}
        if reminder:
            result["protocol_reminder"] = reminder
        return result

    @mcp.tool()
    def task_update(key: str, status: str = "", content: str = "", group: str = "") -> dict:
        """Update a task. Status can be 'pending', 'in_progress', or 'done'. Only provided fields are changed."""
        if error := _validate_key(key):
            return {"error": error}
        if error := _validate_task_status(status):
            return {"error": error}
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
        if error := _validate_task_status(status):
            return {"error": error}
        if error := _validate_limit(limit):
            return {"error": error}
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
        if error := _validate_key(key):
            return {"error": error}
        with _ensure_db() as db:
            deleted = db.task_remove(key)
        return {"key": key, "deleted": deleted}

    # --- Plans ---

    @mcp.tool()
    def plan_create(key: str, content: str, type: str = "") -> dict:
        """Create or update a plan. Content is markdown. Status starts as 'active'. Provide a type to classify this plan (e.g. 'protocol', 'design', 'checklist')."""
        if error := _validate_key(key):
            return {"error": error}
        with _ensure_db() as db:
            written = db.plan_create(key, content, type=type or None)
            reminder = _build_protocol_reminder(db)
        result = {"key": key, "written": written}
        if reminder:
            result["protocol_reminder"] = reminder
        return result

    @mcp.tool()
    def plan_get(key: str) -> dict:
        """Get a single plan by key. Returns the full plan content."""
        if error := _validate_key(key):
            return {"error": error}
        with _ensure_db() as db:
            plan = db.plan_get(key)
        return plan or {"error": f"No plan found with key '{key}'"}

    @mcp.tool()
    def plan_list(status: str = "active", type: str = "", query: str = "", limit: int = 20) -> dict:
        """List plans. Defaults to active plans. Set status to 'archived' or '' for all. Filter by type if provided."""
        if error := _validate_plan_status(status):
            return {"error": error}
        if error := _validate_limit(limit):
            return {"error": error}
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
        if error := _validate_key(key):
            return {"error": error}
        with _ensure_db() as db:
            archived = db.plan_archive(key)
        return {"key": key, "archived": archived}

    @mcp.tool()
    def history_list(key: str, source_type: str, limit: int = 20) -> dict:
        """List immutable history snapshots for a typed memory entry."""
        if error := _validate_key(key):
            return {"error": error}
        if error := _validate_history_source_type(source_type):
            return {"error": error}
        if error := _validate_limit(limit):
            return {"error": error}
        with _ensure_db() as db:
            results = db.history_list(key=key, source_type=source_type, limit=limit)
        return {"results": results}

    @mcp.tool()
    def history_get(version_id: int) -> dict:
        """Get a single history snapshot by version id."""
        if error := _validate_version_id(version_id):
            return {"error": error}
        with _ensure_db() as db:
            version = db.history_get(version_id)
        return version or {"error": f"No history version found with id '{version_id}'"}

    @mcp.tool()
    def history_diff(version_a: int, version_b: int) -> dict:
        """Return a unified diff between two history snapshots."""
        if error := _validate_version_id(version_a):
            return {"error": error}
        if error := _validate_version_id(version_b):
            return {"error": error}
        with _ensure_db() as db:
            diff = db.history_diff(version_a, version_b)
        return diff or {"error": "One or both history versions were not found"}

    @mcp.tool()
    def history_restore(version_id: int) -> dict:
        """Restore a history snapshot as the latest current state."""
        if error := _validate_version_id(version_id):
            return {"error": error}
        with _ensure_db() as db:
            restored = db.history_restore(version_id)
        return restored or {"error": f"No history version found with id '{version_id}'"}

    # --- Export / Import ---

    @mcp.tool()
    def export_memory() -> dict:
        """Export memory entries to MEMORY.md in the repo root. Returns the file path."""
        root = _get_root()
        with _ensure_db() as db:
            md = do_export(db)
        out_path = root / "MEMORY.md"
        out_path.write_text(md, encoding="utf-8")
        return {"path": str(out_path), "exported": True}

    @mcp.tool()
    def import_memory() -> dict:
        """Import entries from MEMORY.md in the repo root. Idempotent — unchanged entries are skipped."""
        root = _get_root()
        md_path = root / "MEMORY.md"
        if not md_path.exists():
            return {"error": "MEMORY.md not found", "imported": 0, "skipped": 0}
        with _ensure_db() as db:
            return do_import(db, md_path)

    return mcp


def create_app(root: str | None = None, auth_token: str | None = None) -> Starlette:
    token = auth_token or os.environ.get("PROJECT_MEMORY_MCP_AUTH_TOKEN")
    if not token:
        raise ValueError("auth_token is required for HTTP MCP")
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
        middleware=[Middleware(_BearerAuthMiddleware, token=token)],
    )
