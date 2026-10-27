"""
SC-004: Graph builder. The central representation for reqlite.

Builds a NetworkX DiGraph from parsed items (DD-004). Integrity findings
are produced during construction; all analyses operate on the returned
graph. Subsumes the former reverse-reference-index and integrity-checker
components into this one.
"""

from dataclasses import dataclass

import networkx as nx

from reqlite.items import Item
from reqlite.references import extract_link_targets


@dataclass(frozen=True)
class Finding:
    """A single integrity finding observed during graph construction."""
    category: str   # orphan, unknown_reference, duplicate_id, cycle
    item_id: str    # the item where the issue was found (or "" for graph-level)
    detail: str     # human-readable explanation


def build_graph(items: list[Item]) -> tuple[nx.DiGraph, list[Finding]]:
    """Build a directed graph from items and report integrity findings.

    Nodes are item IDs. Each node carries the full Item as an attribute.
    Edges represent references found in item body text via SC-001.

    Integrity findings are collected during construction:
    - duplicate_id: multiple items with the same ID
    - unknown_reference: edge target not in the item set, or a link naming a
      file other than the target item's own (DD-003)
    - orphan: item with no edges in either direction
    - cycle: reference loop detected

    Args:
        items: List of parsed Items (from SC-002).

    Returns:
        (graph, findings) — the DiGraph and a list of findings.
        The graph is always returned, even if findings exist.
    """
    if not items:
        return nx.DiGraph(), []

    findings: list[Finding] = []
    G = nx.DiGraph()

    # --- Phase 1: Add nodes, check for duplicate IDs ---
    seen_ids: dict[str, int] = {}

    for item in items:
        seen_ids[item.id] = seen_ids.get(item.id, 0) + 1
        G.add_node(item.id, item=item)

    for item_id, count in seen_ids.items():
        if count > 1:
            findings.append(Finding(
                category="duplicate_id",
                item_id="",
                detail=f"ID {item_id} appears {count} times",
            ))

    # --- Phase 2: Add edges, check references ---
    filenames: dict[str, set[str]] = {}
    for item in items:
        if item.filename is not None:
            filenames.setdefault(item.id, set()).add(item.filename)

    for item in items:
        targets = extract_link_targets(item.body)
        for ref_id in sorted(targets):
            G.add_edge(item.id, ref_id)

            if ref_id not in seen_ids:
                findings.append(Finding(
                    category="unknown_reference",
                    item_id=item.id,
                    detail=f"References {ref_id} which does not exist in the item set",
                ))
                continue

            # DD-003: the link target must be the file that exists, or the link is
            # broken on every renderer even though the id resolves. Only checkable
            # when the target's filename is known (items read from disk).
            known = filenames.get(ref_id)
            if known:
                for href in sorted(targets[ref_id] - known):
                    findings.append(Finding(
                        category="unknown_reference",
                        item_id=item.id,
                        detail=(f"Links {ref_id} as {href}, but its file is "
                                f"{', '.join(sorted(known))}"),
                    ))

    # --- Phase 3: Orphan detection ---
    for item in items:
        if G.in_degree(item.id) == 0 and G.out_degree(item.id) == 0:
            findings.append(Finding(
                category="orphan",
                item_id=item.id,
                detail=f"Item {item.id} has no outgoing or incoming references",
            ))

    # --- Phase 4: Cycle detection ---
    for cycle in sorted(nx.simple_cycles(G), key=lambda c: sorted(c)):
        if len(cycle) == 1:
            findings.append(Finding(
                category="cycle",
                item_id=cycle[0],
                detail=f"Item {cycle[0]} references itself",
            ))
        else:
            first = sorted(cycle)[0]
            findings.append(Finding(
                category="cycle",
                item_id=first,
                detail=f"Reference cycle involving {sorted(cycle)}",
            ))

    return G, findings
