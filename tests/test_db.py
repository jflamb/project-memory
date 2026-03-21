import sqlite3

import pytest

from openbrain.db import OpenBrainDB, content_hash, normalize_fts_query


@pytest.fixture
def db(tmp_path):
    with OpenBrainDB(root=tmp_path) as db:
        yield db


# --- context manager ---


def test_context_manager_closes_connection(tmp_path):
    with OpenBrainDB(root=tmp_path) as db:
        conn = db.conn
    # Connection should be closed after exiting context
    with pytest.raises(Exception):
        conn.execute("SELECT 1")


# --- upsert and content hash ---


def test_upsert_returns_true_on_new(db):
    assert db.upsert_document("a.txt", "hello") is True


def test_upsert_returns_false_on_unchanged(db):
    db.upsert_document("a.txt", "hello")
    assert db.upsert_document("a.txt", "hello") is False


def test_upsert_returns_true_on_changed(db):
    db.upsert_document("a.txt", "hello")
    assert db.upsert_document("a.txt", "hello world") is True


def test_content_hash_stored(db):
    db.upsert_document("a.txt", "test content")
    row = db.conn.execute("SELECT content_hash FROM documents WHERE path = 'a.txt'").fetchone()
    assert row["content_hash"] == content_hash("test content")


# --- FTS sync triggers ---


def test_fts_sync_on_insert(db):
    db.upsert_document("a.txt", "unique findable content")
    results = db.search("findable")
    assert len(results) == 1
    assert results[0]["path"] == "a.txt"


def test_fts_sync_on_update(db):
    db.upsert_document("a.txt", "original content")
    db.upsert_document("a.txt", "updated replacement")
    # Old content should not be findable
    assert db.search("original") == []
    # New content should be findable
    results = db.search("replacement")
    assert len(results) == 1
    assert results[0]["path"] == "a.txt"


def test_fts_sync_on_delete(db):
    db.upsert_document("a.txt", "deletable content")
    db.delete_missing_documents([])  # delete all
    assert db.search("deletable") == []


# --- bm25 ranking ---


def test_search_ranked_by_relevance(db):
    # Doc with more occurrences of "python" should rank higher
    db.upsert_document("sparse.txt", "python is a language")
    db.upsert_document("dense.txt", "python python python programming in python")
    results = db.search("python")
    assert len(results) == 2
    # dense.txt should rank first (closer to 0 = better match)
    assert results[0]["path"] == "dense.txt"
    assert "rank" in results[0]


# --- delete_missing_documents ---


def test_delete_missing_returns_count(db):
    db.upsert_document("a.txt", "alpha")
    db.upsert_document("b.txt", "beta")
    deleted = db.delete_missing_documents(["a.txt"])
    assert deleted == 1
    assert db.document_count() == 1


def test_delete_missing_empty_keeps_nothing(db):
    db.upsert_document("a.txt", "alpha")
    deleted = db.delete_missing_documents([])
    assert deleted == 1
    assert db.document_count() == 0


# --- list_documents ---


def test_list_documents_ordered(db):
    db.upsert_document("b.txt", "beta")
    db.upsert_document("a.txt", "alpha")
    docs = db.list_documents()
    assert [d["path"] for d in docs] == ["a.txt", "b.txt"]


# --- document_count ---


def test_document_count(db):
    assert db.document_count() == 0
    db.upsert_document("a.txt", "alpha")
    assert db.document_count() == 1


# --- WAL mode ---


def test_wal_mode_enabled(db):
    mode = db.conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"


# --- schema migration from v0 ---


def test_migrate_from_v0_schema(tmp_path):
    """Simulate a v0 database and verify migration adds columns and triggers."""
    db_dir = tmp_path / ".openbrain"
    db_dir.mkdir()
    db_path = db_dir / "openbrain.db"

    # Create a v0 schema manually
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY,
            path TEXT UNIQUE,
            content TEXT
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE documents_fts USING fts5(
            path, content, content='documents', content_rowid='id'
        )
    """)
    conn.execute("INSERT INTO documents(path, content) VALUES ('old.txt', 'legacy data')")
    conn.execute("INSERT INTO documents_fts(rowid, path, content) VALUES (1, 'old.txt', 'legacy data')")
    conn.commit()
    conn.close()

    # Open with new code — should trigger migration
    with OpenBrainDB(root=tmp_path) as db:
        # New columns should exist
        row = db.conn.execute("SELECT source_type, content_hash FROM documents WHERE path = 'old.txt'").fetchone()
        assert row["source_type"] == "file"

        # FTS should work (data was rebuilt)
        results = db.search("legacy")
        assert len(results) == 1
        assert results[0]["path"] == "old.txt"

        # Triggers should work for new inserts
        db.upsert_document("new.txt", "fresh data")
        results = db.search("fresh")
        assert len(results) == 1


# --- normalize_fts_query ---


def test_normalize_empty():
    assert normalize_fts_query("") == ""
    assert normalize_fts_query("---") == ""


def test_normalize_single_term():
    assert normalize_fts_query("hello") == '"hello"'


def test_normalize_multiple_terms():
    assert normalize_fts_query("foo-bar") == '"foo" AND "bar"'


def test_normalize_preserves_underscores():
    assert normalize_fts_query("my_func") == '"my_func"'
