import os
import sys
from pathlib import Path
from typing import Iterable

from .db import ProjectMemoryDB

TEXT_EXTENSIONS = {".md", ".txt", ".py", ".json", ".yaml", ".yml", ".toml", ".ini"}
EXCLUDED_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".project_memory",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "build",
    "dist",
}


def _iter_text_files(root: Path) -> Iterable[Path]:
    for current_root, dirs, files in os.walk(root, topdown=True):
        dirs[:] = [name for name in dirs if name not in EXCLUDED_DIRS]
        current_path = Path(current_root)
        for file_name in files:
            file_path = current_path / file_name
            if file_path.suffix.lower() in TEXT_EXTENSIONS:
                yield file_path


def index_repo(root: str = None) -> dict:
    """Index text files in the repo. Returns dict with total, skipped, deleted counts."""
    root_path = Path(root or os.getcwd())
    total = 0
    skipped = 0
    indexed_paths: list[str] = []

    with ProjectMemoryDB(root=root_path) as db:
        for file_path in _iter_text_files(root_path):
            relative_path = str(file_path.relative_to(root_path))
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            written = db.upsert_document(relative_path, content)
            indexed_paths.append(relative_path)
            total += 1
            if not written:
                skipped += 1
        deleted = db.delete_missing_documents(indexed_paths)

    return {"total": total, "skipped": skipped, "deleted": deleted}
