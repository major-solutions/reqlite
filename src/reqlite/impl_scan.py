"""
SC-012: Code justification scanner.

Realises the ephemeral IMPL-extraction decision (DD-013) for FR-019: enumerate
code units with ast, read intentional docstring markers, synthesise ephemeral
IMPL nodes, union with the spec graph, and report traceability. IMPL nodes are
never written to disk (the fence).
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from reqlite.items import parse_all

_ID = r"[A-Z]+-\d+"
# Intentional justification markers ONLY: leading "SC-001:", "Satisfies X",
# "Implements X". A bare id mention or a "Replaces"/"See" reference is not an edge.
_MARKER = re.compile(
    rf"(?:^\s*({_ID})\s*:)"
    rf"|(?:Satisfies\s+({_ID}(?:\s*,\s*{_ID})*))"
    rf"|(?:Implements:?\s+({_ID}(?:\s*,\s*{_ID})*))",
    re.MULTILINE,
)
_SKIP_FILES = {"__init__.py", "__main__.py"}


@dataclass
class ImplNode:
    """An ephemeral code unit (id like 'IMPL-query.run_query'); never persisted.

    Carries enough detail to identify the unit without opening the file, so a
    list of these is debuggable on its own: what it is (role), where it lives
    (loc/end_line), its shape (signature), what it claims to do (summary), and
    what justifies it (spec_ids / inherited).
    """

    id: str
    spec_ids: set[str] = field(default_factory=set)
    kind: str = ""           # raw ast node type: module / FunctionDef / ClassDef
    role: str = ""           # semantic: module / function / internal / command / class / data
    loc: str = ""            # file:line
    end_line: int = 0
    signature: str = ""
    summary: str = ""        # first line of the docstring
    decorators: tuple[str, ...] = ()
    inherited: bool = False  # justified by its module's marker, not its own


def _markers(doc: str | None) -> set[str]:
    out: set[str] = set()
    for m in _MARKER.finditer(doc or ""):
        for g in m.groups():
            if g:
                out.update(re.findall(_ID, g))
    return out


def _summary(doc: str | None) -> str:
    return (doc or "").strip().splitlines()[0].strip() if doc else ""


def _signature(node: ast.AST) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        args = ast.unparse(node.args)
        ret = f" -> {ast.unparse(node.returns)}" if node.returns else ""
        return f"({args}){ret}"
    if isinstance(node, ast.ClassDef):
        bases = ", ".join(ast.unparse(b) for b in node.bases)
        return f"({bases})" if bases else ""
    return ""


def _role(node: ast.AST, decos: tuple[str, ...]) -> str:
    if isinstance(node, ast.ClassDef):
        is_dataclass = any("dataclass" in d for d in decos)
        has_methods = any(
            isinstance(b, (ast.FunctionDef, ast.AsyncFunctionDef))
            and not b.name.startswith("__")
            for b in node.body
        )
        return "data" if (is_dataclass or not has_methods) else "class"
    if any("command" in d or d.startswith("app.") for d in decos):
        return "command"
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return "internal" if node.name.startswith("_") else "function"
    return "?"


def scan_impl(src_dir: Path) -> dict[str, ImplNode]:
    """Enumerate top-level functions/classes under src_dir as ephemeral IMPL nodes.

    A unit inherits its module's marker when it has none of its own. Nothing is
    dropped — data-holders are tagged role='data' rather than hidden.
    """
    nodes: dict[str, ImplNode] = {}
    for f in sorted(Path(src_dir).glob("*.py")):
        if f.name in _SKIP_FILES:
            continue
        mod = f.stem
        tree = ast.parse(f.read_text(encoding="utf-8"))
        mod_marks = _markers(ast.get_docstring(tree))
        if mod_marks:
            nodes[f"IMPL-{mod}"] = ImplNode(
                id=f"IMPL-{mod}", spec_ids=set(mod_marks), kind="module",
                role="module", loc=str(f), summary=_summary(ast.get_docstring(tree)),
            )
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                decos = tuple(ast.unparse(d) for d in node.decorator_list)
                own = _markers(ast.get_docstring(node))
                spec = own or mod_marks
                nodes[f"IMPL-{mod}.{node.name}"] = ImplNode(
                    id=f"IMPL-{mod}.{node.name}",
                    spec_ids=set(spec),
                    kind=type(node).__name__,
                    role=_role(node, decos),
                    loc=f"{f}:{node.lineno}",
                    end_line=node.end_lineno or node.lineno,
                    signature=_signature(node),
                    summary=_summary(ast.get_docstring(node)),
                    decorators=decos,
                    inherited=bool(not own and mod_marks),
                )
    return nodes


def list_impl(
    src_dir: Path,
    roles: set[str] | None = None,
    unjustified_only: bool = False,
) -> list[ImplNode]:
    """Full annotated IMPL list, sorted by id. Optionally filter by role / unjustified.

    Filtering hides nothing structurally — it is a view over the same scan, so the
    tally is always the code as it stands, computed live (never a stored registry).
    """
    out = list(scan_impl(src_dir).values())
    if roles:
        out = [n for n in out if n.role in roles]
    if unjustified_only:
        out = [n for n in out if not n.spec_ids]
    return sorted(out, key=lambda n: n.id)


def justification_report(src_dir: Path, graph_dir: Path) -> dict:
    """Union ephemeral IMPL nodes with the spec graph and report traceability."""
    from collections import Counter

    impl = scan_impl(src_dir)
    spec_ids = {i.id for i in parse_all(Path(graph_dir))}
    sc_ids = {i for i in spec_ids if i.startswith("SC-")}

    claimed: set[str] = set()
    for v in impl.values():
        claimed |= v.spec_ids

    justified = {k: v for k, v in impl.items() if v.spec_ids}
    unjustified = sorted((k for k, v in impl.items() if not v.spec_ids))
    return {
        "total": len(impl),
        "justified": len(justified),
        "unjustified": unjustified,
        "unjustified_by_role": dict(
            Counter(impl[u].role for u in unjustified)
        ),
        "unrealised_sc": sorted(sc_ids - claimed),
        "dangling": {
            k: sorted(v.spec_ids - spec_ids)
            for k, v in justified.items()
            if v.spec_ids - spec_ids
        },
    }
