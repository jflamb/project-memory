import pytest

from project_memory.db import ProjectMemoryDB
from project_memory.portability import export_memory, import_memory, parse_memory_md


@pytest.fixture
def db(tmp_path):
    with ProjectMemoryDB(root=tmp_path) as db:
        yield db


# --- export ---


def test_export_empty_db(db, tmp_path):
    md = export_memory(db)
    assert "# Project Memory" in md
    assert "project-memory" in md


def test_export_notes(db):
    db.remember("auth-pattern", "Use OAuth2 for all public clients", type="convention")
    db.remember("deploy-steps", "Run migrations before restarting", type="reference")
    md = export_memory(db)
    assert "## Notes" in md
    assert "### auth-pattern" in md
    assert "### deploy-steps" in md
    assert "**Type:** convention" in md
    assert "Use OAuth2 for all public clients" in md


def test_export_learnings(db):
    db.learn("sqlite-wal", "WAL mode enables concurrent reads", type="gotcha")
    md = export_memory(db)
    assert "## Learnings" in md
    assert "### sqlite-wal" in md
    assert "**Type:** gotcha" in md


def test_export_tasks(db):
    db.task_add("write-tests", "Write integration tests", group="v0.2", type="feature")
    md = export_memory(db)
    assert "## Tasks" in md
    assert "### write-tests" in md
    assert "**Status:** pending" in md
    assert "**Group:** v0.2" in md
    assert "**Type:** feature" in md


def test_export_plans_grouped_by_type(db):
    db.plan_create("branching", "Always create a feature branch", type="protocol")
    db.plan_create("vector-search", "Add embedding-based search", type="design")
    db.plan_create("release-checklist", "- [ ] Tag\n- [ ] Push", type="checklist")
    db.plan_create("untyped-plan", "A plan without a type")
    md = export_memory(db)
    # Protocols should appear before designs, which appear before checklists
    proto_pos = md.index("## Protocols")
    design_pos = md.index("## Designs")
    checklist_pos = md.index("## Checklists")
    plans_pos = md.index("## Plans")
    assert proto_pos < design_pos < checklist_pos < plans_pos
    assert "### branching" in md
    assert "### vector-search" in md
    assert "### release-checklist" in md
    assert "### untyped-plan" in md


def test_export_plan_includes_status(db):
    db.plan_create("p1", "plan one", type="design")
    md = export_memory(db)
    assert "**Status:** active" in md


def test_export_includes_updated_at(db):
    db.remember("key1", "content", type="convention")
    md = export_memory(db)
    assert "**Updated:**" in md


def test_export_notes_without_type(db):
    db.remember("misc", "something without a type")
    md = export_memory(db)
    assert "### misc" in md
    # Should still be under Notes section even without type
    assert "## Notes" in md


def test_export_archived_plans_excluded(db):
    db.plan_create("old", "archived plan")
    db.plan_archive("old")
    db.plan_create("current", "active plan")
    md = export_memory(db)
    assert "### current" in md
    assert "### old" in md


# --- parse (round-trip support) ---


def test_parse_notes():
    md = """# Project Memory

> Exported from project-memory v0.1.0 on 2026-03-21.

## Notes

### auth-pattern
**Type:** convention | **Updated:** 2026-03-21T10:00:00.000Z

Use OAuth2 for all public clients.

### deploy-steps
**Type:** reference | **Updated:** 2026-03-21T10:00:00.000Z

Run migrations before restarting.
"""
    entries = parse_memory_md(md)
    notes = [e for e in entries if e["source_type"] == "note"]
    assert len(notes) == 2
    assert notes[0]["key"] == "auth-pattern"
    assert notes[0]["type"] == "convention"
    assert notes[0]["content"] == "Use OAuth2 for all public clients."
    assert notes[1]["key"] == "deploy-steps"


def test_parse_learnings():
    md = """# Project Memory

## Learnings

### sqlite-wal
**Type:** gotcha | **Updated:** 2026-03-21T10:00:00.000Z

WAL mode enables concurrent reads.
"""
    entries = parse_memory_md(md)
    assert len(entries) == 1
    assert entries[0]["source_type"] == "learning"
    assert entries[0]["key"] == "sqlite-wal"
    assert entries[0]["type"] == "gotcha"


def test_parse_tasks():
    md = """# Project Memory

## Tasks

### write-tests
**Type:** feature | **Status:** pending | **Group:** v0.2 | **Updated:** 2026-03-21T10:00:00.000Z

Write integration tests for the export command.
"""
    entries = parse_memory_md(md)
    assert len(entries) == 1
    assert entries[0]["source_type"] == "task"
    assert entries[0]["key"] == "write-tests"
    assert entries[0]["status"] == "pending"
    assert entries[0]["group"] == "v0.2"
    assert entries[0]["type"] == "feature"


def test_parse_plans():
    md = """# Project Memory

## Protocols

### branching
**Type:** protocol | **Status:** active | **Updated:** 2026-03-21T10:00:00.000Z

Always create a feature branch.

## Designs

### vector-search
**Type:** design | **Status:** active | **Updated:** 2026-03-21T10:00:00.000Z

Add embedding-based search alongside FTS5.
"""
    entries = parse_memory_md(md)
    assert len(entries) == 2
    plans = [e for e in entries if e["source_type"] == "plan"]
    assert len(plans) == 2
    assert plans[0]["key"] == "branching"
    assert plans[0]["type"] == "protocol"
    assert plans[1]["key"] == "vector-search"
    assert plans[1]["type"] == "design"


def test_parse_entry_without_type():
    md = """# Project Memory

## Notes

### misc
**Updated:** 2026-03-21T10:00:00.000Z

Something without a type.
"""
    entries = parse_memory_md(md)
    assert len(entries) == 1
    assert entries[0]["type"] is None
    assert entries[0]["content"] == "Something without a type."


# --- import ---


def test_import_creates_entries(db, tmp_path):
    md = """# Project Memory

## Notes

### auth-pattern
**Type:** convention | **Updated:** 2026-03-21T10:00:00.000Z

Use OAuth2 for all public clients.

## Learnings

### sqlite-wal
**Type:** gotcha | **Updated:** 2026-03-21T10:00:00.000Z

WAL mode enables concurrent reads.
"""
    (tmp_path / "MEMORY.md").write_text(md)
    result = import_memory(db, tmp_path / "MEMORY.md")
    assert result["imported"] == 2
    assert result["skipped"] == 0

    notes = db.recall()
    assert len(notes) == 1
    assert notes[0]["type"] == "convention"

    learnings = db.recall_learnings()
    assert len(learnings) == 1
    assert learnings[0]["type"] == "gotcha"


def test_import_idempotent(db, tmp_path):
    md = """# Project Memory

## Notes

### key1
**Type:** convention | **Updated:** 2026-03-21T10:00:00.000Z

Some content.
"""
    (tmp_path / "MEMORY.md").write_text(md)
    result1 = import_memory(db, tmp_path / "MEMORY.md")
    assert result1["imported"] == 1

    result2 = import_memory(db, tmp_path / "MEMORY.md")
    assert result2["imported"] == 0
    assert result2["skipped"] == 1


def test_import_tasks(db, tmp_path):
    md = """# Project Memory

## Tasks

### fix-bug
**Type:** bug | **Status:** pending | **Group:** v0.2 | **Updated:** 2026-03-21T10:00:00.000Z

Fix the login bug.
"""
    (tmp_path / "MEMORY.md").write_text(md)
    import_memory(db, tmp_path / "MEMORY.md")
    tasks = db.task_list()
    assert len(tasks) == 1
    assert tasks[0]["type"] == "bug"
    assert tasks[0]["status"] == "pending"
    assert tasks[0]["group"] == "v0.2"


def test_import_preserves_done_task_status(db, tmp_path):
    md = """# Project Memory

## Tasks

### fix-bug
**Type:** bug | **Status:** done | **Group:** v0.2 | **Updated:** 2026-03-21T10:00:00.000Z

Fix the login bug.
"""
    (tmp_path / "MEMORY.md").write_text(md)
    import_memory(db, tmp_path / "MEMORY.md")
    tasks = db.task_list(status="done")
    assert len(tasks) == 1
    assert tasks[0]["status"] == "done"


def test_import_plans(db, tmp_path):
    md = """# Project Memory

## Protocols

### branching
**Type:** protocol | **Status:** active | **Updated:** 2026-03-21T10:00:00.000Z

Always create a feature branch.
"""
    (tmp_path / "MEMORY.md").write_text(md)
    import_memory(db, tmp_path / "MEMORY.md")
    plans = db.plan_list(status=None)
    assert len(plans) == 1
    assert plans[0]["type"] == "protocol"


def test_import_preserves_archived_plan_status(db, tmp_path):
    md = """# Project Memory

## Designs

### vector-search
**Type:** design | **Status:** archived | **Updated:** 2026-03-21T10:00:00.000Z

Add embedding-based search alongside FTS5.
"""
    (tmp_path / "MEMORY.md").write_text(md)
    import_memory(db, tmp_path / "MEMORY.md")
    plans = db.plan_list(status="archived")
    assert len(plans) == 1
    assert plans[0]["status"] == "archived"


# --- round-trip ---


def test_export_import_round_trip(db, tmp_path):
    db.remember("auth", "OAuth2 pattern", type="convention")
    db.learn("wal", "WAL mode", type="gotcha")
    db.task_add("t1", "Fix login", group="v0.2", type="bug")
    db.plan_create("branching", "Feature branch rules", type="protocol")

    md = export_memory(db)
    (tmp_path / "MEMORY.md").write_text(md)

    # Create a fresh DB and import
    db2_path = tmp_path / "db2"
    db2_path.mkdir()
    with ProjectMemoryDB(root=db2_path) as db2:
        result = import_memory(db2, tmp_path / "MEMORY.md")
        assert result["imported"] == 4

        notes = db2.recall()
        assert len(notes) == 1
        assert notes[0]["type"] == "convention"

        learnings = db2.recall_learnings()
        assert len(learnings) == 1
        assert learnings[0]["type"] == "gotcha"

        tasks = db2.task_list()
        assert len(tasks) == 1
        assert tasks[0]["type"] == "bug"
        assert tasks[0]["group"] == "v0.2"

        plans = db2.plan_list(status=None)
        assert len(plans) == 1
        assert plans[0]["type"] == "protocol"


def test_export_import_round_trip_preserves_archived_plan_and_done_task(tmp_path):
    db1_path = tmp_path / "db1"
    db1_path.mkdir()
    with ProjectMemoryDB(root=db1_path) as db1:
        db1.task_add("t1", "Fix login", group="v0.2", type="bug")
        db1.task_update("t1", status="done")
        db1.plan_create("branching", "Feature branch rules", type="protocol")
        db1.plan_archive("branching")
        md = export_memory(db1)

    memory_md = tmp_path / "MEMORY.md"
    memory_md.write_text(md)

    db2_path = tmp_path / "db2"
    db2_path.mkdir()
    with ProjectMemoryDB(root=db2_path) as db2:
        result = import_memory(db2, memory_md)
        assert result["imported"] == 2
        tasks = db2.task_list(status="done")
        assert len(tasks) == 1
        plans = db2.plan_list(status="archived")
        assert len(plans) == 1
