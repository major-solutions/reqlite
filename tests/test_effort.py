"""
Tests for effort scoring scale (ADR-015).
Covers Fibonacci validation in the parser, effort distribution analysis,
and the CLI effort subcommand.
"""

import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reqlite.items import parse_item_content, ParseError, _FIBONACCI_EFFORT
from reqlite import analyses
from reqlite.cli import app

runner = CliRunner()

from reqlite.items import parse_all
from reqlite.graph import build_graph
RULESET = json.loads((Path(__file__).parent.parent / "src" / "reqlite" / "rulesets" / "reqlite" / "ruleset.json").read_text())

_REPO_RULESET = Path(__file__).resolve().parent.parent / "src" / "reqlite" / "rulesets" / "reqlite" / "ruleset.json"


def _with_ruleset(parent):
    """Pair a graph dir with the project ruleset for declared-analysis commands."""
    rdir = parent / "ruleset"
    rdir.mkdir(exist_ok=True)
    shutil.copy(_REPO_RULESET, rdir / "ruleset.json")
    gdir = parent / "graph"
    gdir.mkdir(exist_ok=True)
    return gdir


def _item_content(item_id="SC-001", effort=None, status="active", title="Component"):
    """Build minimal valid item content with optional effort."""
    effort_line = f"effort: {effort}" if effort is not None else ""
    return f"""\
---
id: {item_id}
title: {title}
certainty: verified
negotiability: constrained
status: {status}
evidence: null
{effort_line}
---

Body text.
"""


def _write_item(path, item_id, body="Body.", effort=None, status="active", title=None):
    """Write a minimal valid item file."""
    title = title or item_id
    effort_line = f"effort: {effort}" if effort is not None else ""
    path.write_text(f"""\
---
id: {item_id}
title: {title}
certainty: assumed
negotiability: constrained
status: {status}
evidence: null
{effort_line}
---

{body}
""")


# =========================================================================
# Fibonacci set generation
# =========================================================================

def test_fibonacci_set_contains_expected_values():
    for n in [1, 2, 3, 5, 8, 13, 21, 34, 55, 89]:
        assert n in _FIBONACCI_EFFORT


def test_fibonacci_set_excludes_non_fibonacci():
    for n in [4, 6, 7, 9, 10, 11, 12, 14, 15]:
        assert n not in _FIBONACCI_EFFORT


# =========================================================================
# Parser: Fibonacci effort validation
# =========================================================================

def test_effort_fibonacci_1():
    item = parse_item_content(_item_content(effort=1))
    assert item.effort == 1


def test_effort_fibonacci_2():
    item = parse_item_content(_item_content(effort=2))
    assert item.effort == 2


def test_effort_fibonacci_3():
    item = parse_item_content(_item_content(effort=3))
    assert item.effort == 3


def test_effort_fibonacci_5():
    item = parse_item_content(_item_content(effort=5))
    assert item.effort == 5


def test_effort_fibonacci_8():
    item = parse_item_content(_item_content(effort=8))
    assert item.effort == 8


def test_effort_fibonacci_13():
    item = parse_item_content(_item_content(effort=13))
    assert item.effort == 13


def test_effort_fibonacci_21():
    item = parse_item_content(_item_content(effort=21))
    assert item.effort == 21


def test_effort_none_is_valid():
    item = parse_item_content(_item_content())
    assert item.effort is None


def test_effort_non_fibonacci_4_rejected():
    with pytest.raises(ParseError, match="Fibonacci"):
        parse_item_content(_item_content(effort=4))


def test_effort_non_fibonacci_6_rejected():
    with pytest.raises(ParseError, match="Fibonacci"):
        parse_item_content(_item_content(effort=6))


def test_effort_non_fibonacci_7_rejected():
    with pytest.raises(ParseError, match="Fibonacci"):
        parse_item_content(_item_content(effort=7))


def test_effort_non_fibonacci_10_rejected():
    with pytest.raises(ParseError, match="Fibonacci"):
        parse_item_content(_item_content(effort=10))


def test_effort_zero_rejected():
    with pytest.raises(ParseError, match="Fibonacci"):
        parse_item_content(_item_content(effort=0))


def test_effort_negative_rejected():
    with pytest.raises(ParseError, match="Fibonacci"):
        parse_item_content(_item_content(effort=-1))


# =========================================================================
# Effort distribution analysis (declared: SC self-value-effort, combine eff > 8)
# =========================================================================

def test_effort_distribution_threshold(tmp_path):
    """Result is the declared combine (eff > 8): 8 does not exceed, 13 does."""
    _write_item(tmp_path / "SC-001-a.md", "SC-001", effort=8, title="At threshold")
    _write_item(tmp_path / "SC-002-b.md", "SC-002", effort=13, title="Above threshold")
    items = parse_all(tmp_path)
    G, _ = build_graph(items)
    rows = {r["id"]: r for r in analyses.run_declared_analysis(G, RULESET, "effort_distribution")}
    assert rows["SC-001"]["result"] is False
    assert rows["SC-002"]["result"] is True


def test_effort_distribution_scopes_to_sc(tmp_path):
    _write_item(tmp_path / "SC-001-a.md", "SC-001", effort=5, title="Component")
    _write_item(tmp_path / "SRC-001-b.md", "SRC-001", title="Source")
    _write_item(tmp_path / "FR-001-c.md", "FR-001", title="Requirement")
    items = parse_all(tmp_path)
    G, _ = build_graph(items)
    rows = analyses.run_declared_analysis(G, RULESET, "effort_distribution")
    assert {r["id"] for r in rows} == {"SC-001"}


def test_effort_distribution_unscored_is_none(tmp_path):
    """An SC with no effort field has eff None and a non-True (None) result."""
    _write_item(tmp_path / "SC-001-a.md", "SC-001", title="Unscored")
    items = parse_all(tmp_path)
    G, _ = build_graph(items)
    rows = {r["id"]: r for r in analyses.run_declared_analysis(G, RULESET, "effort_distribution")}
    assert rows["SC-001"]["env"]["eff"] is None
    assert rows["SC-001"]["result"] is not True


def test_effort_distribution_empty(tmp_path):
    """No SC items -> empty result."""
    _write_item(tmp_path / "SRC-001-x.md", "SRC-001", title="Source")
    items = parse_all(tmp_path)
    G, _ = build_graph(items)
    rows = analyses.run_declared_analysis(G, RULESET, "effort_distribution")
    assert rows == []


# =========================================================================
# CLI: effort subcommand
# =========================================================================

def test_effort_cli_output(tmp_path):
    gdir = _with_ruleset(tmp_path)
    _write_item(gdir / "SC-001-a.md", "SC-001", effort=1, title="Small")
    _write_item(gdir / "SC-002-b.md", "SC-002", effort=8, title="Large")

    result = runner.invoke(app, ["effort", str(gdir)])
    assert result.exit_code == 0
    assert "2 scored" in result.output
    assert "SC-002" in result.output
    assert "SC-001" in result.output


def test_effort_cli_warns_above_declared_threshold(tmp_path):
    # threshold is declared in the ruleset (eff > 8), no longer a CLI flag
    gdir = _with_ruleset(tmp_path)
    _write_item(gdir / "SC-001-a.md", "SC-001", effort=13, title="Big")

    result = runner.invoke(app, ["effort", str(gdir)])
    assert result.exit_code == 0
    assert "⚠" in result.output
    assert "consider decomposition" in result.output


def test_effort_cli_no_warning_below_threshold(tmp_path):
    gdir = _with_ruleset(tmp_path)
    _write_item(gdir / "SC-001-a.md", "SC-001", effort=3, title="Small")

    result = runner.invoke(app, ["effort", str(gdir)])
    assert result.exit_code == 0
    assert "⚠" not in result.output


def test_effort_cli_unscored_shown(tmp_path):
    gdir = _with_ruleset(tmp_path)
    _write_item(gdir / "SC-001-a.md", "SC-001", title="Unscored")

    result = runner.invoke(app, ["effort", str(gdir)])
    assert result.exit_code == 0
    assert "unscored" in result.output


def test_effort_cli_empty(tmp_path):
    gdir = _with_ruleset(tmp_path)
    _write_item(gdir / "SRC-001-a.md", "SRC-001", title="Not an SC")

    result = runner.invoke(app, ["effort", str(gdir)])
    assert result.exit_code == 0
    assert "No SC items found" in result.output


# =========================================================================
# Report: effort distribution section
# =========================================================================

def test_report_contains_effort_section(tmp_path):
    gdir = _with_ruleset(tmp_path)
    _write_item(gdir / "SC-001-a.md", "SC-001", effort=5, title="Component")
    _write_item(gdir / "SRC-001-b.md", "SRC-001",
                "See [SC-001](SC-001-a.md).", title="Source")

    result = runner.invoke(app, ["report", str(gdir)])
    assert result.exit_code == 0
    # declared analysis rendered generically by name
    assert "effort_distribution" in result.output


def test_report_effort_section_shows_result(tmp_path):
    gdir = _with_ruleset(tmp_path)
    _write_item(gdir / "SC-001-a.md", "SC-001", effort=13, title="Big one")

    result = runner.invoke(app, ["report", str(gdir)])
    assert result.exit_code == 0
    assert "effort_distribution" in result.output
    # effort 13 > declared threshold (8): combine result is True, detail shows eff
    assert "True" in result.output
    assert "eff=13" in result.output
