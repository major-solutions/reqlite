"""
Tests for the subgraph traversal primitive (analyses.traverse_subgraph)
and the mermaid serializer (analyses.subgraph_to_mermaid).

Uses the shared fixture graph from conftest.py. Fixture topology (edge A->B
means "A depends on B", i.e. B is a foundation of A):

    FR-001 -> SRC-002, SRC-003
    SC-001 -> FR-001
    SC-002 -> FR-001
    UC-001 -> FR-001
    SRC-001 -> SRC-002
    SRC-002 -> SRC-003, SRC-004
    SRC-003 -> SRC-004, SRC-005
    SRC-004 -> SRC-005
    SRC-005 (leaf foundation)
    SRC-006 (orphan)
    SRC-009 -> SRC-009 (self-loop)

So FR-001's foundations (downstream of the arrows) are
{SRC-002, SRC-003, SRC-004, SRC-005} and its dependents are
{SC-001, SC-002, UC-001}.
"""

import pytest

from reqlite.analyses import traverse_subgraph, SubgraphResult, subgraph_to_mermaid
from reqlite.graph import build_graph
from reqlite.items import parse_item_content


# --- traverse_subgraph: direction ---

def test_foundations_one_hop(fixture_graph):
    G, _ = fixture_graph
    sub = traverse_subgraph(G, "FR-001", direction="foundations", depth=1)
    assert set(sub.nodes) == {"FR-001", "SRC-002", "SRC-003"}
    assert sub.distances["FR-001"] == 0
    assert sub.distances["SRC-002"] == 1


def test_dependents_one_hop(fixture_graph):
    G, _ = fixture_graph
    sub = traverse_subgraph(G, "FR-001", direction="dependents", depth=1)
    assert set(sub.nodes) == {"FR-001", "SC-001", "SC-002", "UC-001"}


def test_both_one_hop(fixture_graph):
    G, _ = fixture_graph
    sub = traverse_subgraph(G, "FR-001", direction="both", depth=1)
    assert set(sub.nodes) == {
        "FR-001", "SRC-002", "SRC-003", "SC-001", "SC-002", "UC-001"
    }


def test_foundations_transitive_unbounded(fixture_graph):
    G, _ = fixture_graph
    sub = traverse_subgraph(G, "FR-001", direction="foundations", depth=None)
    assert set(sub.nodes) == {
        "FR-001", "SRC-002", "SRC-003", "SRC-004", "SRC-005"
    }


def test_dependents_transitive_unbounded(fixture_graph):
    G, _ = fixture_graph
    # Nothing depends on the SC/UC items, so the closure is just the direct ones.
    sub = traverse_subgraph(G, "FR-001", direction="dependents", depth=None)
    assert set(sub.nodes) == {"FR-001", "SC-001", "SC-002", "UC-001"}


def test_negative_depth_is_unbounded(fixture_graph):
    G, _ = fixture_graph
    a = traverse_subgraph(G, "FR-001", direction="foundations", depth=-1)
    b = traverse_subgraph(G, "FR-001", direction="foundations", depth=None)
    assert set(a.nodes) == set(b.nodes)
    assert a.depth is None


# --- traverse_subgraph: ordering & determinism (SRC-042) ---

def test_nodes_ordered_by_hop_then_id(fixture_graph):
    G, _ = fixture_graph
    sub = traverse_subgraph(G, "FR-001", direction="both", depth=1)
    # focus first, then distance-1 nodes sorted lexicographically
    assert sub.nodes[0] == "FR-001"
    assert sub.nodes[1:] == ["SC-001", "SC-002", "SRC-002", "SRC-003", "UC-001"]


def test_deterministic_repeat(fixture_graph):
    G, _ = fixture_graph
    a = traverse_subgraph(G, "SRC-002", direction="both", depth=None)
    b = traverse_subgraph(G, "SRC-002", direction="both", depth=None)
    assert a == b


# --- traverse_subgraph: induced edges are faithful ---

def test_induced_edges_include_cross_link(fixture_graph):
    G, _ = fixture_graph
    # At depth 1 foundations of FR-001 we reach SRC-002 and SRC-003; the real
    # edge SRC-002 -> SRC-003 is between two reached nodes, so it is included.
    sub = traverse_subgraph(G, "FR-001", direction="foundations", depth=1)
    assert ("FR-001", "SRC-002") in sub.edges
    assert ("FR-001", "SRC-003") in sub.edges
    assert ("SRC-002", "SRC-003") in sub.edges


def test_edges_sorted(fixture_graph):
    G, _ = fixture_graph
    sub = traverse_subgraph(G, "FR-001", direction="both", depth=1)
    assert sub.edges == sorted(sub.edges)


# --- traverse_subgraph: edge cases ---

def test_missing_start_returns_none(fixture_graph):
    G, _ = fixture_graph
    assert traverse_subgraph(G, "ZZ-999", direction="both") is None


def test_bad_direction_raises(fixture_graph):
    G, _ = fixture_graph
    with pytest.raises(ValueError):
        traverse_subgraph(G, "FR-001", direction="sideways")


def test_self_loop_terminates(fixture_graph):
    G, _ = fixture_graph
    sub = traverse_subgraph(G, "SRC-009", direction="both", depth=None)
    assert sub.nodes == ["SRC-009"]
    assert ("SRC-009", "SRC-009") in sub.edges


def test_orphan_has_only_itself(fixture_graph):
    G, _ = fixture_graph
    sub = traverse_subgraph(G, "SRC-006", direction="both", depth=None)
    assert sub.nodes == ["SRC-006"]
    assert sub.edges == []


# --- mermaid serializer ---

def _label_for(G, lines, node_id):
    """Return the label string emitted for node_id, or None."""
    prefix = f"{node_id}["
    for ln in lines:
        s = ln.strip()
        if s.startswith(prefix):
            return s[len(prefix):].rstrip("]")
    return None


def test_mermaid_header_and_orientation(fixture_graph):
    G, _ = fixture_graph
    sub = traverse_subgraph(G, "FR-001", direction="both", depth=1)
    out = subgraph_to_mermaid(G, sub)
    # Bottom-to-top so foundations render above the focus.
    assert out.splitlines()[0] == "flowchart BT"
    assert "focus: FR-001" in out
    assert "foundations" in out and "dependents" in out


def test_mermaid_label_is_title_without_id(fixture_graph):
    G, _ = fixture_graph
    sub = traverse_subgraph(G, "FR-001", direction="both", depth=1)
    out = subgraph_to_mermaid(G, sub)
    lines = out.splitlines()

    title = G.nodes["FR-001"]["item"].title
    label = _label_for(G, lines, "FR-001")
    assert label is not None
    # the title is present, and the id is NOT duplicated inside the label
    assert title.strip('"') in label
    assert "FR-001" not in label
    # but the id IS the node identifier and appears in edges
    assert any(ln.strip().startswith("FR-001[") for ln in lines)
    assert any("--> " in ln for ln in lines)


def test_mermaid_edges_faithful(fixture_graph):
    G, _ = fixture_graph
    sub = traverse_subgraph(G, "FR-001", direction="foundations", depth=1)
    out = subgraph_to_mermaid(G, sub)
    # dependent -> foundation, exactly as stored
    assert "FR-001 --> SRC-002" in out
    assert "FR-001 --> SRC-003" in out


def test_mermaid_quote_escaping():
    items = [
        parse_item_content('# AA-001: He said "hi"', item_id="AA-001"),
        parse_item_content(
            "# AA-002: Plain\n\nSee [AA-001](AA-001-x.md).", item_id="AA-002"
        ),
    ]
    G, _ = build_graph(items)
    sub = traverse_subgraph(G, "AA-002", direction="foundations", depth=1)
    out = subgraph_to_mermaid(G, sub)
    assert '#quot;' in out          # quote was escaped
    assert '"hi"' not in out        # raw inner quote did not survive


def test_mermaid_phantom_node_labelled():
    items = [
        parse_item_content(
            "# AA-002: Plain\n\nSee [AA-999](AA-999-missing.md).", item_id="AA-002"
        ),
    ]
    G, _ = build_graph(items)
    sub = traverse_subgraph(G, "AA-002", direction="foundations", depth=1)
    out = subgraph_to_mermaid(G, sub)
    assert "AA-999" in out
    assert "unresolved" in out
