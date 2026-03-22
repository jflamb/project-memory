---
name: project-memory-conventions
description: Development conventions and patterns for project-memory. Python project with freeform commits.
---

# Project Memory Conventions

> Generated from [jflamb/project-memory](https://github.com/jflamb/project-memory) on 2026-03-21

## Overview

This skill teaches Claude the development patterns and conventions used in project-memory.

## Tech Stack

- **Primary Language**: Python
- **Architecture**: hybrid module organization
- **Test Location**: separate

## When to Use This Skill

Activate this skill when:
- Making changes to this repository
- Adding new features following established patterns
- Writing tests that match project conventions
- Creating commits with proper message format

## Commit Conventions

Follow these commit message conventions based on 14 analyzed commits.

### Commit Style: Free-form Messages

### Message Guidelines

- Average message length: ~60 characters
- Keep first line concise and descriptive
- Use imperative mood ("Add feature" not "Added feature")


*Commit message example*

```text
Update uv.lock for new dependencies (sqlite-vec, httpx)
```

*Commit message example*

```text
Add adoption polish: mcp-config command and .gitignore auto-add
```

*Commit message example*

```text
Add embedding search: sqlite-vec, hybrid ranking, and embedding config
```

*Commit message example*

```text
Add richer indexing: .gitignore respect, expanded file types, chunking
```

*Commit message example*

```text
Add development protocols: blast-radius framework and agent compliance
```

*Commit message example*

```text
Add knowledge portability: export/import to MEMORY.md
```

*Commit message example*

```text
Add schema evolution: timestamps, type column, and freeform-with-reuse convention
```

*Commit message example*

```text
Rename openbrain to project-memory
```

## Architecture

### Project Structure: Single Package

This project uses **hybrid** module organization.

### Source Layout

```
src/
├── project_memory/
```

### Configuration Files

- `.github/workflows/ci.yml`
- `.github/workflows/release.yml`

### Guidelines

- This project uses a hybrid organization
- Follow existing patterns when adding new code

## Code Style

### Language: Python

### Naming Conventions

| Element | Convention |
|---------|------------|
| Files | snake_case |
| Functions | camelCase |
| Classes | PascalCase |
| Constants | SCREAMING_SNAKE_CASE |

### Import Style: Relative Imports

### Export Style: Named Exports


*Preferred import style*

```typescript
// Use relative imports
import { Button } from '../components/Button'
import { useAuth } from './hooks/useAuth'
```

*Preferred export style*

```typescript
// Use named exports
export function calculateTotal() { ... }
export const TAX_RATE = 0.1
export interface Order { ... }
```

## Common Workflows

These workflows were detected from analyzing commit patterns.

### Feature Development

Standard feature implementation workflow

**Frequency**: ~21 times per month

**Steps**:
1. Add feature implementation
2. Add tests for feature
3. Update documentation

**Files typically involved**:
- `**/*.test.*`

**Example commit sequence**:
```
Add stdio MCP server for cross-project Claude Code integration
Add agent instructions with shared AGENT_GUIDE.md
Add remember/forget/recall for agent-writable project memory
```

### Add Or Evolve Database Schema And Memory Types

Adds new memory types (notes, learnings, tasks, plans) or evolves the database schema (columns, types, migrations) across DB, CLI, and server layers.

**Frequency**: ~1 times per month

**Steps**:
1. Update database logic (db.py) to add new columns or tables and migration logic.
2. Update CLI interface (cli.py) to expose new commands/options for the new memory types or schema fields.
3. Update server logic (server.py) to support new types/fields in MCP tools.
4. Update or add tests for CLI, DB, and server (test_cli.py, test_db.py, test_server.py).
5. Update documentation (AGENT_GUIDE.md) if new types or conventions are introduced.

**Files typically involved**:
- `src/project_memory/db.py`
- `src/project_memory/cli.py`
- `src/project_memory/server.py`
- `tests/test_cli.py`
- `tests/test_db.py`
- `tests/test_server.py`
- `AGENT_GUIDE.md`

**Example commit sequence**:
```
Update database logic (db.py) to add new columns or tables and migration logic.
Update CLI interface (cli.py) to expose new commands/options for the new memory types or schema fields.
Update server logic (server.py) to support new types/fields in MCP tools.
Update or add tests for CLI, DB, and server (test_cli.py, test_db.py, test_server.py).
Update documentation (AGENT_GUIDE.md) if new types or conventions are introduced.
```

### Add New Feature With Cli Server And Tests

Implements a new core feature (e.g., embedding search, portability, protocols, indexing) by updating CLI, server, and adding dedicated modules and tests.

**Frequency**: ~1 times per month

**Steps**:
1. Create or update a new module for the feature (e.g., embeddings.py, portability.py, protocols.py, index.py).
2. Update CLI (cli.py) to add new commands or options for the feature.
3. Update server (server.py) to expose new tools or endpoints.
4. Add or update tests for CLI and the new module (test_cli.py, test_<feature>.py, test_server.py).
5. Update dependencies if needed (pyproject.toml).

**Files typically involved**:
- `src/project_memory/cli.py`
- `src/project_memory/server.py`
- `src/project_memory/embeddings.py`
- `src/project_memory/portability.py`
- `src/project_memory/protocols.py`
- `src/project_memory/index.py`
- `tests/test_cli.py`
- `tests/test_embeddings.py`
- `tests/test_portability.py`
- `tests/test_protocols.py`
- `tests/test_index.py`
- `tests/test_server.py`
- `pyproject.toml`

**Example commit sequence**:
```
Create or update a new module for the feature (e.g., embeddings.py, portability.py, protocols.py, index.py).
Update CLI (cli.py) to add new commands or options for the feature.
Update server (server.py) to expose new tools or endpoints.
Add or update tests for CLI and the new module (test_cli.py, test_<feature>.py, test_server.py).
Update dependencies if needed (pyproject.toml).
```

### Rename Or Rebrand Project

Renames the project or major components, updating all references in source, tests, configs, and documentation.

**Frequency**: ~1 times per month

**Steps**:
1. Rename source directories and update import paths.
2. Update all references in CLI, DB, server, and test files.
3. Update documentation and config files to reflect the new name.
4. Update package metadata (pyproject.toml).

**Files typically involved**:
- `src/openbrain/*`
- `src/project_memory/*`
- `tests/test_cli.py`
- `tests/test_db.py`
- `tests/test_server.py`
- `README.md`
- `AGENT_GUIDE.md`
- `pyproject.toml`
- `.gitignore`
- `uv.lock`

**Example commit sequence**:
```
Rename source directories and update import paths.
Update all references in CLI, DB, server, and test files.
Update documentation and config files to reflect the new name.
Update package metadata (pyproject.toml).
```

### Add Or Update Ci Cd Workflows

Adds or updates GitHub Actions workflows for CI, publishing, or release automation.

**Frequency**: ~1 times per month

**Steps**:
1. Create or update workflow YAML files in .github/workflows.
2. Update package metadata (pyproject.toml) as needed.
3. Test workflow triggers and results.

**Files typically involved**:
- `.github/workflows/ci.yml`
- `.github/workflows/publish.yml`
- `.github/workflows/release.yml`
- `pyproject.toml`

**Example commit sequence**:
```
Create or update workflow YAML files in .github/workflows.
Update package metadata (pyproject.toml) as needed.
Test workflow triggers and results.
```


## Best Practices

Based on analysis of the codebase, follow these practices:

### Do

- Use snake_case for file names
- Prefer named exports

### Don't

- Don't deviate from established patterns without discussion

---

*This skill was auto-generated by [ECC Tools](https://ecc.tools). Review and customize as needed for your team.*
