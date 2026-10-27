"""
Tests for subgraph compile.
Derived from test oracles (tests/ORACLES-COMPILE.md).
Uses the shared fixture graph from conftest.py.
"""

from reqlite.compile import compile_subgraph


PROMPT = "You are a requirements analyst."


# --- Oracle 1: Basic compilation ---

def test_basic_compilation(fixture_graph):
    G, _ = fixture_graph
    result = compile_subgraph(G, "SC-001", PROMPT)
    assert result is not None
    # Should contain the target and its dependencies
    assert "SC-001" in result
    assert "FR-001" in result
    assert "SRC-002" in result


# --- Oracle 2: System prompt prepended ---

def test_system_prompt_prepended(fixture_graph):
    G, _ = fixture_graph
    result = compile_subgraph(G, "SC-001", PROMPT)
    # System prompt should appear before any item content
    prompt_pos = result.index(PROMPT)
    first_item_pos = result.index("SRC-")
    assert prompt_pos < first_item_pos


# --- Oracle 3: Target not in graph ---

def test_target_not_in_graph(fixture_graph):
    G, _ = fixture_graph
    result = compile_subgraph(G, "SRC-999", PROMPT)
    assert result is None


# --- Oracle 4: Target with no dependencies ---

def test_target_no_dependencies(fixture_graph):
    G, _ = fixture_graph
    result = compile_subgraph(G, "SRC-006", PROMPT)
    assert result is not None
    assert "SRC-006" in result
    assert PROMPT in result
    # Should not contain other items
    assert "SRC-001" not in result
    assert "SRC-002" not in result


# --- Oracle 5: Diamond — items appear once ---

def test_diamond_items_appear_once(fixture_graph):
    G, _ = fixture_graph
    # SRC-003 and SRC-004 both depend on SRC-005
    # Compile from SRC-002 which depends on both
    result = compile_subgraph(G, "SRC-002", PROMPT)
    assert result.count("id: SRC-005") == 1
# --- Oracle 7: Phantom nodes skipped ---

def test_phantom_nodes_skipped(tmp_path):
    from reqlite.items import parse_all
    from reqlite.graph import build_graph

    (tmp_path / "SRC-001-a.md").write_text("""\
---
id: SRC-001
title: References phantom
certainty: assumed
negotiability: constrained
status: active
evidence: null
---

Depends on [SRC-999](SRC-999-ghost.md).
""")
    items = parse_all(tmp_path)
    G, _ = build_graph(items)
    result = compile_subgraph(G, "SRC-001", PROMPT)
    assert result is not None
    assert "SRC-001" in result
    # Phantom node should not have its own rendered section
    assert "id: SRC-999" not in result


# --- Oracle 8: Frontmatter included ---

def test_frontmatter_included(fixture_graph):
    G, _ = fixture_graph
    result = compile_subgraph(G, "SRC-006", PROMPT)
    assert "certainty:" in result
    assert "negotiability:" in result
    assert "status: active" in result  # authored, so the reader sees it


# --- Oracle 9: Topological order — foundations first ---

def test_topological_order_foundations_first(fixture_graph):
    G, _ = fixture_graph
    # SC-001 → FR-001 → SRC-002 → SRC-003 → SRC-005
    result = compile_subgraph(G, "SC-001", PROMPT)
    pos_005 = result.index("id: SRC-005")
    pos_003 = result.index("id: SRC-003")
    pos_002 = result.index("id: SRC-002")
    pos_fr = result.index("id: FR-001")
    pos_sc = result.index("id: SC-001")
    # Foundations should appear before the items that depend on them
    assert pos_005 < pos_003
    assert pos_003 < pos_002
    assert pos_002 < pos_fr
    assert pos_fr < pos_sc


# --- Oracle 10: Determinism ---

def test_compile_determinism(fixture_graph):
    G, _ = fixture_graph
    r1 = compile_subgraph(G, "SC-001", PROMPT)
    r2 = compile_subgraph(G, "SC-001", PROMPT)
    assert r1 == r2


# =========================================================================
# compile_item tests (item-only mode for quality checks)
# =========================================================================

from reqlite.compile import compile_item


# --- Oracle 11: Single item only ---

def test_item_only_contains_target(fixture_graph):
    G, _ = fixture_graph
    result = compile_item(G, "FR-001", PROMPT)
    assert result is not None
    assert "id: FR-001" in result
    # Must NOT contain dependencies as rendered items
    assert "id: SRC-002" not in result
    assert "id: SRC-003" not in result


# --- Oracle 12: Prompt prepended ---

def test_item_only_prompt_prepended(fixture_graph):
    G, _ = fixture_graph
    result = compile_item(G, "FR-001", PROMPT)
    prompt_pos = result.index(PROMPT)
    item_pos = result.index("id: FR-001")
    assert prompt_pos < item_pos


# --- Oracle 13: Target not in graph ---

def test_item_only_not_in_graph(fixture_graph):
    G, _ = fixture_graph
    result = compile_item(G, "SRC-999", PROMPT)
    assert result is None


# --- Oracle 14: Frontmatter included ---

def test_item_only_frontmatter(fixture_graph):
    G, _ = fixture_graph
    result = compile_item(G, "SRC-006", PROMPT)
    assert "certainty:" in result
    assert "negotiability:" in result
    assert "status: active" in result  # authored, so the reader sees it


# --- Oracle 15: Body included ---

def test_item_only_body_included(fixture_graph):
    G, _ = fixture_graph
    result = compile_item(G, "FR-001", PROMPT)
    item = G.nodes["FR-001"]["item"]
    # Body text should be present
    assert item.body.strip()[:30] in result


# --- Oracle 16: Determinism ---

def test_item_only_determinism(fixture_graph):
    G, _ = fixture_graph
    r1 = compile_item(G, "FR-001", PROMPT)
    r2 = compile_item(G, "FR-001", PROMPT)
    assert r1 == r2


# --- Depth-bounded compilation (shared traversal primitive) ---

def test_depth_unbounded_default_matches_full_chain(fixture_graph):
    G, _ = fixture_graph
    # Default (depth=None) still pulls the whole foundation chain of FR-001.
    result = compile_subgraph(G, "FR-001", PROMPT)
    for fid in ("FR-001", "SRC-002", "SRC-003", "SRC-004", "SRC-005"):
        assert fid in result


def test_depth_one_limits_to_direct_foundations(fixture_graph):
    G, _ = fixture_graph
    result = compile_subgraph(G, "FR-001", PROMPT, depth=1)
    # direct foundations rendered as items...
    assert "id: SRC-002" in result
    assert "id: SRC-003" in result
    # ...but deeper ones are not rendered as items (the bare id can still appear
    # inside a shallower item's reference text, so assert on the rendered header)
    assert "id: SRC-005" not in result
    assert "id: SRC-004" not in result


def test_depth_missing_target_still_none(fixture_graph):
    G, _ = fixture_graph
    assert compile_subgraph(G, "ZZ-999", PROMPT, depth=2) is None


# --- Oracle 8: every authored field reaches the reader ---

def _single(tmp_path, content):
    from reqlite.items import parse_all
    from reqlite.graph import build_graph

    (tmp_path / "SRC-001-a.md").write_text(content, encoding="utf-8")
    G, _ = build_graph(parse_all(tmp_path))
    return G


def test_ruleset_declared_field_rendered(tmp_path):
    # A reviewer that never sees `source` reports every SRC as missing_source.
    G = _single(tmp_path, "---\ncertainty: assumed\nsource: assumption\n---\n\n# SRC-001: A\n")
    assert "source: assumption" in compile_item(G, "SRC-001", PROMPT)
    assert "source: assumption" in compile_subgraph(G, "SRC-001", PROMPT)


def test_structured_field_rendered_as_yaml(tmp_path):
    G = _single(tmp_path, "---\ntags: [a, b]\nnote: 'x: y'\n---\n\n# SRC-001: A\n")
    result = compile_item(G, "SRC-001", PROMPT)
    assert "tags: [a, b]" in result
    assert "note: 'x: y'" in result
