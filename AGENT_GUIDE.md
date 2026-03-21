# Agent Guide — project-memory

## Memory

This project provides `openbrain`, a repo-scoped memory engine backed by SQLite + FTS5. Use the MCP tools instead of creating markdown files for persistent memory.

### Available MCP tools

| Tool | Purpose |
|------|---------|
| `index` | Re-index text files in the repo after changes |
| `search` | Full-text search with bm25 ranking — use before starting work to find relevant context |
| `remember` | Store a note in project memory (`key` + `content`) |
| `recall` | Retrieve notes — search by content, or list all if no query |
| `forget` | Remove a note by key |
| `list_documents` | See what's currently indexed (files + notes) |
| `stats` | Document count and database size |

### When to use them

- **Starting a task**: `recall` to check for existing project notes, `search` for relevant files
- **Learning something worth keeping**: `remember` with a descriptive key (e.g. `auth-pattern`, `deploy-steps`)
- **After writing/deleting files**: `index` to keep the database current
- **Exploring the codebase**: `search` is faster than grepping for conceptual queries

### What not to do

- Do not create markdown files for memory or notes — use `remember` instead
- Do not manually manage `.openbrain/` — it auto-initializes on first tool use

## Project structure

```
src/openbrain/
  db.py       — SQLite + FTS5 database layer (migrations, triggers, bm25)
  index.py    — File discovery and content ingestion
  search.py   — Search wrapper
  cli.py      — Typer CLI (init, index, search, stats, serve-stdio, serve-mcp)
  server.py   — MCP servers (stdio for agents, HTTP for web)
tests/
  test_db.py      — Database layer tests
  test_cli.py     — CLI tests via CliRunner
  test_server.py  — MCP server integration test
```

## Development rules

- Run `pytest` after every change — don't batch changes then test at the end
- Use context managers (`with OpenBrainDB() as db:`) for all database access
- All CSS tokens must have hardcoded fallbacks — this rule does not apply here but is in the parent CLAUDE.md
- FTS5 sync is handled by triggers — never manually insert into `documents_fts`
- Keep it simple — this is a CLI tool, not a framework
