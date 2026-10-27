"""
SC-009: Context assembler (subgraph compiler).

Extract and render a transitive dependency chain as a single markdown
document suitable for an LLM API call.
"""

import networkx as nx
import yaml

from reqlite.analyses import traverse_subgraph


def _render_item(item) -> str:
    """Reconstruct a markdown representation of an item."""
    lines = [
        "---",
        f"id: {item.id}",
        f"title: {item.title}",
        f"certainty: {item.certainty}",
        f"negotiability: {item.negotiability}",
    ]
    if item.evidence is not None:
        lines.append(f"evidence: {item.evidence}")
    if item.actor is not None:
        lines.append(f"actor: {item.actor}")
    if item.effort is not None:
        lines.append(f"effort: {item.effort}")
    for key, value in item.extra.items():
        lines.append(yaml.safe_dump({key: value}, allow_unicode=True, sort_keys=False,
                                    default_flow_style=None, width=10**6).rstrip("\n"))
    lines.append("---")
    lines.append("")
    lines.append(item.body)
    return "\n".join(lines)


def foundation_chain(
    G: nx.DiGraph,
    target_id: str,
    depth: int | None = None,
) -> tuple[list[str], list[str]] | None:
    """The ids ``compile_subgraph`` renders, in its order, and the phantom ids it skips.

    Returns ``(ordered, phantoms)`` — ``ordered`` foundations first; ``phantoms`` the
    references reached that have no item — or None if target_id is not in the graph.
    """
    sub = traverse_subgraph(G, target_id, direction="foundations", depth=depth)
    if sub is None:
        return None

    subgraph_ids = set(sub.nodes)

    # Filter to nodes that have actual Item data (skip phantoms)
    nodes_with_items = [
        n for n in subgraph_ids
        if G.nodes[n].get("item") is not None
    ]
    phantoms = sorted(subgraph_ids - set(nodes_with_items))

    # Build subgraph and topological sort (foundations first)
    sub = G.subgraph(nodes_with_items)
    try:
        ordered = list(nx.topological_sort(sub))
    except nx.NetworkXUnfeasible:
        # Cycle in subgraph — fall back to sorted for determinism
        ordered = sorted(nodes_with_items)

    # Reverse: topological_sort gives dependents first, we want foundations first
    return list(reversed(ordered)), phantoms


def compile_subgraph(
    G: nx.DiGraph,
    target_id: str,
    system_prompt: str,
    depth: int | None = None,
) -> str | None:
    """Compile the transitive foundation subgraph of target_id.

    Returns a single markdown string with system prompt followed by
    item content in topological order (foundations first), or None
    if target_id is not in the graph.

    ``depth`` bounds how many reference hops of foundations to include
    (``None`` = unbounded, the full chain). Bounding lets a consistency
    review scope its context instead of always pulling the entire upstream
    closure. The traversal itself is the shared primitive in analyses
    (SRC-040/042), so this stays consistent with get_connections.
    """
    chain = foundation_chain(G, target_id, depth)
    if chain is None:
        return None
    ordered, _ = chain

    # Build the document
    sections = [system_prompt, ""]

    for node_id in ordered:
        item = G.nodes[node_id]["item"]
        sections.append(_render_item(item))
        sections.append("")

    return "\n".join(sections)


def compile_item(
    G: nx.DiGraph,
    target_id: str,
    system_prompt: str,
) -> str | None:
    """Compile a single item with a system prompt.

    Returns the system prompt followed by the target item only.
    No dependency walking — used for item-only quality checks (SRC-046).

    Returns None if target_id is not in the graph or has no Item data.
    """
    if target_id not in G:
        return None

    item = G.nodes[target_id].get("item")
    if item is None:
        return None

    sections = [system_prompt, "", _render_item(item), ""]
    return "\n".join(sections)
