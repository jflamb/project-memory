import json

import pytest
from typer.testing import CliRunner

from openbrain.cli import app


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def initialized_repo(tmp_path, runner):
    """A tmp_path with an initialized OpenBrain database."""
    result = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert result.exit_code == 0
    return tmp_path


# --- init ---


def test_init_creates_db(tmp_path, runner):
    result = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / ".openbrain" / "openbrain.db").exists()


def test_init_idempotent(tmp_path, runner):
    runner.invoke(app, ["init", "--path", str(tmp_path)])
    result = runner.invoke(app, ["init", "--path", str(tmp_path)])
    assert result.exit_code == 0


# --- index ---


def test_index_counts_files(initialized_repo, runner):
    (initialized_repo / "a.txt").write_text("hello")
    (initialized_repo / "b.py").write_text("world")
    result = runner.invoke(app, ["index", "--path", str(initialized_repo)])
    assert result.exit_code == 0
    assert "Indexed 2 documents" in result.output


def test_index_skips_generated_directories(initialized_repo, runner):
    (initialized_repo / "app.py").write_text("signal token")
    (initialized_repo / ".venv").mkdir()
    (initialized_repo / ".venv" / "noise.py").write_text("noise token")

    runner.invoke(app, ["index", "--path", str(initialized_repo)])
    result = runner.invoke(app, ["search", "token", "--path", str(initialized_repo)])

    assert result.exit_code == 0
    assert "app.py" in result.output
    assert ".venv/noise.py" not in result.output


def test_index_reports_unchanged(initialized_repo, runner):
    (initialized_repo / "doc.txt").write_text("stable content")
    runner.invoke(app, ["index", "--path", str(initialized_repo)])
    result = runner.invoke(app, ["index", "--path", str(initialized_repo)])
    assert "1 unchanged" in result.output


def test_index_reports_deleted(initialized_repo, runner):
    f = initialized_repo / "gone.txt"
    f.write_text("temporary")
    runner.invoke(app, ["index", "--path", str(initialized_repo)])
    f.unlink()
    result = runner.invoke(app, ["index", "--path", str(initialized_repo)])
    assert "1 removed" in result.output


def test_reindex_removes_deleted_documents(initialized_repo, runner):
    f = initialized_repo / "keep.txt"
    f.write_text("alpha beta")

    runner.invoke(app, ["index", "--path", str(initialized_repo)])
    f.unlink()
    runner.invoke(app, ["index", "--path", str(initialized_repo)])
    result = runner.invoke(app, ["search", "alpha", "--path", str(initialized_repo)])

    assert result.exit_code == 0
    assert "No hits" in result.output


def test_index_requires_init(tmp_path, runner):
    result = runner.invoke(app, ["index", "--path", str(tmp_path)])
    assert result.exit_code == 1
    assert "Run 'openbrain init' first" in result.output


# --- search ---


def test_search_command_name(runner):
    result = runner.invoke(app, ["--help"])
    assert "search" in result.output
    assert "search-cmd" not in result.output


def test_search_finds_document(initialized_repo, runner):
    (initialized_repo / "dummy.txt").write_text("hello openbrain world")
    runner.invoke(app, ["index", "--path", str(initialized_repo)])
    result = runner.invoke(app, ["search", "openbrain", "--path", str(initialized_repo)])
    assert result.exit_code == 0
    assert "dummy.txt" in result.output


def test_search_no_results(initialized_repo, runner):
    result = runner.invoke(app, ["search", "nonexistent", "--path", str(initialized_repo)])
    assert result.exit_code == 0
    assert "No hits" in result.output


def test_search_handles_free_text_punctuation(initialized_repo, runner):
    (initialized_repo / "notes.txt").write_text("foo bar baz")
    runner.invoke(app, ["index", "--path", str(initialized_repo)])
    result = runner.invoke(app, ["search", "foo-bar", "--path", str(initialized_repo)])
    assert result.exit_code == 0
    assert "notes.txt" in result.output


def test_search_requires_init(tmp_path, runner):
    result = runner.invoke(app, ["search", "anything", "--path", str(tmp_path)])
    assert result.exit_code == 1
    assert "Run 'openbrain init' first" in result.output


# --- output formats ---


def test_search_json_format(initialized_repo, runner):
    (initialized_repo / "doc.txt").write_text("json format test content")
    runner.invoke(app, ["index", "--path", str(initialized_repo)])
    result = runner.invoke(app, ["search", "json", "--path", str(initialized_repo), "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert isinstance(data, list)
    assert data[0]["path"] == "doc.txt"


def test_search_plain_format(initialized_repo, runner):
    (initialized_repo / "doc.txt").write_text("plain format test content")
    runner.invoke(app, ["index", "--path", str(initialized_repo)])
    result = runner.invoke(app, ["search", "plain", "--path", str(initialized_repo), "--format", "plain"])
    assert result.exit_code == 0
    assert "doc.txt:" in result.output


# --- stats ---


def test_stats_shows_count(initialized_repo, runner):
    (initialized_repo / "a.txt").write_text("one")
    (initialized_repo / "b.txt").write_text("two")
    runner.invoke(app, ["index", "--path", str(initialized_repo)])
    result = runner.invoke(app, ["stats", "--path", str(initialized_repo)])
    assert result.exit_code == 0
    assert "Documents: 2" in result.output
    assert "Database size:" in result.output


def test_stats_requires_init(tmp_path, runner):
    result = runner.invoke(app, ["stats", "--path", str(tmp_path)])
    assert result.exit_code == 1


# --- remember / forget / recall ---


def test_remember_and_recall(initialized_repo, runner):
    result = runner.invoke(app, ["remember", "deploy", "run migrations first", "--path", str(initialized_repo)])
    assert result.exit_code == 0
    assert "Remembered 'deploy'" in result.output

    result = runner.invoke(app, ["recall", "", "--path", str(initialized_repo)])
    assert result.exit_code == 0
    assert "deploy" in result.output
    assert "migrations" in result.output


def test_recall_json_format(initialized_repo, runner):
    runner.invoke(app, ["remember", "tip", "use pytest -v", "--path", str(initialized_repo)])
    result = runner.invoke(app, ["recall", "", "--path", str(initialized_repo), "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data[0]["path"] == "note:tip"


def test_forget_removes_note(initialized_repo, runner):
    runner.invoke(app, ["remember", "temp", "temporary", "--path", str(initialized_repo)])
    result = runner.invoke(app, ["forget", "temp", "--path", str(initialized_repo)])
    assert result.exit_code == 0
    assert "Forgot 'temp'" in result.output

    result = runner.invoke(app, ["recall", "", "--path", str(initialized_repo)])
    assert "No notes found" in result.output


def test_forget_missing_key(initialized_repo, runner):
    result = runner.invoke(app, ["forget", "nonexistent", "--path", str(initialized_repo)])
    assert result.exit_code == 1


# --- learn / recall-learnings / forget-learning ---


def test_learn_and_recall(initialized_repo, runner):
    result = runner.invoke(app, ["learn", "sqlite-wal", "WAL enables concurrent reads", "--path", str(initialized_repo)])
    assert result.exit_code == 0
    assert "Learned" in result.output

    result = runner.invoke(app, ["recall-learnings", "", "--path", str(initialized_repo)])
    assert result.exit_code == 0
    assert "sqlite-wal" in result.output


def test_forget_learning(initialized_repo, runner):
    runner.invoke(app, ["learn", "temp", "temporary", "--path", str(initialized_repo)])
    result = runner.invoke(app, ["forget-learning", "temp", "--path", str(initialized_repo)])
    assert result.exit_code == 0
    assert "Forgot learning" in result.output


# --- task ---


def test_task_add_and_list(initialized_repo, runner):
    result = runner.invoke(app, ["task", "add", "write-tests", "Write unit tests", "--path", str(initialized_repo)])
    assert result.exit_code == 0
    assert "Added task" in result.output

    result = runner.invoke(app, ["task", "list", "--path", str(initialized_repo)])
    assert result.exit_code == 0
    assert "write-tests" in result.output
    assert "pending" in result.output


def test_task_with_group(initialized_repo, runner):
    runner.invoke(app, ["task", "add", "t1", "task one", "--group", "v0.2", "--path", str(initialized_repo)])
    runner.invoke(app, ["task", "add", "t2", "task two", "--group", "v0.3", "--path", str(initialized_repo)])
    result = runner.invoke(app, ["task", "list", "--group", "v0.2", "--path", str(initialized_repo)])
    assert "t1" in result.output
    assert "t2" not in result.output


def test_task_update_status(initialized_repo, runner):
    runner.invoke(app, ["task", "add", "t1", "task one", "--path", str(initialized_repo)])
    result = runner.invoke(app, ["task", "update", "t1", "--status", "done", "--path", str(initialized_repo)])
    assert result.exit_code == 0

    result = runner.invoke(app, ["task", "list", "--status", "done", "--path", str(initialized_repo)])
    assert "t1" in result.output


def test_task_remove(initialized_repo, runner):
    runner.invoke(app, ["task", "add", "t1", "task one", "--path", str(initialized_repo)])
    result = runner.invoke(app, ["task", "remove", "t1", "--path", str(initialized_repo)])
    assert result.exit_code == 0
    assert "Removed" in result.output


# --- plan ---


def test_plan_create_and_get(initialized_repo, runner):
    result = runner.invoke(app, ["plan", "create", "auth", "## Steps\n1. Add OAuth", "--path", str(initialized_repo)])
    assert result.exit_code == 0
    assert "Created plan" in result.output

    result = runner.invoke(app, ["plan", "get", "auth", "--path", str(initialized_repo)])
    assert result.exit_code == 0
    assert "Steps" in result.output


def test_plan_list_and_archive(initialized_repo, runner):
    runner.invoke(app, ["plan", "create", "p1", "plan one", "--path", str(initialized_repo)])
    runner.invoke(app, ["plan", "create", "p2", "plan two", "--path", str(initialized_repo)])

    result = runner.invoke(app, ["plan", "archive", "p1", "--path", str(initialized_repo)])
    assert result.exit_code == 0
    assert "Archived" in result.output

    result = runner.invoke(app, ["plan", "list", "--path", str(initialized_repo)])
    assert "p2" in result.output
    assert "p1" not in result.output


def test_plan_get_json(initialized_repo, runner):
    runner.invoke(app, ["plan", "create", "p1", "plan content", "--path", str(initialized_repo)])
    result = runner.invoke(app, ["plan", "get", "p1", "--format", "json", "--path", str(initialized_repo)])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["status"] == "active"
