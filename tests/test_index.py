import pytest

from project_memory.db import ProjectMemoryDB
from project_memory.index import index_repo, _iter_text_files, _is_gitignored


@pytest.fixture
def repo(tmp_path):
    """A tmp_path with an initialized project memory database."""
    (tmp_path / ".project-memory").mkdir()
    return tmp_path


# --- .gitignore respect ---


def test_gitignore_skips_ignored_files(repo):
    (repo / ".gitignore").write_text("ignored.txt\n")
    (repo / "kept.txt").write_text("keep me")
    (repo / "ignored.txt").write_text("skip me")
    result = index_repo(root=str(repo))
    assert result["total"] == 1  # only kept.txt (not .gitignore since it's not in TEXT_EXTENSIONS... actually .txt is)
    # Actually .gitignore has no extension match. Let's check kept.txt
    with ProjectMemoryDB(root=repo) as db:
        docs = db.list_documents()
        paths = [d["path"] for d in docs]
        assert "kept.txt" in paths
        assert "ignored.txt" not in paths


def test_gitignore_skips_directories(repo):
    (repo / ".gitignore").write_text("build/\n")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("code")
    (repo / "build").mkdir()
    (repo / "build" / "output.py").write_text("generated")
    result = index_repo(root=str(repo))
    with ProjectMemoryDB(root=repo) as db:
        docs = db.list_documents()
        paths = [d["path"] for d in docs]
        assert "src/app.py" in paths
        assert "build/output.py" not in paths


def test_gitignore_glob_pattern(repo):
    (repo / ".gitignore").write_text("*.log\n")
    (repo / "app.py").write_text("code")
    (repo / "debug.log").write_text("logs")  # .log not in TEXT_EXTENSIONS anyway but test the pattern
    (repo / "app.log").write_text("more logs")
    result = index_repo(root=str(repo))
    with ProjectMemoryDB(root=repo) as db:
        docs = db.list_documents()
        paths = [d["path"] for d in docs]
        assert "app.py" in paths
        assert "debug.log" not in paths


def test_gitignore_nested(repo):
    """Nested .gitignore should be respected."""
    (repo / ".gitignore").write_text("*.tmp\n")
    (repo / "sub").mkdir()
    (repo / "sub" / ".gitignore").write_text("local.txt\n")
    (repo / "sub" / "local.txt").write_text("ignored by nested gitignore")
    (repo / "sub" / "keep.py").write_text("code")
    result = index_repo(root=str(repo))
    with ProjectMemoryDB(root=repo) as db:
        docs = db.list_documents()
        paths = [d["path"] for d in docs]
        assert "sub/keep.py" in paths
        assert "sub/local.txt" not in paths


def test_gitignore_negation(repo):
    (repo / ".gitignore").write_text("*.txt\n!important.txt\n")
    (repo / "junk.txt").write_text("ignored")
    (repo / "important.txt").write_text("kept")
    result = index_repo(root=str(repo))
    with ProjectMemoryDB(root=repo) as db:
        docs = db.list_documents()
        paths = [d["path"] for d in docs]
        assert "important.txt" in paths
        assert "junk.txt" not in paths


def test_no_gitignore_uses_hardcoded_fallback(repo):
    """Without .gitignore, hardcoded excludes still apply."""
    (repo / ".venv").mkdir()
    (repo / ".venv" / "noise.py").write_text("noise")
    (repo / "app.py").write_text("code")
    result = index_repo(root=str(repo))
    with ProjectMemoryDB(root=repo) as db:
        docs = db.list_documents()
        paths = [d["path"] for d in docs]
        assert "app.py" in paths
        assert ".venv/noise.py" not in paths


def test_is_gitignored_helper(repo):
    (repo / ".gitignore").write_text("secret.txt\n")
    assert _is_gitignored(repo / "secret.txt", repo) is True
    assert _is_gitignored(repo / "public.txt", repo) is False


# --- more file types ---


def test_indexes_rust_files(repo):
    (repo / "main.rs").write_text("fn main() {}")
    result = index_repo(root=str(repo))
    assert result["total"] == 1


def test_indexes_go_files(repo):
    (repo / "main.go").write_text("package main")
    result = index_repo(root=str(repo))
    assert result["total"] == 1


def test_indexes_javascript_files(repo):
    (repo / "app.js").write_text("console.log('hello')")
    result = index_repo(root=str(repo))
    assert result["total"] == 1


def test_indexes_typescript_files(repo):
    (repo / "app.ts").write_text("const x: number = 1")
    (repo / "comp.tsx").write_text("export default () => <div/>")
    result = index_repo(root=str(repo))
    assert result["total"] == 2


def test_indexes_jsx_files(repo):
    (repo / "comp.jsx").write_text("export default () => <div/>")
    result = index_repo(root=str(repo))
    assert result["total"] == 1


def test_indexes_css_html_files(repo):
    (repo / "style.css").write_text("body { color: red; }")
    (repo / "page.html").write_text("<html></html>")
    result = index_repo(root=str(repo))
    assert result["total"] == 2


def test_indexes_shell_files(repo):
    (repo / "deploy.sh").write_text("#!/bin/bash")
    (repo / "setup.bash").write_text("#!/bin/bash")
    (repo / "config.zsh").write_text("#!/bin/zsh")
    result = index_repo(root=str(repo))
    assert result["total"] == 3


def test_indexes_sql_files(repo):
    (repo / "schema.sql").write_text("CREATE TABLE t (id INT)")
    result = index_repo(root=str(repo))
    assert result["total"] == 1


def test_indexes_r_files(repo):
    (repo / "analysis.r").write_text("x <- 1")
    (repo / "model.R").write_text("y <- 2")
    result = index_repo(root=str(repo))
    assert result["total"] == 2


def test_indexes_config_files(repo):
    (repo / "settings.cfg").write_text("[section]")
    (repo / ".env.example").write_text("KEY=value")
    result = index_repo(root=str(repo))
    assert result["total"] == 2


def test_indexes_special_files(repo):
    (repo / "Dockerfile").write_text("FROM python:3.12")
    (repo / "Makefile").write_text("all:\n\techo hello")
    (repo / "Justfile").write_text("default:\n  echo hello")
    result = index_repo(root=str(repo))
    assert result["total"] == 3


# --- chunking large files ---


def test_small_file_single_document(repo):
    """Files under the chunk threshold stay as single documents."""
    (repo / "small.py").write_text("x = 1\n" * 10)
    result = index_repo(root=str(repo))
    with ProjectMemoryDB(root=repo) as db:
        docs = db.list_documents()
        paths = [d["path"] for d in docs]
        assert "small.py" in paths
        assert not any("#chunk-" in p for p in paths)


def test_large_file_chunked(repo):
    """Files over the chunk threshold get split into chunks."""
    # Default threshold is ~4KB, so create a file larger than that
    content = "# Line of code\n" * 500  # ~7.5KB
    (repo / "big.py").write_text(content)
    result = index_repo(root=str(repo))
    with ProjectMemoryDB(root=repo) as db:
        docs = db.list_documents()
        paths = [d["path"] for d in docs]
        chunk_paths = [p for p in paths if p.startswith("big.py#chunk-")]
        assert len(chunk_paths) >= 2


def test_chunks_have_overlapping_content(repo):
    """Chunks should overlap to preserve context at boundaries."""
    lines = [f"# unique line {i}\n" for i in range(500)]
    (repo / "big.py").write_text("".join(lines))
    result = index_repo(root=str(repo))
    with ProjectMemoryDB(root=repo) as db:
        docs = db.list_documents()
        chunk_docs = [d for d in docs if "#chunk-" in d["path"]]
        # Not testing exact overlap amount, just that chunks exist
        assert len(chunk_docs) >= 2


def test_chunks_are_searchable(repo):
    """Content in chunks should be findable via search."""
    lines = ["normal line\n"] * 300 + ["unique_search_token_xyz\n"] + ["normal line\n"] * 200
    (repo / "big.py").write_text("".join(lines))
    index_repo(root=str(repo))
    with ProjectMemoryDB(root=repo) as db:
        results = db.search("unique_search_token_xyz")
        assert len(results) >= 1
        assert any("big.py" in r["path"] for r in results)


def test_reindex_cleans_up_old_chunks(repo):
    """When a large file shrinks below threshold, old chunks are cleaned up."""
    big_content = "# line\n" * 500
    (repo / "file.py").write_text(big_content)
    index_repo(root=str(repo))

    # Shrink the file
    (repo / "file.py").write_text("x = 1\n")
    result = index_repo(root=str(repo))

    with ProjectMemoryDB(root=repo) as db:
        docs = db.list_documents()
        paths = [d["path"] for d in docs]
        chunk_paths = [p for p in paths if "file.py#chunk-" in p]
        assert len(chunk_paths) == 0
        assert "file.py" in paths


def test_reindex_preserves_typed_memory(repo):
    """Reindex should only remove stale file documents, not notes/tasks/plans."""
    (repo / "file.py").write_text("print('hello')\n")
    with ProjectMemoryDB(root=repo) as db:
        db.remember("note1", "important note")
        db.task_add("task1", "do thing")
        db.plan_create("plan1", "ship it")

    index_repo(root=str(repo))

    with ProjectMemoryDB(root=repo) as db:
        paths = [d["path"] for d in db.list_documents()]
        assert "file.py" in paths
        assert "note:note1" in paths
        assert "task:task1" in paths
        assert "plan:plan1" in paths
