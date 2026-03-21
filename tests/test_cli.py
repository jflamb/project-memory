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
