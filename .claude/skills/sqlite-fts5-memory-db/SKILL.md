---
name: sqlite-fts5-memory-db
description: Patterns for using SQLite as a knowledge store or memory database — schema design, FTS5 full-text search (content-sync tables, triggers, bm25 ranking, query syntax), migrations without an ORM, WAL mode, connection management, and future-proofing for sqlite-vec embeddings. Use this skill whenever you're working with SQLite for document storage, building search functionality over a local database, designing schemas for AI memory or knowledge bases, writing FTS5 queries, or planning to add vector/semantic search to an existing SQLite database. Also trigger when you see `sqlite3` imports combined with `CREATE VIRTUAL TABLE ... USING fts5`, or the user mentions "full-text search", "document indexing", or "memory database".
---

# SQLite as a Knowledge Store

This skill covers patterns for building local knowledge/memory databases with SQLite, focusing on full-text search with FTS5 and schemas that can evolve toward semantic search.

The core idea: SQLite is a remarkably capable foundation for local AI memory. FTS5 gives you fast keyword search with ranking out of the box. The schema patterns here are designed to work well now and extend cleanly when you're ready to add embeddings.

## Schema Design

### Document table

Start with a clear separation between the document record and its searchable content:

```sql
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    content TEXT NOT NULL,
    source_type TEXT DEFAULT 'file',
    indexed_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    content_hash TEXT
) STRICT;
```

Why each column matters:
- **`path UNIQUE`**: Natural dedup key — re-indexing the same file updates rather than duplicates
- **`source_type`**: Lets you distinguish files, git commits, clipboard entries, etc. as the system grows
- **`indexed_at`**: Know when content was last refreshed; useful for incremental re-indexing
- **`content_hash`**: Skip re-indexing unchanged files (compare hash before writing)
- **`STRICT`**: SQLite's strict typing mode — catches type errors at insert time instead of silently coercing

### Metadata table (optional, add when needed)

Don't add metadata columns to the document table until you need them. When you do:

```sql
CREATE TABLE IF NOT EXISTS document_metadata (
    document_id INTEGER PRIMARY KEY REFERENCES documents(id) ON DELETE CASCADE,
    tags TEXT,  -- JSON array: '["python", "config"]'
    language TEXT,
    line_count INTEGER
) STRICT;
```

Keeping metadata separate avoids bloating the main table with nullable columns.

## FTS5 Full-Text Search

### Content-sync tables

FTS5 content-sync (`content=`) keeps the FTS index pointing at an external table instead of storing its own copy of the text. This saves disk space but requires triggers to stay in sync.

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
    path,
    content,
    content='documents',
    content_rowid='id'
);
```

### Sync triggers — these are essential

Without triggers, the FTS index goes stale when you update or delete documents. The index will return ghost results (deleted docs) or miss updated content. These three triggers fix that:

```sql
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
```

The `'delete'` command is FTS5's way of removing an entry — you insert a row with the special first column set to `'delete'` and provide the old values so FTS5 can remove the right tokens from its index.

With these triggers in place, you can use plain `INSERT OR REPLACE` on the documents table and the FTS index stays correct automatically. No manual FTS inserts needed in application code.

### Query syntax

FTS5 supports a rich query language:

```python
# Simple keyword
db.execute("SELECT * FROM documents_fts WHERE documents_fts MATCH 'migration'")

# Boolean operators
"migration AND schema"      # both terms
"migration OR upgrade"      # either term
"migration NOT test"        # exclude term

# Phrase search
'"schema migration"'        # exact phrase

# Prefix search
"migrat*"                   # matches migration, migrate, migrating

# Column filter
"path:src content:schema"   # path contains 'src', content contains 'schema'
```

### Ranked results with bm25()

Unranked FTS5 results come back in arbitrary order. Use `bm25()` to rank by relevance:

```python
def search(self, query: str, limit: int = 20) -> list[dict]:
    cur = self.conn.execute("""
        SELECT d.id, d.path, d.content, bm25(documents_fts) AS rank
        FROM documents d
        JOIN documents_fts f ON d.id = f.rowid
        WHERE documents_fts MATCH ?
        ORDER BY rank  -- bm25 returns negative values; closer to 0 = better match
        LIMIT ?
    """, (query, limit))
    return [{"id": r[0], "path": r[1], "content": r[2], "rank": r[3]} for r in cur.fetchall()]
```

`bm25()` returns negative scores where closer to 0 is a better match. If you have multiple FTS columns, you can weight them: `bm25(documents_fts, 2.0, 1.0)` gives path matches double the weight of content matches.

### Snippet extraction

FTS5 can extract highlighted snippets for search result previews:

```python
cur.execute("""
    SELECT d.id, d.path, snippet(documents_fts, 1, '<b>', '</b>', '...', 30) AS snippet
    FROM documents d
    JOIN documents_fts f ON d.id = f.rowid
    WHERE documents_fts MATCH ?
    ORDER BY bm25(documents_fts)
    LIMIT ?
""", (query, limit))
```

Arguments to `snippet()`: column index (1 = content), opening marker, closing marker, ellipsis text, max tokens. For CLI output, use `>>` and `<<` instead of HTML tags.

## Schema Migrations

### Version tracking

Track schema version without an ORM using SQLite's `user_version` pragma:

```python
def _get_schema_version(self) -> int:
    return self.conn.execute("PRAGMA user_version").fetchone()[0]

def _set_schema_version(self, version: int):
    self.conn.execute(f"PRAGMA user_version = {version}")
    self.conn.commit()
```

### Migration pattern

Define migrations as a list of functions, run them in order:

```python
MIGRATIONS = [
    # version 0 → 1: initial schema
    lambda conn: conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (...);
        CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(...);
        -- triggers here
    """),
    # version 1 → 2: add source_type column
    lambda conn: conn.execute(
        "ALTER TABLE documents ADD COLUMN source_type TEXT DEFAULT 'file'"
    ),
]

def _run_migrations(self):
    current = self._get_schema_version()
    for i, migration in enumerate(MIGRATIONS):
        if i >= current:
            migration(self.conn)
    self._set_schema_version(len(MIGRATIONS))
    self.conn.commit()
```

Call `_run_migrations()` in `__init__` after opening the connection. Each migration runs once. The version number is stored in the database file itself, so it travels with the `.openbrain/` directory.

## WAL Mode

Write-Ahead Logging lets readers and writers work concurrently. Without it, a long indexing operation blocks searches. Enable it once per database:

```python
def __init__(self, root=None):
    ...
    self.conn = sqlite3.connect(self.db_path)
    self.conn.execute("PRAGMA journal_mode=WAL")
    self.conn.execute("PRAGMA foreign_keys=ON")
```

WAL mode persists — you only need to set it once, but setting it on every connection is harmless and self-documenting. It creates two extra files (`-wal` and `-shm`) alongside the database; include `*.db-wal` and `*.db-shm` in `.gitignore`.

## Connection Management

### Context manager pattern

Wrap the database class as a context manager to prevent connection leaks:

```python
class OpenBrainDB:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False  # don't suppress exceptions
```

Usage:

```python
with OpenBrainDB(root=path) as db:
    results = db.search("query")
# connection is closed even if search() raises
```

This replaces the manual `db = OpenBrainDB(); ...; db.close()` pattern, which leaks the connection if anything between open and close raises an exception.

### Row factory

Use `sqlite3.Row` for dict-like access without manual tuple unpacking:

```python
self.conn.row_factory = sqlite3.Row

# Then in queries:
row = cur.fetchone()
path = row["path"]  # instead of row[1]
```

Or, if you prefer plain dicts:

```python
def dict_factory(cursor, row):
    return {col[0]: row[i] for i, col in enumerate(cursor.description)}

self.conn.row_factory = dict_factory
```

## Path Toward Embeddings

When you're ready to add semantic search (the `sqlite-vec` enhancement from the spec), the schema extends cleanly:

```sql
-- Future: vector table alongside FTS5
CREATE VIRTUAL TABLE IF NOT EXISTS document_embeddings USING vec0(
    document_id INTEGER,
    embedding float[384]  -- dimension depends on model
);
```

Hybrid search combines FTS5 keyword results with vector similarity:

1. FTS5 query returns candidates ranked by `bm25()`
2. Vector query returns candidates ranked by cosine similarity
3. Merge results using reciprocal rank fusion or a weighted score

The important thing is that the current FTS5 schema doesn't need to change — you add the vector table alongside it. Design your search interface to return ranked results now (`rank` field in results), so the calling code doesn't care whether ranking comes from bm25, vector similarity, or a hybrid of both.

Don't add the vector table until you actually need it. The FTS5 keyword search is surprisingly effective for code and documentation — it's worth seeing how far it takes you before adding embedding complexity.
