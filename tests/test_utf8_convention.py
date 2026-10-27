"""Every file read/write in the package must declare encoding="utf-8".

`agent/conventions.md` mandates UTF-8 for all text in the repo. Python's
`Path.read_text()` and `open()` honour the *platform* default when no encoding is
given — UTF-8 on Linux, cp1252 on a Western Windows install — so an omitted
encoding is a bug that passes on CI and fails on the operator's machine. That is
exactly how it reached main: 11 `test_impl_scan.py` failures invisible to a Linux
runner.

This test is the platform-independent guard those tests cannot be. It reads the
source rather than exercising behaviour, because reproducing a cp1252 default on a
UTF-8 host is more fragile than asserting the call is written correctly.
"""

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "src" / "reqlite"

# Text IO that silently depends on the platform default encoding when it is omitted.
TEXT_IO_METHODS = {"read_text", "write_text"}
TEXT_IO_CALLABLES = {"open"}


def _encoding_violations(tree: ast.AST) -> list[tuple[int, str]]:
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue

        if isinstance(node.func, ast.Attribute) and node.func.attr in TEXT_IO_METHODS:
            name = node.func.attr
        elif isinstance(node.func, ast.Name) and node.func.id in TEXT_IO_CALLABLES:
            name = node.func.id
            # open(..., "rb") is binary; an encoding would be a TypeError.
            if any(
                isinstance(a, ast.Constant) and isinstance(a.value, str) and "b" in a.value
                for a in node.args[1:]
            ):
                continue
        else:
            continue

        if not any(kw.arg == "encoding" for kw in node.keywords):
            found.append((node.lineno, name))
    return found


def test_package_declares_utf8_on_every_text_io():
    violations = []
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        violations.extend(
            f"{path.relative_to(PACKAGE)}:{lineno} {call}() without encoding="
            for lineno, call in _encoding_violations(tree)
        )

    assert not violations, (
        "Text IO without an explicit encoding depends on the platform default "
        "(UTF-8 on Linux, cp1252 on Windows), so it passes CI and fails locally. "
        'Add encoding="utf-8":\n  ' + "\n  ".join(violations)
    )


def test_guard_detects_a_missing_encoding():
    """The guard must fail on bad code, or it is decoration."""
    bad = ast.parse("from pathlib import Path\nPath('x').read_text()\n")
    assert _encoding_violations(bad) == [(2, "read_text")]

    good = ast.parse("from pathlib import Path\nPath('x').read_text(encoding='utf-8')\n")
    assert _encoding_violations(good) == []

    binary = ast.parse("open('x', 'rb').read()\n")
    assert _encoding_violations(binary) == []
