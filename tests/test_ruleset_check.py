"""Tests for the ruleset check. One test per oracle in ORACLES-RULESET.md.

The model is never called: the inferential half takes an injected `transport`. Nothing
here asserts on semantic finding content (see ORACLES-RULESET.md).
"""

import json
from pathlib import Path

import pytest

from reqlite.review import MissingCredentialError, ReviewError
from reqlite.ruleset_check import (
    RulesetCheckRequest,
    RulesetError,
    check_ruleset,
    engine_prompt,
    lint_ruleset,
)

REPO = Path(__file__).parent.parent

SRC_PROMPT = "SRC_QUALITY_PROMPT_TEXT"
UC_PROMPT = "UC_QUALITY_PROMPT_TEXT"
CONSISTENCY_PROMPT = "ANALYSIS_PROMPT_TEXT"

_FIELDS = {"certainty": {"values": ["speculative", "assumed", "verified"]}}


def _ruleset(**over):
    rs = {
        "types": {
            "SRC": {"description": "Reality.", "fields": dict(_FIELDS),
                    "quality_prompt": "prompts/src_quality.md"},
            "UC": {"description": "Scenarios.", "fields": dict(_FIELDS),
                   "quality_prompt": "prompts/uc_quality.md"},
        },
        "scales": {"certainty": {"verified": 1, "assumed": 2, "speculative": 3}},
        "analyses": {
            "grounding": {
                "query": {"start": "UC", "terms": [
                    {"name": "best", "direction": "down", "reduce": "min",
                     "dimension": "certainty", "target": "SRC"}],
                    "combine": "best <= 1"},
            },
        },
        "prompts": {"consistency": "prompts/consistency.md"},
        "write_conventions": {"id_pattern": "^[A-Z]+-\\d{3}$",
                              "valid_prefixes_from_types": True},
    }
    rs.update(over)
    return rs


def _project(tmp_path, ruleset=None, prompts=None, graph=True):
    rs_dir = tmp_path / "ruleset"
    (rs_dir / "prompts").mkdir(parents=True)
    for rel, text in (prompts if prompts is not None else {
            "prompts/src_quality.md": SRC_PROMPT,
            "prompts/uc_quality.md": UC_PROMPT,
            "prompts/consistency.md": CONSISTENCY_PROMPT}).items():
        (rs_dir / rel).write_text(text, encoding="utf-8")
    rs = ruleset if ruleset is not None else _ruleset()
    (rs_dir / "ruleset.json").write_text(json.dumps(rs, indent=2), encoding="utf-8")
    g = tmp_path / "graph"
    if graph:
        g.mkdir()
    return g


def _analysis(query):
    return {"analyses": {"a1": {"query": query}}}


def _cats(findings):
    return [f.category for f in findings]


class FakeTransport:
    def __init__(self, response=None, raises=None):
        self._response = response
        self._raises = raises
        self.calls = []

    def __call__(self, *, prompt, options, api_key, gateway=None):
        self.calls.append({"prompt": prompt, "options": options, "api_key": api_key,
                           "gateway": gateway})
        if self._raises is not None:
            raise self._raises
        return self._response

    @property
    def last(self):
        assert self.calls, "transport was never called"
        return self.calls[-1]


def _semantic(findings=None):
    return json.dumps({"findings": findings if findings is not None else [
        {"category": "decision_collision", "types": ["SRC", "UC"], "contested": "x",
         "summary": "s", "reasoning": "r", "fix": "f", "severity": "low"}]})


def _check(graph, transport=None, key="sk-ant-test", **kw):
    transport = transport if transport is not None else FakeTransport(_semantic())
    result = check_ruleset(
        RulesetCheckRequest(graph_dir=str(graph), api_key=key, **kw), transport=transport)
    return result, transport


# --- Algorithmic half -------------------------------------------------------------------

# Oracle 1 lints this repository's own ruleset, which is not published:
# tests/private/test_dogfood.py.


def test_oracle_2_missing_quality_prompt_file(tmp_path):
    rs = _ruleset()
    rs["types"]["SRC"]["quality_prompt"] = "prompts/missing.md"
    findings = lint_ruleset(str(_project(tmp_path, rs)))
    hits = [f for f in findings if f.category == "missing_prompt_file"]
    assert len(hits) == 1
    assert "SRC" in hits[0].where and "prompts/missing.md" in hits[0].detail


def test_oracle_3_missing_analysis_prompt_file(tmp_path):
    rs = _ruleset(prompts={"consistency": "prompts/gone.md"})
    findings = lint_ruleset(str(_project(tmp_path, rs)))
    hits = [f for f in findings if f.category == "missing_prompt_file"]
    assert len(hits) == 1 and "prompts.consistency" in hits[0].where


def test_oracle_4_type_without_quality_prompt(tmp_path):
    rs = _ruleset()
    del rs["types"]["SRC"]["quality_prompt"]
    rs["types"]["UC"]["quality_prompt"] = None
    findings = lint_ruleset(str(_project(tmp_path, rs)))
    hits = [f for f in findings if f.category == "missing_quality_prompt"]
    assert sorted(f.where for f in hits) == ["types.SRC", "types.UC"]


@pytest.mark.parametrize("declared", ["../outside.md", "ABSOLUTE"])
def test_oracle_5_escaping_prompt_path_is_flagged_and_not_read(tmp_path, declared):
    outside = tmp_path / "outside.md"
    outside.write_text("SECRET_OUTSIDE_CONTENT", encoding="utf-8")
    rs = _ruleset()
    rs["types"]["SRC"]["quality_prompt"] = str(outside) if declared == "ABSOLUTE" else declared
    graph = _project(tmp_path, rs)
    findings = lint_ruleset(str(graph))
    assert "prompt_path_escapes" in _cats(findings)
    assert "SECRET_OUTSIDE_CONTENT" not in repr(findings)
    result, t = _check(graph)
    assert t.calls == []
    assert "SECRET_OUTSIDE_CONTENT" not in json.dumps(result)


def test_oracle_6_invalid_id_pattern(tmp_path):
    rs = _ruleset(write_conventions={"id_pattern": "^[A-Z+$"})
    assert "invalid_id_pattern" in _cats(lint_ruleset(str(_project(tmp_path, rs))))


@pytest.mark.parametrize("pattern, unsafe", [
    (r"^(A+)+B$", True),
    (r"^(A|AA)+$", True),
    (r"^[A-Z]+-\d{3}$", False),
    (r"^(FR|SC)-\d+$", False),
])
def test_oracle_6b_backtracking_prone_id_pattern(tmp_path, pattern, unsafe):
    rs = _ruleset(write_conventions={"id_pattern": pattern})
    cats = _cats(lint_ruleset(str(_project(tmp_path / "p", rs))))
    assert ("unsafe_id_pattern" in cats) is unsafe, cats


def test_oracle_7_prefixes_from_types_with_no_types(tmp_path):
    rs = _ruleset(types={}, analyses={},
                  write_conventions={"valid_prefixes_from_types": True})
    assert "empty_types" in _cats(lint_ruleset(str(_project(tmp_path, rs))))


def test_oracle_8_missing_branch_prefix_is_not_a_finding(tmp_path):
    findings = lint_ruleset(str(_project(tmp_path)))
    assert findings == []
    assert "branch_prefix" not in repr(findings)


@pytest.mark.parametrize("decl", [
    {"description": "no query here"},
    {"query": {"start": "UC"}},
    {"query": {"start": "UC", "terms": [{"direction": "self", "reduce": "count"}]}},
])
def test_oracle_9_analysis_without_a_usable_query(tmp_path, decl):
    rs = _ruleset(analyses={"broken": decl})
    hits = [f for f in lint_ruleset(str(_project(tmp_path, rs)))
            if f.category == "analysis_malformed"]
    assert len(hits) == 1 and "broken" in hits[0].where


def test_oracle_10_start_and_target_must_be_types(tmp_path):
    rs = _ruleset(**_analysis({"start": "XX", "terms": [
        {"name": "n", "direction": "up", "reduce": "count", "target": "YY"}]}))
    hits = [f for f in lint_ruleset(str(_project(tmp_path, rs)))
            if f.category == "analysis_unknown_type"]
    assert len(hits) == 2
    assert any("XX" in f.detail for f in hits) and any("YY" in f.detail for f in hits)


def test_oracle_10b_star_start_is_valid(tmp_path):
    rs = _ruleset(**_analysis({"start": "*", "terms": [
        {"name": "n", "direction": "up", "reduce": "count"}]}))
    assert lint_ruleset(str(_project(tmp_path, rs))) == []


def test_oracle_11_bad_direction(tmp_path):
    rs = _ruleset(**_analysis({"start": "UC", "terms": [
        {"name": "n", "direction": "sideways", "reduce": "count"}]}))
    assert _cats(lint_ruleset(str(_project(tmp_path, rs)))) == ["analysis_direction"]


def test_oracle_12_reducer_outside_the_whitelist(tmp_path):
    rs = _ruleset(**_analysis({"start": "UC", "terms": [
        {"name": "n", "direction": "down", "reduce": "avg", "dimension": "certainty"}]}))
    assert _cats(lint_ruleset(str(_project(tmp_path, rs)))) == ["analysis_reducer"]


@pytest.mark.parametrize("term", [
    {"name": "n", "direction": "down", "reduce": "max"},
    {"name": "n", "direction": "down", "reduce": "max", "dimension": "colour"},
])
def test_oracle_13_non_count_reducer_needs_a_declared_dimension(tmp_path, term):
    rs = _ruleset(**_analysis({"start": "UC", "terms": [term]}))
    assert _cats(lint_ruleset(str(_project(tmp_path, rs)))) == ["analysis_dimension"]


def test_oracle_13b_count_needs_no_dimension(tmp_path):
    rs = _ruleset(**_analysis({"start": "UC", "terms": [
        {"name": "n", "direction": "down", "reduce": "count"}]}))
    assert lint_ruleset(str(_project(tmp_path, rs))) == []


def test_oracle_14_labelled_dimension_without_a_scale(tmp_path):
    rs = _ruleset(**_analysis({"start": "UC", "terms": [
        {"name": "n", "direction": "down", "reduce": "max", "dimension": "priority"}]}))
    rs["types"]["SRC"]["fields"]["priority"] = {"values": ["low", "high"]}
    assert _cats(lint_ruleset(str(_project(tmp_path, rs)))) == ["analysis_scale"]


@pytest.mark.parametrize("combine", [
    "cov >=", "cov >= 1 and cov < 3", "len(cov)", "nope * 2",
])
def test_oracle_15_combine_must_parse_whitelist_and_name_known_values(tmp_path, combine):
    rs = _ruleset(**_analysis({"start": "UC", "terms": [
        {"name": "cov", "direction": "up", "reduce": "count"}], "combine": combine}))
    assert _cats(lint_ruleset(str(_project(tmp_path, rs)))) == ["analysis_combine"]


def test_oracle_15b_self_values_are_known_names(tmp_path):
    rs = _ruleset(**_analysis({"start": "UC", "terms": [
        {"name": "cov", "direction": "up", "reduce": "count"}],
        "combine": "self_certainty * cov + self_effort"}))
    assert lint_ruleset(str(_project(tmp_path, rs))) == []


@pytest.mark.parametrize("expr,accepted", [
    ("a + b", True), ("-a", True), ("a <= 1", True), ("a / 2", True),
    ("a and b", False), ("a < b < c", False), ("a != b", False), ("f(a)", False),
    ("a * 'x'", False), ("a == None", False),
])
def test_oracle_16_static_combine_check_agrees_with_the_evaluator(expr, accepted):
    import ast
    from reqlite.query import _eval, combine_errors

    env = {"a": 1, "b": 2, "c": 3, "f": len}
    try:
        _eval(ast.parse(expr, mode="eval"), env)
        runs = True
    except ValueError:
        runs = False
    assert runs is accepted, "test premise: the evaluator's own verdict"
    assert (combine_errors(expr, set(env)) == []) is accepted


def test_oracle_17_underscore_keys_in_analyses_are_notes(tmp_path):
    rs = _ruleset()
    rs["analyses"]["_note"] = "a remark, not an analysis"
    assert lint_ruleset(str(_project(tmp_path, rs))) == []


# --- Refusals ---------------------------------------------------------------------------

def test_oracle_18_missing_ruleset_names_the_path(tmp_path):
    (tmp_path / "graph").mkdir()
    with pytest.raises(RulesetError) as e:
        lint_ruleset(str(tmp_path / "graph"))
    assert "ruleset.json" in str(e.value)


def test_oracle_19_invalid_ruleset_says_invalid(tmp_path):
    graph = _project(tmp_path)
    (tmp_path / "ruleset" / "ruleset.json").write_text("{ not json", encoding="utf-8")
    with pytest.raises(RulesetError) as e:
        lint_ruleset(str(graph))
    assert "not valid JSON" in str(e.value)


def test_oracle_20_graph_directory_need_not_exist(tmp_path):
    graph = _project(tmp_path, graph=False)
    assert not graph.exists()
    assert lint_ruleset(str(graph)) == []
    result, t = _check(graph)
    assert "findings" in result and len(t.calls) == 1


# --- Inferential half -------------------------------------------------------------------

def test_oracle_21_formal_findings_gate_the_inferential_half(tmp_path):
    rs = _ruleset()
    rs["types"]["SRC"]["quality_prompt"] = "prompts/missing.md"
    result, t = _check(_project(tmp_path, rs))
    assert t.calls == []
    assert [f["category"] for f in result["formal"]] == ["missing_prompt_file"]
    assert "findings" not in result
    assert result["inferential"].startswith("not run")


def test_oracle_22_compiled_input_holds_ruleset_and_quality_prompts_only(tmp_path):
    graph = _project(tmp_path)
    _, t = _check(graph)
    prompt = t.last["prompt"]
    raw = (tmp_path / "ruleset" / "ruleset.json").read_text(encoding="utf-8")
    assert "## Ruleset JSON\n\n" + raw in prompt
    assert "## Prompt: SRC.quality_prompt (prompts/src_quality.md)\n\n" + SRC_PROMPT in prompt
    assert "## Prompt: UC.quality_prompt (prompts/uc_quality.md)\n\n" + UC_PROMPT in prompt
    assert CONSISTENCY_PROMPT not in prompt


def test_oracle_23_the_instruction_is_the_engines(tmp_path):
    rs = _ruleset(prompts={"consistency": "prompts/consistency.md",
                           "ruleset": "prompts/ruleset_consistency.md"})
    graph = _project(tmp_path, rs, prompts={
        "prompts/src_quality.md": SRC_PROMPT,
        "prompts/uc_quality.md": UC_PROMPT,
        "prompts/consistency.md": CONSISTENCY_PROMPT,
        "prompts/ruleset_consistency.md": "PROJECT_SUPPLIED_CHECKER"})
    _, t = _check(graph)
    prompt = t.last["prompt"]
    assert prompt.startswith(engine_prompt())
    assert "PROJECT_SUPPLIED_CHECKER" not in prompt


def test_oracle_24_engine_prompt_ships_in_the_package():
    from importlib.resources import files

    text = (files("reqlite") / "prompts" / "ruleset_consistency.md").read_text(
        encoding="utf-8")
    assert text.strip() and text == engine_prompt()
    for category in ("decision_collision", "unstatable_discriminator",
                     "prior_leakage", "term_conflict"):
        assert category in text


def test_oracle_24b_engine_prompt_is_declared_package_data():
    import tomllib

    data = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    patterns = data["tool"]["setuptools"]["package-data"]["reqlite"]
    assert "prompts/*.md" in patterns


def test_oracle_25_isolation_is_the_review_runners(tmp_path):
    from reqlite.review import SYSTEM_PROMPT as ITEM_SYSTEM_PROMPT

    _, t = _check(_project(tmp_path))
    o = t.last["options"]
    assert o["setting_sources"] == []
    assert o["tools"] == []
    assert o["strict_mcp_config"] is True and o["mcp_servers"] == {}
    assert o["max_turns"] == 1
    for tool in ("Read", "Bash", "Agent", "Task"):
        assert tool in o["disallowed_tools"]
    assert o["system_prompt"].strip() and o["system_prompt"] != ITEM_SYSTEM_PROMPT


def test_oracle_26a_no_credential_refuses(tmp_path):
    t = FakeTransport(_semantic())
    with pytest.raises(MissingCredentialError):
        _check(_project(tmp_path), transport=t, key=None)
    assert t.calls == []


def test_oracle_26b_key_and_subscription_together_refuse(tmp_path):
    t = FakeTransport(_semantic())
    with pytest.raises(ReviewError):
        _check(_project(tmp_path), transport=t, use_subscription=True)
    assert t.calls == []


def test_oracle_26c_subscription_refuses_a_rerouting_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://proxy")
    t = FakeTransport(_semantic())
    with pytest.raises(ReviewError) as e:
        _check(_project(tmp_path), transport=t, key=None, use_subscription=True)
    assert "ANTHROPIC_BASE_URL" in str(e.value)
    assert t.calls == []


def test_oracle_27_parseable_response_returns_findings(tmp_path):
    result, _ = _check(_project(tmp_path))
    assert result["formal"] == []
    assert isinstance(result["findings"], list) and len(result["findings"]) == 1
    assert result["inferential"] == "ran"


@pytest.mark.parametrize("raw", ["The ruleset looks fine to me.", '{"result": "ok"}'])
def test_oracle_28_unreadable_response_is_reported(tmp_path, raw):
    result, _ = _check(_project(tmp_path), transport=FakeTransport(raw))
    assert "warning" in result and raw[:10] in result["raw_response"]
    assert "findings" not in result


def test_oracle_29_transport_failure_surfaces(tmp_path):
    with pytest.raises(ReviewError) as e:
        _check(_project(tmp_path), transport=FakeTransport(raises=RuntimeError("reset")))
    assert "reset" in str(e.value)


def test_oracle_29b_ruleset_check_has_a_longer_ceiling(tmp_path, monkeypatch):
    import asyncio
    import reqlite.review as R

    _, t = _check(_project(tmp_path))
    assert t.last["options"]["timeout_s"] > R.REVIEW_TIMEOUT_S

    class FakeOptions:
        def __init__(self, **kw):
            assert "timeout_s" not in kw, "the SDK must not receive the runner's own key"

    async def slow_query(*, prompt, options):
        await asyncio.sleep(5)
        yield None

    monkeypatch.setattr(R, "_load_sdk", lambda: (FakeOptions, slow_query))
    opts = dict(t.last["options"], timeout_s=0.1)
    with pytest.raises(ReviewError) as e:
        R._sdk_transport(prompt="p", options=opts, api_key="sk-ant-x")
    assert "0.1 s" in str(e.value)


def test_oracle_29b_item_review_ceiling_is_unchanged():
    import reqlite.review as R
    from reqlite.review import ReviewRequest

    opts = R._options(ReviewRequest(graph_dir=".", item_id="SRC-001", api_key="k"))
    assert opts["timeout_s"] == R.REVIEW_TIMEOUT_S == 300


# --- The command ------------------------------------------------------------------------

def _cli_transport(monkeypatch, transport):
    import reqlite.review as R
    monkeypatch.setattr(R, "_load_sdk", lambda: (object, object))
    monkeypatch.setattr(R, "_sdk_transport", transport)
    return transport


def _invoke(*args):
    from typer.testing import CliRunner
    from reqlite.cli import app
    return CliRunner().invoke(app, ["check-ruleset", *args])


def test_oracle_30_no_mode_flag_or_key_refuses_and_names_every_way_on(tmp_path, monkeypatch):
    t = _cli_transport(monkeypatch, FakeTransport(_semantic()))
    r = _invoke(str(_project(tmp_path)))
    assert r.exit_code == 1
    for name in ("REQLITE_API_KEY", "--algorithmic", "--gateway"):
        assert name in r.stderr
    assert "subscription" not in r.stderr
    assert r.stdout.strip() == ""
    assert t.calls == []


def test_oracle_30b_key_mode_is_the_default_and_runs_both_halves(tmp_path, monkeypatch):
    monkeypatch.setenv("REQLITE_API_KEY", "sk-ant-envkey")
    t = _cli_transport(monkeypatch, FakeTransport(_semantic()))
    r = _invoke(str(_project(tmp_path)))
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["formal"] == [] and isinstance(out["findings"], list)
    assert t.last["api_key"] == "sk-ant-envkey"


def test_oracle_30c_algorithmic_with_api_key_env_refuses(tmp_path, monkeypatch):
    monkeypatch.setenv("MY_KEY", "sk-ant-envkey")
    t = _cli_transport(monkeypatch, FakeTransport(_semantic()))
    r = _invoke(str(_project(tmp_path)), "--algorithmic", "--api-key-env", "MY_KEY")
    assert r.exit_code == 1
    assert "--algorithmic" in r.stderr and "--api-key-env" in r.stderr
    assert t.calls == []


def test_oracle_31_algorithmic_clean_exits_0_without_a_model(tmp_path, monkeypatch):
    t = _cli_transport(monkeypatch, FakeTransport(_semantic()))
    r = _invoke(str(_project(tmp_path)), "--algorithmic")
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["formal"] == [] and "findings" not in out
    assert out["inferential"] == "not requested"
    assert t.calls == []


def test_oracle_32_algorithmic_runs_without_the_extra(tmp_path, monkeypatch):
    import reqlite.review as R

    def missing():
        raise R.MissingExtraError("the review extra is not installed")

    monkeypatch.setattr(R, "_load_sdk", missing)
    r = _invoke(str(_project(tmp_path)), "--algorithmic")
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["formal"] == []


@pytest.mark.parametrize("mode", ["--algorithmic", "--subscription"])
def test_oracle_33_formal_findings_exit_4(tmp_path, monkeypatch, mode):
    rs = _ruleset(write_conventions={"id_pattern": "^[A-Z+$"})
    t = _cli_transport(monkeypatch, FakeTransport(_semantic()))
    r = _invoke(str(_project(tmp_path, rs)), mode)
    assert r.exit_code == 4, r.output
    out = json.loads(r.stdout)
    assert [f["category"] for f in out["formal"]] == ["invalid_id_pattern"]
    assert "findings" not in out
    assert t.calls == []


def test_oracle_34_subscription_clean_prints_both_halves(tmp_path, monkeypatch):
    t = _cli_transport(monkeypatch, FakeTransport(_semantic()))
    r = _invoke(str(_project(tmp_path)), "--subscription")
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["formal"] == [] and isinstance(out["findings"], list)
    assert t.last["api_key"] is None


def test_oracle_35_unreadable_semantic_response_exits_3(tmp_path, monkeypatch):
    _cli_transport(monkeypatch, FakeTransport("Looks coherent overall."))
    r = _invoke(str(_project(tmp_path)), "--subscription")
    assert r.exit_code == 3
    out = json.loads(r.stdout)
    assert "warning" in out and "raw_response" in out and "findings" not in out


def test_oracle_36_refusal_exits_1_with_reason_on_stderr(tmp_path, monkeypatch):
    t = _cli_transport(monkeypatch, FakeTransport(_semantic()))
    (tmp_path / "graph").mkdir()
    r = _invoke(str(tmp_path / "graph"), "--subscription")
    assert r.exit_code == 1
    assert "ruleset.json" in r.stderr
    assert r.stdout.strip() == ""
    assert t.calls == []


def test_oracle_37_both_mode_flags_refuse(tmp_path, monkeypatch):
    t = _cli_transport(monkeypatch, FakeTransport(_semantic()))
    r = _invoke(str(_project(tmp_path)), "--algorithmic", "--subscription")
    assert r.exit_code == 1
    assert r.stdout.strip() == ""
    assert t.calls == []


def test_oracle_38_model_reaches_the_runner(tmp_path, monkeypatch):
    t = _cli_transport(monkeypatch, FakeTransport(_semantic()))
    r = _invoke(str(_project(tmp_path)), "--subscription", "--model", "claude-haiku-4-5")
    assert r.exit_code == 0, r.output
    assert t.last["options"]["model"] == "claude-haiku-4-5"


def test_oracle_review_62_check_ruleset_takes_gateway(tmp_path, monkeypatch):
    """ORACLES-REVIEW 62: the gateway mode reaches this command's runner too."""
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example.test")
    monkeypatch.setenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "gw-model")
    t = _cli_transport(monkeypatch, FakeTransport(_semantic()))
    r = _invoke(str(_project(tmp_path)), "--gateway")
    assert r.exit_code == 0, r.output
    assert t.last["gateway"].kind == "http" and t.last["api_key"] is None


def test_oracle_review_62_algorithmic_refuses_gateway(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example.test")
    t = _cli_transport(monkeypatch, FakeTransport(_semantic()))
    r = _invoke(str(_project(tmp_path)), "--algorithmic", "--gateway")
    assert r.exit_code == 1
    assert "--algorithmic" in r.stderr and "--gateway" in r.stderr
    assert t.calls == []
