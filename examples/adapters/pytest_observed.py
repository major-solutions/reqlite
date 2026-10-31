"""Write reqlite's observed data (format version 1) from a pytest run.

An adapter knows nothing about the graph: it reports which lines each test executed, and
`reqlite trace-compare` does the rest. Run from the project root:

    pytest --cov=src --cov-context=test --junitxml=junit.xml
    coverage json --show-contexts -o coverage.json
    python pytest_observed.py coverage.json junit.xml -o observed.json --scope "src/**/*.py"

Only the `|run` phase of a test counts as its execution, so fixtures do not make every
test look impure. Lines executed only outside any test's run phase (module import,
collection, fixture setup) are reported as `outside_tests` and kept out of the figures.
`--scope` declares what `--cov` measured: coverage.py lists every file under its source,
imported or not, so a fenced file matching the scope but missing from the data was added
after the run.
Needs pytest-cov; coverage.py comes with it. Write the file with `-o`: shell redirection
in Windows PowerShell 5.1 produces UTF-16, which reqlite refuses.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def content_hash(path: Path) -> str:
    # Line endings normalised, so a CRLF checkout of the same commit is not stale.
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def rel(path: str, root: Path) -> str:
    p = Path(path)
    p = p if p.is_absolute() else Path.cwd() / p
    try:
        return p.resolve().relative_to(root).as_posix()
    except ValueError:
        return p.resolve().as_posix()


def functions(path: Path) -> list[list]:
    """Every function's line span with its qualified name; the unit boundary."""
    out: list[list] = []

    def walk(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{child.name}"
                if not isinstance(child, ast.ClassDef):
                    out.append([child.lineno, child.end_lineno, name])
                walk(child, name + ".")
            else:
                walk(child, prefix)

    walk(ast.parse(path.read_text(encoding="utf-8")), "")
    return sorted(out)


def test_line(root: Path, file: str, chain: list[str]) -> int | None:
    """The `def` line of the test named by a node id's class/function chain."""
    try:
        tree = ast.parse((root / file).read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    node = tree
    for name in chain:
        node = next((c for c in ast.iter_child_nodes(node)
                     if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                     and c.name == name), None)
        if node is None:
            return None
    return node.lineno


def junit_tests(junit: Path, root: Path) -> list[tuple[str, str]]:
    """(node id, outcome) for every test case in a JUnit report."""
    out = []
    for case in ET.parse(junit).getroot().iter("testcase"):
        parts = case.get("classname", "").split(".")
        name = case.get("name", "")
        # classname is the module path plus any classes; find where the file ends.
        for k in range(len(parts), 0, -1):
            file = "/".join(parts[:k]) + ".py"
            if (root / file).is_file():
                nodeid = "::".join([file, *parts[k:], name])
                break
        else:
            continue
        if case.find("failure") is not None:
            outcome = "failed"
        elif case.find("error") is not None:
            outcome = "error"
        elif case.find("skipped") is not None:
            outcome = "skipped"
        else:
            outcome = "passed"
        out.append((nodeid, outcome))
    return out


def commit(root: Path) -> str | None:
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True,
                           text=True, check=True)
        return r.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def observed(coverage_json: Path, junit: Path, root: Path, scope: list[str]) -> dict:
    cov = json.loads(coverage_json.read_text(encoding="utf-8"))
    executable: dict[str, list[int]] = {}
    outside_tests: dict[str, list[int]] = {}
    executed: dict[str, dict[str, set[int]]] = {}   # node id -> file -> lines
    for path, data in cov["files"].items():
        f = rel(path, root)
        executable[f] = sorted(data["executed_lines"] + data["missing_lines"])
        only_outside = []
        for line, contexts in data.get("contexts", {}).items():
            runs = [c[:-4] for c in contexts if c.endswith("|run")]
            for nodeid in runs:
                executed.setdefault(nodeid, {}).setdefault(f, set()).add(int(line))
            if not runs:
                only_outside.append(int(line))
        if only_outside:
            outside_tests[f] = sorted(only_outside)

    tests = []
    for nodeid, outcome in junit_tests(junit, root):
        file, *chain = nodeid.split("::")
        chain[-1] = chain[-1].split("[")[0]          # parametrised: test_x[1] -> test_x
        tests.append({
            "name": nodeid, "file": file, "line": test_line(root, file, chain),
            "outcome": outcome,
            "executed": {k: sorted(v) for k, v in sorted(executed.get(nodeid, {}).items())},
        })

    files = sorted(set(executable) | {t["file"] for t in tests})
    data = {
        "contract": 1,
        "source": {"tool": "pytest-cov", "commit": commit(root), "metric": "line"},
        "files": {f: content_hash(root / f) for f in files if (root / f).is_file()},
        "executable": executable,
        "outside_tests": outside_tests,
        "functions": {f: functions(root / f) for f in executable
                      if f.endswith(".py") and (root / f).is_file()},
        "tests": tests,
    }
    if scope:
        data["scope"] = scope
    return data


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("coverage_json", type=Path, help="coverage json --show-contexts output")
    ap.add_argument("junit", type=Path, help="pytest --junitxml output")
    ap.add_argument("-o", "--output", type=Path, help="write here (UTF-8) instead of stdout")
    ap.add_argument("--root", type=Path, default=Path.cwd(), help="project root (default .)")
    ap.add_argument("--scope", action="append", default=[], metavar="GLOB",
                    help="files --cov measured, e.g. 'src/**/*.py' (repeatable)")
    args = ap.parse_args(argv)
    text = json.dumps(observed(args.coverage_json, args.junit, args.root.resolve(), args.scope), indent=1)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8", newline="\n")
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
