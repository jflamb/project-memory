import sqlite3

import pytest

import project_memory.db as db_module
from project_memory.db import ProjectMemoryDB, content_hash, normalize_fts_query


@pytest.fixture
def db(tmp_path):
    with ProjectMemoryDB(root=tmp_path) as db:
        yield db


# --- context manager ---


def test_context_manager_closes_connection(tmp_path):
    with ProjectMemoryDB(root=tmp_path) as db:
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


def test_busy_timeout_configured(db):
    timeout = db.conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert timeout == 5000


# --- schema migration from v0 ---


def test_migrate_from_v0_schema(tmp_path):
    """Simulate a v0 database and verify migration adds columns and triggers."""
    db_dir = tmp_path / ".project-memory"
    db_dir.mkdir()
    db_path = db_dir / "project_memory.db"

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
    with ProjectMemoryDB(root=tmp_path) as db:
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


def test_remember_updates_type_without_content_change(db):
    db.remember("key1", "version 1")
    assert db.remember("key1", "version 1", type="reference") is True
    notes = db.recall()
    assert notes[0]["type"] == "reference"


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


def test_task_update_group_only(db):
    db.task_add("t1", "original", group="v0.1")
    assert db.task_update("t1", group="v0.2") is True
    tasks = db.task_list(group="v0.2")
    assert len(tasks) == 1
    assert tasks[0]["group"] == "v0.2"


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


def test_plan_create_can_preserve_archived_status(db):
    db.plan_create("p1", "version 1", status="archived")
    plan = db.plan_get("p1")
    assert plan["status"] == "archived"


def test_plan_search(db):
    db.plan_create("auth", "implement OAuth2 authentication flow")
    db.plan_create("db", "add database migrations")
    results = db.plan_list(query="OAuth2", status=None)
    assert len(results) == 1
    assert results[0]["path"] == "plan:auth"


# --- migration v1 to v2 ---


def test_migrate_v1_to_v2(tmp_path):
    """Simulate a v1 database and verify migration adds status and group columns."""
    db_dir = tmp_path / ".project-memory"
    db_dir.mkdir()
    db_path = db_dir / "project_memory.db"

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

    with ProjectMemoryDB(root=tmp_path) as db:
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


def test_normalize_preserves_quoted_phrases():
    assert normalize_fts_query('"connection pool" timeout') == '"connection pool" AND "timeout"'


# --- schema evolution: migration v2 to v3 ---


def test_migrate_v2_to_v3(tmp_path):
    """Simulate a v2 database and verify migration adds created_at, updated_at, type columns."""
    db_dir = tmp_path / ".project-memory"
    db_dir.mkdir()
    db_path = db_dir / "project_memory.db"

    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY,
            path TEXT UNIQUE NOT NULL,
            content TEXT NOT NULL,
            source_type TEXT DEFAULT 'file',
            indexed_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            content_hash TEXT,
            status TEXT,
            "group" TEXT
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
    conn.execute(
        "INSERT INTO documents(path, content, source_type, indexed_at) VALUES ('note:deploy', 'run migrations', 'note', '2026-03-20T10:00:00.000Z')"
    )
    conn.execute("PRAGMA user_version = 2")
    conn.commit()
    conn.close()

    with ProjectMemoryDB(root=tmp_path) as db:
        # Existing note should still work
        notes = db.recall()
        assert len(notes) == 1
        # created_at and updated_at should be backfilled from indexed_at
        row = db.conn.execute("SELECT created_at, updated_at, type FROM documents WHERE path = 'note:deploy'").fetchone()
        assert row["created_at"] == "2026-03-20T10:00:00.000Z"
        assert row["updated_at"] == "2026-03-20T10:00:00.000Z"
        assert row["type"] is None  # backwards compatible


# --- schema evolution: timestamps ---


def test_remember_sets_timestamps(db):
    db.remember("key1", "content")
    row = db.conn.execute("SELECT created_at, updated_at FROM documents WHERE path = 'note:key1'").fetchone()
    assert row["created_at"] is not None
    assert row["updated_at"] is not None


def test_remember_update_preserves_created_at(db):
    db.remember("key1", "v1")
    row1 = db.conn.execute("SELECT created_at, updated_at FROM documents WHERE path = 'note:key1'").fetchone()
    created_at_1 = row1["created_at"]

    import time; time.sleep(0.01)
    db.remember("key1", "v2")
    row2 = db.conn.execute("SELECT created_at, updated_at FROM documents WHERE path = 'note:key1'").fetchone()
    assert row2["created_at"] == created_at_1  # immutable
    assert row2["updated_at"] >= row1["updated_at"]  # bumped


def test_upsert_document_sets_timestamps(db):
    db.upsert_document("file.txt", "content")
    row = db.conn.execute("SELECT created_at, updated_at FROM documents WHERE path = 'file.txt'").fetchone()
    assert row["created_at"] is not None
    assert row["updated_at"] is not None


def test_upsert_document_update_preserves_created_at(db):
    db.upsert_document("file.txt", "v1")
    row1 = db.conn.execute("SELECT created_at FROM documents WHERE path = 'file.txt'").fetchone()

    db.upsert_document("file.txt", "v2")
    row2 = db.conn.execute("SELECT created_at, updated_at FROM documents WHERE path = 'file.txt'").fetchone()
    assert row2["created_at"] == row1["created_at"]


def test_task_add_sets_timestamps(db):
    db.task_add("t1", "task one")
    row = db.conn.execute("SELECT created_at, updated_at FROM documents WHERE path = 'task:t1'").fetchone()
    assert row["created_at"] is not None
    assert row["updated_at"] is not None


def test_plan_create_sets_timestamps(db):
    db.plan_create("p1", "plan one")
    row = db.conn.execute("SELECT created_at, updated_at FROM documents WHERE path = 'plan:p1'").fetchone()
    assert row["created_at"] is not None
    assert row["updated_at"] is not None


def test_learn_sets_timestamps(db):
    db.learn("l1", "learning one")
    row = db.conn.execute("SELECT created_at, updated_at FROM documents WHERE path = 'learning:l1'").fetchone()
    assert row["created_at"] is not None
    assert row["updated_at"] is not None


# --- schema evolution: type column ---


def test_remember_with_type(db):
    db.remember("auth-pattern", "use OAuth2", type="convention")
    row = db.conn.execute("SELECT type FROM documents WHERE path = 'note:auth-pattern'").fetchone()
    assert row["type"] == "convention"


def test_remember_without_type(db):
    db.remember("deploy", "run migrations")
    row = db.conn.execute("SELECT type FROM documents WHERE path = 'note:deploy'").fetchone()
    assert row["type"] is None


def test_learn_with_type(db):
    db.learn("sqlite-wal", "WAL enables concurrent reads", type="gotcha")
    row = db.conn.execute("SELECT type FROM documents WHERE path = 'learning:sqlite-wal'").fetchone()
    assert row["type"] == "gotcha"


def test_task_add_with_type(db):
    db.task_add("fix-bug", "fix the login bug", type="bug")
    row = db.conn.execute("SELECT type FROM documents WHERE path = 'task:fix-bug'").fetchone()
    assert row["type"] == "bug"


def test_plan_create_with_type(db):
    db.plan_create("release", "release checklist", type="checklist")
    row = db.conn.execute("SELECT type FROM documents WHERE path = 'plan:release'").fetchone()
    assert row["type"] == "checklist"


# --- schema evolution: type filtering ---


def test_recall_filter_by_type(db):
    db.remember("auth", "OAuth2 pattern", type="convention")
    db.remember("deploy", "deploy steps", type="reference")
    db.remember("misc", "something else")
    results = db.recall(type="convention")
    assert len(results) == 1
    assert results[0]["path"] == "note:auth"


def test_recall_learnings_filter_by_type(db):
    db.learn("wal", "WAL mode", type="gotcha")
    db.learn("fts", "FTS5 triggers", type="pattern")
    results = db.recall_learnings(type="gotcha")
    assert len(results) == 1
    assert results[0]["path"] == "learning:wal"


def test_task_list_filter_by_type(db):
    db.task_add("t1", "fix login", type="bug")
    db.task_add("t2", "add search", type="feature")
    results = db.task_list(type="bug")
    assert len(results) == 1
    assert results[0]["path"] == "task:t1"


def test_plan_list_filter_by_type(db):
    db.plan_create("p1", "release plan", type="checklist")
    db.plan_create("p2", "branching rules", type="protocol")
    results = db.plan_list(type="protocol", status=None)
    assert len(results) == 1
    assert results[0]["path"] == "plan:p2"


# --- schema evolution: types_in_use ---


def test_recall_returns_types_in_use(db):
    db.remember("a", "content a", type="convention")
    db.remember("b", "content b", type="reference")
    db.remember("c", "content c", type="convention")
    results, types_in_use = db.recall_with_types()
    assert set(types_in_use) == {"convention", "reference"}


def test_recall_learnings_returns_types_in_use(db):
    db.learn("a", "content a", type="gotcha")
    db.learn("b", "content b", type="pattern")
    results, types_in_use = db.recall_learnings_with_types()
    assert set(types_in_use) == {"gotcha", "pattern"}


def test_task_list_returns_types_in_use(db):
    db.task_add("t1", "fix login", type="bug")
    db.task_add("t2", "add search", type="feature")
    results, types_in_use = db.task_list_with_types()
    assert set(types_in_use) == {"bug", "feature"}


def test_plan_list_returns_types_in_use(db):
    db.plan_create("p1", "plan one", type="design")
    db.plan_create("p2", "plan two", type="protocol")
    results, types_in_use = db.plan_list_with_types(status=None)
    assert set(types_in_use) == {"design", "protocol"}


def test_types_in_use_excludes_null(db):
    db.remember("a", "with type", type="convention")
    db.remember("b", "no type")
    results, types_in_use = db.recall_with_types()
    assert types_in_use == ["convention"]


# --- schema evolution: list results include type ---


def test_recall_results_include_type(db):
    db.remember("auth", "OAuth2", type="convention")
    results = db.recall()
    assert results[0]["type"] == "convention"


def test_task_list_results_include_type(db):
    db.task_add("t1", "fix login", type="bug")
    results = db.task_list()
    assert results[0]["type"] == "bug"


def test_plan_get_includes_type(db):
    db.plan_create("p1", "plan content", type="design")
    plan = db.plan_get("p1")
    assert plan["type"] == "design"


# --- history ---


def test_history_versions_created_for_note_updates(db):
    db.remember("auth", "version 1", type="convention")
    db.remember("auth", "version 2", type="reference")

    versions = db.history_list("auth", "note")
    assert len(versions) == 2
    assert versions[0]["operation_type"] == "update"
    assert versions[1]["operation_type"] == "create"

    latest = db.history_get(versions[0]["id"])
    assert latest["content"] == "version 2"
    assert latest["type"] == "reference"


def test_history_noop_write_does_not_create_duplicate_version(db):
    db.remember("auth", "same content")
    assert db.remember("auth", "same content") is False
    versions = db.history_list("auth", "note")
    assert len(versions) == 1


def test_plan_archive_creates_history_version(db):
    db.plan_create("release", "plan content", type="checklist")
    assert db.plan_archive("release") is True
    versions = db.history_list("release", "plan")
    assert len(versions) == 2
    assert versions[0]["operation_type"] == "archive"
    assert versions[0]["status"] == "archived"


def test_history_diff_shows_content_changes(db):
    db.task_add("t1", "first version", status="pending")
    db.task_update("t1", status="done", content="second version")
    versions = db.history_list("t1", "task")
    diff = db.history_diff(versions[1]["id"], versions[0]["id"])
    assert diff is not None
    assert "--- task:t1@" in diff["diff"]
    assert "+status: done" in diff["diff"]
    assert "+second version" in diff["diff"]


def test_history_restore_recreates_prior_state_and_version(db):
    db.task_add("t1", "first version", status="pending", group="v1", type="bug")
    db.task_update("t1", status="done", content="second version", group="v2")
    older_version = db.history_list("t1", "task")[1]

    restored = db.history_restore(older_version["id"])
    assert restored is not None
    assert restored["restored"] is True

    current = db.task_list(status="pending")
    assert len(current) == 1
    assert current[0]["content"] == "first version"
    assert current[0]["group"] == "v1"

    versions = db.history_list("t1", "task")
    assert versions[0]["operation_type"] == "restore"


def test_history_restore_missing_version_returns_none(db):
    assert db.history_restore(9999) is None


def test_migrate_v4_to_v5_backfills_history(tmp_path):
    db_dir = tmp_path / ".project-memory"
    db_dir.mkdir()
    db_path = db_dir / "project_memory.db"

    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY,
            path TEXT UNIQUE NOT NULL,
            content TEXT NOT NULL,
            source_type TEXT DEFAULT 'file',
            indexed_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            content_hash TEXT,
            status TEXT,
            "group" TEXT,
            created_at TEXT,
            updated_at TEXT,
            type TEXT
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
        CREATE TABLE embedding_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            model TEXT NOT NULL,
            dimensions INTEGER NOT NULL,
            base_url TEXT NOT NULL
        );
    """)
    conn.execute(
        """
        INSERT INTO documents(path, content, source_type, content_hash, status, created_at, updated_at, type)
        VALUES ('note:seeded', 'seeded content', 'note', ?, NULL, '2026-03-21T10:00:00.000Z', '2026-03-21T10:00:00.000Z', 'reference')
        """,
        (content_hash("seeded content"),),
    )
    conn.execute("PRAGMA user_version = 4")
    conn.commit()
    conn.close()

    with ProjectMemoryDB(root=tmp_path) as db:
        versions = db.history_list("seeded", "note")
        assert len(versions) == 1
        version = db.history_get(versions[0]["id"])
        assert version["content"] == "seeded content"
        assert version["operation_type"] == "create"
        assert version["type"] == "reference"


def test_history_version_count_tracks_entry_versions(db):
    assert db.history_version_count() == 0
    db.remember("auth", "v1")
    db.remember("auth", "v2")
    assert db.history_version_count() == 2


def test_init_closes_connection_when_migrations_fail(tmp_path, monkeypatch):
    opened_connections = []
    real_connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        conn = real_connect(*args, **kwargs)
        opened_connections.append(conn)
        return conn

    monkeypatch.setattr(db_module.sqlite3, "connect", tracking_connect)
    monkeypatch.setattr(ProjectMemoryDB, "_load_vec_extension", lambda self: setattr(self, "_has_vec", False))
    monkeypatch.setattr(ProjectMemoryDB, "_run_migrations", lambda self: (_ for _ in ()).throw(RuntimeError("boom")))

    with pytest.raises(RuntimeError, match="boom"):
        ProjectMemoryDB(root=tmp_path)

    assert len(opened_connections) == 1
    with pytest.raises(sqlite3.ProgrammingError):
        opened_connections[0].execute("SELECT 1")


def test_failed_migration_rolls_back_and_preserves_schema_version(tmp_path, monkeypatch):
    db_dir = tmp_path / ".project-memory"
    db_dir.mkdir()
    db_path = db_dir / "project_memory.db"

    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE documents (
            id INTEGER PRIMARY KEY,
            path TEXT UNIQUE NOT NULL,
            content TEXT NOT NULL,
            source_type TEXT DEFAULT 'file',
            indexed_at TEXT DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            content_hash TEXT,
            status TEXT,
            "group" TEXT,
            created_at TEXT,
            updated_at TEXT,
            type TEXT
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
        CREATE TABLE embedding_config (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            model TEXT NOT NULL,
            dimensions INTEGER NOT NULL,
            base_url TEXT NOT NULL
        );
    """)
    conn.execute("PRAGMA user_version = 4")
    conn.commit()
    conn.close()

    original = db_module.MIGRATIONS[4]

    def failing_migration(conn):
        conn.execute("CREATE TABLE migration_marker(id INTEGER PRIMARY KEY)")
        raise RuntimeError("migration failed")

    try:
        db_module.MIGRATIONS[4] = failing_migration

        with pytest.raises(RuntimeError, match="migration failed"):
            ProjectMemoryDB(root=tmp_path)

        check_conn = sqlite3.connect(db_path)
        try:
            version = check_conn.execute("PRAGMA user_version").fetchone()[0]
            assert version == 4
            marker = check_conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'migration_marker'"
            ).fetchone()
            assert marker is None
        finally:
            check_conn.close()
    finally:
        db_module.MIGRATIONS[4] = original
