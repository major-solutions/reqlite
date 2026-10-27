"""
Tests for the graph builder, SC-004 (absorbs the planned SC-003 and SC-011, DD-004).
Oracles from ORACLES-SC003.md and ORACLES-SC011.md, except SC011 6-7 (removed, DD-011).
"""

from reqlite.items import Item
from reqlite.graph import build_graph, Finding


def _item(item_id: str, body: str = "") -> Item:
    """Helper to create an Item with minimal valid fields."""
    return Item(
        id=item_id,
        title=item_id,
        certainty="assumed",
        negotiability="constrained",
        body=body,
    )


def _findings_by_cat(findings: list[Finding], cat: str) -> list[Finding]:
    return [f for f in findings if f.category == cat]


# =========================================================================
# Reverse reference tests (from SC-003 oracles)
# =========================================================================

def test_simple_incoming_reference():
    items = [
        _item("SRC-001", "References [SRC-002](SRC-002-foo.md)."),
        _item("SRC-002", "No references here."),
    ]
    G, _ = build_graph(items)
    assert set(G.predecessors("SRC-002")) == {"SRC-001"}
    assert set(G.predecessors("SRC-001")) == set()


def test_multiple_incoming_references():
    items = [
        _item("SRC-001", "The root."),
        _item("SRC-002", "Depends on [SRC-001](SRC-001-dag.md)."),
        _item("SRC-003", "Also depends on [SRC-001](SRC-001-dag.md)."),
    ]
    G, _ = build_graph(items)
    assert set(G.predecessors("SRC-001")) == {"SRC-002", "SRC-003"}


def test_mutual_references():
    items = [
        _item("SRC-001", "See [SRC-002](SRC-002-foo.md)."),
        _item("SRC-002", "See [SRC-001](SRC-001-bar.md)."),
    ]
    G, _ = build_graph(items)
    assert set(G.predecessors("SRC-001")) == {"SRC-002"}
    assert set(G.predecessors("SRC-002")) == {"SRC-001"}


def test_no_references():
    items = [
        _item("SRC-001", "Standalone."),
        _item("SRC-002", "Also standalone."),
        _item("SRC-003", "Me too."),
    ]
    G, _ = build_graph(items)
    assert G.number_of_edges() == 0


def test_self_reference_in_graph():
    items = [
        _item("SRC-001", "I reference myself: [SRC-001](SRC-001-self.md)."),
    ]
    G, _ = build_graph(items)
    assert set(G.predecessors("SRC-001")) == {"SRC-001"}


def test_transitive_not_flattened():
    items = [
        _item("SRC-001", "References [SRC-002](SRC-002-mid.md)."),
        _item("SRC-002", "References [SRC-003](SRC-003-leaf.md)."),
        _item("SRC-003", "Leaf."),
    ]
    G, _ = build_graph(items)
    assert set(G.predecessors("SRC-002")) == {"SRC-001"}
    assert set(G.predecessors("SRC-003")) == {"SRC-002"}
    assert "SRC-001" not in set(G.predecessors("SRC-003"))


def test_reference_to_nonexistent_creates_node():
    items = [
        _item("SRC-001", "References [SRC-999](SRC-999-ghost.md)."),
    ]
    G, _ = build_graph(items)
    # SRC-999 should exist as a node (added by the edge)
    assert set(G.predecessors("SRC-999")) == {"SRC-001"}


def test_empty_item_list_graph():
    G, findings = build_graph([])
    assert G.number_of_nodes() == 0
    assert findings == []


def test_graph_determinism():
    items = [
        _item("SRC-001", "Refs [SRC-002](SRC-002-a.md) and [SRC-003](SRC-003-b.md)."),
        _item("SRC-002", "Refs [SRC-003](SRC-003-b.md)."),
        _item("SRC-003", "Leaf."),
    ]
    G1, f1 = build_graph(items)
    G2, f2 = build_graph(items)
    assert set(G1.nodes) == set(G2.nodes)
    assert set(G1.edges) == set(G2.edges)
    assert len(f1) == len(f2)


# =========================================================================
# Integrity tests (from SC-011 oracles)
# =========================================================================

def test_clean_graph_no_non_cycle_findings():
    items = [
        _item("SRC-001", "See [SRC-002](SRC-002-b.md)."),
        _item("SRC-002", "See [SRC-003](SRC-003-c.md)."),
        _item("SRC-003", "See [SRC-001](SRC-001-a.md)."),
    ]
    _, findings = build_graph(items)
    non_cycle = [f for f in findings if f.category != "cycle"]
    assert non_cycle == []


def test_orphan_detected():
    items = [
        _item("SRC-001", "See [SRC-002](SRC-002-b.md)."),
        _item("SRC-002", "See [SRC-001](SRC-001-a.md)."),
        _item("SRC-003", "Standalone, no references."),
    ]
    _, findings = build_graph(items)
    orphans = _findings_by_cat(findings, "orphan")
    assert len(orphans) == 1
    assert orphans[0].item_id == "SRC-003"


def test_outgoing_only_not_orphan():
    items = [
        _item("SRC-001", "References [SRC-002](SRC-002-b.md)."),
        _item("SRC-002", "Leaf, no outgoing."),
    ]
    _, findings = build_graph(items)
    orphans = _findings_by_cat(findings, "orphan")
    assert orphans == []


def test_unknown_reference():
    items = [
        _item("SRC-001", "References [SRC-999](SRC-999-ghost.md)."),
    ]
    _, findings = build_graph(items)
    unknowns = _findings_by_cat(findings, "unknown_reference")
    assert len(unknowns) == 1
    assert unknowns[0].item_id == "SRC-001"
    assert "SRC-999" in unknowns[0].detail


def test_multiple_unknown_references():
    items = [
        _item("SRC-001", "Refs [SRC-998](SRC-998-a.md) and [SRC-999](SRC-999-b.md)."),
    ]
    _, findings = build_graph(items)
    unknowns = _findings_by_cat(findings, "unknown_reference")
    assert len(unknowns) == 2
    assert all(f.item_id == "SRC-001" for f in unknowns)
def test_duplicate_ids():
    items = [
        _item("SRC-001", "First."),
        _item("SRC-001", "Second with same ID."),
    ]
    _, findings = build_graph(items)
    dupes = _findings_by_cat(findings, "duplicate_id")
    assert len(dupes) == 1
    assert "SRC-001" in dupes[0].detail


def test_cycle_detected():
    items = [
        _item("SRC-001", "Refs [SRC-002](SRC-002-b.md)."),
        _item("SRC-002", "Refs [SRC-003](SRC-003-c.md)."),
        _item("SRC-003", "Refs [SRC-001](SRC-001-a.md)."),
    ]
    _, findings = build_graph(items)
    cycles = _findings_by_cat(findings, "cycle")
    assert len(cycles) >= 1


def test_self_reference_cycle():
    items = [
        _item("SRC-001", "I reference myself [SRC-001](SRC-001-self.md)."),
    ]
    _, findings = build_graph(items)
    cycles = _findings_by_cat(findings, "cycle")
    assert len(cycles) == 1
    assert cycles[0].item_id == "SRC-001"


def test_diamond_dag_no_cycle():
    items = [
        _item("SRC-001", "Refs [SRC-002](SRC-002-b.md) and [SRC-003](SRC-003-c.md)."),
        _item("SRC-002", "Refs [SRC-003](SRC-003-c.md)."),
        _item("SRC-003", "Leaf."),
    ]
    _, findings = build_graph(items)
    cycles = _findings_by_cat(findings, "cycle")
    assert cycles == []


def test_multiple_issue_types():
    items = [
        _item("SRC-001", "Refs [SRC-999](SRC-999-ghost.md) and [SRC-003](SRC-003-c.md)."),
        _item("SRC-002", "Standalone orphan."),
        _item("SRC-003", "A normal item."),
    ]
    _, findings = build_graph(items)
    cats = sorted(f.category for f in findings)
    assert "orphan" in cats
    assert "unknown_reference" in cats


def test_empty_item_list_integrity():
    _, findings = build_graph([])
    assert findings == []


def test_integrity_determinism():
    items = [
        _item("SRC-001", "Refs [SRC-002](SRC-002-b.md)."),
        _item("SRC-002", "Leaf."),
        _item("SRC-003", "Orphan."),
    ]
    _, f1 = build_graph(items)
    _, f2 = build_graph(items)
    assert len(f1) == len(f2)
    assert sorted(f.category for f in f1) == sorted(f.category for f in f2)


# =========================================================================
# Link target must name the existing file (ORACLES-SC011 15-16, DD-003)
# =========================================================================

def _filed(item_id: str, filename: str, body: str = "") -> Item:
    return Item(id=item_id, title=item_id, body=body, filename=filename)


def test_link_to_wrong_filename_of_existing_item():
    items = [
        _filed("FR-001", "FR-001-cap.md", "Rests on [SRC-001](SRC-001-old-slug.md)."),
        _filed("SRC-001", "SRC-001-current.md"),
    ]
    G, findings = build_graph(items)
    unknowns = _findings_by_cat(findings, "unknown_reference")
    assert len(unknowns) == 1
    assert unknowns[0].item_id == "FR-001"
    assert "SRC-001-old-slug.md" in unknowns[0].detail
    assert "SRC-001-current.md" in unknowns[0].detail
    assert G.has_edge("FR-001", "SRC-001")


def test_link_to_right_filename_is_clean():
    items = [
        _filed("FR-001", "FR-001-cap.md", "Rests on [SRC-001](SRC-001-current.md)."),
        _filed("SRC-001", "SRC-001-current.md"),
    ]
    _, findings = build_graph(items)
    assert _findings_by_cat(findings, "unknown_reference") == []


def test_items_without_filename_are_not_checked_for_it():
    items = [
        _item("FR-001", "Rests on [SRC-001](SRC-001-anything.md)."),
        _item("SRC-001"),
    ]
    _, findings = build_graph(items)
    assert _findings_by_cat(findings, "unknown_reference") == []
