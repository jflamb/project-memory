import pytest

from project_memory.db import ProjectMemoryDB
from project_memory.protocols import generate_default_protocols, inspect_repo


@pytest.fixture
def db(tmp_path):
    with ProjectMemoryDB(root=tmp_path) as db:
        yield db


# --- repo inspection ---


def test_inspect_repo_detects_git(tmp_path):
    (tmp_path / ".git").mkdir()
    info = inspect_repo(tmp_path)
    assert info["has_git"] is True


def test_inspect_repo_no_git(tmp_path):
    info = inspect_repo(tmp_path)
    assert info["has_git"] is False


def test_inspect_repo_detects_default_branch(tmp_path):
    """If .git/HEAD points to main, detect it."""
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
    info = inspect_repo(tmp_path)
    assert info["default_branch"] == "main"


def test_inspect_repo_detects_ci(tmp_path):
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("name: CI")
    info = inspect_repo(tmp_path)
    assert info["has_ci"] is True


def test_inspect_repo_no_ci(tmp_path):
    info = inspect_repo(tmp_path)
    assert info["has_ci"] is False


def test_inspect_repo_detects_python(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]")
    info = inspect_repo(tmp_path)
    assert "python" in info["languages"]


def test_inspect_repo_detects_node(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    info = inspect_repo(tmp_path)
    assert "node" in info["languages"]


def test_inspect_repo_detects_rust(tmp_path):
    (tmp_path / "Cargo.toml").write_text("[package]")
    info = inspect_repo(tmp_path)
    assert "rust" in info["languages"]


def test_inspect_repo_detects_go(tmp_path):
    (tmp_path / "go.mod").write_text("module example")
    info = inspect_repo(tmp_path)
    assert "go" in info["languages"]


# --- protocol generation ---


def test_generate_default_protocols_creates_plans(db, tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    generate_default_protocols(db, tmp_path)
    plans = db.plan_list(type="protocol", status=None)
    assert len(plans) >= 1


def test_generated_protocols_have_type_protocol(db, tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    generate_default_protocols(db, tmp_path)
    plans = db.plan_list(type="protocol", status=None)
    for p in plans:
        assert p["type"] == "protocol"


def test_generated_protocols_include_blast_radius(db, tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    generate_default_protocols(db, tmp_path)
    plan = db.plan_get("blast-radius")
    assert plan is not None
    assert "trivial" in plan["content"].lower()
    assert "scoped" in plan["content"].lower()
    assert "cross-cutting" in plan["content"].lower()
    assert "breaking" in plan["content"].lower()


def test_generated_protocols_include_branching(db, tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    generate_default_protocols(db, tmp_path)
    plan = db.plan_get("branching")
    assert plan is not None
    assert "main" in plan["content"]


def test_generated_protocols_with_ci(db, tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    (tmp_path / ".github" / "workflows").mkdir(parents=True)
    (tmp_path / ".github" / "workflows" / "ci.yml").write_text("name: CI")
    generate_default_protocols(db, tmp_path)
    plan = db.plan_get("blast-radius")
    assert "CI" in plan["content"]


def test_generate_protocols_idempotent(db, tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    generate_default_protocols(db, tmp_path)
    count1 = len(db.plan_list(type="protocol", status=None))
    generate_default_protocols(db, tmp_path)
    count2 = len(db.plan_list(type="protocol", status=None))
    assert count1 == count2


def test_generate_protocols_no_git(db, tmp_path):
    """Should still generate protocols even without git, just with defaults."""
    generate_default_protocols(db, tmp_path)
    plans = db.plan_list(type="protocol", status=None)
    assert len(plans) >= 1
