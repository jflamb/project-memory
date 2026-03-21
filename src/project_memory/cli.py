import json
import os
from enum import Enum
from pathlib import Path
from typing import Annotated, Optional

import typer

from .db import ProjectMemoryDB
from .index import index_repo
from .portability import export_memory, import_memory
from .protocols import generate_default_protocols
from .search import search as search_docs
from .server import create_app, create_stdio_server

app = typer.Typer(help="Project Memory — repo-scoped memory engine for AI agents")
task_app = typer.Typer(help="Manage tasks")
plan_app = typer.Typer(help="Manage plans")
app.add_typer(task_app, name="task")
app.add_typer(plan_app, name="plan")

RepoPath = Annotated[
    str, typer.Option("--path", "-p", help="Repository root", envvar="PROJECT_MEMORY_ROOT")
]


class OutputFormat(str, Enum):
    table = "table"
    json = "json"
    plain = "plain"


def _format_list(results: list[dict], prefix: str, output_format: OutputFormat, empty_msg: str):
    """Shared formatting for list-style commands."""
    if not results:
        typer.echo(empty_msg, err=True)
        raise typer.Exit(code=0)

    if output_format == OutputFormat.json:
        typer.echo(json.dumps(results, indent=2))
    elif output_format == OutputFormat.plain:
        for r in results:
            key = r["path"].removeprefix(f"{prefix}:")
            typer.echo(f"{key}: {r['content'][:100]}")
    else:
        for r in results:
            key = r["path"].removeprefix(f"{prefix}:")
            status = f" ({r['status']})" if r.get("status") else ""
            group = f" [{r['group']}]" if r.get("group") else ""
            entry_type = f" <{r['type']}>" if r.get("type") else ""
            typer.echo(f"[{key}]{status}{group}{entry_type}")
            typer.echo(f"  {r['content'][:300]}\n")


# --- Core commands ---


@app.command()
def init(
    protocols: bool = typer.Option(False, "--protocols", help="Generate default development protocols"),
    path: RepoPath = ".",
):
    """Initialize project memory database."""
    try:
        root = Path(path).resolve()
        with ProjectMemoryDB(root=root) as db:
            typer.echo(f"Initialized project memory database at {db.db_path}")
            # Auto-import MEMORY.md if present and DB is empty
            memory_md = root / "MEMORY.md"
            if memory_md.exists() and db.document_count() == 0:
                result = import_memory(db, memory_md)
                if result["imported"] > 0:
                    typer.echo(f"Auto-imported {result['imported']} entries from MEMORY.md")
            # Generate protocols if requested
            if protocols:
                keys = generate_default_protocols(db, root)
                typer.echo(f"Generated {len(keys)} protocol(s): {', '.join(keys)}")
    except PermissionError:
        typer.echo("Error: No write permission for this directory", err=True)
        raise typer.Exit(code=1)


@app.command()
def index(path: RepoPath = "."):
    """Index text files in the repository."""
    root = Path(path).resolve()
    if not (root / ".project-memory").exists():
        typer.echo("Error: No project memory database found. Run 'project-memory init' first.", err=True)
        raise typer.Exit(code=1)
    result = index_repo(root=str(root))
    typer.echo(f"Indexed {result['total']} documents ({result['skipped']} unchanged, {result['deleted']} removed)")


@app.command("search")
def search_command(
    query: str = typer.Argument(..., help="Search query"),
    path: RepoPath = ".",
    output_format: OutputFormat = typer.Option(OutputFormat.table, "--format", "-f", help="Output format"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
):
    """Search indexed repository content."""
    root = Path(path).resolve()
    if not (root / ".project-memory").exists():
        typer.echo("Error: No project memory database found. Run 'project-memory init' first.", err=True)
        raise typer.Exit(code=1)

    results = search_docs(query=query, root=str(root), limit=limit)
    if not results:
        typer.echo("No hits", err=True)
        raise typer.Exit(code=0)

    if output_format == OutputFormat.json:
        typer.echo(json.dumps(results, indent=2))
    elif output_format == OutputFormat.plain:
        for doc in results:
            typer.echo(f"{doc['path']}: {doc['content'][:100]}")
    else:
        for doc in results:
            typer.echo(f"[{doc['id']}] {doc['path']}")
            snippet = doc["content"][:300].replace("\n", " ")
            typer.echo(f"  {snippet}...\n")


@app.command()
def stats(path: RepoPath = "."):
    """Show database statistics."""
    root = Path(path).resolve()
    db_path = root / ".project-memory" / "project_memory.db"
    if not db_path.exists():
        typer.echo("Error: No project memory database found. Run 'project-memory init' first.", err=True)
        raise typer.Exit(code=1)

    with ProjectMemoryDB(root=root) as db:
        count = db.document_count()
    size_bytes = db_path.stat().st_size
    if size_bytes < 1024:
        size_str = f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        size_str = f"{size_bytes / 1024:.1f} KB"
    else:
        size_str = f"{size_bytes / (1024 * 1024):.1f} MB"
    typer.echo(f"Documents: {count}")
    typer.echo(f"Database size: {size_str}")


# --- Export / Import ---


@app.command("export")
def export_command(
    output: str = typer.Option("", "--output", "-o", help="Output file path (default: MEMORY.md in repo root)"),
    path: RepoPath = ".",
):
    """Export project memory to a MEMORY.md file."""
    root = Path(path).resolve()
    if not (root / ".project-memory").exists():
        typer.echo("Error: No project memory database found. Run 'project-memory init' first.", err=True)
        raise typer.Exit(code=1)

    with ProjectMemoryDB(root=root) as db:
        md = export_memory(db)

    out_path = Path(output) if output else root / "MEMORY.md"
    out_path.write_text(md, encoding="utf-8")
    typer.echo(f"Exported to {out_path}")


@app.command("import")
def import_command(
    input_file: str = typer.Option("", "--input", "-i", help="Input file path (default: MEMORY.md in repo root)"),
    path: RepoPath = ".",
):
    """Import project memory from a MEMORY.md file."""
    root = Path(path).resolve()
    if not (root / ".project-memory").exists():
        typer.echo("Error: No project memory database found. Run 'project-memory init' first.", err=True)
        raise typer.Exit(code=1)

    in_path = Path(input_file) if input_file else root / "MEMORY.md"
    if not in_path.exists():
        typer.echo(f"Error: {in_path} not found", err=True)
        raise typer.Exit(code=1)

    with ProjectMemoryDB(root=root) as db:
        result = import_memory(db, in_path)
    typer.echo(f"Imported {result['imported']} entries ({result['skipped']} skipped)")


# --- Notes ---


@app.command()
def remember(
    key: str = typer.Argument(..., help="Short identifier for this note"),
    content: str = typer.Argument(..., help="Text to remember"),
    type: str = typer.Option("", "--type", "-t", help="Classification type (e.g. convention, reference, decision)"),
    path: RepoPath = ".",
):
    """Store a note in project memory."""
    with ProjectMemoryDB(root=Path(path).resolve()) as db:
        written = db.remember(key, content, type=type or None)
    if written:
        typer.echo(f"Remembered '{key}'")
    else:
        typer.echo(f"'{key}' unchanged", err=True)


@app.command()
def forget(
    key: str = typer.Argument(..., help="Key of the note to remove"),
    path: RepoPath = ".",
):
    """Remove a note from project memory."""
    with ProjectMemoryDB(root=Path(path).resolve()) as db:
        deleted = db.forget(key)
    if deleted:
        typer.echo(f"Forgot '{key}'")
    else:
        typer.echo(f"No note found with key '{key}'", err=True)
        raise typer.Exit(code=1)


@app.command()
def recall(
    query: str = typer.Argument("", help="Search query (empty lists all notes)"),
    type: str = typer.Option("", "--type", "-t", help="Filter by type"),
    path: RepoPath = ".",
    output_format: OutputFormat = typer.Option(OutputFormat.table, "--format", "-f", help="Output format"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
):
    """Retrieve notes from project memory."""
    with ProjectMemoryDB(root=Path(path).resolve()) as db:
        results = db.recall(query=query or None, type=type or None, limit=limit)
    _format_list(results, "note", output_format, "No notes found")


# --- Learnings ---


@app.command()
def learn(
    key: str = typer.Argument(..., help="Short identifier for this learning"),
    content: str = typer.Argument(..., help="What was learned"),
    type: str = typer.Option("", "--type", "-t", help="Classification type (e.g. gotcha, pattern, tool-tip)"),
    path: RepoPath = ".",
):
    """Store a learning — knowledge discovered during development."""
    with ProjectMemoryDB(root=Path(path).resolve()) as db:
        written = db.learn(key, content, type=type or None)
    if written:
        typer.echo(f"Learned '{key}'")
    else:
        typer.echo(f"'{key}' unchanged", err=True)


@app.command("recall-learnings")
def recall_learnings_command(
    query: str = typer.Argument("", help="Search query (empty lists all)"),
    type: str = typer.Option("", "--type", "-t", help="Filter by type"),
    path: RepoPath = ".",
    output_format: OutputFormat = typer.Option(OutputFormat.table, "--format", "-f", help="Output format"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
):
    """Retrieve learnings from project memory."""
    with ProjectMemoryDB(root=Path(path).resolve()) as db:
        results = db.recall_learnings(query=query or None, type=type or None, limit=limit)
    _format_list(results, "learning", output_format, "No learnings found")


@app.command("forget-learning")
def forget_learning_command(
    key: str = typer.Argument(..., help="Key of the learning to remove"),
    path: RepoPath = ".",
):
    """Remove a learning from project memory."""
    with ProjectMemoryDB(root=Path(path).resolve()) as db:
        deleted = db.forget_learning(key)
    if deleted:
        typer.echo(f"Forgot learning '{key}'")
    else:
        typer.echo(f"No learning found with key '{key}'", err=True)
        raise typer.Exit(code=1)


# --- Tasks ---


@task_app.command("add")
def task_add_command(
    key: str = typer.Argument(..., help="Short identifier for this task"),
    content: str = typer.Argument(..., help="Task description"),
    group: str = typer.Option("", "--group", "-g", help="Group name (e.g. 'v0.2', 'auth-feature')"),
    type: str = typer.Option("", "--type", "-t", help="Classification type (e.g. bug, feature, chore)"),
    path: RepoPath = ".",
):
    """Add a task."""
    with ProjectMemoryDB(root=Path(path).resolve()) as db:
        db.task_add(key, content, group=group or None, type=type or None)
    typer.echo(f"Added task '{key}'" + (f" [{group}]" if group else ""))


@task_app.command("list")
def task_list_command(
    status: str = typer.Option("", "--status", "-s", help="Filter by status (pending/in_progress/done)"),
    group: str = typer.Option("", "--group", "-g", help="Filter by group"),
    type: str = typer.Option("", "--type", "-t", help="Filter by type (e.g. bug, feature, chore)"),
    query: str = typer.Argument("", help="Search query"),
    path: RepoPath = ".",
    output_format: OutputFormat = typer.Option(OutputFormat.table, "--format", "-f", help="Output format"),
    limit: int = typer.Option(50, "--limit", "-n", help="Max results"),
):
    """List tasks."""
    with ProjectMemoryDB(root=Path(path).resolve()) as db:
        results = db.task_list(status=status or None, group=group or None, type=type or None, query=query or None, limit=limit)
    _format_list(results, "task", output_format, "No tasks found")


@task_app.command("update")
def task_update_command(
    key: str = typer.Argument(..., help="Task key"),
    status: str = typer.Option("", "--status", "-s", help="New status (pending/in_progress/done)"),
    content: str = typer.Option("", "--content", "-c", help="New description"),
    group: str = typer.Option("", "--group", "-g", help="New group"),
    path: RepoPath = ".",
):
    """Update a task's status, content, or group."""
    with ProjectMemoryDB(root=Path(path).resolve()) as db:
        updated = db.task_update(key, status=status or None, content=content or None, group=group or None)
    if updated:
        typer.echo(f"Updated task '{key}'")
    else:
        typer.echo(f"No task found with key '{key}'", err=True)
        raise typer.Exit(code=1)


@task_app.command("remove")
def task_remove_command(
    key: str = typer.Argument(..., help="Task key to remove"),
    path: RepoPath = ".",
):
    """Remove a task."""
    with ProjectMemoryDB(root=Path(path).resolve()) as db:
        deleted = db.task_remove(key)
    if deleted:
        typer.echo(f"Removed task '{key}'")
    else:
        typer.echo(f"No task found with key '{key}'", err=True)
        raise typer.Exit(code=1)


# --- Plans ---


@plan_app.command("create")
def plan_create_command(
    key: str = typer.Argument(..., help="Short identifier for this plan"),
    content: str = typer.Argument(..., help="Plan content (markdown)"),
    type: str = typer.Option("", "--type", "-t", help="Classification type (e.g. protocol, design, checklist)"),
    path: RepoPath = ".",
):
    """Create or update a plan."""
    with ProjectMemoryDB(root=Path(path).resolve()) as db:
        db.plan_create(key, content, type=type or None)
    typer.echo(f"Created plan '{key}'")


@plan_app.command("get")
def plan_get_command(
    key: str = typer.Argument(..., help="Plan key"),
    path: RepoPath = ".",
    output_format: OutputFormat = typer.Option(OutputFormat.table, "--format", "-f", help="Output format"),
):
    """Get a plan by key."""
    with ProjectMemoryDB(root=Path(path).resolve()) as db:
        plan = db.plan_get(key)
    if not plan:
        typer.echo(f"No plan found with key '{key}'", err=True)
        raise typer.Exit(code=1)

    if output_format == OutputFormat.json:
        typer.echo(json.dumps(plan, indent=2))
    else:
        typer.echo(f"[{key}] ({plan['status']})")
        typer.echo(plan["content"])


@plan_app.command("list")
def plan_list_command(
    status: str = typer.Option("active", "--status", "-s", help="Filter by status (active/archived, empty for all)"),
    type: str = typer.Option("", "--type", "-t", help="Filter by type (e.g. protocol, design, checklist)"),
    query: str = typer.Argument("", help="Search query"),
    path: RepoPath = ".",
    output_format: OutputFormat = typer.Option(OutputFormat.table, "--format", "-f", help="Output format"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
):
    """List plans."""
    with ProjectMemoryDB(root=Path(path).resolve()) as db:
        results = db.plan_list(status=status or None, type=type or None, query=query or None, limit=limit)
    _format_list(results, "plan", output_format, "No plans found")


@plan_app.command("archive")
def plan_archive_command(
    key: str = typer.Argument(..., help="Plan key to archive"),
    path: RepoPath = ".",
):
    """Archive a plan."""
    with ProjectMemoryDB(root=Path(path).resolve()) as db:
        archived = db.plan_archive(key)
    if archived:
        typer.echo(f"Archived plan '{key}'")
    else:
        typer.echo(f"No active plan found with key '{key}'", err=True)
        raise typer.Exit(code=1)


# --- Server commands ---


@app.command("serve-stdio")
def serve_stdio_command():
    """Run the MCP server over stdio for AI agent integration."""
    mcp = create_stdio_server()
    mcp.run(transport="stdio")


@app.command("serve-mcp")
def serve_mcp_command(
    host: str = typer.Option("127.0.0.1", help="Host to bind"),
    port: int = typer.Option(8000, help="Port to bind"),
    path: RepoPath = ".",
):
    """Run the MCP HTTP server."""
    import uvicorn

    mcp_app = create_app(root=path)
    typer.echo(f"Starting MCP server on http://{host}:{port}/mcp/")
    uvicorn.run(mcp_app, host=host, port=port)


if __name__ == "__main__":
    app()
