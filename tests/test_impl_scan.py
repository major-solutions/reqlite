from pathlib import Path

from reqlite.impl_scan import scan_impl, justification_report

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "reqlite"
# Any graph will do here: what these tests read does not depend on its items. Dangling
# claims against this repository's own graph: tests/private/test_dogfood.py.
GRAPH = ROOT / "tests" / "fixtures" / "graph"


def test_self_declarations_extracted():
    impl = scan_impl(SRC)
    assert impl["IMPL-references"].spec_ids == {"SC-001", "FR-002"}
    assert impl["IMPL-items"].spec_ids == {"SC-002", "FR-008"}
    assert "SC-012" in impl["IMPL-impl_scan"].spec_ids  # scanner justifies itself


def test_marker_is_intentional_not_mention():
    # graph.py self-declares SC-004; it must NOT claim SC-003/SC-011 by mere mention
    impl = scan_impl(SRC)
    assert impl["IMPL-graph"].spec_ids == {"SC-004"}


def test_query_now_justified():
    impl = scan_impl(SRC)
    assert "SC-011" in impl["IMPL-query"].spec_ids
    assert impl["IMPL-query.run_query"].spec_ids == {"SC-011"}  # inherits module marker


def test_node_detail_populated():
    impl = scan_impl(SRC)
    rq = impl["IMPL-query.run_query"]
    assert rq.role == "function"
    assert rq.signature.startswith("(")
    assert rq.end_line >= int(rq.loc.split(":")[-1])  # span is sane
    # a dataclass result schema is tagged 'data', not dropped from the tally
    assert impl["IMPL-analyses.TopologyInfo"].role == "data"
    # internal helper is tagged distinctly
    assert impl["IMPL-query._apply"].role == "internal"


def test_list_impl_filter_by_role():
    from reqlite.impl_scan import list_impl
    data = list_impl(SRC, roles={"data"})
    assert data and all(n.role == "data" for n in data)
    # filtering is a view, never drops from the underlying scan
    assert len(list_impl(SRC)) == len(scan_impl(SRC))


def test_analyses_library_justified_by_inheritance():
    impl = scan_impl(SRC)
    assert impl["IMPL-analyses.run_declared_analysis"].spec_ids == {"SC-013"}
    assert impl["IMPL-analyses.run_declared_analysis"].inherited  # rides the module marker
    # data schemas inherit too, rather than being excluded
    assert impl["IMPL-analyses.TopologyInfo"].spec_ids == {"SC-013"}


def test_reqlite_fully_self_justified():
    assert justification_report(SRC, GRAPH)["unjustified"] == []


# --- CLI surface ---------------------------------------------------------

from typer.testing import CliRunner
from reqlite.cli import app

_runner = CliRunner()


def test_cli_impl_scan_runs():
    result = _runner.invoke(app, ["impl-scan", str(SRC), "--graph-dir", str(GRAPH)])
    assert result.exit_code == 0
    assert "IMPL units:" in result.output
    assert "justified:" in result.output


def test_cli_impl_list_runs():
    result = _runner.invoke(app, ["impl-list", str(SRC)])
    assert result.exit_code == 0
    assert "IMPL unit(s)" in result.output


def test_cli_impl_list_filter_role_and_unjustified():
    data = _runner.invoke(app, ["impl-list", str(SRC), "--role", "data"])
    assert data.exit_code == 0
    unjust = _runner.invoke(app, ["impl-list", str(SRC), "--unjustified"])
    assert unjust.exit_code == 0
