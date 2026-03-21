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


# --- remember / forget / recall ---


def test_remember_stores_note(db):
    assert db.remember("deploy-steps", "run migrations then restart") is True
    notes = db.recall()
    assert len(notes) == 1
    assert notes[0]["path"] == "note:deploy-steps"
    assert "migrations" in notes[0]["content"]


def test_remember_skips_unchanged(db):
    db.remember("key1", "some content")
    assert db.remember("key1", "some content") is False


def test_remember_updates_changed(db):
    db.remember("key1", "version 1")
    assert db.remember("key1", "version 2") is True
    notes = db.recall()
    assert notes[0]["content"] == "version 2"


def test_forget_removes_note(db):
    db.remember("temp", "temporary note")
    assert db.forget("temp") is True
    assert db.recall() == []


def test_forget_returns_false_if_missing(db):
    assert db.forget("nonexistent") is False


def test_forget_does_not_delete_files(db):
    db.upsert_document("real-file.txt", "file content")
    db.remember("real-file.txt", "note content")
    db.forget("real-file.txt")
    # The file document should still exist
    docs = db.list_documents()
    assert any(d["path"] == "real-file.txt" for d in docs)


def test_recall_searches_notes(db):
    db.remember("auth", "use OAuth2 for authentication")
    db.remember("deploy", "deploy to k8s cluster")
    results = db.recall("OAuth2")
    assert len(results) == 1
    assert results[0]["path"] == "note:auth"


def test_recall_excludes_files(db):
    db.upsert_document("readme.txt", "OAuth2 docs here")
    db.remember("auth", "use OAuth2 for authentication")
    results = db.recall("OAuth2")
    # Only the note, not the file
    assert len(results) == 1
    assert results[0]["path"] == "note:auth"


def test_search_includes_notes(db):
    """Regular search should find both files and notes."""
    db.upsert_document("readme.txt", "project overview")
    db.remember("overview", "this project does X")
    results = db.search("overview")
    assert len(results) == 2


# --- learnings ---


def test_learn_stores_learning(db):
    assert db.learn("sqlite-alter", "ALTER TABLE rejects expression defaults") is True
    results = db.recall_learnings()
    assert len(results) == 1
    assert results[0]["path"] == "learning:sqlite-alter"


def test_learn_skips_unchanged(db):
    db.learn("key1", "content")
    assert db.learn("key1", "content") is False


def test_forget_learning(db):
    db.learn("temp", "temporary")
    assert db.forget_learning("temp") is True
    assert db.recall_learnings() == []


def test_recall_learnings_searches(db):
    db.learn("sqlite", "WAL mode enables concurrent reads")
    db.learn("python", "dataclasses are fast to define")
    results = db.recall_learnings("WAL")
    assert len(results) == 1
    assert results[0]["path"] == "learning:sqlite"


def test_learnings_isolated_from_notes(db):
    db.remember("sqlite", "note about sqlite")
    db.learn("sqlite", "learning about sqlite")
    assert len(db.recall()) == 1
    assert len(db.recall_learnings()) == 1


# --- tasks ---


def test_task_add_and_list(db):
    db.task_add("write-tests", "Write unit tests for db layer")
    tasks = db.task_list()
    assert len(tasks) == 1
    assert tasks[0]["path"] == "task:write-tests"
    assert tasks[0]["status"] == "pending"


def test_task_add_with_group(db):
    db.task_add("t1", "task one", group="v0.2")
    db.task_add("t2", "task two", group="v0.3")
    tasks = db.task_list(group="v0.2")
    assert len(tasks) == 1
    assert tasks[0]["path"] == "task:t1"


def test_task_update_status(db):
    db.task_add("t1", "task one")
    assert db.task_update("t1", status="in_progress") is True
    tasks = db.task_list(status="in_progress")
    assert len(tasks) == 1


def test_task_update_content(db):
    db.task_add("t1", "original")
    db.task_update("t1", content="updated description")
    tasks = db.task_list()
    assert tasks[0]["content"] == "updated description"


def test_task_update_nonexistent(db):
    assert db.task_update("ghost", status="done") is False


def test_task_remove(db):
    db.task_add("t1", "task one")
    assert db.task_remove("t1") is True
    assert db.task_list() == []


def test_task_list_by_status(db):
    db.task_add("t1", "pending task")
    db.task_add("t2", "another task")
    db.task_update("t2", status="done")
    pending = db.task_list(status="pending")
    done = db.task_list(status="done")
    assert len(pending) == 1
    assert len(done) == 1


def test_task_search(db):
    db.task_add("auth", "implement OAuth2 flow")
    db.task_add("db", "add migrations")
    results = db.task_list(query="OAuth2")
    assert len(results) == 1
    assert results[0]["path"] == "task:auth"


# --- plans ---


def test_plan_create_and_get(db):
    db.plan_create("vector-search", "## Phase 1\n- Add schema\n## Phase 2\n- Add API")
    plan = db.plan_get("vector-search")
    assert plan is not None
    assert plan["status"] == "active"
    assert "Phase 1" in plan["content"]


def test_plan_get_nonexistent(db):
    assert db.plan_get("ghost") is None


def test_plan_list_defaults_to_active(db):
    db.plan_create("p1", "plan one")
    db.plan_create("p2", "plan two")
    db.plan_archive("p1")
    active = db.plan_list()
    assert len(active) == 1
    assert active[0]["path"] == "plan:p2"


def test_plan_list_archived(db):
    db.plan_create("p1", "plan one")
    db.plan_archive("p1")
    archived = db.plan_list(status="archived")
    assert len(archived) == 1


def test_plan_list_all(db):
    db.plan_create("p1", "plan one")
    db.plan_create("p2", "plan two")
    db.plan_archive("p1")
    all_plans = db.plan_list(status=None)
    assert len(all_plans) == 2


def test_plan_archive_returns_false_if_already_archived(db):
    db.plan_create("p1", "plan one")
    db.plan_archive("p1")
    assert db.plan_archive("p1") is False


def test_plan_update_content(db):
    db.plan_create("p1", "version 1")
    db.plan_create("p1", "version 2")
    plan = db.plan_get("p1")
    assert plan["content"] == "version 2"


def test_plan_search(db):
    db.plan_create("auth", "implement OAuth2 authentication flow")
    db.plan_create("db", "add database migrations")
    results = db.plan_list(query="OAuth2", status=None)
    assert len(results) == 1
    assert results[0]["path"] == "plan:auth"


# --- migration v1 to v2 ---


def test_migrate_v1_to_v2(tmp_path):
    """Simulate a v1 database and verify migration adds status and group columns."""
    db_dir = tmp_path / ".openbrain"
    db_dir.mkdir()
    db_path = db_dir / "openbrain.db"

    conn = sqlite3.connect(db_path)
    # Create v1 schema (no status/group columns)
    conn.executescript("""
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY,
            path TEXT UNIQUE NOT NULL,
            content TEXT NOT NULL,
            source_type TEXT DEFAULT 'file',
            indexed_at TEXT,
            content_hash TEXT
        );
        CREATE VIRTUAL TABLE documents_fts USING fts5(path, content, content='documents', content_rowid='id');
        CREATE TRIGGER documents_ai AFTER INSERT ON documents BEGIN
            INSERT INTO documents_fts(rowid, path, content) VALUES (new.id, new.path, new.content);
        END;
        CREATE TRIGGER documents_ad AFTER DELETE ON documents BEGIN
            INSERT INTO documents_fts(documents_fts, rowid, path, content) VALUES ('delete', old.id, old.path, old.content);
        END;
        CREATE TRIGGER documents_au AFTER UPDATE ON documents BEGIN
            INSERT INTO documents_fts(documents_fts, rowid, path, content) VALUES ('delete', old.id, old.path, old.content);
            INSERT INTO documents_fts(rowid, path, content) VALUES (new.id, new.path, new.content);
        END;
    """)
    conn.execute("INSERT INTO documents(path, content, source_type) VALUES ('note:test', 'a note', 'note')")
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()

    with OpenBrainDB(root=tmp_path) as db:
        # Existing note should still work
        notes = db.recall()
        assert len(notes) == 1
        # New task features should work
        db.task_add("t1", "test task", group="batch1")
        tasks = db.task_list()
        assert len(tasks) == 1
        assert tasks[0]["status"] == "pending"
        assert tasks[0]["group"] == "batch1"


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
