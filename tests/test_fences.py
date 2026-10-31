"""Tests for `reqlite fences`. One test per oracle in ORACLES-FENCES.md.

Fixture files are written to tmp_path from single-line strings, never as fence lines in this
source: an indented marker here would be a real fence to a scan of the repository.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reqlite.cli import app
from reqlite.fences import IGNORE, fence_report, scan

runner = CliRunner()

B = "reqlite:begin"
E = "reqlite:end"


def _write(root: Path, rel: str, *lines: str, newline: str = "\n", bom: bool = False) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    data = newline.join(lines) + newline
    p.write_bytes((b"\xef\xbb\xbf" if bom else b"") + data.encode("utf-8"))
    return p


def _item(graph: Path, item_id: str) -> None:
    graph.mkdir(exist_ok=True)
    (graph / f"{item_id}-x.md").write_text(f"# {item_id}: x\n\nBody.\n", encoding="utf-8")


def _cats(result) -> list[str]:
    return [f.category for f in result.findings]


def test_oracle_1_fences_are_found_in_any_language(tmp_path):
    cases = {
        "a.py": (f"# {B} SC-001", "x = 1", f"# {E} SC-001"),
        "b.c": (f"// {B} SC-001", "int x;", f"/* {E} SC-001 */"),
        "c.m": (f"% {B} SC-001", "x = 1;", f"% {E} SC-001"),
        "d.ps1": (f"  # {B} SC-001", "$x = 1", f"  # {E} SC-001"),
        "e.yml": (f"# {B} SC-001", "x: 1", f"# {E} SC-001"),
        "f.md": (f"<!-- {B} SC-001 -->", "Text.", f"<!-- {E} SC-001 -->"),
        "g.sql": (f"-- {B} SC-001", "select 1;", f"-- {E} SC-001"),
        "h.bat": (f":: {B} SC-001", "echo x", f"REM {E} SC-001"),
        "i.ini": (f"; {B} SC-001", "x=1", f"; {E} SC-001"),
        "j.vb": (f"' {B} SC-001", "Dim x", f"' {E} SC-001"),
        "k.txt": (f"{B} SC-001", "The text.", f"{E} SC-001"),
        "l.cmd": (f"rem {B} SC-001", "echo x", f"rem {E} SC-001"),
    }
    for rel, lines in cases.items():
        _write(tmp_path, rel, *lines)
    result = scan([tmp_path], root=tmp_path)
    assert result.findings == []
    assert sorted(f.file for f in result.fences) == sorted(cases)
    assert all(f.ids == ("SC-001",) for f in result.fences)


def test_oracle_2_comma_list_and_nesting(tmp_path):
    _write(tmp_path, "a.py",
           f"# {B} SC-001, FR-002", "a = 1", f"# {B} SC-003", "b = 2", f"# {E} SC-003",
           f"# {E} SC-001")
    result = scan([tmp_path], root=tmp_path)
    assert result.findings == []
    outer, inner = sorted(result.fences, key=lambda f: f.begin)
    assert (outer.ids, outer.begin, outer.end) == (("SC-001", "FR-002"), 1, 6)
    assert (inner.ids, inner.begin, inner.end) == (("SC-003",), 3, 5)


def test_oracle_3_fence_id_order_and_first_line(tmp_path):
    _write(tmp_path, "sub/a.py",
           f"# {B} SC-001", "", "first = 1", f"# {E} SC-001",
           f"# {B} SC-002", "second = 2", f"# {E} SC-002")
    result = scan([tmp_path], root=tmp_path)
    by_id = {f.id: f for f in result.fences}
    assert set(by_id) == {"FENCE-sub/a.py#1", "FENCE-sub/a.py#2"}
    assert by_id["FENCE-sub/a.py#1"].first_line == "first = 1"
    assert by_id["FENCE-sub/a.py#2"].first_line == "second = 2"
    assert set(tmp_path.rglob("*")) == {tmp_path / "sub", tmp_path / "sub" / "a.py"}


def test_oracle_4_end_must_match_innermost_begin(tmp_path):
    _write(tmp_path, "a.py", f"# {B} SC-001", "x = 1", f"# {E} SC-002")
    result = scan([tmp_path], root=tmp_path)
    assert [(f.category, f.line) for f in result.findings] == [("mismatched_fence", 3)]


def test_oracle_4_overlap_is_one_finding_and_two_spans(tmp_path):
    _write(tmp_path, "b.py",
           f"# {B} SC-001", f"# {B} SC-002", "x = 1", f"# {E} SC-001", f"# {E} SC-002")
    result = scan([tmp_path], root=tmp_path)
    assert [(f.category, f.line) for f in result.findings] == [("mismatched_fence", 4)]
    assert "overlaps SC-002" in result.findings[0].detail
    spans = sorted((f.ids, f.begin, f.end) for f in result.fences)
    assert spans == [(("SC-001",), 1, 4), (("SC-002",), 2, 5)]


def test_oracle_4_end_takes_exactly_one_id(tmp_path):
    _write(tmp_path, "c.py", f"# {B} SC-001, SC-002", "x = 1", f"# {E} SC-001, SC-999")
    result = scan([tmp_path], root=tmp_path)
    assert [(f.category, f.line) for f in result.findings] == [("mismatched_fence", 3)]
    assert "one id" in result.findings[0].detail
    assert [f.ids for f in result.fences] == [("SC-001", "SC-002")]


def test_oracle_5_unclosed_fence(tmp_path):
    _write(tmp_path, "a.py", "x = 1", f"# {B} SC-001", "y = 2")
    result = scan([tmp_path], root=tmp_path)
    assert [(f.category, f.file, f.line) for f in result.findings] == [
        ("unclosed_fence", "a.py", 2)]
    assert result.fences == []


def test_oracle_6_unopened_fence(tmp_path):
    _write(tmp_path, "a.py", "x = 1", f"# {E} SC-001")
    result = scan([tmp_path], root=tmp_path)
    assert [(f.category, f.line) for f in result.findings] == [("unopened_fence", 2)]


def test_oracle_7_dangling_reference(tmp_path):
    graph = tmp_path / "graph"
    _item(graph, "SC-001")
    _write(tmp_path, "src/a.py", f"# {B} SC-001, SC-099", "x = 1", f"# {E} SC-001")
    rep = fence_report([tmp_path / "src"], graph, root=tmp_path)
    dangling = [f for f in rep.findings if f.category == "dangling_fence_ref"]
    assert len(dangling) == 1
    assert (dangling[0].file, dangling[0].line) == ("src/a.py", 1)
    assert "SC-099" in dangling[0].detail and "SC-001" not in dangling[0].detail


def test_oracle_7_unclosed_begin_ids_are_checked_too(tmp_path):
    graph = tmp_path / "graph"
    _item(graph, "SC-001")
    _write(tmp_path, "src/a.py", f"# {B} SC-999", "x = 1")
    rep = fence_report([tmp_path / "src"], graph, root=tmp_path)
    assert sorted(f.category for f in rep.findings) == ["dangling_fence_ref", "unclosed_fence"]


def test_oracle_8_unrealised_only_for_expected_types(tmp_path):
    graph = tmp_path / "graph"
    for i in ("SC-001", "SC-002", "TC-001"):
        _item(graph, i)
    _write(tmp_path, "src/a.py", f"# {B} SC-001", "x = 1", f"# {E} SC-001")
    assert fence_report([tmp_path / "src"], graph, expect=["SC"],
                        root=tmp_path).unrealised == ["SC-002"]
    assert fence_report([tmp_path / "src"], graph, root=tmp_path).unrealised is None


def test_oracle_8_an_expected_type_with_no_items_is_reported(tmp_path, monkeypatch):
    graph = tmp_path / "graph"
    _item(graph, "SC-001")
    _write(tmp_path, "src/a.py", "x = 1")
    rep = fence_report([tmp_path / "src"], graph, expect=["Sc", "SC"], root=tmp_path)
    assert rep.unknown_types == ["Sc"]
    assert rep.unrealised == ["SC-001"]
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["fences", "src", "--expect", "Sc"])
    assert "Sc matches no item" in result.output
    assert "Unrealised (Sc): none" in result.output
    # --json warns on stderr too, so a CI log shows it; stdout stays pure JSON
    as_json = runner.invoke(app, ["fences", "src", "--expect", "Sc", "--json"])
    assert json.loads(as_json.stdout)["unknown_types"] == ["Sc"]
    assert "Sc matches no item" in as_json.stderr


def test_oracle_9_marker_matched_wherever_it_starts_a_line(tmp_path):
    _write(tmp_path, "doc.md", "Example:", "", "```python", f"# {B} SC-001", "```")
    _write(tmp_path, "s.py", 'X = """', f"    {B} SC-002", '"""')
    _write(tmp_path, "n.py",
           f"x = 1  # {B} SC-003", f"# {B} <ID>", f"# {B} sc-004", f"## {B} SC-005")
    result = scan([tmp_path], root=tmp_path)
    assert sorted((f.file, f.category) for f in result.findings) == [
        ("doc.md", "unclosed_fence"), ("s.py", "unclosed_fence")]


def test_oracle_10_binaries_ignored_dirs_and_graph_are_skipped(tmp_path):
    fence = (f"# {B} SC-001", "x = 1")  # unclosed: reported if ever scanned
    (tmp_path / "bin.dat").write_bytes(b"\x00\x01" + f"# {B} SC-001\n".encode())
    for d in (".git", "node_modules", "deep/.venv", "build", "dist", "a/__pycache__",
              "pkg.egg-info", "vendor"):
        _write(tmp_path, f"{d}/f.py", *fence)
    graph = tmp_path / "graph"
    _item(graph, "SC-001")
    _write(tmp_path, "ok.py", f"# {B} SC-001", "x = 1", f"# {E} SC-001")
    _write(tmp_path, "tools/build", "echo build")  # a file named like an ignored directory
    rep = fence_report([tmp_path], graph, root=tmp_path, ignore=IGNORE + ("vendor",))
    assert rep.findings == []
    assert rep.unfenced_files == ["tools/build"]
    assert [f.file for f in rep.fences] == ["ok.py"]


def test_oracle_10_ignore_option_extends_the_defaults(tmp_path, monkeypatch):
    _item(tmp_path / "graph", "SC-001")
    _write(tmp_path, "vendor/f.py", f"# {B} SC-001")
    _write(tmp_path, "build/f.py", f"# {B} SC-001")
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["fences", "."]).exit_code == 4
    assert runner.invoke(app, ["fences", ".", "--ignore", "vendor"]).exit_code == 0
    # a path named explicitly wins over a pattern that matches it
    assert runner.invoke(app, ["fences", "vendor", "--ignore", "vendor"]).exit_code == 4


def test_oracle_11_bom_and_crlf(tmp_path):
    _write(tmp_path, "bom.py", f"# {B} SC-001", "x = 1", f"# {E} SC-001", bom=True)
    _write(tmp_path, "crlf.py", "y = 0", f"# {B} SC-002", "x = 1", f"# {E} SC-002",
           newline="\r\n")
    result = scan([tmp_path], root=tmp_path)
    assert result.findings == []
    spans = {f.file: (f.begin, f.end, f.first_line) for f in result.fences}
    assert spans == {"bom.py": (1, 3, "x = 1"), "crlf.py": (2, 4, "x = 1")}


def test_oracle_12_coverage_per_file_and_per_gap(tmp_path):
    _write(tmp_path, "bare.py", "x = 1")
    _write(tmp_path, "blank.py", "", "   ")
    _write(tmp_path, "part.py",
           "import os", "",                                   # 1-2: gap 1-1
           f"# {B} SC-001", "a = 1", f"# {E} SC-001",         # 3-5
           "", "  ",                                          # 6-7: blank only
           f"# {B} SC-002", "b = 2", f"# {E} SC-002",         # 8-10
           "", "tail = 1", "more = 2", "")                    # 11-14: gap 12-13
    result = scan([tmp_path], root=tmp_path)
    assert result.unfenced_files == ["bare.py"]
    assert result.gaps == {"part.py": [(1, 1), (12, 13)]}


def test_oracle_13_exit_code_gates_on_integrity_only(tmp_path, monkeypatch):
    graph = tmp_path / "graph"
    for i in ("SC-001", "SC-002"):
        _item(graph, i)
    _write(tmp_path, "src/a.py", "head = 0", f"# {B} SC-001", "x = 1", f"# {E} SC-001")
    _write(tmp_path, "src/b.py", "y = 1")
    monkeypatch.chdir(tmp_path)

    ok = runner.invoke(app, ["fences", "src", "--expect", "SC"])
    assert ok.exit_code == 0, ok.output
    assert "SC-002" in ok.output and "src/a.py:1" in ok.output
    assert "src/b.py" not in ok.output and "--unfenced-files" in ok.output
    files = runner.invoke(app, ["fences", "src", "--unfenced-files"])
    assert "src/b.py" in files.output

    listed = runner.invoke(app, ["fences", "src", "--list"])
    assert listed.exit_code == 0
    assert "FENCE-src/a.py#1" in listed.output

    data = json.loads(runner.invoke(app, ["fences", "src", "--json"]).output)
    assert data["fences"][0]["id"] == "FENCE-src/a.py#1"
    assert data["unfenced_files"] == ["src/b.py"]
    assert data["gaps"] == {"src/a.py": [[1, 1]]}
    assert data["findings"] == []
    assert "unrealised" not in data

    _write(tmp_path, "src/c.py", f"# {B} SC-009", "z = 1", f"# {E} SC-009")
    bad = runner.invoke(app, ["fences", "src", "--expect", "SC"])
    assert bad.exit_code == 4
    out = bad.output
    assert out.index("dangling_fence_ref") < out.index("Unrealised") < out.index("src/a.py:1")


def test_oracle_13_a_run_that_cannot_start_exits_1(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["fences", ".", "--graph-dir", "nope"])
    assert result.exit_code == 1
    assert "nope" in result.output
    _item(tmp_path / "graph", "SC-001")
    result = runner.invoke(app, ["fences", "srcc"])
    assert result.exit_code == 1
    assert "srcc" in result.output


def test_oracle_15_an_unreadable_file_is_a_warning(tmp_path, monkeypatch):
    _write(tmp_path, "ok.py", f"# {B} SC-001", "x = 1", f"# {E} SC-001")
    _write(tmp_path, "locked.py", "x = 1")
    real = Path.read_bytes

    def read_bytes(self):
        if self.name == "locked.py":
            raise PermissionError(13, "Permission denied", str(self))
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    result = scan([tmp_path], root=tmp_path)
    assert result.unreadable == ["locked.py"]
    assert [f.file for f in result.fences] == ["ok.py"]
    assert "locked.py" not in result.unfenced_files
    monkeypatch.chdir(tmp_path)
    _item(tmp_path / "graph", "SC-001")
    cli = runner.invoke(app, ["fences", "."])
    assert cli.exit_code == 0 and "locked.py" in cli.output


@pytest.mark.parametrize("command", ["impl-scan", "impl-list"])
def test_oracle_14_ast_scanner_is_gone(command):
    assert runner.invoke(app, [command]).exit_code != 0


def test_this_package_is_fully_fenced():
    """Structural only; the ids it names are checked against the graph in tests/private."""
    pkg = Path(__file__).resolve().parents[1] / "src" / "reqlite"
    result = scan(sorted(pkg.glob("*.py")), root=pkg)
    assert result.findings == []
    assert result.unfenced_files == []
    assert result.gaps == {}


def test_oracle_16_a_test_fence_realises_nothing(tmp_path, monkeypatch):
    graph = tmp_path / "graph"
    for i in ("SC-001", "SC-002", "SC-003"):
        _item(graph, i)
    _write(tmp_path, "src/a.py", f"# {B} SC-001", "x = 1", f"# {E} SC-001")
    _write(tmp_path, "tests/t.py", f"# {B} SC-002 test", "def test_a(): pass", f"# {E} SC-002",
           f"# {B} SC-001, SC-003 test", "def test_b(): pass", f"# {E} SC-001")
    rep = fence_report([tmp_path], graph, expect=["SC"], root=tmp_path)
    assert rep.findings == []
    assert {(f.file, f.ids, f.role) for f in rep.fences} == {
        ("src/a.py", ("SC-001",), ""),
        ("tests/t.py", ("SC-002",), "test"),
        ("tests/t.py", ("SC-001", "SC-003"), "test")}
    assert rep.unrealised == ["SC-002", "SC-003"]
    assert "tests/t.py" not in rep.gaps

    monkeypatch.chdir(tmp_path)
    listed = runner.invoke(app, ["fences", "--list"]).output
    assert "SC-002  (test)" in listed
    data = json.loads(runner.invoke(app, ["fences", "--json"]).output)
    assert {f["role"] for f in data["fences"]} == {"", "test"}


@pytest.mark.parametrize("line", [
    f"# {B} SC-001 tset", f"# {B} SC-001 converter", f"# {B} SC-001,",
    f"# {B} SC-001 test extra"])
def test_oracle_17_unknown_text_after_the_ids_is_a_finding(tmp_path, monkeypatch, line):
    graph = tmp_path / "graph"
    _item(graph, "SC-001")
    _write(tmp_path, "a.py", line, "x = 1", f"# {E} SC-001")
    rep = fence_report([tmp_path / "a.py"], graph, expect=["SC"], root=tmp_path)
    assert [(f.category, f.line) for f in rep.findings] == [("unknown_fence_role", 1)]
    assert len(rep.fences) == 1                       # the end still pairs
    assert rep.unrealised == ["SC-001"]               # and an unknown role realises nothing
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["fences", "a.py"]).exit_code == 4


def test_oracle_17_a_role_on_an_end_is_a_finding(tmp_path):
    _write(tmp_path, "a.py", f"# {B} SC-001 test", "x = 1", f"# {E} SC-001 test")
    s = scan([tmp_path], root=tmp_path)
    assert [(f.category, f.line) for f in s.findings] == [("unknown_fence_role", 3)]
    assert [f.role for f in s.fences] == ["test"]


def test_oracle_17_comment_closers_are_clean(tmp_path):
    _write(tmp_path, "a.md", f"<!-- {B} SC-001 test -->", "Text.", f"<!--{E} SC-001-->")
    _write(tmp_path, "b.c", f"/* {B} SC-001, SC-002 */", "int x;", f"/* {E} SC-001 */  ")
    _write(tmp_path, "c.py", f"#	{B}	SC-001	test", "x = 1", f"# {E} SC-001")
    s = scan([tmp_path], root=tmp_path)
    assert s.findings == []
    assert sorted((f.file, f.role) for f in s.fences) == [
        ("a.md", "test"), ("b.c", ""), ("c.py", "test")]


def test_oracle_10_nested_projects_are_skipped(tmp_path):
    graph = tmp_path / "graph"
    _item(graph, "SC-001")
    _write(tmp_path, "src/a.py", f"# {B} SC-001", "x = 1", f"# {E} SC-001")
    nested = tmp_path / "examples" / "toy"
    _write(nested, "ruleset/ruleset.json", "{}")
    _item(nested / "graph", "SC-777")
    _write(nested, "src/b.py", f"# {B} SC-777", "y = 2", f"# {E} SC-777")
    _write(tmp_path, "half/graph/README.md", "No ruleset beside it: not a project.")
    _write(tmp_path, "half/c.py", f"# {B} SC-001", "z = 3", f"# {E} SC-001")
    rep = fence_report([tmp_path], graph, root=tmp_path)
    assert rep.findings == []
    assert sorted(f.file for f in rep.fences) == ["half/c.py", "src/a.py"]
    assert "examples/toy/src/b.py" not in rep.unfenced_files
    named = fence_report([nested], nested / "graph", root=tmp_path)
    assert [f.file for f in named.fences] == ["examples/toy/src/b.py"]
