"""Tests for the review runner. One test per oracle in ORACLES-REVIEW.md.

The model is never called: `review_item` takes an injected `transport`. Nothing here
asserts on finding content — measured variance is ±1 finding per item on identical input,
so such an assertion would test sampling noise (see ORACLES-REVIEW.md).
"""

import json

import pytest

from reqlite.review import (
    ReviewError,
    MissingExtraError,
    MissingCredentialError,
    ReviewRequest,
    review_item,
)


# --- fixtures -------------------------------------------------------------

SRC_PROMPT = "You are reviewing one SRC item. Emit findings JSON."
UC_PROMPT = "You are reviewing one UC item. Emit findings JSON."


def _project(tmp_path, types=None, prompts=None):
    """Build a graph + sibling ruleset laid out per ADR-016."""
    graph = tmp_path / "graph"
    graph.mkdir()
    (graph / "SRC-001-root.md").write_text(
        "# SRC-001: Root\n\nThe foundation claim.\n", encoding="utf-8"
    )
    (graph / "SRC-002-dependent.md").write_text(
        "# SRC-002: Dependent\n\nRests on [SRC-001](SRC-001-root.md). "
        "DEPENDENT_BODY_MARKER\n",
        encoding="utf-8",
    )
    (graph / "UC-001-usecase.md").write_text(
        "---\nactor: Analyst\n---\n\n# UC-001: A use case\n\nSteps here.\n",
        encoding="utf-8",
    )

    rs_dir = tmp_path / "ruleset"
    (rs_dir / "prompts").mkdir(parents=True)
    for rel, text in (prompts if prompts is not None else
                      {"prompts/src_quality.md": SRC_PROMPT,
                       "prompts/uc_quality.md": UC_PROMPT}).items():
        (rs_dir / rel).write_text(text, encoding="utf-8")

    ruleset = {"types": types if types is not None else {
        "SRC": {"quality_prompt": "prompts/src_quality.md"},
        "UC": {"quality_prompt": "prompts/uc_quality.md"},
    }}
    (rs_dir / "ruleset.json").write_text(json.dumps(ruleset), encoding="utf-8")
    return graph


class FakeTransport:
    """Records how it was called; returns a canned response."""

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


def _findings(target="SRC-001"):
    return json.dumps({"target": target, "findings": [
        {"category": "x", "items": [target], "summary": "s",
         "reasoning": "r", "severity": "low"}]})


def _run(graph, item_id="SRC-001", transport=None, key="sk-ant-test", **kw):
    transport = transport or FakeTransport(_findings(item_id))
    result = review_item(
        ReviewRequest(graph_dir=str(graph), item_id=item_id, api_key=key, **kw),
        transport=transport,
    )
    return result, transport


# --- Input assembly -------------------------------------------------------

def test_oracle_1_per_type_quality_prompt_comes_from_the_ruleset(tmp_path):
    graph = _project(tmp_path)
    _, t = _run(graph, "SRC-001")
    assert SRC_PROMPT in t.last["prompt"]


def test_oracle_1b_a_different_type_selects_its_own_prompt(tmp_path):
    graph = _project(tmp_path)
    _, t = _run(graph, "UC-001", transport=FakeTransport(_findings("UC-001")))
    assert UC_PROMPT in t.last["prompt"]
    assert SRC_PROMPT not in t.last["prompt"]


def test_oracle_2_review_is_item_scoped_not_the_dependency_chain(tmp_path):
    graph = _project(tmp_path)
    _, t = _run(graph, "SRC-002", transport=FakeTransport(_findings("SRC-002")))
    assert "DEPENDENT_BODY_MARKER" in t.last["prompt"]
    assert "The foundation claim" not in t.last["prompt"]


def test_oracle_3_runner_compiles_its_own_input_from_an_id(tmp_path):
    graph = _project(tmp_path)
    _, t = _run(graph, "SRC-001")
    # The caller supplied only an id; the prompt holds both halves regardless.
    assert SRC_PROMPT in t.last["prompt"]
    assert "SRC-001" in t.last["prompt"]


def test_oracle_4_type_without_a_quality_prompt_errors_and_never_calls(tmp_path):
    graph = _project(tmp_path, types={
        "SRC": {"quality_prompt": None},
        "UC": {"quality_prompt": "prompts/uc_quality.md"},
    })
    t = FakeTransport(_findings())
    with pytest.raises(ReviewError) as e:
        review_item(ReviewRequest(graph_dir=str(graph), item_id="SRC-001",
                                  api_key="sk-ant-test"), transport=t)
    assert "SRC" in str(e.value)
    assert "UC" in str(e.value), "should list the types that do have a prompt"
    assert t.calls == []


def test_oracle_5_unknown_item_errors_and_never_calls(tmp_path):
    graph = _project(tmp_path)
    t = FakeTransport(_findings())
    with pytest.raises(ReviewError) as e:
        review_item(ReviewRequest(graph_dir=str(graph), item_id="SRC-999",
                                  api_key="sk-ant-test"), transport=t)
    assert "SRC-999" in str(e.value)
    assert t.calls == []


def test_oracle_6_missing_ruleset_names_the_expected_path(tmp_path):
    graph = tmp_path / "graph"
    graph.mkdir()
    (graph / "SRC-001-root.md").write_text("# SRC-001: Root\n\nBody.\n", encoding="utf-8")
    t = FakeTransport(_findings())
    with pytest.raises(ReviewError) as e:
        review_item(ReviewRequest(graph_dir=str(graph), item_id="SRC-001",
                                  api_key="sk-ant-test"), transport=t)
    assert "ruleset.json" in str(e.value)
    assert t.calls == []


# --- Isolation ------------------------------------------------------------

def test_oracle_7_setting_sources_is_empty(tmp_path):
    graph = _project(tmp_path)
    _, t = _run(graph)
    assert t.last["options"]["setting_sources"] == []


def test_oracle_8_system_prompt_is_the_runners_own(tmp_path):
    graph = _project(tmp_path)
    _, t = _run(graph)
    sp = t.last["options"]["system_prompt"]
    assert isinstance(sp, str) and sp.strip()


def test_oracle_9_reviewer_gets_no_tools(tmp_path):
    graph = _project(tmp_path)
    _, t = _run(graph)
    assert t.last["options"]["tools"] == [], "base toolset must be empty"
    disallowed = t.last["options"]["disallowed_tools"]
    for tool in ("Read", "Glob", "Grep", "Bash", "Agent", "Task"):
        assert tool in disallowed
    assert t.last["options"]["strict_mcp_config"] is True
    assert t.last["options"]["mcp_servers"] == {}


def test_oracle_10_single_turn(tmp_path):
    graph = _project(tmp_path)
    _, t = _run(graph)
    assert t.last["options"]["max_turns"] == 1


def test_oracle_11_no_session_carried_between_reviews(tmp_path):
    graph = _project(tmp_path)
    t = FakeTransport(_findings())
    for item in ("SRC-001", "SRC-002"):
        t._response = _findings(item)
        review_item(ReviewRequest(graph_dir=str(graph), item_id=item,
                                  api_key="sk-ant-test"), transport=t)
    assert len(t.calls) == 2
    for call in t.calls:
        for leaky in ("resume", "continue_conversation", "session_id", "fork_session"):
            assert not call["options"].get(leaky), f"{leaky} must not be carried"
    # and the second prompt must not contain the first item's body
    assert "The foundation claim" not in t.calls[1]["prompt"]


# --- Credentials ----------------------------------------------------------

def test_oracle_12_no_credential_refuses_and_never_calls(tmp_path):
    graph = _project(tmp_path)
    t = FakeTransport(_findings())
    with pytest.raises(MissingCredentialError) as e:
        review_item(ReviewRequest(graph_dir=str(graph), item_id="SRC-001",
                                  api_key=None), transport=t)
    assert "key" in str(e.value).lower()
    assert t.calls == []


def test_oracle_13_key_is_passed_explicitly_not_through_the_environment(
        tmp_path, monkeypatch):
    graph = _project(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    _, t = _run(graph, key="sk-ant-explicit")
    assert t.last["api_key"] == "sk-ant-explicit"
    import os
    assert "ANTHROPIC_API_KEY" not in os.environ, "runner must not set the ambient var"


# --- Response handling ----------------------------------------------------

def test_oracle_13b_key_reaches_the_child_process_env_not_the_parent(monkeypatch):
    """A transport that accepts a key and drops it leaves the child falling back to
    whatever login exists — the SRC-072 violation oracle 13 cannot catch, because a fake
    records the key it was handed regardless of whether the real transport uses it."""
    import os
    import reqlite.review as R

    captured = {}

    class FakeOptions:
        def __init__(self, **kw):
            captured.update(kw)

    def fake_query(*, prompt, options):
        raise AssertionError("not reached; we only inspect option construction")

    monkeypatch.setattr(R, "_load_sdk", lambda: (FakeOptions, fake_query))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    try:
        R._sdk_transport(prompt="p", options=R._options(
            ReviewRequest(graph_dir=".", item_id="SRC-001", api_key="sk-ant-child")
        ), api_key="sk-ant-child")
    except AssertionError:
        pass  # option construction is what we are asserting on

    assert captured.get("env", {}).get("ANTHROPIC_API_KEY") == "sk-ant-child", (
        "the key must be handed to the spawned process"
    )
    assert "ANTHROPIC_API_KEY" not in os.environ, "and must not touch the parent"


def test_oracle_14_parseable_response_returns_findings_with_target(tmp_path):
    graph = _project(tmp_path)
    result, _ = _run(graph, "SRC-001")
    assert result["target"] == "SRC-001"
    assert isinstance(result["findings"], list)


def test_oracle_15_unparseable_response_warns_and_keeps_the_raw(tmp_path):
    graph = _project(tmp_path)
    result, _ = _run(graph, transport=FakeTransport("I could not comply, sorry."))
    assert "warning" in result
    assert "could not comply" in result["raw_response"]
    assert "findings" not in result, "an empty findings list would read as 'item is clean'"


def test_oracle_16_transport_failure_surfaces(tmp_path):
    graph = _project(tmp_path)
    t = FakeTransport(raises=RuntimeError("connection reset"))
    with pytest.raises(ReviewError) as e:
        review_item(ReviewRequest(graph_dir=str(graph), item_id="SRC-001",
                                  api_key="sk-ant-test"), transport=t)
    assert "connection reset" in str(e.value)


# --- The extra ------------------------------------------------------------

def test_oracle_19_invalid_ruleset_says_invalid_not_missing(tmp_path):
    graph = _project(tmp_path)
    (tmp_path / "ruleset" / "ruleset.json").write_text("{ not json", encoding="utf-8")
    t = FakeTransport(_findings())
    with pytest.raises(ReviewError) as e:
        review_item(ReviewRequest(graph_dir=str(graph), item_id="SRC-001",
                                  api_key="sk-ant-test"), transport=t)
    assert "not valid JSON" in str(e.value)
    assert t.calls == []


def test_oracle_20_declared_but_absent_prompt_file_names_both(tmp_path):
    graph = _project(tmp_path, types={"SRC": {"quality_prompt": "prompts/missing.md"}})
    t = FakeTransport(_findings())
    with pytest.raises(ReviewError) as e:
        review_item(ReviewRequest(graph_dir=str(graph), item_id="SRC-001",
                                  api_key="sk-ant-test"), transport=t)
    msg = str(e.value)
    assert "prompts/missing.md" in msg, "must name the declaration"
    assert "missing.md" in msg and "ruleset" in msg.lower()
    assert t.calls == []


def test_oracle_21_malformed_item_id_is_refused(tmp_path):
    graph = _project(tmp_path)
    t = FakeTransport(_findings())
    with pytest.raises(ReviewError) as e:
        review_item(ReviewRequest(graph_dir=str(graph), item_id="nonsense",
                                  api_key="sk-ant-test"), transport=t)
    assert "nonsense" in str(e.value)
    assert t.calls == []


def test_oracle_23_unparseable_graph_is_refused_not_raised(tmp_path):
    graph = _project(tmp_path)
    # a frontmatter id contradicting the filename is a hard parse error
    (graph / "SRC-003-mismatch.md").write_text(
        "---\nid: SRC-999\n---\n\n# SRC-003: Mismatch\n\nBody.\n", encoding="utf-8"
    )
    t = FakeTransport(_findings())
    with pytest.raises(ReviewError) as e:
        review_item(ReviewRequest(graph_dir=str(graph), item_id="SRC-001",
                                  api_key="sk-ant-test"), transport=t)
    assert "parse" in str(e.value).lower()
    assert t.calls == []


def test_oracle_22_non_directory_graph_dir_is_refused(tmp_path):
    missing = tmp_path / "not-a-dir"
    t = FakeTransport(_findings())
    with pytest.raises(ReviewError) as e:
        review_item(ReviewRequest(graph_dir=str(missing), item_id="SRC-001",
                                  api_key="sk-ant-test"), transport=t)
    assert "not-a-dir" in str(e.value)
    assert t.calls == []


def test_oracle_17_missing_extra_fails_with_the_install_command(tmp_path, monkeypatch):
    graph = _project(tmp_path)
    import reqlite.review as R
    monkeypatch.setattr(R, "_load_sdk", lambda: (_ for _ in ()).throw(
        MissingExtraError('the review extra is not installed: pip install "reqlite[review]"')))
    with pytest.raises(MissingExtraError) as e:
        review_item(ReviewRequest(graph_dir=str(graph), item_id="SRC-001",
                                  api_key="sk-ant-test"))
    assert "reqlite[review]" in str(e.value)


def test_oracle_17_the_real_message_names_an_install_that_works(monkeypatch):
    # The test above substitutes the error, so it never reads the message _load_sdk
    # builds. reqlite is not on PyPI: `pip install "reqlite[review]"` fails today and
    # would install whoever registers the name later.
    import sys
    import reqlite.review as R
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)
    with pytest.raises(MissingExtraError) as e:
        R._load_sdk()
    assert 'pip install "reqlite[review]"' not in str(e.value)
    assert '[review]"' in str(e.value)
    assert "run_analysis" not in str(e.value)


def test_oracle_18_importing_the_module_does_not_require_the_sdk():
    import subprocess, sys, textwrap
    # Block the SDK import, then import the module and raise one of its errors.
    code = textwrap.dedent("""
        import sys
        class Blocker:
            def find_module(self, name, path=None):
                if name.startswith("claude_agent_sdk"):
                    raise AssertionError("module scope imported the SDK")
            def find_spec(self, name, path=None, target=None):
                if name.startswith("claude_agent_sdk"):
                    raise AssertionError("module scope imported the SDK")
                return None
        sys.meta_path.insert(0, Blocker())
        import reqlite.review as R
        assert R.ReviewError is not None
        print("ok")
    """)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "ok" in r.stdout


# --- Subscription override (SRC-072) --------------------------------------

def test_oracle_24_subscription_mode_dispatches_without_a_key(tmp_path):
    graph = _project(tmp_path)
    t = FakeTransport(_findings())
    result = review_item(ReviewRequest(graph_dir=str(graph), item_id="SRC-001",
                                       api_key=None, use_subscription=True), transport=t)
    assert t.last["api_key"] is None
    assert result["target"] == "SRC-001"


def test_oracle_25_key_and_subscription_together_are_refused(tmp_path):
    graph = _project(tmp_path)
    t = FakeTransport(_findings())
    with pytest.raises(ReviewError) as e:
        review_item(ReviewRequest(graph_dir=str(graph), item_id="SRC-001",
                                  api_key="sk-ant-test", use_subscription=True), transport=t)
    msg = str(e.value).lower()
    assert "subscription" in msg and "key" in msg
    assert t.calls == []


def test_oracle_26_subscription_blanks_inherited_credentials_in_the_child(monkeypatch):
    """The SDK overlays options.env on the parent environment and never removes a
    variable, so an inherited key would beat the subscription unless blanked."""
    import os
    import reqlite.review as R

    captured = {}

    class FakeOptions:
        def __init__(self, **kw):
            captured.update(kw)

    def fake_query(*, prompt, options):
        raise AssertionError("not reached; we only inspect option construction")

    monkeypatch.setattr(R, "_load_sdk", lambda: (FakeOptions, fake_query))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-inherited")

    try:
        R._sdk_transport(prompt="p", options=R._options(
            ReviewRequest(graph_dir=".", item_id="SRC-001", api_key=None,
                          use_subscription=True)
        ), api_key=None)
    except AssertionError:
        pass

    env = captured.get("env", {})
    assert env.get("ANTHROPIC_API_KEY") == "", "an inherited key must be blanked"
    assert env.get("ANTHROPIC_AUTH_TOKEN") == "", "an inherited token must be blanked"
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-ant-inherited", "parent untouched"


# --- The `reqlite review` command -----------------------------------------

def _cli_transport(monkeypatch, transport):
    """Route the CLI's real-transport path to a fake, with the extra 'present'."""
    import reqlite.review as R
    monkeypatch.setattr(R, "_load_sdk", lambda: (object, object))
    monkeypatch.setattr(R, "_sdk_transport", transport)
    return transport


def _invoke(*args):
    from typer.testing import CliRunner
    from reqlite.cli import app
    return CliRunner().invoke(app, ["review", *args])


def test_oracle_27_cli_without_any_credential_refuses_and_names_the_ways_on(
        tmp_path, monkeypatch):
    graph = _project(tmp_path)
    t = _cli_transport(monkeypatch, FakeTransport(_findings()))
    r = _invoke("SRC-001", str(graph))
    assert r.exit_code == 1
    for name in ("REQLITE_API_KEY", "--api-key-env", "--subscription"):
        assert name in r.stderr
    assert r.stdout.strip() == ""
    assert t.calls == []


def test_oracle_28_cli_subscription_prints_findings_json(tmp_path, monkeypatch):
    graph = _project(tmp_path)
    t = _cli_transport(monkeypatch, FakeTransport(_findings()))
    r = _invoke("SRC-001", str(graph), "--subscription")
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["target"] == "SRC-001"
    assert isinstance(out["findings"], list)
    assert t.last["api_key"] is None


def test_oracle_29_cli_refusal_exits_1_with_reason_on_stderr(tmp_path, monkeypatch):
    graph = _project(tmp_path)
    t = _cli_transport(monkeypatch, FakeTransport(_findings()))
    r = _invoke("SRC-999", str(graph), "--subscription")
    assert r.exit_code == 1
    assert "SRC-999" in r.stderr
    assert r.stdout.strip() == ""
    assert t.calls == []


def test_oracle_30_cli_unparseable_response_exits_3_with_raw(tmp_path, monkeypatch):
    graph = _project(tmp_path)
    _cli_transport(monkeypatch, FakeTransport("I think this item is fine, mostly."))
    r = _invoke("SRC-001", str(graph), "--subscription")
    assert r.exit_code == 3
    out = json.loads(r.stdout)
    assert "warning" in out and "raw_response" in out
    assert "findings" not in out


def test_oracle_31_cli_model_reaches_the_runner(tmp_path, monkeypatch):
    graph = _project(tmp_path)
    t = _cli_transport(monkeypatch, FakeTransport(_findings()))
    r = _invoke("SRC-001", str(graph), "--subscription", "--model", "claude-haiku-4-5")
    assert r.exit_code == 0, r.output
    assert t.last["options"]["model"] == "claude-haiku-4-5"


def test_oracle_30b_usage_error_is_not_an_unreadable_review(tmp_path, monkeypatch):
    graph = _project(tmp_path)
    t = _cli_transport(monkeypatch, FakeTransport(_findings()))
    r = _invoke("SRC-001", str(graph), "--subscription", "--graph-dir", "x")
    assert r.exit_code not in (0, 3)
    assert r.stdout.strip() == "" or "raw_response" not in r.stdout
    assert t.calls == []


# --- Review of PR #65 -------------------------------------------------------

@pytest.mark.parametrize("declared", ["../outside.md", "ABSOLUTE"])
def test_oracle_32_prompt_path_must_stay_inside_the_ruleset(tmp_path, declared):
    outside = tmp_path / "outside.md"
    outside.write_text("SECRET_OUTSIDE_CONTENT", encoding="utf-8")
    rel = str(outside) if declared == "ABSOLUTE" else declared
    graph = _project(tmp_path, types={"SRC": {"quality_prompt": rel}})
    t = FakeTransport(_findings())
    with pytest.raises(ReviewError) as e:
        review_item(ReviewRequest(graph_dir=str(graph), item_id="SRC-001",
                                  api_key="sk-ant-test"), transport=t)
    assert "escapes" in str(e.value).lower()
    assert t.calls == []


@pytest.mark.parametrize("var", [
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
    "ANTHROPIC_BASE_URL", "CLAUDE_CODE_OAUTH_TOKEN",
])
def test_oracle_33_subscription_refuses_when_env_reroutes(tmp_path, monkeypatch, var):
    graph = _project(tmp_path)
    monkeypatch.setenv(var, "1")
    t = FakeTransport(_findings())
    with pytest.raises(ReviewError) as e:
        review_item(ReviewRequest(graph_dir=str(graph), item_id="SRC-001", api_key=None,
                                  use_subscription=True), transport=t)
    assert var in str(e.value)
    assert t.calls == []



# --- Review of PR #65, round 2 ----------------------------------------------

def _capture_sdk_options(monkeypatch, request, api_key):
    import reqlite.review as R
    captured = {}

    class FakeOptions:
        def __init__(self, **kw):
            captured.update(kw)

    def fake_query(*, prompt, options):
        raise AssertionError("not reached")

    monkeypatch.setattr(R, "_load_sdk", lambda: (FakeOptions, fake_query))
    try:
        R._sdk_transport(prompt="p", options=R._options(request), api_key=api_key)
    except AssertionError:
        pass
    return captured


def test_oracle_34_max_tokens_reaches_the_child(monkeypatch):
    req = ReviewRequest(graph_dir=".", item_id="SRC-001", api_key="sk-ant-x", max_tokens=1234)
    captured = _capture_sdk_options(monkeypatch, req, "sk-ant-x")
    assert captured["env"].get("CLAUDE_CODE_MAX_OUTPUT_TOKENS") == "1234"


def test_oracle_35_a_hung_review_times_out(monkeypatch):
    import asyncio
    import reqlite.review as R

    class FakeOptions:
        def __init__(self, **kw):
            pass

    async def slow_query(*, prompt, options):
        await asyncio.sleep(5)
        yield None

    monkeypatch.setattr(R, "_load_sdk", lambda: (FakeOptions, slow_query))
    monkeypatch.setattr(R, "REVIEW_TIMEOUT_S", 0.1)
    req = ReviewRequest(graph_dir=".", item_id="SRC-001", api_key="sk-ant-x")
    with pytest.raises(ReviewError) as e:
        R._sdk_transport(prompt="p", options=R._options(req), api_key="sk-ant-x")
    assert "timed out" in str(e.value).lower()


def test_oracle_36_target_mismatch_is_flagged(tmp_path):
    graph = _project(tmp_path)
    result, _ = _run(graph, "SRC-001", transport=FakeTransport(_findings("SRC-002")))
    assert result["target"] == "SRC-001"
    assert result["target_mismatch"] == "SRC-002"


def test_oracle_36b_matching_target_carries_no_mismatch(tmp_path):
    graph = _project(tmp_path)
    result, _ = _run(graph, "SRC-001")
    assert "target_mismatch" not in result


def test_oracle_37_rerouting_refusal_does_not_say_unset(tmp_path, monkeypatch):
    graph = _project(tmp_path)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example")
    with pytest.raises(ReviewError) as e:
        review_item(ReviewRequest(graph_dir=str(graph), item_id="SRC-001", api_key=None,
                                  use_subscription=True), transport=FakeTransport(_findings()))
    assert "unset" not in str(e.value).lower()


def test_oracle_38_symlinked_item_outside_the_graph_is_refused(tmp_path):
    import os
    from reqlite.items import ParseError, parse_all
    graph = _project(tmp_path)
    outside = tmp_path / "secret.md"
    outside.write_text("# SRC-009: Secret\n\nOUTSIDE\n", encoding="utf-8")
    try:
        os.symlink(outside, graph / "SRC-009-x.md")
    except OSError:
        pytest.skip("OS will not create symlinks without privilege")
    with pytest.raises(ParseError) as e:
        parse_all(graph)
    assert "SRC-009" in str(e.value)


# --- Key-based review (MVP) -------------------------------------------------

KEY = "sk-ant-api03-SECRET-test-value"


@pytest.mark.parametrize("var", [
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
    "ANTHROPIC_BASE_URL",
])
def test_oracle_39_key_mode_refuses_when_env_reroutes(tmp_path, monkeypatch, var):
    graph = _project(tmp_path)
    monkeypatch.setenv(var, "1")
    t = FakeTransport(_findings())
    with pytest.raises(ReviewError) as e:
        review_item(ReviewRequest(graph_dir=str(graph), item_id="SRC-001", api_key=KEY),
                    transport=t)
    assert var in str(e.value)
    assert "unset" not in str(e.value).lower()
    assert t.calls == []


def test_oracle_40_key_mode_does_not_refuse_on_an_oauth_token(tmp_path, monkeypatch):
    graph = _project(tmp_path)
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    result, t = _run(graph, key=KEY)
    assert t.last["api_key"] == KEY
    assert result["target"] == "SRC-001"


def test_oracle_41_key_mode_blanks_an_inherited_auth_token_in_the_child(monkeypatch):
    import os
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "inherited-token")
    req = ReviewRequest(graph_dir=".", item_id="SRC-001", api_key=KEY)
    captured = _capture_sdk_options(monkeypatch, req, KEY)
    assert captured["env"]["ANTHROPIC_API_KEY"] == KEY
    assert captured["env"]["ANTHROPIC_AUTH_TOKEN"] == ""
    assert os.environ["ANTHROPIC_AUTH_TOKEN"] == "inherited-token", "parent untouched"


class SystemMessage:
    """Named as the SDK's: the transport recognises messages by class name, so this runs
    on CI without the extra."""

    def __init__(self, data, subtype="init"):
        self.subtype = subtype
        self.data = data


class _Text:
    def __init__(self, text):
        self.text = text


class AssistantMessage:
    def __init__(self, text):
        self.content = [_Text(text)]


def _through_real_transport(monkeypatch, *, api_key, init):
    """Run `_sdk_transport` with a fake query that emits `init` (a data dict, or None for
    no init message) and then a response."""
    import reqlite.review as R

    class FakeOptions:
        def __init__(self, **kw):
            pass

    async def fake_query(*, prompt, options):
        if init is not None:
            yield SystemMessage(init)
        yield AssistantMessage("RESPONSE_TEXT")

    monkeypatch.setattr(R, "_load_sdk", lambda: (FakeOptions, fake_query))
    req = ReviewRequest(graph_dir=".", item_id="SRC-001", api_key=api_key,
                        use_subscription=api_key is None)
    return R._sdk_transport(prompt="p", options=R._options(req), api_key=api_key)


@pytest.mark.parametrize("api_key,source", [(KEY, "ANTHROPIC_API_KEY"), (None, "none")])
def test_oracle_42a_matching_credential_source_returns_the_response(
        monkeypatch, api_key, source):
    out = _through_real_transport(monkeypatch, api_key=api_key,
                                  init={"apiKeySource": source})
    assert out == "RESPONSE_TEXT"


@pytest.mark.parametrize("api_key,source,expected", [
    (KEY, "none", "ANTHROPIC_API_KEY"),
    (KEY, "apiKeyHelper", "ANTHROPIC_API_KEY"),
    (None, "ANTHROPIC_API_KEY", "none"),
])
def test_oracle_42b_mismatched_credential_source_is_refused(
        monkeypatch, api_key, source, expected):
    with pytest.raises(ReviewError) as e:
        _through_real_transport(monkeypatch, api_key=api_key,
                                init={"apiKeySource": source})
    msg = str(e.value)
    assert source in msg and expected in msg
    assert "RESPONSE_TEXT" not in msg


@pytest.mark.parametrize("init", [None, {}])
def test_oracle_42c_unreported_credential_source_is_refused(monkeypatch, init):
    with pytest.raises(ReviewError) as e:
        _through_real_transport(monkeypatch, api_key=KEY, init=init)
    assert "credential" in str(e.value).lower()


@pytest.mark.parametrize("raised", [RuntimeError, ReviewError])
def test_oracle_43_the_key_never_appears_in_an_error(tmp_path, raised):
    graph = _project(tmp_path)
    t = FakeTransport(raises=raised(f"rejected header x-api-key: {KEY}"))
    with pytest.raises(ReviewError) as e:
        review_item(ReviewRequest(graph_dir=str(graph), item_id="SRC-001", api_key=KEY),
                    transport=t)
    assert KEY not in str(e.value)
    assert "rejected header" in str(e.value), "the rest of the cause is kept"


def test_oracle_44_cli_default_credential_is_reqlite_api_key(tmp_path, monkeypatch):
    graph = _project(tmp_path)
    monkeypatch.setenv("REQLITE_API_KEY", KEY)
    t = _cli_transport(monkeypatch, FakeTransport(_findings()))
    r = _invoke("SRC-001", str(graph))
    assert r.exit_code == 0, r.output
    assert t.last["api_key"] == KEY
    assert json.loads(r.stdout)["target"] == "SRC-001"


def test_oracle_45_cli_api_key_env_reads_the_named_variable(tmp_path, monkeypatch):
    graph = _project(tmp_path)
    monkeypatch.setenv("MY_KEY", KEY)
    t = _cli_transport(monkeypatch, FakeTransport(_findings()))
    r = _invoke("SRC-001", str(graph), "--api-key-env", "MY_KEY")
    assert r.exit_code == 0, r.output
    assert t.last["api_key"] == KEY


@pytest.mark.parametrize("value", [None, "  \n"])
def test_oracle_46_cli_missing_or_empty_named_variable_refuses(tmp_path, monkeypatch, value):
    graph = _project(tmp_path)
    if value is None:
        monkeypatch.delenv("MY_KEY", raising=False)
    else:
        monkeypatch.setenv("MY_KEY", value)
    t = _cli_transport(monkeypatch, FakeTransport(_findings()))
    r = _invoke("SRC-001", str(graph), "--api-key-env", "MY_KEY")
    assert r.exit_code == 1
    assert "MY_KEY" in r.stderr and "started" in r.stderr
    assert r.stdout.strip() == ""
    assert t.calls == []


def test_oracle_47_cli_subscription_with_api_key_env_refuses(tmp_path, monkeypatch):
    graph = _project(tmp_path)
    monkeypatch.setenv("MY_KEY", KEY)
    t = _cli_transport(monkeypatch, FakeTransport(_findings()))
    r = _invoke("SRC-001", str(graph), "--subscription", "--api-key-env", "MY_KEY")
    assert r.exit_code == 1
    assert "--subscription" in r.stderr and "--api-key-env" in r.stderr
    assert t.calls == []


def test_oracle_48_cli_takes_no_key_value(tmp_path, monkeypatch):
    graph = _project(tmp_path)
    t = _cli_transport(monkeypatch, FakeTransport(_findings()))
    r = _invoke("SRC-001", str(graph), "--api-key", KEY)
    assert r.exit_code == 2
    assert t.calls == []


@pytest.mark.parametrize("transport", [
    FakeTransport(raises=RuntimeError(f"401 for key {KEY}")),
    FakeTransport(_findings()),
])
def test_oracle_49_the_key_never_reaches_the_command_output(tmp_path, monkeypatch, transport):
    graph = _project(tmp_path)
    monkeypatch.setenv("REQLITE_API_KEY", KEY)
    _cli_transport(monkeypatch, transport)
    r = _invoke("SRC-001", str(graph))
    assert KEY not in r.stdout and KEY not in r.stderr


def test_oracle_50_surrounding_whitespace_is_stripped(tmp_path, monkeypatch):
    graph = _project(tmp_path)
    monkeypatch.setenv("REQLITE_API_KEY", f" {KEY}\r\n")
    t = _cli_transport(monkeypatch, FakeTransport(_findings()))
    r = _invoke("SRC-001", str(graph))
    assert r.exit_code == 0, r.output
    assert t.last["api_key"] == KEY


# --- Gateway mode (#86) ---------------------------------------------------------------

GW_URL = "https://gateway.example.test"
GW_SECRET = "pk-GATEWAY-SECRET-value-123"
GW_TOKEN = "bearer-INHERITED-token-456"
AWS_SECRET = "aws-SECRET-access-key-789"


def _gw(**kw):
    from reqlite.review import gateway_from_env
    return gateway_from_env(**kw)


def _http_gw():
    """A gateway built directly, for tests about what the runner does with one."""
    from reqlite.review import Gateway
    return Gateway(kind="http", env={"ANTHROPIC_BASE_URL": GW_URL})


def _child_env(monkeypatch, gateway):
    """The child environment the real transport builds for `gateway`."""
    import reqlite.review as R
    req = ReviewRequest(graph_dir=".", item_id="SRC-001", api_key=None, gateway=gateway)
    captured = {}

    class FakeOptions:
        def __init__(self, **kw):
            captured.update(kw)

    def fake_query(*, prompt, options):
        raise AssertionError("not reached")

    monkeypatch.setattr(R, "_load_sdk", lambda: (FakeOptions, fake_query))
    try:
        R._sdk_transport(prompt="p", options=R._options(req), api_key=None, gateway=gateway)
    except AssertionError:
        pass
    return captured["env"]


def test_oracle_51_inherited_http_gateway_is_passed_on(monkeypatch):
    import os
    monkeypatch.setenv("ANTHROPIC_BASE_URL", GW_URL)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", GW_TOKEN)
    monkeypatch.setenv("ANTHROPIC_CUSTOM_HEADERS", f"x-portkey-api-key: {GW_SECRET}")
    gw = _gw()
    assert gw.kind == "http"
    env = _child_env(monkeypatch, gw)
    assert env["ANTHROPIC_BASE_URL"] == GW_URL
    assert env["ANTHROPIC_AUTH_TOKEN"] == GW_TOKEN
    assert env["ANTHROPIC_CUSTOM_HEADERS"] == f"x-portkey-api-key: {GW_SECRET}"
    assert env["ANTHROPIC_API_KEY"] == ""
    assert os.environ["ANTHROPIC_AUTH_TOKEN"] == GW_TOKEN, "parent untouched"


def test_oracle_52_explicit_gateway_gives_the_child_only_that_gateway(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://other.example.test")
    monkeypatch.setenv("ANTHROPIC_CUSTOM_HEADERS", "x-unrelated: other")
    monkeypatch.setenv("GW", GW_SECRET)
    env = _child_env(monkeypatch, _gw(url=GW_URL, key_env="GW", header="x-test-gateway-key"))
    assert env["ANTHROPIC_BASE_URL"] == GW_URL
    assert env["ANTHROPIC_CUSTOM_HEADERS"] == f"x-test-gateway-key: {GW_SECRET}"
    assert env["ANTHROPIC_AUTH_TOKEN"] and env["ANTHROPIC_AUTH_TOKEN"] != GW_SECRET
    assert env["ANTHROPIC_API_KEY"] == ""


@pytest.mark.parametrize("header", ["Authorization", None])
def test_oracle_52b_authorization_header_is_the_bearer_token(monkeypatch, header):
    monkeypatch.setenv("ANTHROPIC_CUSTOM_HEADERS", "x-unrelated: other")
    monkeypatch.setenv("GW", GW_SECRET)
    env = _child_env(monkeypatch, _gw(url=GW_URL, key_env="GW", header=header))
    assert env["ANTHROPIC_AUTH_TOKEN"] == GW_SECRET
    assert env["ANTHROPIC_CUSTOM_HEADERS"] == ""


@pytest.mark.parametrize("selector,kind", [
    ("CLAUDE_CODE_USE_BEDROCK", "bedrock"), ("CLAUDE_CODE_USE_VERTEX", "vertex")])
def test_oracle_53_cloud_providers_are_passed_on_with_anthropic_credentials_blanked(
        monkeypatch, selector, kind):
    monkeypatch.setenv(selector, "1")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-inherited")
    gw = _gw()
    assert gw.kind == kind
    env = _child_env(monkeypatch, gw)
    assert env["ANTHROPIC_API_KEY"] == "" and env["ANTHROPIC_AUTH_TOKEN"] == ""
    assert env.get(selector, "1") == "1", "the provider selector is not blanked"
    assert env.get("AWS_REGION", "us-east-1") == "us-east-1"
    assert "ANTHROPIC_BASE_URL" not in env


@pytest.mark.parametrize("setup,kw,needle", [
    ({}, {}, "ANTHROPIC_BASE_URL"),
    ({"CLAUDE_CODE_USE_BEDROCK": "1", "CLAUDE_CODE_USE_VERTEX": "1"}, {},
     "CLAUDE_CODE_USE_VERTEX"),
    ({"CLAUDE_CODE_USE_BEDROCK": "1", "ANTHROPIC_BASE_URL": GW_URL}, {},
     "ANTHROPIC_BASE_URL"),
    ({"CLAUDE_CODE_USE_FOUNDRY": "1"}, {"url": GW_URL}, "CLAUDE_CODE_USE_FOUNDRY"),
    ({"CLAUDE_CODE_OAUTH_TOKEN": "tok"}, {"url": GW_URL}, "CLAUDE_CODE_OAUTH_TOKEN"),
    ({"CLAUDE_CODE_USE_BEDROCK": "1", "GW": "v"}, {"key_env": "GW"}, "--gateway-key-env"),
    ({"CLAUDE_CODE_USE_VERTEX": "1"}, {"header": "x-h"}, "--gateway-header"),
    ({}, {"url": GW_URL, "header": "x-h"}, "--gateway-header"),
    ({}, {"url": GW_URL}, "--gateway-key-env"),
    ({"ANTHROPIC_BASE_URL": "https://inherited.example.test",
      "ANTHROPIC_CUSTOM_HEADERS": f"x-portkey-api-key: {GW_SECRET}"},
     {"url": GW_URL}, "--gateway-key-env"),
    ({}, {"url": GW_URL, "key_env": "GW_UNSET"}, "GW_UNSET"),
])
def test_oracle_54_gateway_refuses_what_it_cannot_vouch_for(monkeypatch, setup, kw, needle):
    for var, value in setup.items():
        monkeypatch.setenv(var, value)
    with pytest.raises(ReviewError) as e:
        _gw(**kw)
    assert needle in str(e.value)
    assert GW_SECRET not in str(e.value)


@pytest.mark.parametrize("url", [GW_URL, GW_URL + "/"])
def test_oracle_54b_a_url_equal_to_the_inherited_one_is_the_inherited_gateway(
        monkeypatch, url):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", GW_URL)
    monkeypatch.setenv("ANTHROPIC_CUSTOM_HEADERS", f"x-portkey-api-key: {GW_SECRET}")
    env = _child_env(monkeypatch, _gw(url=url))
    assert env["ANTHROPIC_CUSTOM_HEADERS"] == f"x-portkey-api-key: {GW_SECRET}"


def test_oracle_54_gateway_refuses_on_macos(monkeypatch):
    import sys
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(ReviewError) as e:
        _gw(url=GW_URL)
    assert "macos" in str(e.value).lower()


def test_oracle_54_the_runner_rechecks_a_gateway_built_earlier(tmp_path, monkeypatch):
    """A library caller can hold a Gateway while the environment changes; _dispatch checks
    the environment again."""
    graph = _project(tmp_path)
    gw = _http_gw()
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    t = FakeTransport(_findings())
    with pytest.raises(ReviewError) as e:
        review_item(ReviewRequest(graph_dir=str(graph), item_id="SRC-001", api_key=None,
                                  gateway=gw), transport=t)
    assert "CLAUDE_CODE_OAUTH_TOKEN" in str(e.value)
    assert t.calls == []


def test_oracle_54_a_gateway_review_dispatches(tmp_path):
    graph = _project(tmp_path)
    gw = _http_gw()
    t = FakeTransport(_findings())
    result = review_item(ReviewRequest(graph_dir=str(graph), item_id="SRC-001",
                                       api_key=None, gateway=gw), transport=t)
    assert t.last["gateway"] == gw and t.last["api_key"] is None
    assert result["target"] == "SRC-001"


@pytest.mark.parametrize("kw,named", [
    ({"api_key": KEY}, "key"), ({"api_key": None, "use_subscription": True}, "subscription")])
def test_oracle_55_gateway_with_another_credential_is_refused(tmp_path, kw, named):
    graph = _project(tmp_path)
    t = FakeTransport(_findings())
    with pytest.raises(ReviewError) as e:
        review_item(ReviewRequest(graph_dir=str(graph), item_id="SRC-001",
                                  gateway=_http_gw(), **kw), transport=t)
    msg = str(e.value).lower()
    assert "gateway" in msg and named in msg
    assert t.calls == []


def _gateway_run(monkeypatch, gateway, *, init=None, behaviour=None):
    """Run the real transport in gateway mode with a fake query. `behaviour(options)` runs
    inside the query, before any message."""
    import reqlite.review as R

    class FakeOptions:
        def __init__(self, **kw):
            self.env = kw.get("env", {})
            self.extra_args = kw.get("extra_args")

    async def fake_query(*, prompt, options):
        if behaviour is not None:
            await behaviour(options)
        yield SystemMessage(init if init is not None else {"apiKeySource": "none"})
        yield AssistantMessage("RESPONSE_TEXT")

    monkeypatch.setattr(R, "_load_sdk", lambda: (FakeOptions, fake_query))
    req = ReviewRequest(graph_dir=".", item_id="SRC-001", api_key=None, gateway=gateway)
    return R._sdk_transport(prompt="p", options=R._options(req), api_key=None,
                            gateway=gateway)


def test_oracle_56_gateway_runs_on_an_empty_throwaway_config_dir(monkeypatch, tmp_path):
    from pathlib import Path
    user_config = tmp_path / "user-config"
    user_config.mkdir()
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(user_config))
    seen = {}

    async def inspect(options):
        d = Path(options.env["CLAUDE_CONFIG_DIR"])
        seen.update(path=d, exists=d.is_dir(), empty=d.is_dir() and not any(d.iterdir()))
        (d / "projects").mkdir()            # the child writes its session here

    assert _gateway_run(monkeypatch, _http_gw(), behaviour=inspect) == "RESPONSE_TEXT"
    assert seen["exists"] and seen["empty"]
    assert seen["path"] != user_config and seen["path"] != Path.home() / ".claude"
    assert not seen["path"].exists(), "removed after the call"


@pytest.mark.parametrize("failure", ["raise", "timeout"])
def test_oracle_56_the_config_dir_is_removed_after_a_failure(monkeypatch, failure):
    import asyncio
    from pathlib import Path
    import reqlite.review as R
    seen = {}

    async def fail(options):
        seen["path"] = Path(options.env["CLAUDE_CONFIG_DIR"])
        if failure == "raise":
            raise RuntimeError("boom")
        await asyncio.sleep(5)

    monkeypatch.setattr(R, "REVIEW_TIMEOUT_S", 0.1)
    with pytest.raises((RuntimeError, ReviewError)):
        _gateway_run(monkeypatch, _http_gw(), behaviour=fail)
    assert not seen["path"].exists()


@pytest.mark.parametrize("kw", [
    {"api_key": KEY}, {"api_key": None, "use_subscription": True}])
def test_oracle_57_no_mode_persists_the_session(kw):
    import reqlite.review as R
    opts = R._options(ReviewRequest(graph_dir=".", item_id="SRC-001", **kw))
    assert "no-session-persistence" in opts["extra_args"]
    assert opts["extra_args"]["no-session-persistence"] is None


def test_oracle_57_gateway_mode_does_not_persist_the_session_either(monkeypatch):
    seen = {}

    async def inspect(options):
        seen["extra"] = options.extra_args

    _gateway_run(monkeypatch, _http_gw(), behaviour=inspect)
    assert "no-session-persistence" in seen["extra"]


@pytest.mark.parametrize("init", [{"apiKeySource": "ANTHROPIC_API_KEY"}, {}])
def test_oracle_58_gateway_mode_verifies_the_reported_source(monkeypatch, init):
    with pytest.raises(ReviewError) as e:
        _gateway_run(monkeypatch, _http_gw(), init=init)
    assert "RESPONSE_TEXT" not in str(e.value)
    assert "credential" in str(e.value).lower()


@pytest.mark.parametrize("setup,kw,secret", [
    ({"GW": GW_SECRET}, {"url": GW_URL, "key_env": "GW", "header": "x-gw"}, GW_SECRET),
    ({"ANTHROPIC_BASE_URL": GW_URL, "ANTHROPIC_AUTH_TOKEN": GW_TOKEN}, {}, GW_TOKEN),
    ({"ANTHROPIC_BASE_URL": GW_URL,
      "ANTHROPIC_CUSTOM_HEADERS": f"x-a: {GW_SECRET}\nx-b: {GW_TOKEN}"}, {}, GW_TOKEN),
    ({"CLAUDE_CODE_USE_BEDROCK": "1", "AWS_SECRET_ACCESS_KEY": AWS_SECRET}, {}, AWS_SECRET),
])
@pytest.mark.parametrize("raised", [RuntimeError, ReviewError])
def test_oracle_59_gateway_secrets_never_appear_in_an_error(
        tmp_path, monkeypatch, setup, kw, secret, raised):
    for var, value in setup.items():
        monkeypatch.setenv(var, value)
    graph = _project(tmp_path)
    t = FakeTransport(raises=raised(f"rejected credential {secret} at gateway"))
    with pytest.raises(ReviewError) as e:
        review_item(ReviewRequest(graph_dir=str(graph), item_id="SRC-001", api_key=None,
                                  gateway=_gw(**kw)), transport=t)
    assert secret not in str(e.value)
    assert "at gateway" in str(e.value), "the rest of the cause is kept"


def test_oracle_60_gateway_model_comes_from_the_environment(tmp_path, monkeypatch):
    graph = _project(tmp_path)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", GW_URL)
    monkeypatch.setenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "us.anthropic.gw-sonnet")
    t = _cli_transport(monkeypatch, FakeTransport(_findings()))
    r = _invoke("SRC-001", str(graph), "--gateway")
    assert r.exit_code == 0, r.output
    assert t.last["options"]["model"] == "us.anthropic.gw-sonnet"
    assert t.last["gateway"].kind == "http" and t.last["api_key"] is None


def test_oracle_60_model_option_wins_in_gateway_mode(tmp_path, monkeypatch):
    graph = _project(tmp_path)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", GW_URL)
    monkeypatch.setenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "us.anthropic.gw-sonnet")
    t = _cli_transport(monkeypatch, FakeTransport(_findings()))
    r = _invoke("SRC-001", str(graph), "--gateway", "--model", "explicit-id")
    assert r.exit_code == 0, r.output
    assert t.last["options"]["model"] == "explicit-id"


def test_oracle_60_gateway_without_a_model_id_refuses(tmp_path, monkeypatch):
    graph = _project(tmp_path)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", GW_URL)
    t = _cli_transport(monkeypatch, FakeTransport(_findings()))
    r = _invoke("SRC-001", str(graph), "--gateway")
    assert r.exit_code == 1
    assert "--model" in r.stderr and "ANTHROPIC_DEFAULT_SONNET_MODEL" in r.stderr
    assert t.calls == []


def test_oracle_60_explicit_gateway_from_the_command_line(tmp_path, monkeypatch):
    graph = _project(tmp_path)
    monkeypatch.setenv("TEST_GW", GW_SECRET)
    t = _cli_transport(monkeypatch, FakeTransport(_findings()))
    r = _invoke("SRC-001", str(graph), "--gateway", "--gateway-url", GW_URL,
                "--gateway-key-env", "TEST_GW", "--gateway-header", "x-test-gateway-key",
                "--model", "claude-sonnet-4-6")
    assert r.exit_code == 0, r.output
    assert t.last["gateway"].env["ANTHROPIC_CUSTOM_HEADERS"] == (
        f"x-test-gateway-key: {GW_SECRET}")
    assert GW_SECRET not in r.stdout and GW_SECRET not in r.stderr


@pytest.mark.parametrize("args", [
    ["--gateway-url", GW_URL],
    ["--gateway-key-env", "TEST_GW"],
    ["--gateway-header", "x-h"],
    ["--gateway", "--subscription"],
    ["--gateway", "--api-key-env", "MY_KEY"],
])
def test_oracle_61_gateway_options_need_gateway_and_exclude_other_modes(
        tmp_path, monkeypatch, args):
    graph = _project(tmp_path)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", GW_URL)
    monkeypatch.setenv("MY_KEY", KEY)
    monkeypatch.setenv("TEST_GW", GW_SECRET)
    t = _cli_transport(monkeypatch, FakeTransport(_findings()))
    r = _invoke("SRC-001", str(graph), *args, "--model", "m")
    assert r.exit_code == 1, r.output
    assert "--gateway" in r.stderr
    assert t.calls == []


@pytest.mark.parametrize("mode", ["key", "subscription"])
def test_oracle_63_inherited_custom_headers_are_refused(tmp_path, monkeypatch, mode):
    graph = _project(tmp_path)
    monkeypatch.setenv("ANTHROPIC_CUSTOM_HEADERS", f"x-portkey-api-key: {GW_SECRET}")
    t = FakeTransport(_findings())
    kw = {"api_key": KEY} if mode == "key" else {"api_key": None, "use_subscription": True}
    with pytest.raises(ReviewError) as e:
        review_item(ReviewRequest(graph_dir=str(graph), item_id="SRC-001", **kw),
                    transport=t)
    assert "ANTHROPIC_CUSTOM_HEADERS" in str(e.value)
    assert GW_SECRET not in str(e.value)
    assert t.calls == []


def test_oracle_56b_a_killed_runs_old_config_dir_is_removed(monkeypatch, tmp_path):
    import os
    import tempfile
    import time
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    old = tmp_path / "reqlite-review-old"
    recent = tmp_path / "reqlite-review-recent"
    unrelated = tmp_path / "something-else"
    for d in (old, recent, unrelated):
        d.mkdir()
    day_ago = time.time() - 2 * 86400
    os.utime(old, (day_ago, day_ago))
    os.utime(unrelated, (day_ago, day_ago))
    _gateway_run(monkeypatch, _http_gw())
    assert not old.exists()
    assert recent.exists() and unrelated.exists()


def test_oracle_56c_gateway_mode_retries_at_most_twice(monkeypatch):
    seen = {}

    async def inspect(options):
        seen["retries"] = options.env.get("CLAUDE_CODE_MAX_RETRIES")

    _gateway_run(monkeypatch, _http_gw(), behaviour=inspect)
    assert seen["retries"] == "2"


@pytest.mark.parametrize("api_key", [KEY, None])
def test_oracle_56c_other_modes_keep_the_cli_default(monkeypatch, api_key):
    req = ReviewRequest(graph_dir=".", item_id="SRC-001", api_key=api_key,
                        use_subscription=api_key is None)
    captured = _capture_sdk_options(monkeypatch, req, api_key)
    assert "CLAUDE_CODE_MAX_RETRIES" not in captured["env"]
