---
name: add-or-evolve-database-schema-and-memory-types
description: Workflow command scaffold for add-or-evolve-database-schema-and-memory-types in project-memory.
allowed_tools: ["Bash", "Read", "Write", "Grep", "Glob"]
---

# /add-or-evolve-database-schema-and-memory-types

Use this workflow when working on **add-or-evolve-database-schema-and-memory-types** in `project-memory`.

## Goal

Adds new memory types (notes, learnings, tasks, plans) or evolves the database schema (columns, types, migrations) across DB, CLI, and server layers.

## Common Files

- `src/project_memory/db.py`
- `src/project_memory/cli.py`
- `src/project_memory/server.py`
- `tests/test_cli.py`
- `tests/test_db.py`
- `tests/test_server.py`

## Suggested Sequence

1. Understand the current state and failure mode before editing.
2. Make the smallest coherent change that satisfies the workflow goal.
3. Run the most relevant verification for touched files.
4. Summarize what changed and what still needs review.

## Typical Commit Signals

- Update database logic (db.py) to add new columns or tables and migration logic.
- Update CLI interface (cli.py) to expose new commands/options for the new memory types or schema fields.
- Update server logic (server.py) to support new types/fields in MCP tools.
- Update or add tests for CLI, DB, and server (test_cli.py, test_db.py, test_server.py).
- Update documentation (AGENT_GUIDE.md) if new types or conventions are introduced.

## Notes

- Treat this as a scaffold, not a hard-coded script.
- Update the command if the workflow evolves materially.