"""
SC-002: Item parser.

Parses item files into structured Item values.
Satisfies FR-008. See tests/ORACLES-SC002.md for the behavioural spec.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from reqlite.hidden import hidden_text


class ParseError(Exception):
    """Raised when an item file cannot be parsed."""
    pass


@dataclass(frozen=True)
class Item:
    """Immutable representation of a parsed item."""
    id: str
    title: str
    certainty: str | None = None
    negotiability: str | None = None
    body: str = ""
    evidence: str | None = None
    actor: str | None = None
    effort: int | None = None
    filename: str | None = None  # the file it was read from; None when parsed from content alone
    # Frontmatter the fields above do not model (a ruleset's own fields, e.g. SRC `source`),
    # raw values in file order. Kept so compile shows the reader everything authored (ADR-016).
    extra: dict = field(default_factory=dict, hash=False)
    # What in the file does not render on the page (reqlite.hidden), as short reasons.
    hidden: tuple[str, ...] = ()


_MODELLED_KEYS = {"id", "title", "certainty", "negotiability", "evidence", "actor", "effort"}


_REQUIRED_FIELDS = ()  # nothing mandatory: id comes from the filename, the rest are optional

_ENUMS = {
    "certainty": {"speculative", "assumed", "verified"},
    "negotiability": {"immovable", "constrained", "negotiable"},
}

def _fibonacci_set(limit: int = 1000) -> frozenset[int]:
    """Generate Fibonacci numbers up to limit. ADR-015."""
    fibs = []
    a, b = 1, 2
    while a <= limit:
        fibs.append(a)
        a, b = b, a + b
    return frozenset(fibs)


_FIBONACCI_EFFORT = _fibonacci_set()

# Item filename: {PREFIX}-{NUM}-{slug}.md. The id is the {PREFIX}-{NUM} stem;
# the filename is the single source of id (see SRC-049).
_ITEM_FILENAME = re.compile(r"^([A-Z]+-\d+)-.+\.md$")

# Buried (retired) items live here and are excluded from the graph entirely.
_OBSOLETE_DIR = "obsolete"


def _split_frontmatter(content: str) -> tuple[str, str]:
    """Split content into (frontmatter_yaml, body).

    The frontmatter block is optional: a file that does not start with ---
    is all body (minimum viable item — DD-012). An opened block must close.
    """
    if not content.startswith("---"):
        return "", content

    # Find closing --- (must be on its own line)
    end = content.find("\n---", 3)
    if end == -1:
        raise ParseError("Missing frontmatter: no closing --- found")

    fm_yaml = content[4:end]  # skip opening ---\n
    body_start = end + 4      # skip \n---
    if body_start < len(content) and content[body_start] == "\n":
        body_start += 1
    body = content[body_start:] if body_start < len(content) else ""

    return fm_yaml, body


def _title_from_h1(body: str, item_id: str) -> str:
    """Derive the title from the first markdown H1, stripping a leading 'ID:'.

    The H1 is the single human-readable source of the title; falls back to
    the id when no H1 exists.
    """
    m = re.search(r"^# (.+)$", body, re.MULTILINE)
    if not m:
        return item_id
    h1 = m.group(1).strip()
    return re.sub(rf"^{re.escape(item_id)}:\s*", "", h1) or item_id


def parse_item_content(
    content: str, item_id: str | None = None, filename: str | None = None
) -> Item:
    """Parse item file content into an Item value.

    Args:
        content: Full item file content, including frontmatter.
        item_id: Authoritative id (from the filename). When given it is the
            single source of id; a disagreeing frontmatter ``id`` is a hard error.
            When omitted, falls back to the frontmatter ``id`` (back-compat).
        filename: The file's name, recorded so the graph builder can check that
            links name the file that exists (DD-003).

    Returns:
        Immutable Item with typed frontmatter fields and raw body.

    Raises:
        ParseError: If an opened frontmatter block does not close, YAML is
            malformed, or enum values are invalid. Frontmatter itself is
            optional (DD-012): absent or empty means no metadata.
    """
    fm_yaml, body = _split_frontmatter(content)

    try:
        fm = yaml.safe_load(fm_yaml) if fm_yaml.strip() else None
    except yaml.YAMLError as e:
        raise ParseError(f"Malformed YAML in frontmatter: {e}") from e

    if fm is None:
        fm = {}
    if not isinstance(fm, dict):
        raise ParseError("Malformed YAML in frontmatter: expected a mapping")

    # Validate required fields
    for field in _REQUIRED_FIELDS:
        if field not in fm or fm[field] is None:
            raise ParseError(f"Missing required field: {field}")

    # Validate enum fields (only when present — all are optional now)
    for field, allowed in _ENUMS.items():
        if field not in fm or fm[field] is None:
            continue
        value = str(fm[field])
        if value not in allowed:
            raise ParseError(
                f"Invalid value for {field}: '{value}'. "
                f"Allowed: {sorted(allowed)}"
            )

    # Validate effort is Fibonacci (ADR-015)
    if fm.get("effort") is not None:
        try:
            effort_val = int(fm["effort"])
        except (ValueError, TypeError):
            raise ParseError(
                f"Invalid effort value: '{fm['effort']}'. Must be a Fibonacci number."
            )
        if effort_val not in _FIBONACCI_EFFORT:
            raise ParseError(
                f"Invalid effort value: {effort_val}. "
                f"Must be a Fibonacci number (1, 2, 3, 5, 8, 13, 21, ...)"
            )

    fm_id = str(fm["id"]) if fm.get("id") is not None else None
    if item_id is not None and fm_id is not None and fm_id != item_id:
        raise ParseError(
            f"id mismatch: filename says '{item_id}', frontmatter says '{fm_id}'"
        )
    resolved_id = item_id if item_id is not None else fm_id
    if resolved_id is None:
        raise ParseError("Missing id: not derivable from filename or frontmatter")

    return Item(
        id=resolved_id,
        title=str(fm["title"]) if fm.get("title") is not None else _title_from_h1(body, resolved_id),
        certainty=str(fm["certainty"]) if fm.get("certainty") is not None else None,
        negotiability=str(fm["negotiability"]) if fm.get("negotiability") is not None else None,
        body=body,
        evidence=str(fm["evidence"]) if fm.get("evidence") is not None else None,
        actor=str(fm["actor"]) if fm.get("actor") is not None else None,
        effort=int(fm["effort"]) if fm.get("effort") is not None else None,
        filename=filename,
        extra={k: v for k, v in fm.items() if k not in _MODELLED_KEYS},
        hidden=hidden_text(body, fm_yaml),
    )


def hidden_items(items: list[Item]) -> list[tuple[str, tuple[str, ...]]]:
    """(id, reasons) for each item holding text the rendered page does not show."""
    return sorted((i.id, i.hidden) for i in items if i.hidden)


def describe_hidden(found: list[tuple[str, tuple[str, ...]]]) -> str:
    """`FR-001 (HTML comment), SRC-002 (…)`, for one-line notices."""
    return ", ".join(f"{item_id} ({'; '.join(reasons)})" for item_id, reasons in found)


def parse_all(graph_dir: Path) -> list[Item]:
    """Parse all item files in a directory, sorted by filename.

    Files whose names do not match the {ID}-{slug}.md pattern are skipped.

    Args:
        graph_dir: Path to the flat graph directory.

    Returns:
        List of Items, sorted by filename (lexicographic).
    """
    items = []
    root = Path(graph_dir).resolve()
    for path in sorted(graph_dir.iterdir()):
        if path.is_dir() and path.name == _OBSOLETE_DIR:
            continue  # buried (retired) items: intentionally excluded
        match = _ITEM_FILENAME.match(path.name)
        if path.is_file() and match:
            # The graph belongs to the repository under analysis, which may be someone
            # else's clone: a symlink out of it would feed any local file to the analyses
            # and to the reviewer (ORACLES-REVIEW 38).
            if not path.resolve().is_relative_to(root):
                raise ParseError(
                    f"{match.group(1)}: {path.name} resolves outside the graph directory "
                    f"{root}; item files must live inside it"
                )
            content = path.read_text(encoding="utf-8")
            items.append(parse_item_content(content, item_id=match.group(1), filename=path.name))
    return items
