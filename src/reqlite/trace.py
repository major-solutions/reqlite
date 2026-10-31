# reqlite:begin SC-012, DD-022, DD-023
"""
Observed traceability: a test run's per-test coverage against what the graph expects.

An adapter, run inside the project's own toolchain, writes the observed data (format
version 1, documented in the user guide): which lines each test executed. The expected side
is computed here at compare time, from the graph and the fences; nothing graph-related is
stored or read from the adapter. Line coverage cannot tell which unit called which, so
coupling is reported as an unordered pair.

Types are ruleset data (the top-level ``observed_trace`` key); the defaults name the shipped
ones. This is a named engine algorithm in the manner of DD-020's vetted registry, outside
the query algebra; DD-024 is to be amended to record it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Iterable

from reqlite.fences import IGNORE, INTEGRITY, TEST, UNKNOWN, fence_report
from reqlite.graph import build_graph
from reqlite.items import parse_all

FORMAT = 1
OUTCOMES = ("passed", "failed", "skipped", "error")
FINDINGS = (
    "untraced_test", "stale", "test_misses_target", "partial_system_test",
    "not_a_unit_test", "undeclared_coupling", "coincidental_coverage",
    "no_unit_test", "unexecuted_realisation",
    "unjustified_code", "mixed_role_fence",
)
DEFAULTS = {
    "requirement_type": "FR", "implementation_type": "SC", "verification_type": "TC",
    "intermediate_types": ["DD"], "require_unit_test": False, "blocking": ["untraced_test"],
}


class TraceError(Exception):
    """The comparison cannot run. Never raised to mean 'no findings'."""


@dataclass(frozen=True)
class TraceFinding:
    category: str           # one of FINDINGS, or a fence integrity category
    subject: str            # a test name, an item id, a pair, a file or file:line
    detail: str
    ids: tuple[str, ...] = ()
    blocking: bool = False


@dataclass(frozen=True)
class TracedTest:
    name: str
    kind: str               # unit | system | untraced
    ids: tuple[str, ...]    # the SCs a unit test checks, the TCs a system test implements
    outcome: str


@dataclass
class Coverage:
    """Executable fenced lines of one SC, and how many each kind of test executed."""

    measured: int
    suite: int = 0
    related: int = 0
    unit: int = 0
    unit_tests: int = 0     # passing unit tests of the SC; 0 means none, not "missed"


@dataclass
class TraceResult:
    findings: list[TraceFinding] = field(default_factory=list)
    coverage: dict[str, Coverage] = field(default_factory=dict)
    tests: list[TracedTest] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    stale: list[str] = field(default_factory=list)
    matrix: dict = field(default_factory=dict)      # the regenerated expected side
    implementation_type: str = DEFAULTS["implementation_type"]

    @property
    def blocking(self) -> bool:
        return any(f.blocking for f in self.findings)


def content_hash(data: bytes) -> str:
    """sha256 with CRLF normalised to LF, so a Windows checkout of a commit is not stale."""
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def _glob(pattern: str) -> re.Pattern:
    """A scope glob: ``*`` and ``?`` stay within a directory, ``**`` crosses them."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        elif pattern[i] == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out + r"\Z")


def _norm(path: str) -> str:
    p = path.replace("\\", "/")
    return p[2:] if p.startswith("./") else p


# --- the observed data ---------------------------------------------------------------------

def load_observed(data: bytes) -> dict:
    """Parse and validate observed data. Raises TraceError naming what is wrong."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        raise TraceError("the observed data is UTF-16; write it with the adapter's output "
                         "option rather than shell redirection")
    try:
        obj = json.loads(data.decode("utf-8-sig"))
    except UnicodeDecodeError:
        raise TraceError("the observed data is not UTF-8") from None
    except json.JSONDecodeError as e:
        raise TraceError(f"the observed data is not JSON: {e}") from None
    _validate(obj)
    return obj


def _is_lines(v) -> bool:
    return isinstance(v, dict) and all(
        isinstance(k, str) and isinstance(ls, list) and all(isinstance(n, int) for n in ls)
        for k, ls in v.items())


def _validate(obj) -> None:
    if not isinstance(obj, dict):
        raise TraceError("the observed data is not a JSON object")
    if "contract" not in obj:
        raise TraceError(f"the observed data has no 'contract' field; expected format "
                         f"version {FORMAT}")
    if obj["contract"] != FORMAT:
        raise TraceError(f"observed data format version {obj['contract']!r} is not "
                         f"supported; this reqlite reads version {FORMAT}")
    for key in ("source", "files", "executable", "tests"):
        if key not in obj:
            raise TraceError(f"the observed data has no '{key}' field")
    if not isinstance(obj["files"], dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in obj["files"].items()):
        raise TraceError("'files' must map file paths to sha256 hashes")
    scope = obj.get("scope")
    if scope is not None and not (isinstance(scope, list)
                                  and all(isinstance(g, str) for g in scope)):
        raise TraceError("'scope' must be a list of globs")
    for key in ("executable", "outside_tests"):
        if key in obj and not _is_lines(obj[key]):
            raise TraceError(f"'{key}' must map file paths to lists of line numbers")
    funcs = obj.get("functions")
    if funcs is not None and not (isinstance(funcs, dict) and all(
            isinstance(spans, list) and all(
                isinstance(s, list) and len(s) == 3 and isinstance(s[0], int)
                and isinstance(s[1], int) for s in spans)
            for spans in funcs.values())):
        raise TraceError("'functions' must map file paths to [begin, end, name] lists")
    if not isinstance(obj["tests"], list):
        raise TraceError("'tests' must be a list")
    for i, t in enumerate(obj["tests"]):
        if not isinstance(t, dict) or not isinstance(t.get("name"), str):
            raise TraceError(f"test {i} has no 'name'")
        where = f"test {i} ({t['name']})"
        if not isinstance(t.get("file"), str):
            raise TraceError(f"{where} has no 'file'")
        if "line" not in t or not (t["line"] is None or isinstance(t["line"], int)):
            raise TraceError(f"{where} has no 'line' (a number, or null when unknown)")
        if t.get("outcome") not in OUTCOMES:
            raise TraceError(f"{where} has no valid 'outcome'; expected one of {OUTCOMES}")
        if not _is_lines(t.get("executed")):
            raise TraceError(f"{where}: 'executed' must map file paths to lists of line "
                             "numbers")


# --- configuration -------------------------------------------------------------------------

def config_errors(raw, types: Iterable[str] | None = None) -> list[tuple[str, str, str]]:
    """(category, where, detail) for each defect of an ``observed_trace`` entry. Type names
    are checked against ``types`` only when it is given."""
    w = "observed_trace"
    if not isinstance(raw, dict):
        return [("observed_trace_malformed", w, "must be an object")]
    types = set(types) if types is not None else None
    out: list[tuple[str, str, str]] = []

    def bad(key, detail):
        out.append(("observed_trace_malformed", f"{w}.{key}", detail))

    def known(key, name):
        if types is not None and name not in types:
            out.append(("observed_trace_unknown_type", f"{w}.{key}",
                        f"'{name}' is not a type defined in types"))

    for key in raw:
        if not key.startswith("_") and key not in DEFAULTS:
            bad(key, f"unknown key '{key}'; expected one of {', '.join(DEFAULTS)}")
    for key in ("requirement_type", "implementation_type", "verification_type"):
        if key in raw:
            if isinstance(raw[key], str):
                known(key, raw[key])
            else:
                bad(key, f"'{key}' must be a type name")
    if "intermediate_types" in raw:
        v = raw["intermediate_types"]
        if isinstance(v, list) and all(isinstance(t, str) for t in v):
            for t in v:
                known("intermediate_types", t)
        else:
            bad("intermediate_types", "'intermediate_types' must be a list of type names")
    if "require_unit_test" in raw and not isinstance(raw["require_unit_test"], bool):
        bad("require_unit_test", "'require_unit_test' must be true or false")
    if "blocking" in raw:
        v = raw["blocking"]
        if not isinstance(v, list) or not all(isinstance(c, str) for c in v):
            bad("blocking", "'blocking' must be a list of finding names")
        else:
            unknown = [c for c in v if c not in FINDINGS]
            if unknown:
                bad("blocking", f"unknown finding(s) {', '.join(unknown)}; expected names "
                                f"from {', '.join(FINDINGS)}")
    return out


def _config(ruleset: dict | None) -> tuple[dict, list[str]]:
    raw = (ruleset or {}).get("observed_trace")
    if raw is None:
        return dict(DEFAULTS), ["no observed_trace entry in the ruleset; the defaults apply"]
    errors = config_errors(raw)
    if errors:
        raise TraceError("observed_trace in the ruleset: "
                         + "; ".join(f"{where}: {detail}" for _, where, detail in errors))
    return {**DEFAULTS, **{k: v for k, v in raw.items() if not k.startswith("_")}}, []


def _ranges(lines: list[int]) -> str:
    runs: list[list[int]] = []
    for n in lines:
        if runs and n == runs[-1][1] + 1:
            runs[-1][1] = n
        else:
            runs.append([n, n])
    text = ", ".join(f"{a}" if a == b else f"{a}-{b}" for a, b in runs)
    return ("line " if len(lines) == 1 else "lines ") + text


# --- the comparison ------------------------------------------------------------------------

def trace_compare(
    observed: dict,
    paths: Iterable[Path],
    graph_dir: Path,
    root: Path | None = None,
    ruleset: dict | None = None,
    ignore: Iterable[str] = IGNORE,
) -> TraceResult:
    """Compare observed per-test coverage with the graph and the fences under ``paths``.

    Stale data (a file whose content differs from the run's) returns with only ``stale``
    set: line numbers on changed files attribute nothing reliably. Raises TraceError when
    the data or the configuration is malformed.
    """
    _validate(observed)
    root = Path(root if root is not None else Path.cwd()).resolve()
    cfg, notes = _config(ruleset)
    res = TraceResult(notes=notes, implementation_type=cfg["implementation_type"])

    for file, digest in sorted(observed["files"].items()):
        try:
            same = content_hash((root / _norm(file)).read_bytes()) == digest
        except OSError:
            same = False
        if not same:
            res.stale.append(_norm(file))

    req, impl, ver = (cfg["requirement_type"], cfg["implementation_type"],
                      cfg["verification_type"])
    mid = set(cfg["intermediate_types"])

    def typ(i: str) -> str:
        return i.split("-")[0]

    items = parse_all(Path(graph_dir))
    known = {i.id for i in items}
    G, _ = build_graph(items)

    def reach(start: str) -> set[str]:
        """The requirements a path of links leads to through intermediate types only."""
        out, seen, todo = set(), {start}, [start]
        while todo:
            for t in G.successors(todo.pop()):
                if t in seen or t not in known:
                    continue
                seen.add(t)
                if typ(t) == req:
                    out.add(t)
                elif typ(t) in mid:
                    todo.append(t)
        return out

    realises = {i: reach(i) for i in sorted(known) if typ(i) == impl}
    verifies = {i: reach(i) for i in sorted(known) if typ(i) == ver}
    deps = {i: sorted(t for t in G.successors(i) if typ(t) == impl and t in known)
            for i in realises}
    realisers = {r: sorted(i for i, rs in realises.items() if r in rs)
                 for r in sorted(known) if typ(r) == req}

    def linked(a: str, b: str) -> bool:
        return G.has_edge(a, b) or G.has_edge(b, a)

    # Fences: what each one is, and which fence owns each line (the innermost).
    rep = fence_report(paths, Path(graph_dir), root=root, ignore=ignore)

    # A declared scope says every matching file is in the data: a fenced one that is not
    # was added since the run.
    scope = [_glob(g) for g in observed.get("scope") or ()]
    seen = {_norm(f) for f in observed["executable"]}
    res.stale += sorted({f.file for f in rep.fences if f.file not in seen
                         and any(g.match(f.file) for g in scope)})
    if res.stale:
        res.stale.sort()
        return res
    found: list[TraceFinding] = [
        TraceFinding(f.category, f"{f.file}:{f.line}", f.detail) for f in rep.findings]
    fences = rep.fences
    kinds: list[str] = []
    impl_of: list[tuple[str, ...]] = []
    ver_of: list[tuple[str, ...]] = []
    ignored: set[str] = set()
    for f in fences:
        im = tuple(i for i in f.ids if typ(i) == impl)
        ve = tuple(i for i in f.ids if typ(i) == ver)
        ignored.update(i for i in f.ids if typ(i) not in (impl, ver))
        if f.role == UNKNOWN:
            kind = "other"
        elif im and ve:
            kind = "mixed"
            found.append(TraceFinding(
                "mixed_role_fence", f"{f.file}:{f.begin}",
                f"names both {', '.join(im)} and {', '.join(ve)}; a fence wraps a test of "
                f"an {impl} or a {ver}, not both", im + ve))
        elif ve:
            kind = "system"
        elif im:
            kind = "unit" if f.role == TEST else "realisation"
        else:
            kind = "other"
        kinds.append(kind)
        impl_of.append(im)
        ver_of.append(ve)
    if ignored:
        res.notes.append(f"ids of other types in fences are ignored: {', '.join(sorted(ignored))}")

    owner: dict[str, dict[int, int]] = {}
    for k in sorted(range(len(fences)), key=lambda k: fences[k].begin):
        span = owner.setdefault(fences[k].file, {})
        for n in range(fences[k].begin, fences[k].end + 1):
            span[n] = k

    def realised_at(file: str, n: int) -> tuple[str, ...]:
        k = owner.get(file, {}).get(n)
        return impl_of[k] if k is not None and kinds[k] == "realisation" else ()

    imp = {_norm(f): set(ls) for f, ls in (observed.get("outside_tests") or {}).items()}
    measured: dict[str, set[tuple[str, int]]] = {}
    for file, lines in observed["executable"].items():
        file = _norm(file)
        for n in set(lines) - imp.get(file, set()):
            for sc in realised_at(file, n):
                measured.setdefault(sc, set()).add((file, n))
    realised = sorted({i for k, f in enumerate(fences) if kinds[k] == "realisation"
                       for i in impl_of[k]})
    unmeasured = [sc for sc in realised if sc not in measured]
    if unmeasured:
        res.notes.append(f"not measured (no executable line in the observed data): "
                         f"{', '.join(unmeasured)}")
    if not scope:
        res.notes.append("the observed data declares no scope, so a fenced file added since "
                         "the run cannot be told from one the tool does not measure")
    candidates = seen | {f.file for f in fences}
    for glob, rx in zip(observed.get("scope") or (), scope):
        if not any(rx.match(f) for f in candidates):
            res.notes.append(f"scope glob '{glob}' matches no file; a mistyped glob never "
                             "reports a file as stale")

    funcs = observed.get("functions")
    fallback: set[str] = set()

    def unit_of(file: str, n: int) -> tuple:
        spans = (funcs or {}).get(file)
        if spans is None:
            fallback.add(file)
            return (file, None)
        best = None
        for b, e, _name in spans:
            if b <= n <= e and (best is None or b > best):
                best = b
        return (file, best)

    # Tests: classified by the innermost fence around their location.
    test_files = {f.file for k, f in enumerate(fences) if f.role == TEST or ver_of[k]}
    executed: dict[str, dict[str, set[tuple[str, int]]]] = {}
    ran_lines: dict[str, set[tuple[str, int]]] = {}
    for t in observed["tests"]:
        file = _norm(t["file"])
        test_files.add(file)
        k = owner.get(file, {}).get(t["line"]) if t["line"] is not None else None
        kind = kinds[k] if k is not None else None
        if kind == "unit":
            tt = TracedTest(t["name"], "unit", impl_of[k], t["outcome"])
        elif kind == "system":
            tt = TracedTest(t["name"], "system", ver_of[k], t["outcome"])
        else:
            tt = TracedTest(t["name"], "untraced", (), t["outcome"])
            found.append(TraceFinding(
                "untraced_test", t["name"],
                f"not inside a test fence naming an {impl}, or a fence naming a {ver}"))
        res.tests.append(tt)
        if t["outcome"] != "passed":
            continue
        lines = {(_norm(f), n) for f, ls in t["executed"].items() for n in ls
                 if n not in imp.get(_norm(f), set())}
        ran_lines[tt.name] = lines
        per_sc: dict[str, set[tuple[str, int]]] = {}
        for f, n in lines:
            for sc in realised_at(f, n):
                if (f, n) in measured.get(sc, ()):
                    per_sc.setdefault(sc, set()).add((f, n))
        executed[tt.name] = per_sc

    passing = [t for t in res.tests if t.outcome == "passed"]
    ran_by: dict[str, list[str]] = {}
    for t in passing:
        for sc in executed[t.name]:
            ran_by.setdefault(sc, []).append(t.name)

    def frs_of(t: TracedTest) -> set[str]:
        source = realises if t.kind == "unit" else verifies
        return set().union(*(source.get(i, set()) for i in t.ids))

    def related(t: TracedTest, sc: str) -> bool:
        if t.kind == "unit":
            return (sc in t.ids or any(sc in deps.get(x, ()) for x in t.ids)
                    or bool(frs_of(t) & realises.get(sc, set())))
        return t.kind == "system" and bool(frs_of(t) & realises.get(sc, set()))

    # Per test: did it reach its target, and did a unit test stay inside its unit?
    pairs: dict[tuple[str, str], set[str]] = {}
    for t in passing:
        ran = executed[t.name]
        if t.kind == "unit":
            for x in t.ids:
                if x in measured and x not in ran:
                    others = [n for n in ran_by.get(x, ()) if n != t.name]
                    found.append(TraceFinding(
                        "test_misses_target", t.name,
                        f"unit test of {x} did not execute it"
                        + (f"; it ran {', '.join(sorted(ran))}" if ran else "")
                        + (f"; the suite does run it, via {', '.join(others)}"
                           if others else ""), (x,)))
            mine = set(t.ids)
            allowed = mine | {d for x in mine for d in deps.get(x, ())}
            units = {unit_of(f, n) for x in mine for f, n in measured.get(x, ())}
            outside = sorted(y for y, ls in ran.items() if y not in allowed
                             and any(unit_of(f, n) not in units for f, n in ls))
            if outside:
                found.append(TraceFinding(
                    "not_a_unit_test", t.name,
                    f"unit test of {', '.join(sorted(mine))} also executed "
                    f"{', '.join(outside)} outside its unit", tuple(outside)))
            for y in outside:
                # Reached through a dependency another reached SC declares: explained.
                if any(y in deps.get(z, ()) for z in ran if z != y and z not in mine):
                    continue
                for x in sorted(mine):
                    if not linked(x, y):
                        pairs.setdefault(tuple(sorted((x, y))), set()).add(t.name)
        elif t.kind == "system":
            targets = {sc for r in frs_of(t) for sc in realisers.get(r, ()) if sc in measured}
            if targets and not targets & set(ran):
                found.append(TraceFinding(
                    "test_misses_target", t.name,
                    f"system test of {', '.join(t.ids)} executed none of "
                    f"{', '.join(sorted(targets))}", tuple(sorted(targets))))
    for (a, b), names in sorted(pairs.items()):
        found.append(TraceFinding(
            "undeclared_coupling", f"{a} ~ {b}",
            f"executed together by {', '.join(sorted(names))}; the graph has no link "
            "between them", (a, b)))
    if fallback:
        res.notes.append(f"no function spans for {', '.join(sorted(fallback))}; unit "
                         "purity compared by file there")

    # Per requirement: do its system tests together reach every realisation?
    reached: dict[str, set[str]] = {}
    for t in passing:
        if t.kind == "system":
            for r in frs_of(t):
                reached.setdefault(r, set()).update(executed[t.name])
    for r in sorted(reached):
        missing = [sc for sc in realisers.get(r, ()) if sc in measured and sc not in reached[r]]
        if missing:
            found.append(TraceFinding(
                "partial_system_test", r,
                f"its system tests together did not reach {', '.join(missing)}",
                tuple(missing)))

    # Per SC: coverage figures and what they say.
    for sc in sorted(measured):
        suite, rel, own = set(), set(), set()
        by = [t for t in passing if sc in executed[t.name]]
        for t in by:
            lines = executed[t.name][sc]
            suite |= lines
            if related(t, sc):
                rel |= lines
            if t.kind == "unit" and sc in t.ids:
                own |= lines
        units = [t.name for t in passing if t.kind == "unit" and sc in t.ids]
        res.coverage[sc] = Coverage(len(measured[sc]), len(suite), len(rel), len(own),
                                    len(units))
        names = ", ".join(t.name for t in by)
        if not by:
            found.append(TraceFinding("unexecuted_realisation", sc,
                                      "no passing test executed it", (sc,)))
        elif not any(related(t, sc) for t in by):
            found.append(TraceFinding(
                "coincidental_coverage", sc,
                f"executed only by tests unrelated to its {req}s: {names}", (sc,)))
    if cfg["require_unit_test"]:
        tested = {i for t in res.tests if t.kind == "unit" for i in t.ids}
        for sc in realised:
            if sc not in tested:
                found.append(TraceFinding("no_unit_test", sc, "no unit test names it", (sc,)))

    # Executed lines no fence justifies, outside test code. A file with no fence at all is
    # only noted: `fences` reports it as unfenced, and a test helper looks just the same.
    code_files = {f.file for k, f in enumerate(fences) if kinds[k] == "realisation"}
    bare = []
    for file in sorted({f for ls in ran_lines.values() for f, _ in ls} - test_files):
        if file not in owner:
            bare.append(file)
            continue
        if file not in code_files:
            continue
        lines = sorted({n for ls in ran_lines.values() for f, n in ls
                        if f == file and n not in owner[file]})
        if lines:
            found.append(TraceFinding("unjustified_code", file, _ranges(lines)))
    if bare:
        res.notes.append(f"executed files with no fence: {', '.join(bare)}")

    blocking = set(cfg["blocking"]) | set(INTEGRITY)
    order = {c: k for k, c in enumerate(INTEGRITY + FINDINGS)}
    res.findings = sorted(
        (replace(f, blocking=f.category in blocking) for f in found),
        key=lambda f: (not f.blocking, order.get(f.category, len(order)), f.subject))

    res.matrix = {
        "contract": FORMAT,
        "requirements": {r: {"realised_by": scs,
                             "verified_by": sorted(v for v, rs in verifies.items() if r in rs)}
                         for r, scs in realisers.items()},
        "components": {sc: {"realises": sorted(rs), "depends_on": deps[sc],
                            "related_verifications": sorted(
                                v for v, vr in verifies.items() if vr & rs)}
                       for sc, rs in realises.items()},
        "verifications": {v: {"verifies": sorted(rs),
                              "targets": sorted({sc for r in rs for sc in realisers.get(r, ())})}
                          for v, rs in verifies.items()},
        "fences": [{"ids": list(f.ids), "role": f.role, "file": f.file, "begin": f.begin,
                    "end": f.end} for f in fences],
        "files": {file: content_hash((root / file).read_bytes())
                  for file in sorted({f.file for f in fences})},
        "fence_findings": [asdict(f) for f in rep.findings],
    }
    return res
# reqlite:end SC-012
