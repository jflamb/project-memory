# CLAUDE.md

Read and follow [AGENT_GUIDE.md](AGENT_GUIDE.md) for project context, memory tools, and development rules.

## Claude-specific

- Two project-scoped skills are available in `.claude/skills/`:
  - **python-typer-cli** — Typer CLI patterns (CliRunner testing, output formats, error handling)
  - **sqlite-fts5-memory-db** — SQLite/FTS5 patterns (sync triggers, bm25 ranking, migrations, WAL mode)
- Use both skills when working on their respective modules.
