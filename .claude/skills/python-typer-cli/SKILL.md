---
name: python-typer-cli
description: Patterns for building well-structured Typer CLI applications — command organization, argument/option conventions, output formatting, error handling, and testing with CliRunner. Use this skill whenever you're building or modifying a Python CLI that uses Typer, adding new CLI commands, writing tests for CLI tools, or structuring a command-line interface. Also trigger when you see imports from `typer` or `click`, test files that invoke CLI commands, or the user mentions "CLI", "command-line", or "terminal interface" in the context of a Python project.
---

# Building Typer CLIs

This skill covers how to build clean, testable Typer command-line interfaces. The goal is CLIs that are pleasant to use, easy to test, and straightforward to extend.

## Command Structure

### Single app vs command groups

For a small CLI (under ~8 commands), a flat `typer.Typer()` with `@app.command()` decorators works well. Once you have logical groupings, split into sub-apps:

```python
# flat — good for small CLIs
app = typer.Typer(help="Project Memory CLI")

@app.command()
def init(): ...

@app.command()
def search(query: str): ...
```

```python
# grouped — when you have distinct command families
app = typer.Typer(help="Project Memory CLI")
db_app = typer.Typer(help="Database management")
app.add_typer(db_app, name="db")

@db_app.command()
def migrate(): ...

@db_app.command()
def reset(): ...
```

Don't group prematurely — a flat list of 5 commands is easier to discover than nested sub-groups.

### Naming conventions

- Command names: kebab-case in the CLI (`serve-mcp`), but the Python function can be `serve_mcp` — Typer converts automatically
- If a function name collides with a builtin or import (like `search`), suffix the function: `search_cmd`, but set the CLI name explicitly: `@app.command("search")`

## Arguments and Options

### When to use which

- **Arguments** (`typer.Argument`): The primary input — what the command acts on. A search query, a file path, a name. Positional and required by default.
- **Options** (`typer.Option`): Configuration that modifies behavior. Output format, verbosity, limits, paths to resources. Named with `--flag` syntax.

The distinction matters for usability: `project-memory search "my query"` reads naturally because the query is the argument. `project-memory search --query "my query"` is clunky.

### Shared options

When multiple commands share the same option (like `--path` for the repo root), define it once and reuse:

```python
from typing import Annotated

RepoPath = Annotated[str, typer.Option("--path", "-p", help="Repository root", envvar="PROJECT_MEMORY_ROOT")]

@app.command()
def index(path: RepoPath = "."):
    ...

@app.command("search")
def search_cmd(query: str, path: RepoPath = "."):
    ...
```

This keeps help text consistent and lets users set `PROJECT_MEMORY_ROOT` once instead of passing `--path` every time.

### Defaults and environment variables

Prefer sensible defaults (`"."` for paths, `20` for limits) so commands work without flags. Use `envvar=` on options for values users set once per environment. Don't use `envvar` on arguments — positional inputs should be explicit.

## Output Formatting

### The `--output-format` pattern

For commands that produce data (search results, document lists), support multiple output formats:

```python
from enum import Enum

class OutputFormat(str, Enum):
    table = "table"
    json = "json"
    plain = "plain"

@app.command("search")
def search_cmd(
    query: str,
    output_format: OutputFormat = typer.Option(OutputFormat.table, "--format", "-f", help="Output format"),
):
    results = do_search(query)
    if output_format == OutputFormat.json:
        import json
        typer.echo(json.dumps(results, indent=2))
    elif output_format == OutputFormat.table:
        _print_table(results)
    else:
        for r in results:
            typer.echo(f"{r['path']}: {r['content'][:100]}")
```

The key principle: **internal functions return structured data (dicts/lists), and formatting happens at the CLI boundary.** This makes the core logic testable without parsing CLI output.

### Where output goes

- **Results** → stdout (`typer.echo`)
- **Progress/diagnostics** → stderr (`typer.echo(..., err=True)`)
- **Errors** → stderr with non-zero exit code

This lets users pipe results (`project-memory search "query" | jq .`) while still seeing progress messages.

## Error Handling

### Exit codes

Use consistent exit codes:

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error (bad input, operation failed) |
| 2 | Usage error (wrong arguments — Typer/Click handles this) |

```python
@app.command()
def search_cmd(query: str):
    results = do_search(query)
    if not results:
        typer.echo("No results found", err=True)
        raise typer.Exit(code=0)  # not an error, just empty
    ...
```

### User-facing errors

Catch expected exceptions and translate them into helpful messages. Don't let raw tracebacks reach users:

```python
@app.command()
def init():
    try:
        db = ProjectMemoryDB(root=root)
        db.close()
        typer.echo(f"Initialized database at {db.db_path}")
    except PermissionError:
        typer.echo("Error: No write permission for this directory", err=True)
        raise typer.Exit(code=1)
```

Let unexpected exceptions propagate — they indicate bugs that should be visible during development.

### Callbacks for shared setup

If multiple commands need the same validation (e.g., checking that `.project-memory/` exists), use a Typer callback instead of repeating the check:

```python
@app.callback()
def main(ctx: typer.Context):
    """Project Memory CLI — repo-scoped memory engine."""
    # Shared setup that runs before any command
    pass
```

## Testing with CliRunner

This is the most important section. Good CLI tests catch real bugs — bad ones just verify that Python functions work (which unit tests already do).

### The pattern

```python
from typer.testing import CliRunner
from project_memory.cli import app

runner = CliRunner()

def test_init_creates_db(tmp_path):
    result = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / ".project-memory" / "project_memory.db").exists()

def test_search_no_results(tmp_path):
    runner.invoke(app, ["init", "--path", str(tmp_path)])
    result = runner.invoke(app, ["search", "nonexistent", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert "No" in result.output
```

### Why CliRunner instead of calling functions directly

Calling `init()` directly in a test bypasses Typer's argument parsing, help generation, and error handling. `CliRunner` tests the full command as a user would invoke it — including argument validation, option defaults, and exit codes. It also avoids the `os.chdir` hack because you pass `--path` as a proper option.

### What to test

- **Happy path**: Command runs, exit code is 0, output contains expected data
- **Empty/missing input**: What happens with no results, missing files, empty databases
- **Bad input**: Invalid arguments, missing required options — check exit code and error message
- **Output formats**: If you support `--format json`, verify the output is valid JSON
- **Piping**: Commands that produce structured output should work when stdout isn't a TTY

### Fixtures

```python
import pytest
from typer.testing import CliRunner

@pytest.fixture
def runner():
    return CliRunner()

@pytest.fixture
def initialized_repo(tmp_path):
    """A tmp_path with an initialized project memory database."""
    runner = CliRunner()
    runner.invoke(app, ["init", "--path", str(tmp_path)])
    return tmp_path
```

## Help Text

Good help text is documentation that lives where users actually look.

- **Command docstring** → shown in `project-memory --help` and `project-memory <command> --help`
- **`help=` on options/arguments** → shown next to each flag in help output
- Keep docstrings to one line for the summary, add detail in the extended help if needed
- Use `rich_help_panel` to visually group related options when a command has many flags

```python
@app.command()
def index(
    path: str = typer.Option(".", "--path", "-p", help="Repository root to index"),
    extensions: str = typer.Option(None, "--ext", help="Comma-separated file extensions to include"),
):
    """Index text files in the repository into the memory database."""
    ...
```
