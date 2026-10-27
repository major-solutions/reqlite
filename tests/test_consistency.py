"""Tests for the consistency check. One test per oracle in ORACLES-CONSISTENCY.md.

The model is never called: the check takes an injected `transport`. Nothing here asserts
on finding content (see ORACLES-CONSISTENCY.md).
"""

import json
import re
from pathlib import Path

import pytest

from reqlite.consistency import ConsistencyRequest, check_consistency
from reqlite.review import MissingCredentialError, ReviewError

LIBRARY_RULESET = Path(__file__).parent.parent / "src" / "reqlite" / "rulesets" / "reqlite"

INSTRUCTION = "CONSISTENCY_INSTRUCTION_TEXT"
SRC_DESC = "SRC_DESCRIPTION_FROM_RULESET"
FR_DESC = "FR_DESCRIPTION_FROM_RULESET"
UC_DESC = "UC_DESCRIPTION_FROM_RULESET"


def _ruleset(**over):
    rs = {
        "types": {
            "SRC": {"label": "Source item", "description": SRC_DESC,
                    "quality_prompt": "prompts/src_quality.md"},
            "FR": {"label": "Functional requirement", "description": FR_DESC,
                   "quality_prompt": "prompts/fr_quality.md"},
            "UC": {"label": "Use case", "description": UC_DESC,
                   "quality_prompt": "prompts/uc_quality.md"},
        },
        "reference_conventions": {
            "semantics": "LINK_SEMANTICS_FROM_RULESET",
            "traceability_rule": "TRACEABILITY_RULE_FROM_RULESET",
        },
        "prompts": {"consistency": "prompts/consistency.md"},
    }
    rs.update(over)
    return rs


#: FR-001 → SRC-002 → SRC-001; UC-001 → FR-001 (a dependent of the target).
_ITEMS = {
    "SRC-001-root.md": "# SRC-001: Root\n\nROOT_BODY\n",
    "SRC-002-middle.md": "# SRC-002: Middle\n\nRests on [SRC-001](SRC-001-root.md). "
                         "MIDDLE_BODY\n",
    "FR-001-target.md": "# FR-001: Target\n\nRests on [SRC-002](SRC-002-middle.md). "
                        "TARGET_BODY\n",
    "UC-001-dependent.md": "# UC-001: Dependent\n\nRests on [FR-001](FR-001-target.md). "
                           "DEPENDENT_BODY\n",
    "SRC-009-alone.md": "# SRC-009: Alone\n\nNo links.\n",
}


def _project(tmp_path, ruleset=None, items=None, prompt=INSTRUCTION, extra_files=None):
    graph = tmp_path / "graph"
    graph.mkdir()
    for name, text in (items if items is not None else _ITEMS).items():
        (graph / name).write_text(text, encoding="utf-8")
    rs_dir = tmp_path / "ruleset"
    (rs_dir / "prompts").mkdir(parents=True)
    if prompt is not None:
        (rs_dir / "prompts" / "consistency.md").write_text(prompt, encoding="utf-8")
    for rel, text in (extra_files or {}).items():
        (rs_dir / rel).write_text(text, encoding="utf-8")
    rs = ruleset if ruleset is not None else _ruleset()
    (rs_dir / "ruleset.json").write_text(json.dumps(rs, indent=2), encoding="utf-8")
    return graph


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


FULL_SCOPE = "SRC-001, SRC-002, FR-001"


def _response(target="FR-001", scope=FULL_SCOPE, findings=None):
    out = {"target": target, "findings": findings if findings is not None else [
        {"category": "gap", "items": ["FR-001"], "summary": "s", "reasoning": "r",
         "severity": "low"}]}
    if scope is not None:
        out["scope"] = scope
    return json.dumps(out)


def _check(graph, item_id="FR-001", transport=None, key="sk-ant-test", **kw):
    transport = transport if transport is not None else FakeTransport(_response())
    result = check_consistency(
        ConsistencyRequest(graph_dir=str(graph), item_id=item_id, api_key=key, **kw),
        transport=transport)
    return result, transport


def _refused(graph, item_id="FR-001", **kw):
    t = FakeTransport(_response())
    with pytest.raises(ReviewError) as e:
        _check(graph, item_id, transport=t, **kw)
    assert t.calls == []
    return str(e.value)


def _first_item(prompt):
    return min(prompt.index(m) for m in ("ROOT_BODY", "MIDDLE_BODY", "TARGET_BODY")
               if m in prompt)


# --- Input assembly ---------------------------------------------------------------------

def test_oracle_1_instruction_is_the_projects_prompt(tmp_path):
    _, t = _check(_project(tmp_path))
    assert t.last["prompt"].startswith(INSTRUCTION)


def test_oracle_2_type_descriptions_come_from_the_ruleset(tmp_path):
    _, t = _check(_project(tmp_path))
    prompt = t.last["prompt"]
    types_at = prompt.index("## Item types")
    assert prompt.index(INSTRUCTION) < types_at < _first_item(prompt)
    section = prompt[types_at:_first_item(prompt)]
    for prefix, label, desc in (("SRC", "Source item", SRC_DESC),
                                ("FR", "Functional requirement", FR_DESC),
                                ("UC", "Use case", UC_DESC)):
        assert prefix in section and label in section and desc in section


def test_oracle_3_repository_prompt_carries_no_type_system_copy():
    rs = json.loads((LIBRARY_RULESET / "ruleset.json").read_text(encoding="utf-8"))
    rel = rs["prompts"]["consistency"]
    text = (LIBRARY_RULESET / rel).read_text(encoding="utf-8")
    assert not re.search(r"^- [A-Z]+ \(", text, re.MULTILINE)
    for name, tdef in rs["types"].items():
        assert tdef["description"] not in text, name
        for sentence in tdef["description"].split(". ")[:1]:
            assert sentence not in text, name


def test_oracle_4_reference_conventions_from_the_ruleset(tmp_path):
    _, t = _check(_project(tmp_path))
    prompt = t.last["prompt"]
    at = prompt.index("## Reference conventions")
    assert at < _first_item(prompt)
    assert "LINK_SEMANTICS_FROM_RULESET" in prompt[at:]
    assert "TRACEABILITY_RULE_FROM_RULESET" in prompt[at:]


def test_oracle_4b_no_reference_conventions_section_when_undeclared(tmp_path):
    rs = _ruleset()
    del rs["reference_conventions"]
    _, t = _check(_project(tmp_path, rs))
    assert "## Reference conventions" not in t.last["prompt"]


def test_oracle_5_default_scope_is_the_full_transitive_chain(tmp_path):
    _, t = _check(_project(tmp_path))
    prompt = t.last["prompt"]
    for marker in ("ROOT_BODY", "MIDDLE_BODY", "TARGET_BODY"):
        assert marker in prompt
    assert "DEPENDENT_BODY" not in prompt and "UC-001" not in prompt


def test_oracle_6_foundations_first_target_last(tmp_path):
    _, t = _check(_project(tmp_path))
    prompt = t.last["prompt"]
    assert prompt.index("ROOT_BODY") < prompt.index("MIDDLE_BODY") < prompt.index("TARGET_BODY")


@pytest.mark.parametrize("depth,present,absent", [
    (1, ["TARGET_BODY", "MIDDLE_BODY"], ["ROOT_BODY"]),
    (2, ["TARGET_BODY", "MIDDLE_BODY", "ROOT_BODY"], []),
])
def test_oracle_7_depth_bounds_the_chain(tmp_path, depth, present, absent):
    _, t = _check(_project(tmp_path), depth=depth,
                  transport=FakeTransport(_response(scope=None)))
    prompt = t.last["prompt"]
    assert all(m in prompt for m in present)
    assert not any(m in prompt for m in absent)


@pytest.mark.parametrize("depth", [0, -1])
def test_oracle_8_depth_below_one_is_refused(tmp_path, depth):
    assert "depth" in _refused(_project(tmp_path), depth=depth)


# --- Refusals ---------------------------------------------------------------------------

def test_oracle_9_unknown_item_is_refused(tmp_path):
    assert "FR-404" in _refused(_project(tmp_path), "FR-404")


@pytest.mark.parametrize("item_id", ["SRC-009", "SRC-010"])
def test_oracle_10_item_with_no_foundations_is_refused(tmp_path, item_id):
    items = dict(_ITEMS)
    items["SRC-010-dangling.md"] = "# SRC-010: Dangling\n\nSee [SRC-404](SRC-404-gone.md).\n"
    msg = _refused(_project(tmp_path, items=items), item_id)
    assert item_id in msg and "nothing to check" in msg


def test_oracle_11_no_consistency_prompt_declared(tmp_path):
    msg = _refused(_project(tmp_path, _ruleset(prompts={})))
    assert "prompts.consistency" in msg


def test_oracle_12a_declared_prompt_missing(tmp_path):
    rs = _ruleset(prompts={"consistency": "prompts/gone.md"})
    assert "prompts/gone.md" in _refused(_project(tmp_path, rs))


def test_oracle_12b_escaping_prompt_is_refused_and_not_read(tmp_path):
    (tmp_path / "outside.md").write_text("SECRET_OUTSIDE_CONTENT", encoding="utf-8")
    rs = _ruleset(prompts={"consistency": "../outside.md"})
    msg = _refused(_project(tmp_path, rs))
    assert "SECRET_OUTSIDE_CONTENT" not in msg


def test_oracle_13a_missing_ruleset(tmp_path):
    graph = _project(tmp_path)
    (tmp_path / "ruleset" / "ruleset.json").unlink()
    assert "ruleset.json" in _refused(graph)


def test_oracle_13b_invalid_ruleset(tmp_path):
    graph = _project(tmp_path)
    (tmp_path / "ruleset" / "ruleset.json").write_text("{ nope", encoding="utf-8")
    assert "not valid JSON" in _refused(graph)


def test_oracle_14_cycle_in_the_chain_is_refused(tmp_path):
    items = {
        "FR-001-a.md": "# FR-001: A\n\n[SRC-001](SRC-001-b.md)\n",
        "SRC-001-b.md": "# SRC-001: B\n\n[FR-001](FR-001-a.md)\n",
    }
    assert "cycle" in _refused(_project(tmp_path, items=items)).lower()


def test_oracle_15_unparseable_graph_is_refused(tmp_path):
    graph = _project(tmp_path)
    (graph / "SRC-003-mismatch.md").write_text(
        "---\nid: SRC-999\n---\n\n# SRC-003: Mismatch\n\nBody.\n", encoding="utf-8")
    assert "parse" in _refused(graph).lower()


# --- Scope and envelope -----------------------------------------------------------------

def test_oracle_16_scope_is_the_engines_compiled_ids(tmp_path):
    result, _ = _check(_project(tmp_path),
                       transport=FakeTransport(_response(scope="whatever, the model, says")))
    assert result["scope"] == ["SRC-001", "SRC-002", "FR-001"]


@pytest.mark.parametrize("scope", [" FR-001 ,SRC-001,  SRC-002",
                                   ["FR-001", "SRC-002", "SRC-001"]])
def test_oracle_17_matching_scope_carries_no_mismatch(tmp_path, scope):
    result, _ = _check(_project(tmp_path), transport=FakeTransport(_response(scope=scope)))
    assert "scope_mismatch" not in result


def test_oracle_18a_differing_scope_is_flagged(tmp_path):
    result, _ = _check(_project(tmp_path),
                       transport=FakeTransport(_response(scope="FR-001, SRC-002, UC-001")))
    assert result["scope_mismatch"] == {"missing": ["SRC-001"], "extra": ["UC-001"]}


def test_oracle_18b_absent_scope_is_all_missing(tmp_path):
    result, _ = _check(_project(tmp_path), transport=FakeTransport(_response(scope=None)))
    assert result["scope_mismatch"] == {"missing": ["SRC-001", "SRC-002", "FR-001"],
                                        "extra": []}


def test_oracle_19_target_mismatch_is_flagged(tmp_path):
    result, _ = _check(_project(tmp_path),
                       transport=FakeTransport(_response(target="SRC-002")))
    assert result["target"] == "FR-001" and result["target_mismatch"] == "SRC-002"


def test_oracle_19b_matching_target_carries_no_mismatch(tmp_path):
    result, _ = _check(_project(tmp_path))
    assert "target_mismatch" not in result


def test_oracle_20_dangling_references_are_reported(tmp_path):
    items = dict(_ITEMS)
    items["SRC-002-middle.md"] = ("# SRC-002: Middle\n\nRests on [SRC-001](SRC-001-root.md) "
                                  "and [SRC-404](SRC-404-gone.md). MIDDLE_BODY\n")
    result, t = _check(_project(tmp_path, items=items))
    assert result["unresolved"] == ["SRC-404"]
    assert len(t.calls) == 1
    assert "SRC-404" not in result["scope"]


def test_oracle_20b_no_unresolved_key_when_none(tmp_path):
    result, _ = _check(_project(tmp_path))
    assert "unresolved" not in result


# --- The runner -------------------------------------------------------------------------

def test_oracle_21_isolation_and_own_system_prompt(tmp_path):
    from reqlite.review import SYSTEM_PROMPT as ITEM_SYSTEM_PROMPT
    from reqlite.ruleset_check import SYSTEM_PROMPT as RULESET_SYSTEM_PROMPT

    _, t = _check(_project(tmp_path))
    o = t.last["options"]
    assert o["setting_sources"] == []
    assert o["tools"] == []
    assert o["strict_mcp_config"] is True and o["mcp_servers"] == {}
    assert o["max_turns"] == 1
    for tool in ("Read", "Bash", "Agent", "Task"):
        assert tool in o["disallowed_tools"]
    assert o["system_prompt"].strip()
    assert o["system_prompt"] not in (ITEM_SYSTEM_PROMPT, RULESET_SYSTEM_PROMPT)


def test_oracle_22a_no_credential_refuses(tmp_path):
    t = FakeTransport(_response())
    with pytest.raises(MissingCredentialError):
        _check(_project(tmp_path), transport=t, key=None)
    assert t.calls == []


def test_oracle_22b_key_and_subscription_together_refuse(tmp_path):
    _refused(_project(tmp_path), use_subscription=True)


def test_oracle_22c_subscription_refuses_a_rerouting_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://proxy")
    msg = _refused(_project(tmp_path), key=None, use_subscription=True)
    assert "ANTHROPIC_BASE_URL" in msg


def test_oracle_23_parseable_response(tmp_path):
    result, _ = _check(_project(tmp_path))
    assert result["target"] == "FR-001"
    assert result["scope"] == ["SRC-001", "SRC-002", "FR-001"]
    assert isinstance(result["findings"], list) and len(result["findings"]) == 1


@pytest.mark.parametrize("raw", ["The chain holds together.", '{"target": "FR-001"}'])
def test_oracle_24_unreadable_response_is_reported(tmp_path, raw):
    result, _ = _check(_project(tmp_path), transport=FakeTransport(raw))
    assert "warning" in result and raw[:10] in result["raw_response"]
    assert "findings" not in result


def test_oracle_25_transport_failure_surfaces(tmp_path):
    with pytest.raises(ReviewError) as e:
        _check(_project(tmp_path), transport=FakeTransport(raises=RuntimeError("reset")))
    assert "reset" in str(e.value)


def test_oracle_26_own_longer_ceiling(tmp_path):
    import reqlite.review as R

    _, t = _check(_project(tmp_path))
    assert t.last["options"]["timeout_s"] > R.REVIEW_TIMEOUT_S == 300


# --- The command ------------------------------------------------------------------------

def _cli_transport(monkeypatch, transport):
    import reqlite.review as R
    monkeypatch.setattr(R, "_load_sdk", lambda: (object, object))
    monkeypatch.setattr(R, "_sdk_transport", transport)
    return transport


def _invoke(*args):
    from typer.testing import CliRunner
    from reqlite.cli import app
    return CliRunner().invoke(app, ["consistency", *args])


def test_oracle_27_without_any_credential_refuses(tmp_path, monkeypatch):
    t = _cli_transport(monkeypatch, FakeTransport(_response()))
    r = _invoke("FR-001", str(_project(tmp_path)))
    assert r.exit_code == 1
    assert "REQLITE_API_KEY" in r.stderr and "--subscription" in r.stderr
    assert r.stdout.strip() == ""
    assert t.calls == []


def test_oracle_27b_key_mode_is_the_default(tmp_path, monkeypatch):
    monkeypatch.setenv("REQLITE_API_KEY", "sk-ant-envkey")
    t = _cli_transport(monkeypatch, FakeTransport(_response()))
    r = _invoke("FR-001", str(_project(tmp_path)))
    assert r.exit_code == 0, r.output
    assert t.last["api_key"] == "sk-ant-envkey"


def test_oracle_28_subscription_prints_the_result(tmp_path, monkeypatch):
    t = _cli_transport(monkeypatch, FakeTransport(_response()))
    r = _invoke("FR-001", str(_project(tmp_path)), "--subscription")
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["target"] == "FR-001" and isinstance(out["findings"], list)
    assert out["scope"] == ["SRC-001", "SRC-002", "FR-001"]
    assert t.last["api_key"] is None


def test_oracle_29_depth_reaches_the_compile_step(tmp_path, monkeypatch):
    _cli_transport(monkeypatch, FakeTransport(_response()))
    r = _invoke("FR-001", str(_project(tmp_path)), "--subscription", "--depth", "1")
    assert r.exit_code == 0, r.output
    assert json.loads(r.stdout)["scope"] == ["SRC-002", "FR-001"]


def test_oracle_30_refusal_exits_1_with_reason_on_stderr(tmp_path, monkeypatch):
    t = _cli_transport(monkeypatch, FakeTransport(_response()))
    r = _invoke("FR-404", str(_project(tmp_path)), "--subscription")
    assert r.exit_code == 1
    assert "FR-404" in r.stderr and r.stdout.strip() == ""
    assert t.calls == []


def test_oracle_31_unreadable_response_exits_3(tmp_path, monkeypatch):
    _cli_transport(monkeypatch, FakeTransport("All consistent."))
    r = _invoke("FR-001", str(_project(tmp_path)), "--subscription")
    assert r.exit_code == 3
    out = json.loads(r.stdout)
    assert "warning" in out and "raw_response" in out and "findings" not in out


def test_oracle_32_model_reaches_the_runner(tmp_path, monkeypatch):
    t = _cli_transport(monkeypatch, FakeTransport(_response()))
    r = _invoke("FR-001", str(_project(tmp_path)), "--subscription",
                "--model", "claude-haiku-4-5")
    assert r.exit_code == 0, r.output
    assert t.last["options"]["model"] == "claude-haiku-4-5"


def test_oracle_33_depth_zero_is_a_usage_error(tmp_path, monkeypatch):
    t = _cli_transport(monkeypatch, FakeTransport(_response()))
    r = _invoke("FR-001", str(_project(tmp_path)), "--subscription", "--depth", "0")
    assert r.exit_code == 2
    assert t.calls == []


def test_oracle_review_62_consistency_takes_gateway(tmp_path, monkeypatch):
    """ORACLES-REVIEW 62: the gateway mode reaches this command's runner too."""
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example.test")
    monkeypatch.setenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "gw-model")
    t = _cli_transport(monkeypatch, FakeTransport(_response()))
    r = _invoke("FR-001", str(_project(tmp_path)), "--gateway")
    assert r.exit_code == 0, r.output
    assert t.last["gateway"].kind == "http" and t.last["api_key"] is None
    assert t.last["options"]["model"] == "gw-model"
