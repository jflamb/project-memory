import json
import os
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer

from .db import OpenBrainDB
from .index import index_repo
from .search import search as search_docs
from .server import create_app, create_stdio_server

app = typer.Typer(help="OpenBrain — repo-scoped memory engine for AI agents")

RepoPath = Annotated[
    str, typer.Option("--path", "-p", help="Repository root", envvar="OPENBRAIN_ROOT")
]


class OutputFormat(str, Enum):
    table = "table"
    json = "json"
    plain = "plain"


@app.command()
def init(path: RepoPath = "."):
    """Initialize OpenBrain repo memory."""
    try:
        root = Path(path).resolve()
        with OpenBrainDB(root=root) as db:
            typer.echo(f"Initialized OpenBrain database at {db.db_path}")
    except PermissionError:
        typer.echo("Error: No write permission for this directory", err=True)
        raise typer.Exit(code=1)


@app.command()
def index(path: RepoPath = "."):
    """Index text files in the repository."""
    root = Path(path).resolve()
    if not (root / ".openbrain").exists():
        typer.echo("Error: No OpenBrain database found. Run 'openbrain init' first.", err=True)
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
    if not (root / ".openbrain").exists():
        typer.echo("Error: No OpenBrain database found. Run 'openbrain init' first.", err=True)
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
        # table format
        for doc in results:
            typer.echo(f"[{doc['id']}] {doc['path']}")
            snippet = doc["content"][:300].replace("\n", " ")
            typer.echo(f"  {snippet}...\n")


@app.command()
def stats(path: RepoPath = "."):
    """Show database statistics."""
    root = Path(path).resolve()
    db_path = root / ".openbrain" / "openbrain.db"
    if not db_path.exists():
        typer.echo("Error: No OpenBrain database found. Run 'openbrain init' first.", err=True)
        raise typer.Exit(code=1)

    with OpenBrainDB(root=root) as db:
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


@app.command()
def remember(
    key: str = typer.Argument(..., help="Short identifier for this note"),
    content: str = typer.Argument(..., help="Text to remember"),
    path: RepoPath = ".",
):
    """Store a note in project memory."""
    root = Path(path).resolve()
    with OpenBrainDB(root=root) as db:
        written = db.remember(key, content)
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
    root = Path(path).resolve()
    with OpenBrainDB(root=root) as db:
        deleted = db.forget(key)
    if deleted:
        typer.echo(f"Forgot '{key}'")
    else:
        typer.echo(f"No note found with key '{key}'", err=True)
        raise typer.Exit(code=1)


@app.command()
def recall(
    query: str = typer.Argument("", help="Search query (empty lists all notes)"),
    path: RepoPath = ".",
    output_format: OutputFormat = typer.Option(OutputFormat.table, "--format", "-f", help="Output format"),
    limit: int = typer.Option(20, "--limit", "-n", help="Max results"),
):
    """Retrieve notes from project memory."""
    root = Path(path).resolve()
    with OpenBrainDB(root=root) as db:
        results = db.recall(query=query or None, limit=limit)
    if not results:
        typer.echo("No notes found", err=True)
        raise typer.Exit(code=0)

    if output_format == OutputFormat.json:
        typer.echo(json.dumps(results, indent=2))
    elif output_format == OutputFormat.plain:
        for note in results:
            key = note["path"].removeprefix("note:")
            typer.echo(f"{key}: {note['content'][:100]}")
    else:
        for note in results:
            key = note["path"].removeprefix("note:")
            typer.echo(f"[{key}]")
            typer.echo(f"  {note['content'][:300]}\n")


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
