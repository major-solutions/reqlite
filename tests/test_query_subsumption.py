"""
Query-algebra guard: the generic query algebra (query.py) produces the expected
dimension-analysis results on the fixture graph.

These snapshots were originally captured as equivalence against the bespoke
dimension analyses (assumption_risk / implementation_justification /
effort_distribution). Those functions have since been retired in favour of
ruleset-declared QuerySpecs, so the snapshots now pin the algebra's output
directly. test_ruleset_spec.py asserts the same values via the ruleset-loaded
path.
"""

from reqlite.query import QuerySpec, Term, run_query

SCALES = {"certainty": {"verified": 1, "assumed": 2, "speculative": 3}}


def test_query_assumption_risk(fixture_graph):
    G, _ = fixture_graph
    expected = {
        "SRC-002": (2, 6, 12), "SRC-004": (2, 6, 12), "SRC-005": (2, 6, 12),
        "SRC-003": (1, 6, 6),
        "SRC-001": (3, 0, 0), "SRC-006": (3, 0, 0), "SRC-009": (3, 0, 0),
    }
    spec = QuerySpec(start="SRC",
                     terms=[Term("eff", "up", "sum", "effort", target="SC")],
                     combine="self_certainty * eff")
    got = {r["id"]: (r["env"]["self_certainty"], r["env"]["eff"], r["result"])
           for r in run_query(G, spec, SCALES)}
    assert got == expected


def test_query_justification(fixture_graph):
    G, _ = fixture_graph
    expected = {"SC-001": ("verified", True), "SC-002": ("verified", True)}
    spec = QuerySpec(start="SC",
                     terms=[Term("best", "down", "min", "certainty", target="SRC")],
                     combine="best <= 1")
    got = {r["id"]: (r["labels"]["best"], r["result"] is True)
           for r in run_query(G, spec, SCALES)}
    assert got == expected


def test_query_effort_distribution(fixture_graph):
    G, _ = fixture_graph
    expected = {"SC-001": (5, False), "SC-002": (1, False)}
    spec = QuerySpec(start="SC",
                     terms=[Term("eff", "self", "value", "effort")],
                     combine="eff > 8")
    got = {r["id"]: (r["env"]["eff"], r["result"] is True)
           for r in run_query(G, spec, SCALES)}
    assert got == expected
