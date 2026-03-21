"""Development protocol generation based on repo inspection."""

from pathlib import Path
from typing import List

from .db import ProjectMemoryDB

# Language detection: marker file → language name
_LANGUAGE_MARKERS = {
    "pyproject.toml": "python",
    "setup.py": "python",
    "setup.cfg": "python",
    "package.json": "node",
    "Cargo.toml": "rust",
    "go.mod": "go",
    "pom.xml": "java",
    "build.gradle": "java",
    "Gemfile": "ruby",
}


def inspect_repo(root: Path) -> dict:
    """Inspect a repository to gather context for protocol generation.

    Returns a dict with: has_git, default_branch, has_ci, languages.
    """
    info = {
        "has_git": False,
        "default_branch": "main",
        "has_ci": False,
        "languages": [],
    }

    # Git
    git_dir = root / ".git"
    if git_dir.is_dir():
        info["has_git"] = True
        head_file = git_dir / "HEAD"
        if head_file.exists():
            head = head_file.read_text().strip()
            if head.startswith("ref: refs/heads/"):
                info["default_branch"] = head.removeprefix("ref: refs/heads/")

    # CI
    gh_workflows = root / ".github" / "workflows"
    if gh_workflows.is_dir() and any(gh_workflows.iterdir()):
        info["has_ci"] = True
    if (root / ".gitlab-ci.yml").exists():
        info["has_ci"] = True

    # Languages
    for marker, lang in _LANGUAGE_MARKERS.items():
        if (root / marker).exists() and lang not in info["languages"]:
            info["languages"].append(lang)

    return info


def generate_default_protocols(db: ProjectMemoryDB, root: Path) -> List[str]:
    """Generate default development protocols based on repo inspection.

    Protocols are stored as plans with type='protocol'. Returns list of
    protocol keys that were created or updated.
    """
    info = inspect_repo(root)
    branch = info["default_branch"]
    ci_line = "CI must pass before merge." if info["has_ci"] else "Run the full test suite before merge."

    keys = []

    # Blast radius protocol
    db.plan_create("blast-radius", _blast_radius_protocol(ci_line), type="protocol")
    keys.append("blast-radius")

    # Branching protocol
    db.plan_create("branching", _branching_protocol(branch), type="protocol")
    keys.append("branching")

    return keys


def _blast_radius_protocol(ci_line: str) -> str:
    return f"""# Blast Radius Framework

Assess the blast radius of every change before choosing a workflow.

| Blast radius | Example | Branch? | PR? | Review? |
|---|---|---|---|---|
| **Trivial** | Typo fix, comment update | Optional | Optional | No |
| **Scoped** | Bug fix in one module, new test | Yes | Yes | {ci_line} |
| **Cross-cutting** | Rename, dependency change, new feature | Yes | Yes | 1 approval + {ci_line} |
| **Breaking** | API change, schema migration, protocol change | Yes | Yes | 2 approvals + {ci_line} |

## How to assess

1. List every file touched by the change.
2. If all files are in one module and no public API changes → **Scoped**.
3. If multiple modules or a dependency changes → **Cross-cutting**.
4. If the change breaks existing callers, requires a migration, or changes a protocol → **Breaking**.
5. If the change is cosmetic with no behavior change → **Trivial**.

## Agent compliance

At session start and before creating commits, branches, or PRs, call `plan_list(type='protocol')` and follow all active protocols."""


def _branching_protocol(default_branch: str) -> str:
    return f"""# Branching Protocol

## Rules

- The default branch is `{default_branch}`. Never push directly to it for scoped+ changes.
- Create a feature branch for every scoped, cross-cutting, or breaking change.
- Branch names: `<category>/<short-description>` (e.g., `feature/add-search`, `fix/login-bug`).
- Trivial changes (typos, comment-only) may commit directly to `{default_branch}`.
- Delete feature branches after merge.

## PR workflow

1. Push the feature branch.
2. Open a PR targeting `{default_branch}`.
3. Follow the blast-radius protocol for review requirements.
4. Squash-merge or rebase-merge (team preference)."""
