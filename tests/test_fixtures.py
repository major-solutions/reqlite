"""
Tests that validate the fixture graph itself.

These ensure the test fixtures are well-formed and document
the structural properties that other tests rely on.
"""

import networkx as nx


def test_fixture_loads_11_items(fixture_items):
    assert len(fixture_items) == 11


def test_fixture_graph_builds(fixture_graph):
    G, findings = fixture_graph
    assert isinstance(G, nx.DiGraph)


def test_fixture_has_expected_nodes(fixture_graph):
    G, _ = fixture_graph
    ids = set(G.nodes)
    assert "SRC-001" in ids
    assert "SRC-006" in ids  # orphan
    assert "SRC-009" in ids  # self-cycle
    assert "FR-001" in ids   # cross-prefix
    assert "UC-001" in ids   # three-layer chain


def test_fixture_orphan_is_src_006(fixture_graph):
    G, findings = fixture_graph
    orphans = [f for f in findings if f.category == "orphan"]
    assert len(orphans) == 1
    assert orphans[0].item_id == "SRC-006"
def test_fixture_self_cycle_is_src_009(fixture_graph):
    G, findings = fixture_graph
    cycles = [f for f in findings if f.category == "cycle"]
    assert len(cycles) == 1
    assert cycles[0].item_id == "SRC-009"


def test_fixture_diamond_not_a_cycle(fixture_graph):
    G, findings = fixture_graph
    cycle_items = {f.item_id for f in findings if f.category == "cycle"}
    # SRC-003 and SRC-004 converge on SRC-005 but are not cycles
    assert "SRC-003" not in cycle_items
    assert "SRC-004" not in cycle_items


def test_fixture_src_002_has_highest_in_degree(fixture_graph):
    G, _ = fixture_graph
    # SRC-002 is referenced by SRC-001 and FR-001
    assert G.in_degree("SRC-002") == 2


def test_fixture_src_005_is_leaf(fixture_graph):
    G, _ = fixture_graph
    assert G.out_degree("SRC-005") == 0
    assert G.in_degree("SRC-005") > 0


def test_fixture_three_layer_chain(fixture_graph):
    G, _ = fixture_graph
    # UC-001 → FR-001 → SRC-002
    assert G.has_edge("UC-001", "FR-001")
    assert G.has_edge("FR-001", "SRC-002")


def test_fixture_no_duplicate_ids(fixture_graph):
    G, findings = fixture_graph
    dupes = [f for f in findings if f.category == "duplicate_id"]
    assert dupes == []
