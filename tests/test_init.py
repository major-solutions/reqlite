"""Tests for `reqlite init` and the ruleset library. One test per oracle in ORACLES-INIT.md."""

import fnmatch
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reqlite.cli import app
from reqlite.ruleset_check import lint_ruleset

REPO = Path(__file__).parent.parent
LIBRARY = REPO / "src" / "reqlite" / "rulesets"

runner = CliRunner()


def _files(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in sorted(root.rglob("*")) if p.is_file()}


def _ruleset_dir(root: Path, quality_prompt="prompts/src_quality.md", with_prompt=True,
                 marker="CUSTOM"):
    (root / "prompts").mkdir(parents=True)
    if with_prompt:
        (root / "prompts" / "src_quality.md").write_text(f"{marker} quality", encoding="utf-8")
    (root / "prompts" / "consistency.md").write_text(f"{marker} consistency", encoding="utf-8")
    (root / "ruleset.json").write_text(json.dumps({
        "types": {"SRC": {"label": "Source", "description": f"{marker} sources.",
                          "quality_prompt": quality_prompt}},
        "prompts": {"consistency": "prompts/consistency.md"},
    }), encoding="utf-8")
    return root


def _invoke(*args):
    return runner.invoke(app, ["init", *args])


# --- The library ------------------------------------------------------------------------

# Oracle 1 compares against this repository's own ruleset, which is not published:
# tests/private/test_dogfood.py.

def test_oracle_2_every_packaged_ruleset_supports_every_check(tmp_path):
    entries = [d for d in LIBRARY.iterdir() if d.is_dir() and not d.name.startswith("_")]
    assert entries
    for entry in entries:
        rs = json.loads((entry / "ruleset.json").read_text(encoding="utf-8"))
        assert rs.get("prompts", {}).get("consistency"), entry.name
        project = tmp_path / entry.name
        project.mkdir()
        assert _invoke(str(project), "--ruleset", entry.name).exit_code == 0
        assert lint_ruleset(str(project / "graph")) == [], entry.name


def test_oracle_3_library_ships_in_the_package():
    import tomllib

    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = data["tool"]["setuptools"]["package-data"]["reqlite"]
    pkg = REPO / "src" / "reqlite"
    for f in LIBRARY.rglob("*"):
        if f.is_file() and "__pycache__" not in f.parts:
            rel = f.relative_to(pkg).as_posix()
            # setuptools globs do not cross directories with '*'; check segment-wise
            assert any(len(p.split("/")) == len(rel.split("/")) and fnmatch.fnmatch(rel, p)
                       for p in patterns), rel


def test_oracle_4_orientation_carries_nothing_repository_specific():
    text = (LIBRARY / "reqlite" / "readme.md").read_text(encoding="utf-8").lower()
    assert "describing itself" not in text
    assert "dogfood" not in text


# --- The command ------------------------------------------------------------------------

def test_oracle_5_bare_init_scaffolds_graph_and_default_ruleset(tmp_path):
    r = _invoke(str(tmp_path))
    assert r.exit_code == 0, r.output
    assert (tmp_path / "graph").is_dir() and not any((tmp_path / "graph").iterdir())
    assert _files(tmp_path / "ruleset") == _files(LIBRARY / "reqlite")
    assert lint_ruleset(str(tmp_path / "graph")) == []
    doctor = runner.invoke(app, ["doctor", str(tmp_path / "graph")])
    assert doctor.exit_code == 0, doctor.output


def test_oracle_6_output_names_source_risk_and_next_step(tmp_path):
    out = _invoke(str(tmp_path)).stdout
    assert "reqlite" in out
    assert "own risk" in out
    assert "doctor" in out
    from reqlite.scaffold import library_root
    assert str(library_root()) not in out


def test_oracle_6_a_ruleset_directory_is_named_by_its_path(tmp_path):
    src = _ruleset_dir(tmp_path / "mine")
    project = tmp_path / "p"
    project.mkdir()
    out = _invoke(str(project), "--ruleset", str(src)).stdout
    assert str(src) in out


def test_oracle_7_named_library_entry_is_selected(tmp_path, monkeypatch):
    import reqlite.scaffold as S

    lib = tmp_path / "lib"
    _ruleset_dir(lib / "other", marker="OTHER")
    monkeypatch.setattr(S, "library_root", lambda: lib)
    project = tmp_path / "p"
    project.mkdir()
    r = _invoke(str(project), "--ruleset", "other")
    assert r.exit_code == 0, r.output
    assert _files(project / "ruleset") == _files(lib / "other")


def test_oracle_8_unknown_name_refused_and_library_listed(tmp_path):
    r = _invoke(str(tmp_path), "--ruleset", "nosuch")
    assert r.exit_code == 1
    assert "reqlite" in r.stderr
    assert list(tmp_path.iterdir()) == []


def test_oracle_9_ruleset_path_is_copied(tmp_path):
    src = _ruleset_dir(tmp_path / "mine")
    project = tmp_path / "p"
    project.mkdir()
    r = _invoke(str(project), "--ruleset", str(src))
    assert r.exit_code == 0, r.output
    assert _files(project / "ruleset") == _files(src)


def test_oracle_10_path_without_ruleset_json_is_refused(tmp_path):
    (tmp_path / "notaruleset").mkdir()
    project = tmp_path / "p"
    project.mkdir()
    r = _invoke(str(project), "--ruleset", str(tmp_path / "notaruleset"))
    assert r.exit_code == 1
    assert list(project.iterdir()) == []


def test_oracle_11_copied_ruleset_with_findings_is_reported(tmp_path):
    src = _ruleset_dir(tmp_path / "mine", with_prompt=False)
    project = tmp_path / "p"
    project.mkdir()
    r = _invoke(str(project), "--ruleset", str(src))
    assert r.exit_code == 4, r.output
    assert "missing_prompt_file" in r.output
    assert (project / "ruleset" / "ruleset.json").is_file()


def test_oracle_12_existing_ruleset_is_never_overwritten(tmp_path):
    (tmp_path / "ruleset").mkdir()
    (tmp_path / "ruleset" / "ruleset.json").write_text("MINE", encoding="utf-8")
    r = _invoke(str(tmp_path))
    assert r.exit_code == 1
    assert (tmp_path / "ruleset" / "ruleset.json").read_text(encoding="utf-8") == "MINE"
    assert not (tmp_path / "graph").exists()


def test_oracle_13_existing_graph_is_kept(tmp_path):
    (tmp_path / "graph").mkdir()
    item = tmp_path / "graph" / "SRC-001-x.md"
    item.write_text("# SRC-001: X\n\nBody.\n", encoding="utf-8")
    r = _invoke(str(tmp_path))
    assert r.exit_code == 0, r.output
    assert item.read_text(encoding="utf-8") == "# SRC-001: X\n\nBody.\n"


def test_oracle_14_symlink_in_source_is_refused(tmp_path):
    import os

    src = _ruleset_dir(tmp_path / "mine")
    secret = tmp_path / "secret.md"
    secret.write_text("SECRET", encoding="utf-8")
    try:
        os.symlink(secret, src / "prompts" / "linked.md")
    except OSError:
        pytest.skip("OS will not create symlinks without privilege")
    project = tmp_path / "p"
    project.mkdir()
    r = _invoke(str(project), "--ruleset", str(src))
    assert r.exit_code == 1
    assert list(project.iterdir()) == []


def test_oracle_15_project_directory_must_exist(tmp_path):
    r = _invoke(str(tmp_path / "missing"))
    assert r.exit_code == 1
    assert "missing" in r.stderr
    assert "create it first" in r.stderr
