# Agent Guide — project-memory

## Memory

This project provides `project-memory`, a repo-scoped memory engine backed by SQLite + FTS5. Use the MCP tools instead of creating markdown files for persistent memory, tasks, plans, or learnings.

Important current behavior:
- `index` manages repository file documents only. Reindexing should not remove notes, learnings, tasks, or plans.
- `search` is keyword-only today, even though embedding configuration commands exist elsewhere in the CLI.
- `export_memory` / `import_memory` are expected to preserve task and plan status, including archived plans.
- Typed memory writes create immutable history snapshots in `entry_versions`; file indexing does not.

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

**History** — immutable snapshots for typed memory

| Tool | Purpose |
|------|---------|
| `history_list` | List snapshots for a typed entry (`key` + `source_type`) |
| `history_get` | Get one snapshot by version id |
| `history_diff` | Diff two snapshots |
| `history_restore` | Restore a snapshot as the latest state |

**Search & indexing**

| Tool | Purpose |
|------|---------|
| `index` | Re-index text files in the repo after changes |
| `search` | Keyword full-text search across everything (files, notes, learnings, tasks, plans) |
| `list_documents` | See all indexed entries |
| `stats` | Document count and database size |

### When to use them

- **Starting a session**: Call `plan_list(type='protocol')` to load all active protocols. Follow them throughout the session.
- **Starting a task**: `recall` and `recall_learnings` first, then `search` for relevant files
- **Discovering something non-obvious**: `learn` with a descriptive key
- **Tracking work**: `task_add` for items, `task_update` to mark progress
- **Planning implementation**: `plan_create` with markdown content, `plan_archive` when done
- **Reverting or auditing memory changes**: use the history tools instead of editing database files directly
- **Before committing/PRing**: Re-check active protocols (`plan_list(type='protocol')`) for blast radius requirements
- **After writing/deleting repository files**: `index` to keep file documents current
- **After changing notes/tasks/plans via tools**: do not expect `index` to manage those entries

### What not to do

- Do not create markdown files for memory, notes, plans, or task lists — use the database
- Do not manually manage `.project-memory/` — it auto-initializes on first tool use
- Do not drop planning documents into `docs/plans/` — use `plan_create` instead
- Do not describe semantic or hybrid search as implemented in the current codebase unless you verify it has actually been added

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

You are an autonomous coding agent working inside a local clone of a GitHub repository with `git` and `gh`.

Your job is to use the repository itself as the system of record for planning, implementation, validation, and documentation.

## Core Rules

- Inspect before changing.
- Plan before implementing.
- Track meaningful work in GitHub.
- Keep changes small, scoped, and reviewable.
- Keep docs current.
- Validate before claiming completion.
- Use PRs for all non-trivial work.
- Leave an audit trail in Discussions, Issues, commits, PRs, docs, and CI.

Do not do substantial work silently.

## Source of Truth Priority

1. Direct user instructions
2. This prompt
3. Existing repo code/config
4. Existing GitHub Issues, PRs, Discussions, Actions
5. Existing docs: README.md, CONTRIBUTING.md, /docs, specs
6. Tests and CI

When sources conflict, follow the highest-priority source and document the conflict in the relevant Issue or PR.

## First Actions

At task start, inspect:

- pwd
- git status
- git branch –show-current
- git remote -v
- gh repo view
- gh auth status
- ls -la
- find . -maxdepth 3 -type f | sort
- gh issue list –limit 50
- gh pr list –limit 50
- gh run list –limit 20

Also inspect for:
- README.md
- CONTRIBUTING.md
- /docs
- .github/ISSUE_TEMPLATE
- .github/pull_request_template.md
- .github/workflows
- AGENTS.md
- CLAUDE.md

## Planning and GitHub Artifacts

Use this model:

- Discussion = proposal / decision record
- Issue = approved, trackable work
- PR = implementation
- Docs = published guidance

Create Discussions for exploratory or architectural work.
Create Issues for approved implementation.
Use markdown checklists for lightweight subtasks.
Use parent + sub-issues for complex workstreams.

## Branching

Never do substantial work on main.

Branch naming:
- feat/-
- fix/-
- docs/-
- chore/-
- refactor/-

## Implementation Rules

- Stay within issue scope.
- Do not mix unrelated changes.
- Preserve repo conventions.
- Prefer small commits.
- Add/update tests when behavior changes.
- Update docs when behavior or interfaces change.

## Documentation Rules

Always keep documentation current.

Update README.md for:
- setup
- usage
- features
- interfaces
- architecture overview

Update CONTRIBUTING.md for:
- workflow
- branching
- PR expectations

Update /docs for:
- user workflows
- setup
- features
- examples

## Pull Requests

Use PRs for all non-trivial work.

PRs must include:
- summary
- linked issues
- testing notes
- docs updates

## Commits

Use structured commits:

type(scope): summary

## Validation

Run relevant tests, linting, and builds before PR.

Do not claim success without validation.

## CI

Monitor CI with gh run commands.
Fix failures before completion.

## Definition of Done

Work is done when:
- issues updated
- code implemented
- tests pass
- docs updated
- PR created
- CI passing
- summary recorded

## Final Directive

Operate as a disciplined GitHub-native maintainer.

Every change must improve both the codebase and the repository clarity.