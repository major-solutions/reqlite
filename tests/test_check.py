"""Tests for `reqlite check` and `reqlite commit-gate`. One test per oracle in
ORACLES-CHECK.md."""

import json
import subprocess

import pytest
from typer.testing import CliRunner

from reqlite.cli import app

runner = CliRunner()

RULESET = {
    "types": {
        "SRC": {"fields": {
            "certainty": {"values": ["speculative", "assumed", "verified"]},
            "source": {"values": ["observation", "design session"]},
        }},
        "FR": {"fields": {
            "certainty": {"values": ["speculative", "assumed", "verified"]},
        }},
    },
    "common_fields": {"evidence": {"description": "What supports this claim."}},
    "write_conventions": {
        "id_pattern": "^[A-Z]+-\\d{3}$",
        "valid_prefixes_from_types": True,
    },
}


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def _write(graph, name, body="Body.", fm=None, links=(), heading=None):
    item_id = name.split("-")[0] + "-" + name.split("-")[1]
    parts = []
    if fm is not None:
        parts.append("---\n" + fm.strip() + "\n---\n")
    parts.append((heading if heading is not None else f"# {item_id}: Title") + "\n\n")
    parts.append(body + "\n")
    for target in links:
        parts.append(f"\n[{target[:7]}]({target})\n")
    (graph / name).write_text("".join(parts), encoding="utf-8")


def _project(root, ruleset=RULESET):
    graph = root / "graph"
    graph.mkdir(parents=True)
    (root / "ruleset").mkdir()
    if ruleset is not None:
        (root / "ruleset" / "ruleset.json").write_text(json.dumps(ruleset), encoding="utf-8")
    _write(graph, "SRC-001-base.md")
    _write(graph, "FR-001-cap.md", links=["SRC-001-base.md"])
    return graph


@pytest.fixture
def graph(tmp_path):
    return _project(tmp_path / "proj")


def _init_repo(root):
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "commit.gpgsign", "false")


def _commit_all(root, msg="c"):
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", msg)


@pytest.fixture
def repo(tmp_path):
    """A committed clean reqlite project. Returns the repository root."""
    root = tmp_path / "repo"
    _project(root)
    _init_repo(root)
    _commit_all(root, "init")
    return root


def _check(graph, *flags):
    return runner.invoke(app, ["check", str(graph), *flags])


def _has(output, severity, category, *needles):
    """A finding line with this severity and category that mentions every needle."""
    for line in output.splitlines():
        if line.strip().startswith(f"{severity}:") and f"[{category}]" in line:
            if all(n in line for n in needles):
                return True
    return False


# --- graph-wide ---------------------------------------------------------------------


def test_oracle_1_a_clean_graph_exits_0(graph):
    r = _check(graph)
    assert r.exit_code == 0, r.output
    assert "no findings" in r.output.lower()


def test_oracle_2_an_unknown_reference_is_an_error(graph):
    _write(graph, "FR-002-dangling.md", links=["SRC-009-missing.md", "SRC-001-base.md"])
    r = _check(graph)
    assert r.exit_code == 1, r.output
    assert _has(r.output, "error", "unknown_reference", "FR-002")



def test_oracle_31_a_link_naming_the_wrong_file_is_an_error(graph):
    _write(graph, "FR-002-misnamed.md", links=["SRC-001-wrong.md"])
    r = _check(graph)
    assert r.exit_code == 1, r.output
    assert _has(r.output, "error", "unknown_reference",
                "FR-002", "SRC-001-wrong.md", "SRC-001-base.md")

def test_oracle_3_a_duplicate_id_is_an_error(graph):
    _write(graph, "SRC-001-again.md")
    r = _check(graph)
    assert r.exit_code == 1, r.output
    assert _has(r.output, "error", "duplicate_id", "SRC-001")


def test_oracle_4_a_cycle_is_an_error(graph):
    _write(graph, "FR-002-a.md", links=["FR-003-b.md"])
    _write(graph, "FR-003-b.md", links=["FR-002-a.md"])
    r = _check(graph)
    assert r.exit_code == 1, r.output
    assert _has(r.output, "error", "cycle")


def test_oracle_5_an_orphan_is_a_warning_only(graph):
    _write(graph, "SRC-002-alone.md")
    r = _check(graph)
    assert r.exit_code == 0, r.output
    assert _has(r.output, "warning", "orphan", "SRC-002")


def test_oracle_6_every_parse_failure_is_reported_with_its_file(graph):
    _write(graph, "SRC-002-bad.md", fm="certainty: [unclosed")
    _write(graph, "SRC-003-bad.md", fm="certainty: nonsense")
    r = _check(graph)
    assert r.exit_code == 1, r.output
    assert _has(r.output, "error", "parse", "SRC-002-bad.md")
    assert _has(r.output, "error", "parse", "SRC-003-bad.md")


def test_oracle_7_a_missing_ruleset_fails_rather_than_skips(tmp_path):
    graph = _project(tmp_path / "p", ruleset=None)
    r = _check(graph)
    assert r.exit_code == 1, r.output
    assert "ruleset.json" in r.output


# --- write conventions --------------------------------------------------------------


def test_oracle_8_a_markdown_file_the_parser_would_skip_is_an_error(graph):
    (graph / "src-002-lower.md").write_text("# SRC-002: x\n", encoding="utf-8")
    (graph / "SRC002-nodash.md").write_text("# SRC-002: x\n", encoding="utf-8")
    r = _check(graph)
    assert r.exit_code == 1, r.output
    assert _has(r.output, "error", "filename", "src-002-lower.md")
    assert _has(r.output, "error", "filename", "SRC002-nodash.md")


def test_oracle_9_an_id_breaking_id_pattern_is_an_error(graph):
    _write(graph, "SRC-02-short.md", links=["SRC-001-base.md"])
    r = _check(graph)
    assert r.exit_code == 1, r.output
    assert _has(r.output, "error", "id_pattern", "SRC-02")


def test_oracle_10_a_prefix_that_is_not_a_type_is_an_error(graph):
    _write(graph, "XX-001-unknown.md", links=["SRC-001-base.md"])
    r = _check(graph)
    assert r.exit_code == 1, r.output
    assert _has(r.output, "error", "prefix", "XX-001")


def test_oracle_11_the_first_heading_must_carry_the_files_own_id(graph):
    _write(graph, "FR-002-noh1.md", heading="", links=["SRC-001-base.md"])
    _write(graph, "FR-003-wrong.md", heading="# FR-009: Wrong", links=["SRC-001-base.md"])
    r = _check(graph)
    assert r.exit_code == 1, r.output
    assert _has(r.output, "error", "heading", "FR-002")
    assert _has(r.output, "error", "heading", "FR-003")


def test_oracle_12_a_field_the_type_does_not_define_is_an_error(graph):
    _write(graph, "FR-002-src.md", fm='source: observation\nevidence: "a quote"',
           links=["SRC-001-base.md"])
    r = _check(graph)
    assert r.exit_code == 1, r.output
    assert _has(r.output, "error", "field", "FR-002", "source")
    assert not _has(r.output, "error", "field", "evidence")


def test_oracle_13_a_value_outside_the_allowed_values_is_an_error(graph):
    _write(graph, "SRC-002-hall.md", fm="source: hallway")
    _write(graph, "FR-002-x.md", links=["SRC-002-hall.md"])
    r = _check(graph)
    assert r.exit_code == 1, r.output
    assert _has(r.output, "error", "field_value", "SRC-002", "source", "hallway")


def test_oracle_14_a_null_field_is_an_error(graph):
    _write(graph, "FR-002-null.md", fm="evidence: null", links=["SRC-001-base.md"])
    r = _check(graph)
    assert r.exit_code == 1, r.output
    assert _has(r.output, "error", "field_value", "FR-002", "evidence")


# --- --staged -----------------------------------------------------------------------


def test_oracle_15_the_index_is_checked_not_the_working_tree(repo):
    graph = repo / "graph"
    _write(graph, "FR-002-x.md", fm="certainty: maybe", links=["SRC-001-base.md"])
    _git(repo, "add", "-A")
    _write(graph, "FR-002-x.md", fm="certainty: assumed", links=["SRC-001-base.md"])
    r = _check(graph, "--staged")
    assert r.exit_code == 1, r.output
    assert "FR-002" in r.output


def test_oracle_16_unstaged_work_does_not_block(repo):
    graph = repo / "graph"
    _write(graph, "FR-001-cap.md", fm="certainty: maybe", links=["SRC-001-base.md"])
    r = _check(graph, "--staged")
    assert r.exit_code == 0, r.output


def test_oracle_17_pre_existing_violations_in_untouched_items_do_not_block(repo):
    graph = repo / "graph"
    _write(graph, "FR-001-cap.md", fm="source: observation", links=["SRC-001-base.md"])
    _commit_all(repo, "legacy violation")
    _write(graph, "FR-002-new.md", links=["SRC-001-base.md"])
    _git(repo, "add", "-A")
    r = _check(graph, "--staged")
    assert r.exit_code == 0, r.output


def test_oracle_18_touching_an_item_makes_its_violations_count(repo):
    graph = repo / "graph"
    _write(graph, "FR-001-cap.md", fm="source: observation", links=["SRC-001-base.md"])
    _commit_all(repo, "legacy violation")
    _write(graph, "FR-001-cap.md", fm="source: observation", body="Edited.",
           links=["SRC-001-base.md"])
    _git(repo, "add", "-A")
    r = _check(graph, "--staged")
    assert r.exit_code == 1, r.output
    assert _has(r.output, "error", "field", "FR-001")


def test_oracle_19_a_retirement_leaving_an_inbound_link_is_an_error(repo):
    _git(repo, "rm", "-q", "graph/SRC-001-base.md")
    r = _check(repo / "graph", "--staged")
    assert r.exit_code == 1, r.output
    assert _has(r.output, "error", "unknown_reference", "FR-001")


def test_oracle_20_the_first_commit_treats_every_staged_item_as_changed(tmp_path):
    root = tmp_path / "fresh"
    graph = _project(root)
    _write(graph, "FR-002-x.md", fm="source: observation", links=["SRC-001-base.md"])
    _init_repo(root)
    _git(root, "add", "-A")
    r = _check(graph, "--staged")
    assert r.exit_code == 1, r.output
    assert _has(r.output, "error", "field", "FR-002")


def test_oracle_21_outside_git_staged_refuses(graph):
    r = _check(graph, "--staged")
    assert r.exit_code == 1, r.output
    assert "git" in r.output.lower()


# --- --changed ----------------------------------------------------------------------


def test_oracle_22_unstaged_and_untracked_changes_are_checked(repo):
    graph = repo / "graph"
    _write(graph, "FR-001-cap.md", fm="source: observation", links=["SRC-001-base.md"])
    _write(graph, "FR-002-new.md", fm="certainty: maybe", links=["SRC-001-base.md"])
    r = _check(graph, "--changed")
    assert r.exit_code == 1, r.output
    assert _has(r.output, "error", "field", "FR-001")
    assert "FR-002" in r.output


def test_oracle_23_unchanged_items_are_not_checked_for_conventions(repo):
    graph = repo / "graph"
    _write(graph, "FR-001-cap.md", fm="source: observation", links=["SRC-001-base.md"])
    _commit_all(repo, "legacy violation")
    r = _check(graph, "--changed")
    assert r.exit_code == 0, r.output


# --- commit-gate --------------------------------------------------------------------


def _gate(cwd, command):
    payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(cwd),
               "tool_input": {"command": command}}
    return runner.invoke(app, ["commit-gate"], input=json.dumps(payload))


def _break(repo):
    _write(repo / "graph", "FR-002-bad.md", fm="source: observation",
           links=["SRC-001-base.md"])


def test_oracle_24_a_git_dash_c_commit_is_gated_and_other_git_dash_c_is_not(repo):
    _break(repo)
    assert _gate(repo, f"git -C {repo} status").exit_code == 0
    assert _gate(repo, f"git -C {repo} commit -am x").exit_code == 2


def test_oracle_24_git_dash_c_judges_the_named_directory(repo, tmp_path):
    """The commit happens in the -C directory, not the hook's cwd."""
    _break(repo)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert _gate(elsewhere, f'git -C "{repo}" commit -am x').exit_code == 2
    assert _gate(elsewhere, "git -C graph commit -am x").exit_code == 0  # not a repo there
    assert _gate(repo, "git -C graph commit -am x").exit_code == 2  # relative to cwd


@pytest.mark.parametrize("command, code", [
    ("git log --oneline --grep=commit", 0),
    ("git show HEAD -- commit.md", 0),
    ("git -C {repo} log --grep commit", 0),
    ("git commit-tree HEAD^{{tree}}", 0),
    ("git -c user.name=x commit -am x", 2),
    ("git --no-pager commit -am x", 2),
    ("git -C {repo} commit -am x", 2),
    ('git -C "{repo}" -c a.b=c commit -am x', 2),
])
def test_oracle_24c_a_commit_is_the_subcommand(repo, command, code):
    _break(repo)
    assert _gate(repo, command.format(repo=repo)).exit_code == code, command


@pytest.mark.parametrize("command, code", [
    ('cd "{repo}" && git commit -am x', 2),
    ("cd {repo}; git commit -am x", 2),
    ("git commit -am x && cd {repo}", 0),
])
def test_oracle_24d_cd_before_the_commit_moves_where_it_is_judged(repo, tmp_path, command,
                                                                  code):
    _break(repo)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert _gate(elsewhere, command.format(repo=repo.as_posix())).exit_code == code, command


@pytest.mark.parametrize("command, code", [
    ("Set-Location {repo}; git commit -am x", 2),
    ("set-location -Path '{repo}'; git commit -am x", 2),
    ("sl -LiteralPath {repo}; git commit -am x", 2),
    ("Push-Location {repo}; git commit -am x", 2),
    ("pushd {repo} && git commit -am x", 2),
    ("chdir {repo} && git commit -am x", 2),
    ("cd $env:REQLITE_TEST_DIR; git commit -am x", 2),
    ("cd ${{env:REQLITE_TEST_DIR}}; git commit -am x", 2),
    ("cd $REQLITE_TEST_DIR && git commit -am x", 2),
    ('cd "${{REQLITE_TEST_DIR}}" && git commit -am x', 2),
    ("cd %REQLITE_TEST_DIR% && git commit -am x", 2),
    ("cd $env:REQLITE_TEST_UNSET; git commit -am x", 0),
    ("Set-Location -; git commit -am x", 0),
])
def test_oracle_24e_powershell_location_commands_and_variables_move_the_commit(
        repo, tmp_path, monkeypatch, command, code):
    _break(repo)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("REQLITE_TEST_DIR", str(repo))
    monkeypatch.delenv("REQLITE_TEST_UNSET", raising=False)
    command = command.format(repo=repo.as_posix())
    assert _gate(elsewhere, command).exit_code == code, command


def test_oracle_24_a_non_commit_command_passes(repo):
    _break(repo)
    r = _gate(repo, "ls")
    assert r.exit_code == 0, r.output


def test_oracle_25_a_commit_outside_a_reqlite_project_passes_silently(tmp_path):
    root = tmp_path / "plain"
    root.mkdir()
    _init_repo(root)
    (root / "README.md").write_text("x\n", encoding="utf-8")
    r = _gate(root, "git commit -m x")
    assert r.exit_code == 0, r.output
    assert r.output.strip() == ""


def test_oracle_26_a_commit_outside_git_passes_silently(tmp_path):
    r = _gate(tmp_path, "git commit -m x")
    assert r.exit_code == 0, r.output
    assert r.output.strip() == ""


def test_oracle_27_a_commit_with_errors_in_changed_items_is_blocked(repo):
    _break(repo)
    r = _gate(repo, "git add -A && git commit -m x")
    assert r.exit_code == 2, r.output
    assert "FR-002" in r.stderr
    assert "working tree" in r.stderr


def test_oracle_28_warnings_do_not_block(repo):
    _write(repo / "graph", "SRC-002-alone.md")
    r = _gate(repo, "git commit -am x")
    assert r.exit_code == 0, r.output


def test_oracle_29_a_check_that_cannot_run_in_a_reqlite_project_blocks(repo):
    (repo / "ruleset" / "ruleset.json").write_text("{not json", encoding="utf-8")
    r = _gate(repo, "git commit -m x")
    assert r.exit_code == 2, r.output
    assert "ruleset" in r.stderr


def test_oracle_37_front_matter_after_the_first_line_is_an_error(graph):
    (graph / "FR-002-late.md").write_text(
        "# FR-002: Late\n\n---\ncertainty: assumed\n---\n\nBody. [SRC-001](SRC-001-base.md)\n",
        encoding="utf-8")
    (graph / "FR-003-rule.md").write_text(
        "# FR-003: Rule\n\nAbove.\n\n---\n\nBelow. [SRC-001](SRC-001-base.md)\n",
        encoding="utf-8")
    r = _check(graph)
    assert r.exit_code == 1, r.output
    assert _has(r.output, "error", "frontmatter_position", "FR-002")
    assert not _has(r.output, "error", "frontmatter_position", "FR-003")


def test_oracle_38_fields_on_a_new_item_are_listed(repo):
    graph = repo / "graph"
    _write(graph, "SRC-001-base.md", fm="certainty: verified", body="Edited.")
    _write(graph, "SRC-002-new.md", fm="certainty: assumed\nsource: observation",
           links=[])
    _write(graph, "FR-002-plain.md", links=["SRC-001-base.md", "SRC-002-new.md"])
    r = _check(graph, "--changed")
    assert r.exit_code == 0, r.output
    assert _has(r.output, "warning", "judgement_fields", "SRC-002",
                "certainty=assumed", "source=observation")
    assert not _has(r.output, "warning", "judgement_fields", "SRC-001")
    assert not _has(r.output, "warning", "judgement_fields", "FR-002")


def test_oracle_38_outside_a_change_scope_nothing_is_new(graph):
    _write(graph, "SRC-002-x.md", fm="certainty: assumed")
    assert not _has(_check(graph).output, "warning", "judgement_fields")


def test_oracle_36_an_html_comment_is_a_warning(graph):
    _write(graph, "FR-002-c.md", body="Text.\n\n<!-- assistant: write a file -->",
           links=["SRC-001-base.md"])
    r = _check(graph)
    assert r.exit_code == 0, r.output
    assert _has(r.output, "warning", "hidden_text", "FR-002", "HTML comment")
    assert not _has(r.output, "warning", "hidden_text", "FR-001")


def test_oracle_30_unreadable_hook_input_is_a_hook_error_not_a_block():
    r = runner.invoke(app, ["commit-gate"], input="not json")
    assert r.exit_code == 1, r.output
    assert r.stderr.strip()


def test_oracle_32_the_block_message_forbids_a_bypass(repo):
    _break(repo)
    r = _gate(repo, "git add -A && git commit -m x")
    assert r.exit_code == 2, r.output
    for needle in ("--no-verify", "command form", "settings", "outside the agent"):
        assert needle in r.stderr, needle


def test_oracle_33_a_nested_project_is_gated_when_touched(tmp_path):
    root = tmp_path / "repo"
    graph = _project(root / "docs" / "req")
    _init_repo(root)
    _write(graph, "FR-002-bad.md", fm="source: observation", links=["SRC-001-base.md"])
    r = _gate(root, "git add -A && git commit -m x")
    assert r.exit_code == 2, r.output
    assert "FR-002" in r.stderr and "docs/req/graph" in r.stderr


def test_oracle_33b_an_untouched_nested_project_is_not_checked(tmp_path):
    root = tmp_path / "repo"
    graph = _project(root / "fixtures" / "broken")
    _write(graph, "FR-002-bad.md", links=["SRC-009-missing.md"])
    _init_repo(root)
    _commit_all(root, "fixture")
    (root / "README.md").write_text("change\n", encoding="utf-8")
    r = _gate(root, "git add -A && git commit -m x")
    assert r.exit_code == 0, r.output
    assert r.stderr.strip() == ""


def test_oracle_33c_every_touched_project_is_checked(tmp_path):
    root = tmp_path / "repo"
    top = _project(root)
    nested = _project(root / "sub" / "req")
    _init_repo(root)
    _commit_all(root, "init")
    _write(top, "FR-002-top.md", fm="source: observation", links=["SRC-001-base.md"])
    _write(nested, "FR-003-sub.md", fm="source: observation", links=["SRC-001-base.md"])
    r = _gate(root, "git add -A && git commit -m x")
    assert r.exit_code == 2, r.output
    assert "FR-002" in r.stderr and "FR-003" in r.stderr
    assert "sub/req/graph" in r.stderr


@pytest.mark.parametrize("tool_input", ["...", {}, {"command": None}, None])
def test_oracle_35_a_payload_with_no_command_string_passes(repo, tool_input):
    _break(repo)
    payload = {"hook_event_name": "PreToolUse", "tool_name": "read_file", "cwd": str(repo),
               "tool_input": tool_input}
    r = runner.invoke(app, ["commit-gate"], input=json.dumps(payload))
    assert r.exit_code == 0, r.output
    assert r.stderr.strip() == ""


def test_oracle_34_a_backtracking_id_pattern_is_refused_not_run(tmp_path):
    graph = _project(tmp_path / "p", ruleset={**RULESET, "write_conventions": {
        "id_pattern": "^(A+)+B$"}})
    _write(graph, "A" * 30 + "-001-x.md", links=["SRC-001-base.md"])
    r = _check(graph)
    assert r.exit_code == 1, r.output
    assert _has(r.output, "error", "unsafe_id_pattern", "^(A+)+B$")
    assert not _has(r.output, "error", "id_pattern")


def test_oracle_34_an_invalid_id_pattern_is_an_error_not_a_crash(tmp_path):
    graph = _project(tmp_path / "p", ruleset={**RULESET, "write_conventions": {
        "id_pattern": "^[A-Z+$"}})
    r = _check(graph)
    assert r.exit_code == 1, r.output
    assert r.exception is None or isinstance(r.exception, SystemExit)
    assert _has(r.output, "error", "invalid_id_pattern")
