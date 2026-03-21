---
name: add-new-feature-with-cli-server-and-tests
description: Workflow command scaffold for add-new-feature-with-cli-server-and-tests in project-memory.
allowed_tools: ["Bash", "Read", "Write", "Grep", "Glob"]
---

# /add-new-feature-with-cli-server-and-tests

Use this workflow when working on **add-new-feature-with-cli-server-and-tests** in `project-memory`.

## Goal

Implements a new core feature (e.g., embedding search, portability, protocols, indexing) by updating CLI, server, and adding dedicated modules and tests.

## Common Files

- `src/project_memory/cli.py`
- `src/project_memory/server.py`
- `src/project_memory/embeddings.py`
- `src/project_memory/portability.py`
- `src/project_memory/protocols.py`
- `src/project_memory/index.py`

## Suggested Sequence

1. Understand the current state and failure mode before editing.
2. Make the smallest coherent change that satisfies the workflow goal.
3. Run the most relevant verification for touched files.
4. Summarize what changed and what still needs review.

## Typical Commit Signals

- Create or update a new module for the feature (e.g., embeddings.py, portability.py, protocols.py, index.py).
- Update CLI (cli.py) to add new commands or options for the feature.
- Update server (server.py) to expose new tools or endpoints.
- Add or update tests for CLI and the new module (test_cli.py, test_<feature>.py, test_server.py).
- Update dependencies if needed (pyproject.toml).

## Notes

- Treat this as a scaffold, not a hard-coded script.
- Update the command if the workflow evolves materially.