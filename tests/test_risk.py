"""
Edge-focused behaviour of the declared risk analyses (assumption_risk,
justification), run via run_declared_analysis. Exact fixture-graph values are
snapshotted in test_ruleset_spec.py; this file keeps the cases the fixture does
not exercise — prefix scoping and the None/unjustified edges on purpose-built
graphs.
Derived from context/notes/risk-at-the-edges.md.
"""

import json
from pathlib import Path

from reqlite.items import parse_all
from reqlite.graph import build_graph
from reqlite import analyses

RULESET = json.loads((Path(__file__).parent.parent / "src" / "reqlite" / "rulesets" / "reqlite" / "ruleset.json").read_text())


def _rows(G, name):
    return {r["id"]: r for r in analyses.run_declared_analysis(G, RULESET, name)}


# =========================================================================
# Assumption risk: certainty × sum(downstream SC effort)
# =========================================================================

def test_assumption_risk_scopes_to_src(fixture_graph):
    G, _ = fixture_graph
    ids = set(_rows(G, "assumption_risk"))
    assert ids, "expected SRC rows"
    assert all(i.startswith("SRC-") for i in ids)
    assert "FR-001" not in ids
    assert "SC-001" not in ids


def test_assumption_risk_incomplete_effort_is_none(tmp_path):
    """An SC with no effort field leaves downstream risk incomplete (None), not 0."""
    (tmp_path / "SRC-001-a.md").write_text("""\
---
id: SRC-001
title: Assumption
certainty: speculative
negotiability: negotiable
status: active
evidence: null
---

Foundation.
""")
    (tmp_path / "SC-001-comp.md").write_text("""\
---
id: SC-001
title: Component
certainty: verified
negotiability: constrained
status: active
evidence: null
---

Depends on [SRC-001](SRC-001-a.md).
""")
    items = parse_all(tmp_path)
    G, _ = build_graph(items)
    rows = _rows(G, "assumption_risk")
    # No downstream effort field → incomplete, not silently defaulted to 0
    assert rows["SRC-001"]["env"]["eff"] is None
    assert rows["SRC-001"]["result"] is None


# =========================================================================
# Implementation justification: is each SC backed by a solid SRC?
# =========================================================================

def test_justification_scopes_to_sc(fixture_graph):
    G, _ = fixture_graph
    ids = set(_rows(G, "justification"))
    assert ids, "expected SC rows"
    assert all(i.startswith("SC-") for i in ids)


def test_justification_no_src_ancestry_is_unjustified(tmp_path):
    """An SC with no SRC in its chain is unjustified (result not True, no best)."""
    (tmp_path / "FR-001-req.md").write_text("""\
---
id: FR-001
title: Requirement
certainty: verified
negotiability: immovable
status: active
evidence: null
---

Standalone FR.
""")
    (tmp_path / "SC-001-comp.md").write_text("""\
---
id: SC-001
title: Component
certainty: verified
negotiability: constrained
status: active
evidence: null
---

Depends on [FR-001](FR-001-req.md). No SRC in the chain.
""")
    items = parse_all(tmp_path)
    G, _ = build_graph(items)
    rows = _rows(G, "justification")
    assert rows["SC-001"]["result"] is not True
    assert rows["SC-001"]["labels"]["best"] is None
