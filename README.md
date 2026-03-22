# Project Memory — Repo-Scoped Memory Engine

This project is a repo-scoped memory engine, including:
- CLI (`project-memory`) via Typer
- SQLite memory database under `.project-memory/`
- File ingestion plus typed memory for notes, learnings, tasks, and plans
- Keyword search across indexed files and typed memory
- MCP HTTP server over streamable HTTP
- GitHub Actions CI/release/publish workflows

## Quickstart

```bash
python -m pip install -e .
project-memory init
project-memory index
project-memory search "your query"
project-memory remember deploy "Run migrations before restart"
project-memory plan create branching "Use feature branches" --type protocol
project-memory serve-mcp
```

## Current behavior

- `project-memory index` indexes repository text files only. Reindexing cleans up stale file documents, but it does not delete notes, learnings, tasks, or plans.
- `project-memory search` is keyword-only today. Search results can include both indexed files and typed memory.
- `project-memory export` / `project-memory import` round-trip task and plan status, including archived plans.
- Embedding configuration commands exist, but embedding-backed indexing and query-time hybrid search are not implemented yet.

## Commands

- `project-memory init` - initialize `.project-memory/project_memory.db`
- `project-memory index` - ingest repository text files into SQLite
- `project-memory search QUERY` - perform a keyword search across files and typed memory
- `project-memory remember KEY CONTENT` - store a note
- `project-memory learn KEY CONTENT` - store a learning
- `project-memory task ...` - manage tracked tasks
- `project-memory plan ...` - manage implementation plans and protocols
- `project-memory export` / `project-memory import` - round-trip memory through `MEMORY.md`
- `project-memory serve-mcp` - run the MCP server at `http://127.0.0.1:8000/mcp/`

## Project structure

- `src/project_memory/` core implementation
- `.project-memory/` runtime storage
- `.github/workflows` CI/CD
