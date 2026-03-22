import fnmatch
import os
from pathlib import Path
from typing import Iterable, List

from .db import ProjectMemoryDB

TEXT_EXTENSIONS = {
    # Original
    ".md", ".txt", ".py", ".json", ".yaml", ".yml", ".toml", ".ini",
    # Phase 4: expanded file types
    ".rs", ".go", ".js", ".ts", ".tsx", ".jsx",
    ".css", ".html",
    ".sh", ".bash", ".zsh",
    ".sql",
    ".r",  # .R handled via case-insensitive check
    ".cfg",
}

# Files matched by exact name (no extension).
TEXT_FILENAMES = {
    "Dockerfile", "Makefile", "Justfile", ".env.example",
}

# Hardcoded fallback dirs to exclude when no .gitignore is present.
_FALLBACK_EXCLUDED_DIRS = {
    ".git", ".hg", ".svn",
    ".project-memory",
    ".venv", "venv",
    "node_modules",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "build", "dist",
}

# Chunking defaults
CHUNK_THRESHOLD = 4096  # bytes (~4KB)
CHUNK_SIZE = 3072       # bytes per chunk (~3KB)
CHUNK_OVERLAP = 512     # bytes of overlap between chunks


def _parse_gitignore(gitignore_path: Path) -> List[tuple]:
    """Parse a .gitignore file into a list of (pattern, negated) tuples."""
    rules = []
    if not gitignore_path.exists():
        return rules
    for line in gitignore_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        negated = line.startswith("!")
        if negated:
            line = line[1:]
        # Normalize trailing slashes (directory patterns)
        line = line.rstrip("/")
        rules.append((line, negated))
    return rules


def _matches_pattern(rel_path: str, pattern: str) -> bool:
    """Check if a relative path matches a gitignore-style pattern."""
    # If pattern contains a slash (not trailing), it's anchored to the root
    if "/" in pattern:
        return fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(rel_path, pattern + "/*")
    # Otherwise, match against any path component or the basename
    basename = os.path.basename(rel_path)
    if fnmatch.fnmatch(basename, pattern):
        return True
    # Also check full path for directory-level patterns
    parts = rel_path.split("/")
    for part in parts:
        if fnmatch.fnmatch(part, pattern):
            return True
    return False


class _GitignoreChecker:
    """Collects .gitignore rules from root and nested directories."""

    def __init__(self, root: Path):
        self.root = root
        self._rules: List[tuple] = []  # (pattern, negated, base_dir_rel)
        self._load_gitignore(root, "")

    def _load_gitignore(self, directory: Path, rel_prefix: str):
        gitignore = directory / ".gitignore"
        if gitignore.exists():
            for pattern, negated in _parse_gitignore(gitignore):
                self._rules.append((pattern, negated, rel_prefix))

    def load_nested(self, directory: Path):
        """Load .gitignore for a nested directory."""
        rel_prefix = str(directory.relative_to(self.root))
        self._load_gitignore(directory, rel_prefix)

    def is_ignored(self, rel_path: str) -> bool:
        """Check if a relative path is ignored by any loaded .gitignore rules."""
        ignored = False
        for pattern, negated, base_dir_rel in self._rules:
            # For nested gitignores, check relative to their directory
            if base_dir_rel:
                if not rel_path.startswith(base_dir_rel + "/"):
                    continue
                check_path = rel_path[len(base_dir_rel) + 1:]
            else:
                check_path = rel_path

            if _matches_pattern(check_path, pattern):
                ignored = not negated
        return ignored

    @property
    def has_rules(self) -> bool:
        return len(self._rules) > 0


def _is_gitignored(path: Path, root: Path) -> bool:
    """Check if a single path is gitignored. Convenience for external use."""
    checker = _GitignoreChecker(root)
    rel = str(path.relative_to(root))
    return checker.is_ignored(rel)


def _is_text_file(file_path: Path) -> bool:
    """Check if a file should be indexed based on extension or name."""
    if file_path.name in TEXT_FILENAMES:
        return True
    return file_path.suffix.lower() in TEXT_EXTENSIONS


def _iter_text_files(root: Path) -> Iterable[Path]:
    checker = _GitignoreChecker(root)
    use_gitignore = checker.has_rules

    for current_root, dirs, files in os.walk(root, topdown=True):
        current_path = Path(current_root)
        rel_dir = str(current_path.relative_to(root)) if current_path != root else ""

        # Filter directories
        filtered_dirs = []
        for name in dirs:
            # Always skip these regardless of gitignore
            if name in _FALLBACK_EXCLUDED_DIRS:
                continue
            if use_gitignore:
                dir_rel = f"{rel_dir}/{name}" if rel_dir else name
                if checker.is_ignored(dir_rel):
                    continue
            filtered_dirs.append(name)
        dirs[:] = filtered_dirs

        # Load nested .gitignore if present
        if use_gitignore:
            for name in dirs:
                subdir = current_path / name
                if (subdir / ".gitignore").exists():
                    checker.load_nested(subdir)

        for file_name in files:
            file_path = current_path / file_name
            if not _is_text_file(file_path):
                continue
            if use_gitignore:
                file_rel = f"{rel_dir}/{file_name}" if rel_dir else file_name
                if checker.is_ignored(file_rel):
                    continue
            yield file_path


def _chunk_content(content: str) -> List[str]:
    """Split content into overlapping chunks. Returns list of chunk strings."""
    content_bytes = content.encode("utf-8")
    if len(content_bytes) <= CHUNK_THRESHOLD:
        return []  # No chunking needed

    chunks = []
    start = 0
    while start < len(content_bytes):
        end = start + CHUNK_SIZE
        chunk_bytes = content_bytes[start:end]
        # Try to break at a newline near the end for cleaner chunks
        if end < len(content_bytes):
            last_nl = chunk_bytes.rfind(b"\n")
            if last_nl > CHUNK_SIZE // 2:
                chunk_bytes = content_bytes[start:start + last_nl + 1]
                end = start + last_nl + 1

        chunks.append(chunk_bytes.decode("utf-8", errors="ignore"))
        # Next chunk starts overlap-bytes before the end of this one
        start = end - CHUNK_OVERLAP
        if start <= 0 and len(chunks) > 0:
            break  # Safety: prevent infinite loop on tiny overlap

    return chunks


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

            # Chunking: large files get split
            chunks = _chunk_content(content)
            if chunks:
                for i, chunk in enumerate(chunks):
                    chunk_path = f"{relative_path}#chunk-{i}"
                    written = db.upsert_document(chunk_path, chunk)
                    indexed_paths.append(chunk_path)
                    total += 1
                    if not written:
                        skipped += 1
            else:
                written = db.upsert_document(relative_path, content)
                indexed_paths.append(relative_path)
                total += 1
                if not written:
                    skipped += 1

        deleted = db.delete_missing_documents(indexed_paths, source_type="file")

    return {"total": total, "skipped": skipped, "deleted": deleted}
