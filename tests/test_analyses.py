"""
Tests for algorithmic analyses.
Uses the shared fixture graph from conftest.py.
"""

import json
from pathlib import Path

from reqlite.analyses import connections, orphans, topology
from reqlite import analyses

RULESET = json.loads((Path(__file__).parent.parent / "src" / "reqlite" / "rulesets" / "reqlite" / "ruleset.json").read_text())


# =========================================================================
# Connections
# =========================================================================

def test_connections_outgoing(fixture_graph):
    G, _ = fixture_graph
    info = connections(G, "SRC-002")
    assert "SRC-003" in info.outgoing
    assert "SRC-004" in info.outgoing


def test_connections_incoming(fixture_graph):
    G, _ = fixture_graph
    info = connections(G, "SRC-002")
    assert "SRC-001" in info.incoming
    assert "FR-001" in info.incoming


def test_connections_leaf_has_no_outgoing(fixture_graph):
    G, _ = fixture_graph
    info = connections(G, "SRC-005")
    assert info.outgoing == []
    assert len(info.incoming) > 0


def test_connections_nonexistent_item(fixture_graph):
    G, _ = fixture_graph
    assert connections(G, "SRC-999") is None


def test_connections_orphan(fixture_graph):
    G, _ = fixture_graph
    info = connections(G, "SRC-006")
    assert info.outgoing == []
    assert info.incoming == []


def test_connections_self_referencing(fixture_graph):
    G, _ = fixture_graph
    info = connections(G, "SRC-009")
    assert "SRC-009" in info.outgoing
    assert "SRC-009" in info.incoming


# =========================================================================
# Orphans
# =========================================================================

def test_orphans_finds_src_006(fixture_graph):
    G, _ = fixture_graph
    result = orphans(G)
    assert "SRC-006" in result


def test_orphans_excludes_connected_items(fixture_graph):
    G, _ = fixture_graph
    result = orphans(G)
    assert "SRC-001" not in result  # has outgoing
    assert "SRC-005" not in result  # has incoming
    assert "SRC-002" not in result  # has both


def test_orphans_self_ref_not_orphan(fixture_graph):
    G, _ = fixture_graph
    result = orphans(G)
    # SRC-009 references itself — has both in-degree and out-degree 1
    assert "SRC-009" not in result


# =========================================================================
# Coverage
# =========================================================================

def test_coverage_includes_all_frs(fixture_graph):
    G, _ = fixture_graph
    rows = analyses.run_declared_analysis(G, RULESET, "coverage")
    assert "FR-001" in {r["id"] for r in rows}


def test_coverage_fr_count_and_status(fixture_graph):
    G, _ = fixture_graph
    rows = {r["id"]: r for r in analyses.run_declared_analysis(G, RULESET, "coverage")}
    # FR-001 is covered by 2 SCs. The per-SC covered-by list is no longer
    # retained (DD-025); the count stands in for it.
    assert rows["FR-001"]["env"]["cov"] == 2
    assert rows["FR-001"]["result"] is True


# =========================================================================
# Topology
# =========================================================================

def test_topology_source_items(fixture_graph):
    G, _ = fixture_graph
    result = topology(G)
    roles = {t.item_id: t.role for t in result}
    # SRC-001 has outgoing but no incoming from active items
    assert roles["SRC-001"] == "source"
    # UC-001 has outgoing but no incoming
    assert roles["UC-001"] == "source"


def test_topology_leaf_items(fixture_graph):
    G, _ = fixture_graph
    result = topology(G)
    roles = {t.item_id: t.role for t in result}
    assert roles["SRC-005"] == "leaf"


def test_topology_middle_items(fixture_graph):
    G, _ = fixture_graph
    result = topology(G)
    roles = {t.item_id: t.role for t in result}
    # SRC-002 has both incoming and outgoing
    assert roles["SRC-002"] == "middle"
    # FR-001 has incoming (UC-001) and outgoing (SRC-002, SRC-003)
    assert roles["FR-001"] == "middle"


def test_topology_orphan_classified_as_source(fixture_graph):
    G, _ = fixture_graph
    result = topology(G)
    roles = {t.item_id: t.role for t in result}
    # SRC-006 is an orphan — in-degree 0, out-degree 0
    assert roles["SRC-006"] == "source"


def test_topology_covers_all_active_items(fixture_graph):
    G, _ = fixture_graph
    result = topology(G)
    # Should have one entry per active item with Item data
    active_with_data = [
        n for n in G.nodes
        if G.nodes[n].get("item")
    ]
    assert len(result) == len(active_with_data)


def test_topology_determinism(fixture_graph):
    G, _ = fixture_graph
    r1 = topology(G)
    r2 = topology(G)
    assert r1 == r2
