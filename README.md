# Project Memory — Repo-Scoped Memory Engine

This project is a minimal implementation of a repo-scoped memory engine, including:
- CLI (`project-memory`) via Typer
- SQLite memory database under `.project-memory/`
- Ingestion and search modules
- MCP HTTP server over streamable HTTP
- GitHub Actions CI/release/publish workflows

## Quickstart

```bash
python -m pip install -e .
project-memory init
project-memory index
project-memory search "your query"
project-memory serve-mcp
```

## Commands

- `project-memory init` - initialize `.project-memory/project_memory.db`
- `project-memory index` - ingest repository text files into SQLite
- `project-memory search QUERY` - perform a keyword search
- `project-memory serve-mcp` - run the MCP server at `http://127.0.0.1:8000/mcp/`

## Project structure

- `src/project_memory/` core implementation
- `.project-memory/` runtime storage
- `.github/workflows` CI/CD
