import hashlib
import os
import re
import sqlite3
from pathlib import Path
from typing import Iterable, List, Optional

DEFAULT_DIR = ".openbrain"
DEFAULT_DB = "openbrain.db"

# Each migration takes a connection and applies one schema version bump.
# Version 0 → 1: initial schema with FTS5 triggers, new columns.
MIGRATIONS = [
    lambda conn: conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY,
            path TEXT UNIQUE NOT NULL,
            content TEXT NOT NULL,
            source_type TEXT DEFAULT 'file',
            indexed_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            content_hash TEXT
        ) STRICT;

        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
            path, content, content='documents', content_rowid='id'
        );

        -- Keep FTS in sync on INSERT
        CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
            INSERT INTO documents_fts(rowid, path, content)
            VALUES (new.id, new.path, new.content);
        END;

        -- Keep FTS in sync on DELETE
        CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
            INSERT INTO documents_fts(documents_fts, rowid, path, content)
            VALUES ('delete', old.id, old.path, old.content);
        END;

        -- Keep FTS in sync on UPDATE
        CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
            INSERT INTO documents_fts(documents_fts, rowid, path, content)
            VALUES ('delete', old.id, old.path, old.content);
            INSERT INTO documents_fts(rowid, path, content)
            VALUES (new.id, new.path, new.content);
        END;
    """),
]


def _migrate_from_v0(conn: sqlite3.Connection):
    """Migrate a pre-migration database (v0 schema) to v1.

    The v0 schema had documents(id, path, content) without STRICT,
    no triggers, and a manually-managed FTS table. We add the new columns,
    create triggers, and rebuild FTS to sync with current data.
    """
    # Add new columns (ignore if already present)
    for stmt in [
        "ALTER TABLE documents ADD COLUMN source_type TEXT DEFAULT 'file'",
        "ALTER TABLE documents ADD COLUMN indexed_at TEXT",
        "ALTER TABLE documents ADD COLUMN content_hash TEXT",
    ]:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # column already exists

    # Drop old FTS table and recreate with triggers
    conn.executescript("""
        DROP TABLE IF EXISTS documents_fts;

        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
            path, content, content='documents', content_rowid='id'
        );

        CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
            INSERT INTO documents_fts(rowid, path, content)
            VALUES (new.id, new.path, new.content);
        END;

        CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
            INSERT INTO documents_fts(documents_fts, rowid, path, content)
            VALUES ('delete', old.id, old.path, old.content);
        END;

        CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
            INSERT INTO documents_fts(documents_fts, rowid, path, content)
            VALUES ('delete', old.id, old.path, old.content);
            INSERT INTO documents_fts(rowid, path, content)
            VALUES (new.id, new.path, new.content);
        END;
    """)

    # Rebuild FTS index from existing data
    conn.execute("""
        INSERT INTO documents_fts(rowid, path, content)
        SELECT id, path, content FROM documents
    """)
    conn.commit()


def content_hash(content: str) -> str:
    """Return a hex SHA-256 digest of the content string."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class OpenBrainDB:
    def __init__(self, root: Optional[str] = None):
        self.root = Path(root or os.getcwd())
        self.db_dir = self.root / DEFAULT_DIR
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.db_dir / DEFAULT_DB
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._run_migrations()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def _get_schema_version(self) -> int:
        return self.conn.execute("PRAGMA user_version").fetchone()[0]

    def _set_schema_version(self, version: int):
        self.conn.execute(f"PRAGMA user_version = {version}")
        self.conn.commit()

    def _run_migrations(self):
        current = self._get_schema_version()

        # Handle pre-migration databases: they have documents table but user_version=0
        if current == 0:
            tables = {
                row[0]
                for row in self.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "documents" in tables:
                # Existing v0 database — migrate in place
                _migrate_from_v0(self.conn)
                self._set_schema_version(len(MIGRATIONS))
                return

        # Run any pending migrations
        for i, migration in enumerate(MIGRATIONS):
            if i >= current:
                migration(self.conn)
        self._set_schema_version(len(MIGRATIONS))
        self.conn.commit()

    def upsert_document(self, path: str, content: str, source_type: str = "file") -> bool:
        """Insert or update a document. Returns True if content was written, False if skipped (unchanged)."""
        new_hash = content_hash(content)
        cur = self.conn.execute("SELECT id, content_hash FROM documents WHERE path = ?", (path,))
        existing = cur.fetchone()
        if existing and existing["content_hash"] == new_hash:
            return False  # content unchanged, skip

        if existing:
            self.conn.execute(
                "UPDATE documents SET content = ?, content_hash = ?, indexed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), source_type = ? WHERE id = ?",
                (content, new_hash, source_type, existing["id"]),
            )
        else:
            self.conn.execute(
                "INSERT INTO documents(path, content, content_hash, source_type) VALUES (?, ?, ?, ?)",
                (path, content, new_hash, source_type),
            )
        self.conn.commit()
        return True

    def delete_missing_documents(self, paths_to_keep: Iterable[str]) -> int:
        """Delete documents whose paths are not in paths_to_keep. Returns count deleted."""
        keep = list(paths_to_keep)
        if keep:
            placeholders = ",".join("?" for _ in keep)
            cur = self.conn.execute(
                f"SELECT COUNT(*) FROM documents WHERE path NOT IN ({placeholders})", keep
            )
            count = cur.fetchone()[0]
            self.conn.execute(
                f"DELETE FROM documents WHERE path NOT IN ({placeholders})", keep
            )
        else:
            count = self.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
            self.conn.execute("DELETE FROM documents")
        self.conn.commit()
        return count

    def search(self, query: str, limit: int = 20) -> List[dict]:
        normalized_query = normalize_fts_query(query)
        if not normalized_query:
            return []
        cur = self.conn.execute(
            """SELECT d.id, d.path, d.content, bm25(documents_fts) AS rank
               FROM documents d
               JOIN documents_fts f ON d.id = f.rowid
               WHERE documents_fts MATCH ?
               ORDER BY rank
               LIMIT ?""",
            (normalized_query, limit),
        )
        return [dict(row) for row in cur.fetchall()]

    def list_documents(self) -> List[dict]:
        cur = self.conn.execute("SELECT id, path FROM documents ORDER BY path")
        return [dict(row) for row in cur.fetchall()]

    def document_count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]

    def close(self):
        self.conn.close()


def normalize_fts_query(query: str) -> str:
    terms = re.findall(r"[A-Za-z0-9_]+", query)
    if not terms:
        return ""
    return " AND ".join(f'"{term}"' for term in terms)
