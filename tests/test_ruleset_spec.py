"""
Ruleset-sourced analysis snapshots: an analysis *declared in the ruleset* as a
raw QuerySpec, loaded and run through the generic query algebra, produces the
expected results on the fixture graph.

This is the live path now that the bespoke dimension analyses are retired: the
project owns each analysis's definition (prefixes, fields, scale — all data in
ruleset.json) and the engine only runs the generic primitive. The snapshots
below were captured from the bespoke functions before they were deleted, so they
also document the behaviour those functions used to provide.
"""

import json
from pathlib import Path

from reqlite import analyses
from reqlite.query import parse_query_spec, run_query

RULESET_PATH = Path(__file__).parent.parent / "src" / "reqlite" / "rulesets" / "reqlite" / "ruleset.json"

# Snapshots on tests/fixtures/graph (captured from the original bespoke analyses).
ASSUMPTION_RISK = {
    "SRC-002": (2, 6, 12), "SRC-004": (2, 6, 12), "SRC-005": (2, 6, 12),
    "SRC-003": (1, 6, 6),
    "SRC-001": (3, 0, 0), "SRC-006": (3, 0, 0), "SRC-009": (3, 0, 0),
}
JUSTIFICATION = {"SC-001": ("verified", True), "SC-002": ("verified", True)}
EFFORT = {"SC-001": (5, False), "SC-002": (1, False)}
COVERAGE = {"FR-001": (2, True)}


def _load_ruleset() -> dict:
    return json.loads(RULESET_PATH.read_text())


def test_ruleset_declares_scales_and_queries():
    """Guard the declarations themselves: the blocks analyses depend on exist."""
    ruleset = _load_ruleset()
    assert "scales" in ruleset, "ruleset must declare a top-level scales block"
    assert "certainty" in ruleset["scales"]
    for name in ("assumption_risk", "justification", "effort_distribution", "coverage"):
        assert "query" in ruleset["analyses"][name], f"{name} must carry a QuerySpec"


def test_ruleset_assumption_risk_spec_matches_snapshot(fixture_graph):
    """The declared spec, parsed and run directly, matches the snapshot."""
    G, _ = fixture_graph
    ruleset = _load_ruleset()
    spec = parse_query_spec(ruleset["analyses"]["assumption_risk"]["query"])
    got = {
        r["id"]: (r["env"]["self_certainty"], r["env"]["eff"], r["result"])
        for r in run_query(G, spec, ruleset["scales"])
    }
    assert got == ASSUMPTION_RISK


def test_run_declared_assumption_risk_matches_snapshot(fixture_graph):
    """The runner (ruleset -> query) matches the assumption_risk snapshot."""
    G, _ = fixture_graph
    rows = analyses.run_declared_analysis(G, _load_ruleset(), "assumption_risk")
    got = {r["id"]: (r["env"]["self_certainty"], r["env"]["eff"], r["result"]) for r in rows}
    assert got == ASSUMPTION_RISK


def test_run_declared_analysis_applies_declared_sort(fixture_graph):
    """The declared 'sort: desc' ranks rows by combine result, Nones last."""
    G, _ = fixture_graph
    rows = analyses.run_declared_analysis(G, _load_ruleset(), "assumption_risk")
    scored = [r["result"] for r in rows if r["result"] is not None]
    assert scored == sorted(scored, reverse=True)
    none_idx = [i for i, r in enumerate(rows) if r["result"] is None]
    if none_idx:
        assert min(none_idx) >= len(scored)


def test_run_declared_justification_matches_snapshot(fixture_graph):
    G, _ = fixture_graph
    rows = analyses.run_declared_analysis(G, _load_ruleset(), "justification")
    got = {r["id"]: (r["labels"]["best"], r["result"] is True) for r in rows}
    assert got == JUSTIFICATION


def test_run_declared_effort_distribution_matches_snapshot(fixture_graph):
    G, _ = fixture_graph
    rows = analyses.run_declared_analysis(G, _load_ruleset(), "effort_distribution")
    got = {r["id"]: (r["env"]["eff"], r["result"] is True) for r in rows}
    assert got == EFFORT


def test_run_declared_coverage_matches_snapshot(fixture_graph):
    G, _ = fixture_graph
    rows = analyses.run_declared_analysis(G, _load_ruleset(), "coverage")
    got = {r["id"]: (r["env"]["cov"], r["result"]) for r in rows}
    assert got == COVERAGE


def test_declared_analyses_carry_severity():
    """Every declared analysis sets a project severity the engine carries (DD-025)."""
    ruleset = _load_ruleset()
    declared = {
        name: a for name, a in ruleset["analyses"].items()
        if isinstance(a, dict) and "query" in a
    }
    assert declared, "expected at least one declared analysis"
    for name, a in declared.items():
        assert a.get("severity") in {"error", "warn", "info"}, f"{name} missing/invalid severity"
