# reqlite:begin SC-011
"""
SC-011: Dimension query primitive.

Generic dimension-aggregation query over the reqlite graph.

One primitive subsumes the bespoke weight analyses: each is a traversal from a
start node, a filter to a target type, and a reduction of one dimension,
optionally combined by a small scalar expression.

Frozen operator set — the HARD CEILING. Anything beyond this is the signal to
spin up an ephemeral graph database and write the query there, NOT to extend
this module:

    reducers : min, max, sum, count, value
    combine  : + - * /, comparisons (< <= > >= ==), unary minus, over numbers only
               (numeric literals; names whose values are numbers or None)

Traversal directions: down (dependencies / descendants), up (dependents /
ancestors), self. A QuerySpec is data, not code — no plugin loader.

Structural reachability counts (e.g. impact = number of dependents) and
integrity checks (cycles, dangling refs) deliberately live OUTSIDE this algebra,
in the engine, because they are domain-universal and not dimension reductions.

Specs are declared per project in the ruleset (`analyses.<name>.query`, with
dimension scales under a top-level `scales` block) and loaded by
parse_query_spec; the engine holds no named analysis. See DD-024.
"""

from __future__ import annotations

import ast
import operator
from dataclasses import dataclass

import networkx as nx

# dimension value -> ordinal score; ultimately supplied by the ruleset.
# numeric dimensions (effort) need no scale: their value is the number.
Scale = dict[str, dict[str, int]]

# empty-set defaults, chosen to match the existing analyses' conventions
_EMPTY = {"sum": 0, "count": 0, "max": 0, "min": None, "value": None}

REDUCERS = frozenset(_EMPTY)
DIRECTIONS = ("down", "up", "self")

_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub,
    ast.Mult: operator.mul, ast.Div: operator.truediv,
}
_CMP = {
    ast.Lt: operator.lt, ast.LtE: operator.le,
    ast.Gt: operator.gt, ast.GtE: operator.ge, ast.Eq: operator.eq,
}


@dataclass(frozen=True)
class Term:
    name: str                       # referenced in combine
    direction: str                  # "down" | "up" | "self"
    reduce: str                     # "min" | "max" | "sum" | "count" | "value"
    dimension: str | None = None    # None for count
    target: str | None = None       # type-prefix filter on reached nodes
    include_self: bool = False      # include the start node in the reached set


@dataclass(frozen=True)
class QuerySpec:
    start: str                      # type-prefix, or "*" for all; one row per node
    terms: list[Term]
    combine: str | None = None      # scalar expression over term names + self_<dim>


def parse_query_spec(d: dict) -> QuerySpec:
    """Build a QuerySpec from a plain dict (e.g. a ruleset analysis declaration).

    This is the bridge that lets a project *declare* an analysis as data instead
    of the engine hardcoding it. The dict shape mirrors the dataclasses exactly:

        {"start": "SRC",
         "terms": [{"name": "eff", "direction": "up", "reduce": "sum",
                    "dimension": "effort", "target": "SC"}],
         "combine": "self_certainty * eff"}

    Required per term: name, direction, reduce. Optional: dimension, target,
    include_self. Raises KeyError/TypeError on a malformed spec — fail loud, do
    not silently run a half-built query.
    """
    return QuerySpec(
        start=d["start"],
        terms=[
            Term(
                name=t["name"],
                direction=t["direction"],
                reduce=t["reduce"],
                dimension=t.get("dimension"),
                target=t.get("target"),
                include_self=t.get("include_self", False),
            )
            for t in d["terms"]
        ],
        combine=d.get("combine"),
    )


def _is_number(v) -> bool:
    # bool passes as an int, so a comparison's result can be scaled: (a >= 1) * 2
    return isinstance(v, (int, float))


def _eval(node, env):
    """Safe arithmetic/comparison evaluator. None propagates. Whitelist = ceiling.

    Numbers only: a string reaching ``*`` would be sequence repetition, an allocation the
    ruleset's author sizes. Literals and name values are both checked, since a scale can
    map a label to any JSON value.
    """
    if isinstance(node, ast.Expression):
        return _eval(node.body, env)
    if isinstance(node, ast.Constant):
        if not _is_number(node.value):
            raise ValueError(f"combine: non-numeric literal {node.value!r}")
        return node.value
    if isinstance(node, ast.Name):
        v = env[node.id]
        if v is not None and not _is_number(v):
            raise ValueError(f"combine: '{node.id}' is {type(v).__name__}, not a number")
        return v
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        v = _eval(node.operand, env)
        return None if v is None else -v
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        a, b = _eval(node.left, env), _eval(node.right, env)
        return None if a is None or b is None else _BINOPS[type(node.op)](a, b)
    if isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in _CMP:
        a, b = _eval(node.left, env), _eval(node.comparators[0], env)
        return None if a is None or b is None else _CMP[type(node.ops[0])](a, b)
    raise ValueError(f"combine: unsupported expression element {ast.dump(node)}")


def combine_errors(expr: str, names: set[str]) -> list[str]:
    """Static check of a combine expression against the evaluator's whitelist.

    Mirrors ``_eval`` node for node without evaluating, so a ruleset lint and the engine
    can never disagree on what runs (ORACLES-RULESET 16). Empty list = it would run.
    """
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        return [f"does not parse: {e.msg}"]
    errors: list[str] = []

    def walk(node):
        if isinstance(node, ast.Expression):
            walk(node.body)
        elif isinstance(node, ast.Constant):
            if not _is_number(node.value):
                errors.append(f"uses the literal {ast.unparse(node)}, which is not a number")
        elif isinstance(node, ast.Name):
            if node.id not in names:
                errors.append(f"names '{node.id}', which is no term and no self_ value")
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            walk(node.operand)
        elif isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            walk(node.left)
            walk(node.right)
        elif (isinstance(node, ast.Compare) and len(node.ops) == 1
              and type(node.ops[0]) in _CMP):
            walk(node.left)
            walk(node.comparators[0])
        else:
            errors.append(f"uses '{ast.unparse(node)}', outside the frozen operator set")

    walk(tree)
    return errors


def self_dimensions(scales: Scale) -> list[str]:
    """The dimensions a combine expression can read as ``self_<dim>``."""
    return list(scales) + ["effort"]


def _score(item, dimension: str | None, scales: Scale):
    """Resolve a node's dimension to a number: via scale, or raw if numeric."""
    if dimension is None:
        return None
    raw = getattr(item, dimension, None)
    if raw is None:
        return None
    if dimension in scales:
        return scales[dimension].get(str(raw))
    return int(raw)


def _reached(G, node, term: Term):
    if term.direction == "self":
        ids = {node}
    elif term.direction == "down":
        ids = set(nx.descendants(G, node))
    elif term.direction == "up":
        ids = set(nx.ancestors(G, node))
    else:
        raise ValueError(f"bad direction {term.direction!r}")
    if term.include_self:
        ids.add(node)
    out = []
    for n in ids:
        item = G.nodes[n].get("item")
        if item is None:
            continue
        if term.target and not n.startswith(term.target + "-"):
            continue
        out.append((n, item))
    return out


def _apply(term: Term, reached, scales: Scale):
    """Return (value, label); label = achieving node's dimension for min/max."""
    if term.reduce == "count":
        return len(reached), None
    scored = [(_score(item, term.dimension, scales), item) for _, item in reached]
    if term.reduce == "value":
        return (scored[0][0] if scored else None), None
    if term.reduce == "sum":
        complete = all(s is not None for s, _ in scored)
        return (sum(s for s, _ in scored if s is not None) if complete else None), None
    present = [(s, item) for s, item in scored if s is not None]
    if not present:
        return _EMPTY[term.reduce], None
    pick = min if term.reduce == "min" else max
    s, item = pick(present, key=lambda p: p[0])
    label = getattr(item, term.dimension, None)
    return s, (str(label) if label is not None else None)


def run_query(G, spec: QuerySpec, scales: Scale):
    """Run a QuerySpec over the graph. One result row per start node.

    Each row: {id, env (term + self_<dim> values), labels, result}.
    """
    rows = []
    start_nodes = sorted(
        n for n in G.nodes
        if (spec.start == "*" or n.startswith(spec.start + "-"))
        and G.nodes[n].get("item") is not None
    )
    self_dims = self_dimensions(scales)
    for node in start_nodes:
        item = G.nodes[node]["item"]
        env, labels = {}, {}
        for term in spec.terms:
            env[term.name], labels[term.name] = _apply(term, _reached(G, node, term), scales)
        for dim in self_dims:
            env[f"self_{dim}"] = _score(item, dim, scales)
        result = _eval(ast.parse(spec.combine, mode="eval"), env) if spec.combine else None
        rows.append({"id": node, "env": env, "labels": labels, "result": result})
    return rows
# reqlite:end SC-011
