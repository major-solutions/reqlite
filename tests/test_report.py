"""
Tests for the report command.
"""

import shutil
from pathlib import Path

from typer.testing import CliRunner
from reqlite.cli import app

runner = CliRunner()

_REPO_RULESET = Path(__file__).resolve().parent.parent / "src" / "reqlite" / "rulesets" / "reqlite" / "ruleset.json"


def _with_ruleset(parent):
    """Pair a graph dir with the project ruleset so declared analyses run."""
    rdir = parent / "ruleset"
    rdir.mkdir(exist_ok=True)
    shutil.copy(_REPO_RULESET, rdir / "ruleset.json")
    gdir = parent / "graph"
    gdir.mkdir(exist_ok=True)
    return gdir


def _write_item(path, item_id, body="Body.", status="active", effort=None):
    """Write a minimal valid item file."""
    effort_line = f"effort: {effort}" if effort is not None else ""
    path.write_text(f"""\
---
id: {item_id}
title: {item_id}
certainty: assumed
negotiability: constrained
status: {status}
evidence: null
{effort_line}
---

{body}
""")


def test_report_contains_all_sections(tmp_path):
    gdir = _with_ruleset(tmp_path)
    _write_item(gdir / "SRC-001-a.md", "SRC-001",
                "See [SRC-002](SRC-002-b.md).")
    _write_item(gdir / "SRC-002-b.md", "SRC-002", "Leaf.")
    _write_item(gdir / "FR-001-req.md", "FR-001",
                "Refs [SRC-001](SRC-001-a.md).")
    _write_item(gdir / "SC-001-comp.md", "SC-001",
                "Covers [FR-001](FR-001-req.md).", effort=3)

    result = runner.invoke(app, ["report", str(gdir)])
    assert result.exit_code == 0
    out = result.output.lower()
    # engine-owned structural sections
    assert "integrity" in out
    assert "topology" in out
    # declared analyses, rendered generically by section name + severity
    assert "coverage" in out
    assert "assumption_risk" in out
    assert "justification" in out
    assert "severity" in out


def test_report_topology_says_what_source_and_leaf_mean(tmp_path):
    """'Sources' beside a type called SRC read as the SRC items, which are usually leaves
    (glossary: "source" has three meanings; say which one). Issue #94."""
    gdir = _with_ruleset(tmp_path)
    _write_item(gdir / "SRC-001-a.md", "SRC-001", "Leaf.")
    _write_item(gdir / "FR-001-req.md", "FR-001", "Refs [SRC-001](SRC-001-a.md).")
    out = runner.invoke(app, ["report", str(gdir)]).output
    assert "Sources (1, nothing depends on them): FR-001" in out
    assert "Leaves (1, they depend on nothing): SRC-001" in out


def test_report_contains_markdown_links(tmp_path):
    _write_item(tmp_path / "SRC-001-a.md", "SRC-001", "Body.")

    result = runner.invoke(app, [
        "report", str(tmp_path),
        "--repo-url", "https://github.com/example-org/reqlite/blob/main/graph",
    ])
    assert result.exit_code == 0
    assert "[SRC-001](" in result.output
    assert "example-org/reqlite" in result.output


def test_report_without_repo_url_uses_plain_ids(tmp_path):
    _write_item(tmp_path / "SRC-001-a.md", "SRC-001", "Body.")

    result = runner.invoke(app, ["report", str(tmp_path)])
    assert result.exit_code == 0
    assert "SRC-001" in result.output


def test_report_empty_dir(tmp_path):
    result = runner.invoke(app, ["report", str(tmp_path)])
    assert result.exit_code == 0


def _item(gdir, name, certainty=None, body="Body."):
    item_id = "-".join(name.split("-")[:2])
    fm = f"---\ncertainty: {certainty}\n---\n\n" if certainty else ""
    (gdir / name).write_text(f"{fm}# {item_id}: T\n\n{body}\n", encoding="utf-8")


def _section(out, heading):
    """The text of one `## heading` section of the report."""
    start = out.index(f"## {heading}")
    nxt = out.find("\n## ", start + 1)
    return out[start:nxt if nxt != -1 else None]


def test_show_flagged_lists_only_flagged_rows_with_a_count(tmp_path):
    """A declared `"show": "flagged"` renders only rows whose result is truthy (#92)."""
    import json

    gdir = _with_ruleset(tmp_path)
    rs_path = tmp_path / "ruleset" / "ruleset.json"
    rs = json.loads(rs_path.read_text(encoding="utf-8"))
    rs["analyses"]["coverage"]["show"] = "flagged"
    rs["analyses"]["coverage"]["query"]["combine"] = "cov == 0"
    rs_path.write_text(json.dumps(rs), encoding="utf-8")
    _item(gdir, "SRC-001-a.md")
    _item(gdir, "FR-001-covered.md", body="[SRC-001](SRC-001-a.md)")
    _item(gdir, "FR-002-open.md", body="[SRC-001](SRC-001-a.md)")
    _item(gdir, "SC-001-c.md", body="[FR-001](FR-001-covered.md)")
    section = _section(runner.invoke(app, ["report", str(gdir)]).output, "coverage")
    assert "FR-002" in section and "FR-001" not in section
    assert "1 of 2" in section


def test_shipped_ruleset_flags_an_assumption_nothing_rests_on(tmp_path):
    """#92: an unconfirmed fact recorded as `assumed` with nothing depending on it scored 0
    in assumption_risk, so a verified source topped the risk list instead."""
    gdir = _with_ruleset(tmp_path)
    _item(gdir, "SRC-001-alone.md", certainty="assumed")
    _item(gdir, "SRC-002-guess.md", certainty="speculative")
    _item(gdir, "SRC-003-fact.md", certainty="verified")
    _item(gdir, "SRC-004-used.md", certainty="assumed")
    _item(gdir, "FR-001-x.md", body="[SRC-004](SRC-004-used.md) [SRC-003](SRC-003-fact.md)")
    section = _section(runner.invoke(app, ["report", str(gdir)]).output,
                       "unsupported_assumption")
    assert "SRC-001" in section and "SRC-002" in section
    assert "SRC-003" not in section and "SRC-004" not in section
    assert "severity: warn" in section

def test_report_lists_items_with_hidden_comments(tmp_path):
    """#88: hidden text is reported where an agent reads the graph's state."""
    _write_item(tmp_path / "SRC-001-a.md", "SRC-001", "Body.\n\n<!-- do X quietly -->")
    _write_item(tmp_path / "SRC-002-b.md", "SRC-002", "Body.")
    out = runner.invoke(app, ["report", str(tmp_path)]).output
    section = out[out.index("## Hidden text"):]
    assert "SRC-001" in section and "SRC-002" not in section.split("\n## ")[0]


def test_report_has_no_hidden_text_section_when_there_is_none(tmp_path):
    _write_item(tmp_path / "SRC-001-a.md", "SRC-001", "Body.")
    assert "Hidden text" not in runner.invoke(app, ["report", str(tmp_path)]).output


def test_report_integrity_gate_omits_analyses(tmp_path):
    gdir = _with_ruleset(tmp_path)
    # dangling reference -> unknown_reference (tier-1 integrity finding)
    _write_item(gdir / "SC-001-a.md", "SC-001",
                "Refs [SRC-999](SRC-999-x.md).")

    result = runner.invoke(app, ["report", str(gdir)])
    assert result.exit_code == 0
    assert "unknown_reference" in result.output
    # gated: descriptive structure and declared analyses are omitted
    assert "Topology" not in result.output
    assert "severity" not in result.output
