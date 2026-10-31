# reqlite:begin SC-012, FR-019
"""
SC-012: Code justification scanner — language-agnostic fences.

A fence is a pair of comment lines around a span of any text file:

    reqlite:begin <ID>[, <ID>...] [test]
    ...
    reqlite:end <ID>

The marker is the first token on its line, after optional whitespace and one optional
comment leader. After the ids only the role ``test`` (on a begin) and a comment closer may
follow; a test fence wraps code that checks its ids and realises none of them. Fences are matched line by line at scan time, never parsed and never
stored: a fence travels with the text it wraps, so nothing drifts (DD-019, DD-021). The
scan yields ephemeral FENCE nodes, integrity findings and per-file coverage.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Iterable

from reqlite.items import parse_all

_ID = r"[A-Z]+-\d+"
_LEADER = r"(?:#|//|--|;|%|<!--|/\*|\*|::|(?i:rem)\b|')"
_MARKER = re.compile(
    rf"^[ \t]*(?:{_LEADER})?[ \t]*reqlite:(begin|end)[ \t]+({_ID}(?:[ \t]*,[ \t]*{_ID})*)"
)
# After the ids: an optional role, then an optional comment closer. Anything else is a
# finding, so a typo can never turn a test into a realisation.
_TAIL = re.compile(r"(?:[ \t]+(test))?[ \t]*(?:-->|\*/)?[ \t]*$")
_NEEDLE = b"reqlite:"
_SNIFF = 8192

IGNORE = (".git", ".venv", "node_modules", "build", "dist", "__pycache__", "*.egg-info")
INTEGRITY = ("unclosed_fence", "unopened_fence", "mismatched_fence", "dangling_fence_ref",
             "unknown_fence_role")
TEST = "test"
UNKNOWN = "unknown"   # the role of a begin whose tail did not parse


@dataclass(frozen=True)
class Fence:
    """An ephemeral fenced span. Lines are for display; nothing is persisted."""

    id: str                 # FENCE-<relpath>#<n>, unstable by design (DD-019)
    ids: tuple[str, ...]
    file: str
    begin: int
    end: int
    first_line: str = ""
    role: str = ""          # "" realises its ids; TEST checks them; UNKNOWN does neither


@dataclass(frozen=True)
class FenceFinding:
    category: str           # one of INTEGRITY
    file: str
    line: int
    detail: str


@dataclass
class Scan:
    fences: list[Fence] = field(default_factory=list)
    findings: list[FenceFinding] = field(default_factory=list)
    unfenced_files: list[str] = field(default_factory=list)
    gaps: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    unreadable: list[str] = field(default_factory=list)
    # every begin marker, closed or not: (file, line, ids), so dangling ids surface
    # alongside an unclosed fence rather than after it is fixed
    refs: list[tuple[str, int, tuple[str, ...]]] = field(default_factory=list)


@dataclass
class Report(Scan):
    unrealised: list[str] | None = None   # None: no type was expected
    unknown_types: list[str] = field(default_factory=list)   # expected, but no such item


def _ignored(name: str, ignore: Iterable[str]) -> bool:
    return any(fnmatch(name, pat) for pat in ignore)


def _nested_project(d: Path) -> bool:
    """A reqlite project of its own: the commit check's marker, a ruleset beside a graph.
    Its fences name its own graph, so a scan from above skips it."""
    return (d / "graph").is_dir() and (d / "ruleset" / "ruleset.json").is_file()


def _files(paths: Iterable[Path], ignore: Iterable[str], exclude: set[Path]) -> list[Path]:
    """Files under ``paths``; ``ignore`` names directories, never files. Nested projects
    below a given path are skipped; a path given explicitly is always scanned."""
    out: list[Path] = []
    for p in map(Path, paths):
        if p.is_file():
            out.append(p)
            continue
        for dirpath, dirnames, filenames in os.walk(p):
            here = Path(dirpath)
            dirnames[:] = sorted(
                d for d in dirnames
                if not _ignored(d, ignore) and (here / d).resolve() not in exclude
                and not _nested_project(here / d)
            )
            out.extend(here / f for f in sorted(filenames))
    return out


def _rel(p: Path, root: Path) -> str:
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def _lines(data: bytes) -> list[str]:
    text = data.decode("utf-8-sig", errors="replace")
    # Split on \n only: str.splitlines also breaks on \f, \x1c, U+2028 and others,
    # which would shift line numbers away from what an editor shows.
    return [ln.rstrip("\r") for ln in text.split("\n")][: -1 if text.endswith("\n") else None]


def _scan_file(rel: str, lines: list[str], out: Scan) -> None:
    stack: list[tuple[tuple[str, ...], int, str]] = []
    spans: list[tuple[tuple[str, ...], int, int, str]] = []
    for n, line in enumerate(lines, 1):
        m = _MARKER.match(line)
        if not m:
            continue
        ids = tuple(re.findall(_ID, m.group(2)))
        tail = _TAIL.match(line, m.end())
        if m.group(1) == "begin":
            if tail:
                role = tail.group(1) or ""
            else:
                role = UNKNOWN
                out.findings.append(FenceFinding(
                    "unknown_fence_role", rel, n,
                    f"unexpected {line[m.end():].strip()!r} after the ids; only the role "
                    f"'{TEST}' and a comment closer may follow"))
            stack.append((ids, n, role))
            out.refs.append((rel, n, ids))
            continue
        if not tail or tail.group(1):
            out.findings.append(FenceFinding(
                "unknown_fence_role", rel, n,
                f"unexpected {line[m.end():].strip()!r} after the id; reqlite:end takes "
                "no role, only a comment closer"))
        if len(ids) > 1:
            out.findings.append(FenceFinding(
                "mismatched_fence", rel, n,
                f"reqlite:end takes one id, the first of its begin; got {', '.join(ids)}"))
        if not stack:
            out.findings.append(FenceFinding(
                "unopened_fence", rel, n, f"reqlite:end {ids[0]} has no open begin"))
            continue
        if stack[-1][0][0] == ids[0]:
            open_ids, start, role = stack.pop()
        else:
            # Overlap: the end closes a fence deeper in the stack. One finding, and the
            # fences opened inside it stay open so their own ends still pair.
            deeper = [k for k in range(len(stack) - 1) if stack[k][0][0] == ids[0]]
            inner_ids, inner_start, _ = stack[-1]
            if deeper:
                open_ids, start, role = stack.pop(deeper[-1])
                out.findings.append(FenceFinding(
                    "mismatched_fence", rel, n,
                    f"reqlite:end {ids[0]} overlaps {inner_ids[0]} opened at line "
                    f"{inner_start}; fences must nest"))
            else:
                open_ids, start, role = stack.pop()
                out.findings.append(FenceFinding(
                    "mismatched_fence", rel, n,
                    f"reqlite:end {ids[0]} closes the begin of {open_ids[0]} at line {start}"))
        spans.append((open_ids, start, n, role))
    for ids, start, _ in stack:
        out.findings.append(FenceFinding(
            "unclosed_fence", rel, start, f"reqlite:begin {ids[0]} has no end"))

    if not spans:
        if any(ln.strip() for ln in lines):
            out.unfenced_files.append(rel)
        return
    for k, (ids, start, end, role) in enumerate(sorted(spans, key=lambda s: s[1]), 1):
        first = next((ln.strip() for ln in lines[start:end - 1] if ln.strip()), "")
        out.fences.append(Fence(f"FENCE-{rel}#{k}", ids, rel, start, end, first, role))
    covered = set()
    for _, start, end, _ in spans:
        covered.update(range(start, end + 1))
    gaps = _gaps(lines, covered)
    if gaps:
        out.gaps[rel] = gaps


def _gaps(lines: list[str], covered: set[int]) -> list[tuple[int, int]]:
    """Ranges outside every fence that hold a non-blank line, trimmed of blank ends."""
    gaps: list[tuple[int, int]] = []
    run: list[int] = []
    for n in range(1, len(lines) + 2):
        if n <= len(lines) and n not in covered:
            if lines[n - 1].strip():
                run.append(n)
            continue
        if run:
            gaps.append((run[0], run[-1]))
        run = []
    return gaps


def scan(
    paths: Iterable[Path],
    root: Path | None = None,
    ignore: Iterable[str] = IGNORE,
    exclude: Iterable[Path] = (),
) -> Scan:
    """Fences, structural findings and coverage over the text files under ``paths``.

    Binaries (a NUL byte in the first 8 KB) and directories matching ``ignore`` are
    skipped; ``exclude`` drops whole directories (the graph). A file that cannot be read
    is listed in ``unreadable`` instead of ending the scan. Paths in the result are
    relative to ``root``.
    """
    root = Path(root) if root is not None else Path.cwd()
    out = Scan()
    for f in _files(paths, tuple(ignore), {Path(e).resolve() for e in exclude}):
        rel = _rel(f, root)
        try:
            data = f.read_bytes()
        except OSError:
            out.unreadable.append(rel)
            continue
        if b"\x00" in data[:_SNIFF]:
            continue
        if _NEEDLE not in data:
            if data.removeprefix(b"\xef\xbb\xbf").strip():
                out.unfenced_files.append(rel)
            continue
        _scan_file(rel, _lines(data), out)
    out.unfenced_files.sort()
    out.unreadable.sort()
    out.findings.sort(key=lambda x: (x.file, x.line))
    return out


def fence_report(
    paths: Iterable[Path],
    graph_dir: Path,
    expect: Iterable[str] = (),
    root: Path | None = None,
    ignore: Iterable[str] = IGNORE,
) -> Report:
    """``scan`` plus what needs the graph: dangling ids and unrealised items.

    Unrealised items are reported only for the types in ``expect``; no type is assumed.
    Only a fence with no role realises its ids: a test fence checks them.
    An expected type that no item has is listed in ``unknown_types``, so a mistyped type
    cannot read as full coverage.
    """
    graph_ids = {i.id for i in parse_all(Path(graph_dir))}
    s = scan(paths, root=root, ignore=ignore, exclude=[graph_dir])
    rep = Report(s.fences, s.findings, s.unfenced_files, s.gaps, s.unreadable, s.refs)
    for file, line, ids in s.refs:
        missing = [i for i in ids if i not in graph_ids]
        if missing:
            rep.findings.append(FenceFinding(
                "dangling_fence_ref", file, line,
                f"names {', '.join(missing)}, not in the graph"))
    rep.findings.sort(key=lambda x: (x.file, x.line))
    expect = set(expect)
    if expect:
        types = {i.split("-")[0] for i in graph_ids}
        rep.unknown_types = sorted(expect - types)
        named = {i for f in s.fences if not f.role for i in f.ids}
        rep.unrealised = sorted(
            i for i in graph_ids if i.split("-")[0] in expect and i not in named)
    return rep
# reqlite:end SC-012
