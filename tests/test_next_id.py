"""Tests for `reqlite next-id`. One test per oracle in ORACLES-NEXTID.md."""

import subprocess

import pytest
from typer.testing import CliRunner

from reqlite.cli import app

runner = CliRunner()


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _item(graph, name):
    (graph / name).write_text(f"# {name[:7]}: x\n\nBody.\n", encoding="utf-8")


def _commit(root, msg):
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", msg)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    graph = root / "graph"
    graph.mkdir(parents=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")
    _item(graph, "SRC-001-a.md")
    _item(graph, "SRC-002-b.md")
    _commit(root, "init")
    return root


def _next(graph, prefix):
    return runner.invoke(app, ["next-id", prefix, str(graph)])


def _retire_three(repo):
    graph = repo / "graph"
    _item(graph, "SRC-003-c.md")
    _commit(repo, "add 3")
    (graph / "SRC-003-c.md").unlink()
    _commit(repo, "retire 3")


def test_oracle_1_follows_the_highest_live_number(repo):
    r = _next(repo / "graph", "SRC")
    assert r.exit_code == 0, r.output
    assert r.stdout.strip() == "SRC-003"


def test_oracle_2_a_retired_number_is_never_reused(repo):
    _retire_three(repo)
    assert _next(repo / "graph", "SRC").stdout.strip() == "SRC-004"


def test_oracle_3_retired_on_another_branch_counts(repo):
    graph = repo / "graph"
    _git(repo, "checkout", "-q", "-b", "side")
    _item(graph, "SRC-005-e.md")
    _commit(repo, "add 5")
    (graph / "SRC-005-e.md").unlink()
    _commit(repo, "retire 5")
    _git(repo, "checkout", "-q", "main")
    assert _next(graph, "SRC").stdout.strip() == "SRC-006"


def test_oracle_4_numbering_is_per_prefix(repo):
    graph = repo / "graph"
    _item(graph, "UC-007-g.md")
    _commit(repo, "uc")
    assert _next(graph, "UC").stdout.strip() == "UC-008"
    assert _next(graph, "SRC").stdout.strip() == "SRC-003"


def test_oracle_5_shallow_clone_is_refused(repo, tmp_path):
    _retire_three(repo)
    clone = tmp_path / "shallow"
    subprocess.run(["git", "clone", "-q", "--depth", "1", repo.as_uri(), str(clone)],
                   check=True, capture_output=True)
    r = _next(clone / "graph", "SRC")
    assert r.exit_code != 0
    assert "unshallow" in r.output
    assert "SRC-0" not in r.stdout


def test_oracle_6_graph_outside_git_is_refused(tmp_path):
    graph = tmp_path / "graph"
    graph.mkdir()
    _item(graph, "SRC-001-a.md")
    r = _next(graph, "SRC")
    assert r.exit_code != 0
    assert "git" in r.output.lower()
    assert "SRC-0" not in r.stdout


def test_oracle_7_width_is_three_digits(repo):
    assert _next(repo / "graph", "DD").stdout.strip() == "DD-001"
