# Agent Guide — project-memory

## Memory

This project provides `project-memory`, a repo-scoped memory engine backed by SQLite + FTS5. Use the MCP tools instead of creating markdown files for persistent memory, tasks, plans, or learnings.

### Available MCP tools

**Notes** — general project knowledge

| Tool | Purpose |
|------|---------|
| `remember` | Store a note (`key` + `content`) |
| `recall` | Retrieve notes — search by content, or list all |
| `forget` | Remove a note by key |

**Learnings** — knowledge discovered during development

| Tool | Purpose |
|------|---------|
| `learn` | Store a learning (`key` + `content`) |
| `recall_learnings` | Retrieve learnings — search or list all |
| `forget_learning` | Remove a learning by key |

**Tasks** — work items with status tracking

| Tool | Purpose |
|------|---------|
| `task_add` | Add a task (status starts as `pending`, optional `group`) |
| `task_list` | List tasks — filter by `status` and/or `group` |
| `task_update` | Change a task's `status`, `content`, or `group` |
| `task_remove` | Remove a task |

Task statuses: `pending`, `in_progress`, `done`. Groups are freeform strings (e.g. `v0.2`, `auth-feature`).

**Plans** — implementation plans (markdown)

| Tool | Purpose |
|------|---------|
| `plan_create` | Create or update a plan (starts as `active`) |
| `plan_get` | Get a plan's full content by key |
| `plan_list` | List plans (defaults to `active` only) |
| `plan_archive` | Archive a completed plan |

**Search & indexing**

| Tool | Purpose |
|------|---------|
| `index` | Re-index text files in the repo after changes |
| `search` | Full-text search across everything (files, notes, learnings, tasks, plans) |
| `list_documents` | See all indexed entries |
| `stats` | Document count and database size |

### When to use them

- **Starting a session**: Call `plan_list(type='protocol')` to load all active protocols. Follow them throughout the session.
- **Starting a task**: `recall` and `recall_learnings` first, then `search` for relevant files
- **Discovering something non-obvious**: `learn` with a descriptive key
- **Tracking work**: `task_add` for items, `task_update` to mark progress
- **Planning implementation**: `plan_create` with markdown content, `plan_archive` when done
- **Before committing/PRing**: Re-check active protocols (`plan_list(type='protocol')`) for blast radius requirements
- **After writing/deleting files**: `index` to keep the database current

### What not to do

- Do not create markdown files for memory, notes, plans, or task lists — use the database
- Do not manually manage `.project-memory/` — it auto-initializes on first tool use
- Do not drop planning documents into `docs/plans/` — use `plan_create` instead

## Project structure

```
src/project_memory/
  db.py           — SQLite + FTS5 database layer (migrations, triggers, bm25)
  index.py        — File discovery and content ingestion
  search.py       — Search wrapper
  portability.py  — Export/import to MEMORY.md
  protocols.py    — Development protocol generation (blast-radius framework)
  cli.py          — Typer CLI with subcommands for all operations
  server.py       — MCP servers (stdio for agents, HTTP for web)
tests/
  test_db.py          — Database layer tests
  test_cli.py         — CLI tests via CliRunner
  test_server.py      — MCP server integration tests
  test_portability.py — Export/import round-trip tests
  test_protocols.py   — Protocol generation tests
```

## Development rules

- Run `pytest` after every change — don't batch changes then test at the end
- Use context managers (`with ProjectMemoryDB() as db:`) for all database access
- FTS5 sync is handled by triggers — never manually insert into `documents_fts`
- Keep it simple — this is a CLI tool, not a framework
