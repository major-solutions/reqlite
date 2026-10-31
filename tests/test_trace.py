"""Tests for `reqlite trace-compare`. One test per oracle in ORACLES-TRACE.md.

The fixture project (tests/fixtures/trace) carries real fences and an observed.json written
by the example adapter. Edge cases build their own project in tmp_path, from single-line
strings, so this source holds no fence lines.
"""

import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from reqlite.cli import app
from reqlite.trace import TraceError, content_hash, load_observed, trace_compare

runner = CliRunner()

ROOT = Path(__file__).resolve().parent.parent
FIX = Path(__file__).resolve().parent / "fixtures" / "trace"
B = "reqlite:begin"
E = "reqlite:end"


def _observed() -> dict:
    return json.loads((FIX / "observed.json").read_text(encoding="utf-8"))


def _fixture(observed: dict | None = None, ruleset: dict | None = None):
    return trace_compare(observed or _observed(), [FIX], FIX / "graph", root=FIX,
                         ruleset=ruleset)


def _subjects(res, category: str) -> list[str]:
    return sorted(f.subject for f in res.findings if f.category == category)


def _ids(res, category: str) -> dict[str, tuple]:
    return {f.subject: f.ids for f in res.findings if f.category == category}


# --- a small project in tmp_path -------------------------------------------------------

def _project(root: Path, items: dict[str, list[str]], files: dict[str, list[str]]) -> None:
    graph = root / "graph"
    graph.mkdir(parents=True)
    for i, links in items.items():
        body = " ".join(f"[{t}]({t}-x.md)" for t in links) or "Root."
        (graph / f"{i}-x.md").write_text(f"# {i}: x\n\n{body}\n", encoding="utf-8")
    for rel, lines in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def _obs(root: Path, executable: dict, tests: list[dict], **extra) -> dict:
    files = sorted(set(executable) | {t["file"] for t in tests})
    return {"contract": 1, "source": {"tool": "hand", "commit": None, "metric": "line"},
            "files": {f: content_hash((root / f).read_bytes()) for f in files},
            "executable": executable, "tests": tests, **extra}


def _test(name, file, line, executed, outcome="passed"):
    return {"name": name, "file": file, "line": line, "outcome": outcome,
            "executed": executed}


# Two SCs of one FR, in separate functions, and one unit test of SC-001.
SMALL_ITEMS = {"FR-001": [], "SC-001": ["FR-001"], "SC-002": ["FR-001"], "TC-001": ["FR-001"]}
SMALL_SRC = [f"# {B} SC-001", "def a():", "    return b()", f"# {E} SC-001",
             f"# {B} SC-002", "def b():", "    return 1", f"# {E} SC-002"]


# --- oracle 1 -----------------------------------------------------------------------------

@pytest.mark.parametrize("mutate, needle", [
    (lambda d: d.pop("contract"), "contract"),
    (lambda d: d.update(contract=2), "format version 2"),
    (lambda d: d.pop("tests"), "tests"),
    (lambda d: d["tests"][0].pop("outcome"), "outcome"),
    (lambda d: d.update(executable=[1, 2]), "executable"),
])
def test_oracle_1_only_version_1_is_read(mutate, needle):
    data = _observed()
    mutate(data)
    with pytest.raises(TraceError, match=needle):
        _fixture(data)


def test_oracle_1_a_file_that_is_not_utf8_json_cannot_run(tmp_path, monkeypatch):
    with pytest.raises(TraceError, match="UTF-16"):
        load_observed(json.dumps(_observed()).encode("utf-16"))
    with pytest.raises(TraceError, match="not JSON"):
        load_observed(b"{nope")
    p = tmp_path / "observed.json"
    p.write_bytes(json.dumps(_observed()).encode("utf-16"))
    monkeypatch.chdir(FIX)
    result = runner.invoke(app, ["trace-compare", str(p)])
    assert result.exit_code == 1
    assert "UTF-16" in result.stderr


# --- oracle 2 -----------------------------------------------------------------------------

def test_oracle_2_a_changed_or_missing_file_is_stale(tmp_path, monkeypatch):
    proj = tmp_path / "p"
    shutil.copytree(FIX, proj)
    (proj / "src" / "app.py").write_text("x = 1\n", encoding="utf-8")
    (proj / "tests" / "test_app.py").unlink()
    res = trace_compare(_observed(), [proj], proj / "graph", root=proj)
    assert res.stale == ["src/app.py", "tests/test_app.py"]
    assert res.findings == [] and res.coverage == {}
    monkeypatch.chdir(proj)
    result = runner.invoke(app, ["trace-compare", "observed.json"])
    assert result.exit_code == 1
    assert "stale" in result.output and "src/app.py" in result.output


def test_oracle_2_a_fenced_file_in_scope_the_run_never_saw_is_stale(tmp_path):
    proj = tmp_path / "p"
    shutil.copytree(FIX, proj)
    fenced = [f"# {B} SC-001", "def extra():", "    return 1", f"# {E} SC-001"]
    (proj / "src" / "extra.py").write_text("\n".join(fenced) + "\n", encoding="utf-8")
    (proj / "src" / "pkg").mkdir()
    (proj / "src" / "pkg" / "deep.py").write_text("\n".join(fenced) + "\n", encoding="utf-8")
    (proj / "src" / "notes.md").write_text(
        f"<!-- {B} SC-001 -->\nProse.\n<!-- {E} SC-001 -->\n", encoding="utf-8")
    (proj / "lib.py").write_text("\n".join(fenced) + "\n", encoding="utf-8")
    obs = _observed()
    assert obs["scope"] == ["src/**/*.py"]
    res = trace_compare(obs, [proj], proj / "graph", root=proj)
    assert res.stale == ["src/extra.py", "src/pkg/deep.py"]     # not the .md, not lib.py

    del obs["scope"]
    res = trace_compare(obs, [proj], proj / "graph", root=proj)
    assert res.stale == []
    assert any("declares no scope" in n for n in res.notes)


def test_oracle_2_a_scope_glob_that_matches_nothing_is_a_note():
    obs = _observed()
    assert not any("matches no file" in n for n in _fixture(obs).notes)
    obs["scope"] = ["src/**/*.py", "scr/**/*.py"]
    notes = [n for n in _fixture(obs).notes if "matches no file" in n]
    assert len(notes) == 1 and "scr/**/*.py" in notes[0] and "src/**" not in notes[0]


def test_oracle_2_a_crlf_checkout_is_not_stale(tmp_path):
    proj = tmp_path / "p"
    shutil.copytree(FIX, proj)
    for rel in ("src/app.py", "tests/test_app.py"):
        p = proj / rel
        p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
    res = trace_compare(_observed(), [proj], proj / "graph", root=proj)
    assert res.stale == []
    assert _subjects(res, "untraced_test") == _subjects(_fixture(), "untraced_test")


# --- oracle 3 -----------------------------------------------------------------------------

def test_oracle_3_realisation_follows_links_through_intermediate_types_only():
    res = _fixture()
    sc = res.matrix["components"]
    assert sc["SC-001"]["realises"] == ["FR-001"]        # not FR-004 via SC-004, nor FR-003
    assert sc["SC-001"]["depends_on"] == ["SC-004"]
    assert sc["SC-005"]["realises"] == ["FR-005"]        # DD-002 -> SC-005 does not count
    assert sc["SC-002"]["realises"] == ["FR-002"]        # a direct link counts
    fr = res.matrix["requirements"]
    assert fr["FR-001"]["realised_by"] == ["SC-001", "SC-003"]
    assert fr["FR-003"]["realised_by"] == ["SC-006"]
    assert fr["FR-004"]["realised_by"] == ["SC-004", "SC-009", "SC-010"]
    assert res.matrix["verifications"]["TC-006"] == {
        "verifies": ["FR-004"], "targets": ["SC-004", "SC-009", "SC-010"]}
    assert _subjects(res, "partial_system_test") == ["FR-005"]


# --- oracle 4 -----------------------------------------------------------------------------

def test_oracle_4_tests_are_classified_by_their_innermost_fence():
    res = _fixture()
    kinds = {t.name.split("::")[-1]: (t.kind, t.ids) for t in res.tests}
    assert kinds["test_validate_accepts_numbers"] == ("unit", ("SC-002",))
    assert kinds["test_limits"] == ("system", ("TC-006",))
    assert kinds["test_untraced"] == ("untraced", ())
    assert _subjects(res, "untraced_test") == ["tests/test_app.py::test_untraced"]
    assert all(f.blocking for f in res.findings if f.category == "untraced_test")


def test_oracle_4_mixed_fences_and_other_ids(tmp_path):
    _project(tmp_path, {**SMALL_ITEMS, "DD-001": ["FR-001"]}, {
        "src/a.py": SMALL_SRC,
        "tests/t.py": [f"# {B} SC-001, TC-001 test", "def test_mixed(): pass", f"# {E} SC-001",
                       f"# {B} DD-001 test", "def test_other(): pass", f"# {E} DD-001",
                       f"# {B} SC-001", "def test_in_code(): pass", f"# {E} SC-001",
                       f"# {B} SC-002, DD-001 test", "def test_ok(): pass", f"# {E} SC-002"]})
    obs = _obs(tmp_path, {"src/a.py": [3, 7]}, [
        _test("t::test_mixed", "tests/t.py", 2, {}), _test("t::test_other", "tests/t.py", 5, {}),
        _test("t::test_in_code", "tests/t.py", 8, {}), _test("t::test_ok", "tests/t.py", 11, {})])
    res = trace_compare(obs, [tmp_path], tmp_path / "graph", root=tmp_path)
    assert _subjects(res, "mixed_role_fence") == ["tests/t.py:1"]
    assert _subjects(res, "untraced_test") == ["t::test_in_code", "t::test_mixed",
                                               "t::test_other"]
    assert {t.name: t.kind for t in res.tests}["t::test_ok"] == "unit"
    assert any("DD-001" in n for n in res.notes)


# --- oracles 5 and 6 ----------------------------------------------------------------------

def test_oracle_5_lines_belong_to_the_innermost_realisation_fence():
    res = _fixture()
    assert res.coverage["SC-006"].measured == 1          # the UNITS line runs outside tests
    assert res.coverage["SC-009"].measured == 2
    assert res.coverage["SC-010"].measured == 1


def test_oracle_5_unmeasured_sc_gets_no_finding(tmp_path):
    _project(tmp_path, SMALL_ITEMS, {
        "src/a.py": SMALL_SRC, "docs/b.md": [f"<!-- {B} SC-002 -->", "Prose.",
                                             f"<!-- {E} SC-002 -->"]})
    (tmp_path / "src" / "a.py").write_text("\n".join(SMALL_SRC[:4]) + "\n", encoding="utf-8")
    obs = _obs(tmp_path, {"src/a.py": [3]}, [])
    res = trace_compare(obs, [tmp_path], tmp_path / "graph", root=tmp_path)
    assert _subjects(res, "unexecuted_realisation") == ["SC-001"]
    assert "SC-002" not in res.coverage
    assert any("SC-002" in n and "not measured" in n for n in res.notes)


def test_oracle_6_failed_and_skipped_tests_do_not_count(tmp_path):
    _project(tmp_path, SMALL_ITEMS, {
        "src/a.py": SMALL_SRC,
        "tests/t.py": [f"# {B} SC-001 test", "def test_a(): pass", f"# {E} SC-001",
                       "def test_loose(): pass"]})
    obs = _obs(tmp_path, {"src/a.py": [3, 7]}, [
        _test("t::test_a", "tests/t.py", 2, {"src/a.py": [3, 7]}, outcome="failed"),
        _test("t::test_loose", "tests/t.py", 4, {}, outcome="skipped")])
    res = trace_compare(obs, [tmp_path], tmp_path / "graph", root=tmp_path)
    assert _subjects(res, "unexecuted_realisation") == ["SC-001", "SC-002"]
    assert _subjects(res, "test_misses_target") == []
    assert _subjects(res, "untraced_test") == ["t::test_loose"]


# --- oracles 7 to 14 on the fixture -------------------------------------------------------

def test_oracle_7_test_misses_target():
    res = _fixture()
    assert _subjects(res, "test_misses_target") == [
        "tests/test_app.py::test_calibration_forgets_to_calibrate",
        "tests/test_app.py::test_validation_dump"]
    detail = {f.subject: f.detail for f in res.findings if f.category == "test_misses_target"}
    assert ("the suite does run it, via tests/test_app.py::test_calibration"
            in detail["tests/test_app.py::test_calibration_forgets_to_calibrate"])
    assert "covered_not_unit_tested" not in {f.category for f in res.findings}


def test_oracle_8_partial_system_test_is_per_fr():
    res = _fixture()
    assert _ids(res, "partial_system_test") == {"FR-005": ("SC-007",)}


def test_oracle_9_not_a_unit_test_crosses_a_function_boundary():
    res = _fixture()
    assert _ids(res, "not_a_unit_test") == {
        "tests/test_app.py::test_validate_accepts_numbers": ("SC-008",),
        "tests/test_app.py::test_calibration_forgets_to_calibrate": ("SC-001", "SC-004")}


def test_oracle_9_without_functions_the_boundary_is_the_file():
    data = _observed()
    del data["functions"]
    res = _fixture(data)
    assert _subjects(res, "not_a_unit_test") == []
    assert any("by file" in n for n in res.notes)


def test_oracle_10_undeclared_coupling_is_an_unordered_pair():
    res = _fixture()
    assert _ids(res, "undeclared_coupling") == {
        "SC-002 ~ SC-008": ("SC-002", "SC-008"), "SC-001 ~ SC-005": ("SC-001", "SC-005")}


def test_oracle_11_coincidental_coverage():
    assert _subjects(_fixture(), "coincidental_coverage") == ["SC-008"]


def test_oracle_12_no_unit_test_only_when_required():
    res = _fixture()
    assert _subjects(res, "no_unit_test") == []
    strict = _fixture(ruleset={"observed_trace": {"require_unit_test": True}})
    assert _subjects(strict, "no_unit_test") == [
        "SC-003", "SC-004", "SC-006", "SC-007", "SC-008"]


def test_oracle_13_unexecuted_realisation_and_unjustified_code():
    res = _fixture()
    assert _subjects(res, "unexecuted_realisation") == ["SC-007"]
    [unjustified] = [f for f in res.findings if f.category == "unjustified_code"]
    line = next(n for n, text in enumerate(
        (FIX / "src" / "app.py").read_text(encoding="utf-8").splitlines(), 1)
        if "return repr(x)" in text)
    assert (unjustified.subject, unjustified.detail) == ("src/app.py", f"line {line}")


def test_oracle_13_executed_files_with_no_fence_are_a_note(tmp_path):
    _project(tmp_path, SMALL_ITEMS, {
        "src/a.py": SMALL_SRC + ["def loose():", "    return 2"],
        "src/util.py": ["def util():", "    return 3"],
        "tests/helpers.py": ["def helper():", "    return 4"],
        "tests/t.py": [f"# {B} SC-001 test", "def test_a(): pass", f"# {E} SC-001"]})
    obs = _obs(tmp_path, {"src/a.py": [3, 7, 10], "src/util.py": [2], "tests/helpers.py": [2]},
               [_test("t::test_a", "tests/t.py", 2,
                      {"src/a.py": [3, 7, 10], "src/util.py": [2], "tests/helpers.py": [2]})])
    res = trace_compare(obs, [tmp_path], tmp_path / "graph", root=tmp_path)
    assert [(f.subject, f.detail) for f in res.findings if f.category == "unjustified_code"] \
        == [("src/a.py", "line 10")]
    assert any("src/util.py" in n and "tests/helpers.py" in n and "no fence" in n
               for n in res.notes)


def test_oracle_14_coverage_per_sc():
    cov = _fixture().coverage
    assert (cov["SC-008"].measured, cov["SC-008"].suite, cov["SC-008"].related,
            cov["SC-008"].unit) == (1, 1, 0, 0)
    assert (cov["SC-004"].suite, cov["SC-004"].related, cov["SC-004"].unit) == (1, 1, 0)
    assert (cov["SC-002"].measured, cov["SC-002"].suite, cov["SC-002"].unit) == (4, 4, 3)
    assert cov["SC-007"].suite == 0


# --- oracle 15 ----------------------------------------------------------------------------

def test_oracle_15_defaults_without_config_and_config_applies():
    assert any("defaults" in n for n in _fixture().notes)
    res = _fixture(ruleset={"observed_trace": {"blocking": ["untraced_test", "stale",
                                                            "coincidental_coverage"]}})
    assert not any("defaults" in n for n in res.notes)
    assert {f.category for f in res.findings if f.blocking} == {
        "untraced_test", "coincidental_coverage"}


@pytest.mark.parametrize("cfg, needle", [
    ({"blokcing": []}, "blokcing"),
    ({"implementation_type": 3}, "implementation_type"),
    ({"blocking": ["untraced"]}, "untraced"),
    ({"intermediate_types": "DD"}, "intermediate_types"),
    ({"require_unit_test": "yes"}, "require_unit_test"),
])
def test_oracle_15_a_malformed_config_cannot_run(cfg, needle):
    with pytest.raises(TraceError, match=needle):
        _fixture(ruleset={"observed_trace": cfg})


def test_oracle_15_check_ruleset_lints_the_config(tmp_path):
    from reqlite.ruleset_check import _lint

    # The library copy: byte-identical to ruleset/, and published.
    lib = ROOT / "src" / "reqlite" / "rulesets" / "reqlite"
    base = json.loads((lib / "ruleset.json").read_text(encoding="utf-8"))
    assert [f for f in _lint(base, lib) if f.where.startswith("observed_trace")] == []
    bad = copy.deepcopy(base)
    bad["observed_trace"].update(verification_type="XX", blocking=["nope"])
    found = {(f.category, f.where) for f in _lint(bad, lib)}
    assert ("observed_trace_unknown_type", "observed_trace.verification_type") in found
    assert ("observed_trace_malformed", "observed_trace.blocking") in found


# --- oracles 16 and 17 --------------------------------------------------------------------

def test_oracle_16_fence_integrity_findings_block(tmp_path):
    _project(tmp_path, SMALL_ITEMS, {
        "src/a.py": SMALL_SRC + [f"# {B} SC-009", "x = 1"],
        "tests/t.py": [f"# {B} SC-001 tset", "def test_a(): pass", f"# {E} SC-001"]})
    obs = _obs(tmp_path, {"src/a.py": [3, 7]}, [])
    res = trace_compare(obs, [tmp_path], tmp_path / "graph", root=tmp_path)
    blocking = {f.category for f in res.findings if f.blocking}
    assert {"unclosed_fence", "dangling_fence_ref", "unknown_fence_role"} <= blocking


def test_oracle_17_exit_codes_output_and_matrix(tmp_path, monkeypatch):
    monkeypatch.chdir(FIX)
    result = runner.invoke(app, ["trace-compare", "observed.json"])
    assert result.exit_code == 4
    out = result.output
    rows = {line.split()[0]: line.split() for line in out.splitlines()
            if line.startswith("  SC-")}
    assert rows["SC-003"][-1] == "-"          # no unit test at all
    assert rows["SC-005"][-1] == "0%"         # a unit test that misses it
    order = [out.index(s) for s in ("Tests:", "Blocking", "untraced_test", "Findings",
                                    "partial_system_test", "Coverage per SC")]
    assert order == sorted(order)

    data = json.loads(runner.invoke(app, ["trace-compare", "observed.json", "--json"]).stdout)
    assert {"findings", "coverage", "tests", "notes"} <= set(data)

    out_file = tmp_path / "matrix.json"
    runner.invoke(app, ["trace-compare", "observed.json", "-o", str(out_file)])
    matrix = json.loads(out_file.read_text(encoding="utf-8"))
    assert {"requirements", "components", "verifications", "fences", "files"} <= set(matrix)

    obs = _observed()
    obs["tests"] = [t for t in obs["tests"] if not t["name"].endswith("test_untraced")]
    clean = tmp_path / "clean.json"
    clean.write_text(json.dumps(obs), encoding="utf-8")
    assert runner.invoke(app, ["trace-compare", str(clean)]).exit_code == 0

    assert runner.invoke(app, ["trace-compare", "missing.json"]).exit_code == 1
    assert runner.invoke(app, ["trace-compare", "observed.json",
                               "--graph-dir", "nope"]).exit_code == 1


# --- oracle 18 ----------------------------------------------------------------------------

def test_oracle_18_the_example_adapter_writes_format_1(tmp_path):
    pytest.importorskip("pytest_cov")
    proj = tmp_path / "p"
    shutil.copytree(FIX, proj, ignore=shutil.ignore_patterns("observed.json"))
    # An outer pytest-cov run hands its subprocess hooks down through COV_CORE_*.
    env = {k: v for k, v in os.environ.items() if not k.startswith("COV_CORE")}
    env.update(COVERAGE_FILE=str(tmp_path / ".coverage"), PYTHONDONTWRITEBYTECODE="1")
    run = dict(cwd=proj, env=env, capture_output=True, text=True)
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                        "--cov=src", "--cov-context=test", "--cov-report=",
                        f"--junitxml={tmp_path / 'junit.xml'}"], **run)
    assert r.returncode == 0, r.stdout + r.stderr
    r = subprocess.run([sys.executable, "-m", "coverage", "json", "--show-contexts",
                        "--data-file", str(tmp_path / ".coverage"),
                        "-o", str(tmp_path / "coverage.json")], **run)
    assert r.returncode == 0, r.stdout + r.stderr
    r = subprocess.run([sys.executable, str(ROOT / "examples" / "adapters" / "pytest_observed.py"),
                        str(tmp_path / "coverage.json"), str(tmp_path / "junit.xml"),
                        "-o", str(proj / "observed.json"), "--scope", "src/**/*.py"], **run)
    assert r.returncode == 0, r.stdout + r.stderr

    fresh = load_observed((proj / "observed.json").read_bytes())
    assert fresh["contract"] == 1 and fresh["outside_tests"] and fresh["functions"]
    assert fresh["scope"] == ["src/**/*.py"]
    got = trace_compare(fresh, [proj], proj / "graph", root=proj)
    want = _fixture()
    key = lambda res: sorted((f.category, f.subject, f.ids) for f in res.findings)
    assert key(got) == key(want)
