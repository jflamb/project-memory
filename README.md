# OpenBrain — Repo-Scoped Memory Engine

This project is a minimal implementation of the OpenBrain spec, including:
- CLI (`openbrain`) via Typer
- SQLite memory database under `.openbrain/`
- Ingestion and search modules
- MCP HTTP server over streamable HTTP
- GitHub Actions CI/release/publish workflows

## Quickstart

```bash
python -m pip install -e .
openbrain init
openbrain index
openbrain search "your query"
openbrain serve-mcp
```

## Commands

- `openbrain init` - initialize `.openbrain/openbrain.db`
- `openbrain index` - ingest repository text files into SQLite
- `openbrain search QUERY` - perform a keyword search
- `openbrain serve-mcp` - run the MCP server at `http://127.0.0.1:8000/mcp/`

## Project structure

- `src/openbrain/` core implementation
- `.openbrain/` runtime storage
- `.github/workflows` CI/CD
