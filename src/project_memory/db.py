import hashlib
import os
import re
import sqlite3
from pathlib import Path
from typing import Iterable, List, Optional

DEFAULT_DIR = ".project-memory"
DEFAULT_DB = "project_memory.db"

# Each migration takes a connection and applies one schema version bump.
MIGRATIONS = [
    # Version 0 → 1: initial schema with FTS5 triggers, new columns.
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
    # Version 1 → 2: add status and group columns for tasks/plans.
    lambda conn: conn.executescript("""
        ALTER TABLE documents ADD COLUMN status TEXT;
        ALTER TABLE documents ADD COLUMN "group" TEXT;
    """),
    # Version 2 → 3: add created_at, updated_at, type columns.
    lambda conn: _migrate_v2_to_v3(conn),
    # Version 3 → 4: add embedding tables (sqlite-vec + config).
    lambda conn: _migrate_v3_to_v4(conn),
]


def _migrate_v2_to_v3(conn: sqlite3.Connection):
    """Add created_at, updated_at, type columns and backfill timestamps from indexed_at."""
    for stmt in [
        "ALTER TABLE documents ADD COLUMN created_at TEXT",
        "ALTER TABLE documents ADD COLUMN updated_at TEXT",
        "ALTER TABLE documents ADD COLUMN type TEXT",
    ]:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # column already exists

    # Backfill: copy indexed_at into created_at and updated_at for existing rows
    conn.execute("""
        UPDATE documents
        SET created_at = COALESCE(indexed_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            updated_at = COALESCE(indexed_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        WHERE created_at IS NULL
    """)
    conn.commit()


def _migrate_v3_to_v4(conn: sqlite3.Connection):
    """Add embedding tables: vec_documents (sqlite-vec) and embedding_config."""
    # embedding_config stores active model settings
    conn.execute("""
        CREATE TABLE IF NOT EXISTS embedding_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            model TEXT NOT NULL,
            dimensions INTEGER NOT NULL,
            base_url TEXT NOT NULL
        )
    """)
    # vec_documents: virtual table via sqlite-vec, keyed by document ID.
    # We try to create it, but if sqlite-vec isn't loaded we skip gracefully.
    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_documents USING vec0(
                embedding float[384]
            )
        """)
    except Exception:
        pass  # sqlite-vec not available; vector search will be disabled
    conn.commit()


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
        "ALTER TABLE documents ADD COLUMN status TEXT",
        'ALTER TABLE documents ADD COLUMN "group" TEXT',
        "ALTER TABLE documents ADD COLUMN created_at TEXT",
        "ALTER TABLE documents ADD COLUMN updated_at TEXT",
        "ALTER TABLE documents ADD COLUMN type TEXT",
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


class ProjectMemoryDB:
    def __init__(self, root: Optional[str] = None):
        self.root = Path(root or os.getcwd())
        self.db_dir = self.root / DEFAULT_DIR
        self.db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.db_dir / DEFAULT_DB
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._load_vec_extension()
        self._run_migrations()

    def _load_vec_extension(self):
        """Load the sqlite-vec extension for vector search."""
        try:
            import sqlite_vec
            self.conn.enable_load_extension(True)
            sqlite_vec.load(self.conn)
            self.conn.enable_load_extension(False)
            self._has_vec = True
        except (ImportError, Exception):
            self._has_vec = False

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

        now = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
        if existing:
            self.conn.execute(
                f"UPDATE documents SET content = ?, content_hash = ?, indexed_at = {now}, updated_at = {now}, source_type = ? WHERE id = ?",
                (content, new_hash, source_type, existing["id"]),
            )
        else:
            self.conn.execute(
                f"INSERT INTO documents(path, content, content_hash, source_type, created_at, updated_at) VALUES (?, ?, ?, ?, {now}, {now})",
                (path, content, new_hash, source_type),
            )
        self.conn.commit()
        return True

    def delete_missing_documents(self, paths_to_keep: Iterable[str], source_type: str = "file") -> int:
        """Delete documents of a given source_type whose paths are not in paths_to_keep."""
        keep = list(paths_to_keep)
        if keep:
            placeholders = ",".join("?" for _ in keep)
            cur = self.conn.execute(
                f"SELECT COUNT(*) FROM documents WHERE source_type = ? AND path NOT IN ({placeholders})",
                [source_type, *keep],
            )
            count = cur.fetchone()[0]
            self.conn.execute(
                f"DELETE FROM documents WHERE source_type = ? AND path NOT IN ({placeholders})",
                [source_type, *keep],
            )
        else:
            count = self.conn.execute(
                "SELECT COUNT(*) FROM documents WHERE source_type = ?",
                (source_type,),
            ).fetchone()[0]
            self.conn.execute("DELETE FROM documents WHERE source_type = ?", (source_type,))
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

    # --- Generic helpers for typed entries ---

    def _put(self, prefix: str, source_type: str, key: str, content: str,
             status: str = None, group: str = None, type: str = None) -> bool:
        """Insert or update a typed entry. Returns True if written, False if unchanged."""
        path = f"{prefix}:{key}"
        new_hash = content_hash(content)
        cur = self.conn.execute(
            'SELECT id, content_hash, source_type, status, "group", type FROM documents WHERE path = ?',
            (path,),
        )
        existing = cur.fetchone()

        if (
            existing
            and existing["content_hash"] == new_hash
            and existing["source_type"] == source_type
            and existing["status"] == status
            and existing["group"] == group
            and existing["type"] == type
        ):
            return False

        now = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
        if existing:
            self.conn.execute(
                f'UPDATE documents SET content = ?, content_hash = ?, indexed_at = {now}, updated_at = {now}, source_type = ?, status = ?, "group" = ?, type = ? WHERE id = ?',
                (content, new_hash, source_type, status, group, type, existing["id"]),
            )
        else:
            self.conn.execute(
                f'INSERT INTO documents(path, content, content_hash, source_type, status, "group", type, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, {now}, {now})',
                (path, content, new_hash, source_type, status, group, type),
            )
        self.conn.commit()
        return True

    def _remove(self, prefix: str, source_type: str, key: str) -> bool:
        """Remove a typed entry by key. Returns True if deleted."""
        path = f"{prefix}:{key}"
        cur = self.conn.execute("DELETE FROM documents WHERE path = ? AND source_type = ?", (path, source_type))
        self.conn.commit()
        return cur.rowcount > 0

    def _list_typed(self, source_type: str, query: str = None, status: str = None,
                    group: str = None, type: str = None, limit: int = 20) -> List[dict]:
        """List or search entries of a given source_type."""
        if query:
            normalized = normalize_fts_query(query)
            if not normalized:
                return []
            sql = """SELECT d.id, d.path, d.content, d.indexed_at, d.status, d."group", d.type, d.created_at, d.updated_at, bm25(documents_fts) AS rank
                     FROM documents d
                     JOIN documents_fts f ON d.id = f.rowid
                     WHERE documents_fts MATCH ? AND d.source_type = ?"""
            params: list = [normalized, source_type]
            if status:
                sql += " AND d.status = ?"
                params.append(status)
            if group:
                sql += ' AND d."group" = ?'
                params.append(group)
            if type:
                sql += " AND d.type = ?"
                params.append(type)
            sql += " ORDER BY rank LIMIT ?"
            params.append(limit)
        else:
            sql = 'SELECT id, path, content, indexed_at, status, "group", type, created_at, updated_at FROM documents WHERE source_type = ?'
            params = [source_type]
            if status:
                sql += " AND status = ?"
                params.append(status)
            if group:
                sql += ' AND "group" = ?'
                params.append(group)
            if type:
                sql += " AND type = ?"
                params.append(type)
            sql += " ORDER BY path LIMIT ?"
            params.append(limit)

        cur = self.conn.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]

    def _types_in_use(self, source_type: str) -> List[str]:
        """Return distinct non-null type values for a given source_type."""
        cur = self.conn.execute(
            "SELECT DISTINCT type FROM documents WHERE source_type = ? AND type IS NOT NULL ORDER BY type",
            (source_type,),
        )
        return [row[0] for row in cur.fetchall()]

    # --- Notes ---

    def remember(self, key: str, content: str, type: str = None) -> bool:
        """Store a note in memory."""
        return self._put("note", "note", key, content, type=type)

    def forget(self, key: str) -> bool:
        """Remove a note by key."""
        return self._remove("note", "note", key)

    def recall(self, query: str = None, type: str = None, limit: int = 20) -> List[dict]:
        """Retrieve notes. Search by content if query given, else list all."""
        return self._list_typed("note", query=query, type=type, limit=limit)

    def recall_with_types(self, query: str = None, type: str = None, limit: int = 20) -> tuple:
        """Retrieve notes plus types_in_use. Returns (results, types_in_use)."""
        results = self.recall(query=query, type=type, limit=limit)
        return results, self._types_in_use("note")

    # --- Learnings ---

    def learn(self, key: str, content: str, type: str = None) -> bool:
        """Store a learning."""
        return self._put("learning", "learning", key, content, type=type)

    def forget_learning(self, key: str) -> bool:
        """Remove a learning by key."""
        return self._remove("learning", "learning", key)

    def recall_learnings(self, query: str = None, type: str = None, limit: int = 20) -> List[dict]:
        """Retrieve learnings. Search by content if query given, else list all."""
        return self._list_typed("learning", query=query, type=type, limit=limit)

    def recall_learnings_with_types(self, query: str = None, type: str = None, limit: int = 20) -> tuple:
        """Retrieve learnings plus types_in_use. Returns (results, types_in_use)."""
        results = self.recall_learnings(query=query, type=type, limit=limit)
        return results, self._types_in_use("learning")

    # --- Tasks ---

    def task_add(
        self,
        key: str,
        content: str,
        group: str = None,
        type: str = None,
        status: str = "pending",
    ) -> bool:
        """Add or replace a task, defaulting to status 'pending'."""
        return self._put("task", "task", key, content, status=status, group=group, type=type)

    def task_update(self, key: str, status: str = None, content: str = None, group: str = None) -> bool:
        """Update a task's status, content, or group. Returns True if changed."""
        path = f"task:{key}"
        cur = self.conn.execute('SELECT id, content, status, "group", type FROM documents WHERE path = ? AND source_type = ?', (path, "task"))
        existing = cur.fetchone()
        if not existing:
            return False

        new_content = content if content is not None else existing["content"]
        new_status = status if status is not None else existing["status"]
        new_group = group if group is not None else existing["group"]
        existing_type = existing["type"]

        return self._put("task", "task", key, new_content, status=new_status, group=new_group, type=existing_type)

    def task_remove(self, key: str) -> bool:
        """Remove a task by key."""
        return self._remove("task", "task", key)

    def task_list(self, status: str = None, group: str = None, query: str = None,
                  type: str = None, limit: int = 50) -> List[dict]:
        """List tasks, optionally filtered by status and/or group."""
        return self._list_typed("task", query=query, status=status, group=group, type=type, limit=limit)

    def task_list_with_types(self, status: str = None, group: str = None, query: str = None,
                             type: str = None, limit: int = 50) -> tuple:
        """List tasks plus types_in_use. Returns (results, types_in_use)."""
        results = self.task_list(status=status, group=group, query=query, type=type, limit=limit)
        return results, self._types_in_use("task")

    # --- Plans ---

    def plan_create(self, key: str, content: str, type: str = None, status: str = "active") -> bool:
        """Create or update a plan, defaulting to status 'active'."""
        return self._put("plan", "plan", key, content, status=status, type=type)

    def plan_get(self, key: str) -> Optional[dict]:
        """Get a single plan by key."""
        path = f"plan:{key}"
        cur = self.conn.execute(
            'SELECT id, path, content, indexed_at, status, "group", type, created_at, updated_at FROM documents WHERE path = ? AND source_type = ?',
            (path, "plan"),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def plan_archive(self, key: str) -> bool:
        """Archive a plan. Returns True if changed."""
        path = f"plan:{key}"
        cur = self.conn.execute(
            "UPDATE documents SET status = 'archived', indexed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE path = ? AND source_type = ? AND status = 'active'",
            (path, "plan"),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def plan_list(self, status: str = "active", query: str = None,
                  type: str = None, limit: int = 20) -> List[dict]:
        """List plans, defaulting to active only."""
        return self._list_typed("plan", query=query, status=status, type=type, limit=limit)

    def plan_list_with_types(self, status: str = "active", query: str = None,
                             type: str = None, limit: int = 20) -> tuple:
        """List plans plus types_in_use. Returns (results, types_in_use)."""
        results = self.plan_list(status=status, query=query, type=type, limit=limit)
        return results, self._types_in_use("plan")

    def close(self):
        self.conn.close()


def normalize_fts_query(query: str) -> str:
    terms = re.findall(r"[A-Za-z0-9_]+", query)
    if not terms:
        return ""
    return " AND ".join(f'"{term}"' for term in terms)
