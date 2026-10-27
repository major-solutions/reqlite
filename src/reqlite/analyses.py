"""
SC-013: Analysis library.

Algorithmic analyses on the reqlite graph.

Each function takes a DiGraph (from build_graph) and returns
structured results. No LLM involvement — deterministic and cheap.
"""

from dataclasses import dataclass

import networkx as nx

from reqlite.query import parse_query_spec, run_query


# =========================================================================
# Declared-analysis runner (DD-024)
# =========================================================================

def run_declared_analysis(G: nx.DiGraph, ruleset: dict, name: str) -> list[dict]:
    """Run a ruleset-declared analysis through the generic query primitive.

    Reads ``ruleset["analyses"][name]["query"]`` (a raw QuerySpec) and the shared
    ``ruleset["scales"]`` map, runs it over ``G`` (SC-011), and returns the rows
    ``[{id, env, labels, result}]``. An optional ``"sort": "desc"`` on the
    declaration ranks rows by the combine result, Nones last — matching the
    score-ranked bespoke analyses.

    The engine holds no per-analysis knowledge: the prefixes, fields, scale, and
    sort are all data in the ruleset (DD-024). Raises KeyError if the named
    analysis has no ``query`` declaration.
    """
    decl = ruleset["analyses"][name]
    spec = parse_query_spec(decl["query"])
    scales = ruleset.get("scales", {})
    rows = run_query(G, spec, scales)
    if decl.get("sort") == "desc":
        rows.sort(key=lambda r: (r["result"] is None, -(r["result"] or 0), r["id"]))
    return rows



@dataclass(frozen=True)
class ConnectionInfo:
    """Connections for a single item."""
    item_id: str
    outgoing: list[str]
    incoming: list[str]


@dataclass(frozen=True)
class TopologyInfo:
    """Topology classification for a single item."""
    item_id: str
    role: str  # "source", "leaf", "middle"


def connections(G: nx.DiGraph, target: str) -> ConnectionInfo | None:
    """Return incoming and outgoing connections for a target item.

    Returns None if the target is not in the graph.
    """
    if target not in G:
        return None

    return ConnectionInfo(
        item_id=target,
        outgoing=sorted(G.successors(target)),
        incoming=sorted(G.predecessors(target)),
    )


def orphans(G: nx.DiGraph) -> list[str]:
    """Return IDs of active items with no connections in either direction."""
    return sorted(
        n for n in G.nodes
        if G.in_degree(n) == 0 and G.out_degree(n) == 0
        and G.nodes[n].get("item") is not None
    )


def topology(G: nx.DiGraph) -> list[TopologyInfo]:
    """Classify each item as source, leaf, or middle.

    - Source: in-degree 0, out-degree > 0
    - Leaf: out-degree 0, in-degree > 0
    - Middle: both in-degree and out-degree > 0
    - Orphan items (both 0) are classified as source (they have no
      incoming influence, like a source, but also no output)

    Only items with actual Item data are classified (skip phantom
    nodes created by edges to nonexistent items).
    """
    result = []
    for n in sorted(G.nodes):
        item = G.nodes[n].get("item")
        if item is None:
            continue

        ind = G.in_degree(n)
        outd = G.out_degree(n)

        if outd == 0 and ind > 0:
            role = "leaf"
        elif ind == 0:
            role = "source"
        else:
            role = "middle"

        result.append(TopologyInfo(item_id=n, role=role))

    return result


# =========================================================================
# Subgraph traversal (SRC-024 connections, DD-027 mermaid subgraph)
# =========================================================================

_DIRECTIONS = ("foundations", "dependents", "both")


@dataclass(frozen=True)
class SubgraphResult:
    """A bounded traversal around one focus item.

    The orientation convention: an item references the items that justify it,
    so its *foundations* (upstream) are its transitive dependencies and its
    *dependents* (downstream) are the items that reference it.

    - ``nodes``: reached ids including the focus, ordered deterministically by
      ``(hop distance, id)`` so the listing reads outward in hops (SRC-042).
    - ``edges``: the induced edges among the reached nodes — every real edge
      whose endpoints are both present — sorted lexicographically. Kept faithful
      to the markdown (each edge points from an item at its foundation).
    - ``distances``: reached id -> hop distance from the focus (focus == 0).
    """
    start: str
    direction: str
    depth: int | None
    nodes: list[str]
    edges: list[tuple[str, str]]
    distances: dict[str, int]


def _bfs_hops(G: nx.DiGraph, start: str, neighbors, depth: int | None) -> dict[str, int]:
    """Breadth-first hop distances from start following ``neighbors`` edges.

    Bounded by ``depth`` hops (None = unbounded). Self-loops and cycles are
    safe: a node already seen is never re-enqueued.
    """
    dist = {start: 0}
    frontier = [start]
    hop = 0
    while frontier and (depth is None or hop < depth):
        hop += 1
        nxt: list[str] = []
        for n in frontier:
            for m in neighbors(n):
                if m not in dist:
                    dist[m] = hop
                    nxt.append(m)
        frontier = nxt
    return dist


def traverse_subgraph(
    G: nx.DiGraph,
    start: str,
    direction: str = "both",
    depth: int | None = None,
) -> SubgraphResult | None:
    """Walk the dependency DAG outward from one item (SRC-040, SRC-042).

    Args:
        G: the graph from build_graph.
        start: focus item id.
        direction:
            ``"foundations"`` — follow references to what justifies the item
            (its transitive dependencies / upstream);
            ``"dependents"`` — walk back to what references the item (its
            transitive dependents / downstream);
            ``"both"`` — the union.
        depth: hop limit; ``None`` (or a negative value) means unbounded.

    Returns:
        A SubgraphResult, or None if ``start`` is not in the graph.

    Deterministic by construction: the same inputs always yield the same nodes,
    edges, and ordering. Phantom nodes (references to items absent from the set)
    are included when reached — a dangling reference is meaningful, not an error
    (DD-029).
    """
    if direction not in _DIRECTIONS:
        raise ValueError(
            f"bad direction {direction!r}; expected one of {_DIRECTIONS}"
        )
    if start not in G:
        return None
    if depth is not None and depth < 0:
        depth = None

    dist: dict[str, int] = {start: 0}
    if direction in ("foundations", "both"):
        for n, d in _bfs_hops(G, start, G.successors, depth).items():
            dist[n] = min(d, dist.get(n, d))
    if direction in ("dependents", "both"):
        for n, d in _bfs_hops(G, start, G.predecessors, depth).items():
            dist[n] = min(d, dist.get(n, d))

    node_set = set(dist)
    nodes = sorted(node_set, key=lambda n: (dist[n], n))
    edges = sorted((u, v) for u, v in G.edges if u in node_set and v in node_set)

    return SubgraphResult(
        start=start,
        direction=direction,
        depth=depth,
        nodes=nodes,
        edges=edges,
        distances=dist,
    )


def _mermaid_label(text: str) -> str:
    """Make a title safe to sit inside a mermaid ``["..."]`` label.

    Labels are double-quoted, so an embedded quote would end the label early;
    escape it as the HTML entity mermaid understands. Newlines (rare in an H1)
    collapse to spaces.
    """
    return text.replace('"', "#quot;").replace("\n", " ").strip()


def subgraph_to_mermaid(G: nx.DiGraph, result: SubgraphResult) -> str:
    """Serialize a SubgraphResult as a mermaid flowchart for an LLM consumer.

    Orientation (the project convention): foundations sit *above* the focus,
    dependents *below* it. This is achieved with ``flowchart BT`` plus edges
    kept faithful to the markdown — each item points at its foundations — so in
    a bottom-to-top layout the foundation end of every edge renders higher.

    Node identifier is the item id (so edges and navigation stay faithful); the
    label is the item *title* only, never the id again. Phantom nodes (dangling
    references) are labelled as unresolved. Output is deterministic: nodes follow
    ``result.nodes`` order, edges follow ``result.edges`` order.
    """
    lines = [
        "flowchart BT",
        f"%% reqlite connections — focus: {result.start} "
        f"(direction={result.direction}, depth={'∞' if result.depth is None else result.depth})",
        "%% foundations (upstream) render on top · dependents (downstream) below",
        "%% each arrow points from an item to one of its foundations",
    ]

    for node_id in result.nodes:
        item = G.nodes[node_id].get("item")
        label = "(unresolved reference)" if item is None else _mermaid_label(item.title)
        lines.append(f'    {node_id}["{label}"]')

    for u, v in result.edges:
        lines.append(f"    {u} --> {v}")

    return "\n".join(lines)


def impact_count(G: nx.DiGraph, node: str) -> int:
    """Number of items that transitively depend on this node.

    Structural reachability count — a domain-universal analysis that stays in
    the engine (DD-010), independent of the retired weight ranking that was its
    only caller.
    """
    return len(nx.ancestors(G, node))
