"""Tests for `reqlite doctor`. One test per oracle in ORACLES-DOCTOR.md."""

import json

import pytest

from typer.testing import CliRunner

from reqlite.cli import app

runner = CliRunner()


def _healthy(tmp_path, ruleset=None):
    graph = tmp_path / "graph"
    graph.mkdir()
    (graph / "SRC-001-root.md").write_text(
        "# SRC-001: Root\n\nA claim.\n", encoding="utf-8"
    )
    rs_dir = tmp_path / "ruleset"
    (rs_dir / "prompts").mkdir(parents=True)
    (rs_dir / "prompts" / "src_quality.md").write_text("Review it.", encoding="utf-8")
    (rs_dir / "ruleset.json").write_text(
        ruleset if ruleset is not None
        else json.dumps({"types": {"SRC": {"quality_prompt": "prompts/src_quality.md"}}}),
        encoding="utf-8",
    )
    return graph


def _sdk_present(monkeypatch, bundled=True):
    """Fake every SDK touchpoint doctor uses. CI installs without the review extra
    (DD-031), so a fake that misses one imports the real SDK and fails there only."""
    import reqlite.review as R
    monkeypatch.setattr(R, "_load_sdk", lambda: (object(), object()))
    monkeypatch.setattr(R, "sdk_versions", lambda: ("9.9.9", "8.8.8"))
    monkeypatch.setattr(R, "bundled_cli_present", lambda: bundled)


def test_oracle_1_healthy_project_exits_zero_and_reports_checks(tmp_path):
    graph = _healthy(tmp_path)
    result = runner.invoke(app, ["doctor", str(graph)])
    assert result.exit_code == 0, result.output
    assert "engine" in result.output.lower()
    assert "ruleset" in result.output.lower()
    assert "graph" in result.output.lower()


def test_oracle_2_missing_ruleset_fails_and_names_the_path(tmp_path):
    graph = tmp_path / "graph"
    graph.mkdir()
    (graph / "SRC-001-root.md").write_text("# SRC-001: Root\n\nA claim.\n", encoding="utf-8")
    result = runner.invoke(app, ["doctor", str(graph)])
    assert result.exit_code != 0
    assert "ruleset.json" in result.output


def test_oracle_3_invalid_ruleset_says_invalid_not_missing(tmp_path):
    graph = _healthy(tmp_path, ruleset="{ not json")
    result = runner.invoke(app, ["doctor", str(graph)])
    assert result.exit_code != 0
    out = result.output.lower()
    assert "invalid" in out or "not valid" in out


def test_oracle_4_missing_review_extra_is_a_warning_not_a_failure(tmp_path, monkeypatch):
    graph = _healthy(tmp_path)
    import reqlite.review as R

    def _missing():
        raise R.MissingExtraError('pip install "reqlite[review]"')

    monkeypatch.setattr(R, "_load_sdk", _missing)
    result = runner.invoke(app, ["doctor", str(graph)])
    assert result.exit_code == 0, result.output
    assert '[review]"' in result.output
    # reqlite is not on PyPI, so this form installs nothing, or a squatter's package.
    assert 'pip install "reqlite[review]"' not in result.output


def test_oracle_5_present_review_extra_is_reported_available(tmp_path, monkeypatch):
    graph = _healthy(tmp_path)
    _sdk_present(monkeypatch)
    result = runner.invoke(app, ["doctor", str(graph)])
    assert result.exit_code == 0, result.output
    assert "review" in result.output.lower()


def test_oracle_6_unparseable_graph_fails_cleanly(tmp_path):
    graph = _healthy(tmp_path)
    # frontmatter id contradicting the filename is a hard parse error
    (graph / "SRC-002-mismatch.md").write_text(
        "---\nid: SRC-999\n---\n\n# SRC-002: Mismatch\n\nBody.\n", encoding="utf-8"
    )
    result = runner.invoke(app, ["doctor", str(graph)])
    assert result.exit_code != 0
    assert result.exception is None or isinstance(result.exception, SystemExit), (
        "doctor must report, not raise"
    )
    assert "SRC-002" in result.output or "SRC-999" in result.output


def test_oracle_8_orphan_is_not_reported_as_an_integrity_problem(tmp_path):
    """DD-025: integrity is the gate; orphans and topology are descriptive and never gate.
    Counting an orphan as an integrity finding cries wolf on a healthy graph."""
    graph = _healthy(tmp_path)
    (graph / "SRC-050-orphan.md").write_text(
        "# SRC-050: Orphan\n\nNothing links here and it links nowhere.\n", encoding="utf-8"
    )
    result = runner.invoke(app, ["doctor", str(graph)])
    assert result.exit_code == 0, result.output
    graph_line = next(ln for ln in result.output.splitlines() if "graph" in ln)
    assert graph_line.strip().startswith("[ok]"), graph_line
    assert "integrity" not in graph_line.lower()


def test_oracle_7_output_is_a_scannable_checklist(tmp_path):
    graph = _healthy(tmp_path)
    result = runner.invoke(app, ["doctor", str(graph)])
    markers = [ln for ln in result.output.splitlines()
               if ln.strip().startswith(("[ok]", "[warn]", "[fail]"))]
    assert len(markers) >= 3, f"expected a marker per check, got:\n{result.output}"


def test_oracle_18_hidden_comments_are_a_warning(tmp_path):
    graph = _healthy(tmp_path)
    (graph / "SRC-002-c.md").write_text(
        "# SRC-002: C\n\nText. [SRC-001](SRC-001-root.md)\n\n<!-- quietly do X -->\n",
        encoding="utf-8")
    result = runner.invoke(app, ["doctor", str(graph)])
    assert result.exit_code == 0, result.output
    line = next(l for l in result.output.splitlines() if "hidden text" in l)
    assert line.startswith("[warn]") and "SRC-002" in line and "not instructions" in line


def test_oracle_8_review_line_names_sdk_and_bundled_cli_versions(tmp_path, monkeypatch):
    graph = _healthy(tmp_path)
    import reqlite.review as R
    _sdk_present(monkeypatch)
    result = runner.invoke(app, ["doctor", str(graph)])
    assert result.exit_code == 0, result.output
    line = next(l for l in result.output.splitlines() if "review extra" in l)
    assert "9.9.9" in line and "8.8.8" in line


def test_oracle_9_no_bundled_cli_warns_the_pinned_pair_is_not_in_effect(tmp_path, monkeypatch):
    graph = _healthy(tmp_path)
    import reqlite.review as R
    monkeypatch.setattr(R, "_load_sdk", lambda: (object(), object()))
    monkeypatch.setattr(R, "sdk_versions", lambda: ("9.9.9", "8.8.8"))
    monkeypatch.setattr(R, "bundled_cli_present", lambda: False)
    result = runner.invoke(app, ["doctor", str(graph)])
    assert result.exit_code == 0, result.output
    line = next(l for l in result.output.splitlines() if "review extra" in l)
    assert line.startswith("[warn]")
    assert "PATH" in line


def _sub_line(output):
    return next(l for l in output.splitlines() if "subscription review" in l)


def _clear_rerouting(monkeypatch):
    import reqlite.review as R
    for var in R._SUBSCRIPTION_REROUTING_VARS:
        monkeypatch.delenv(var, raising=False)


def test_oracle_10_rerouting_variable_warns_subscription_is_refused(tmp_path, monkeypatch):
    graph = _healthy(tmp_path)
    _sdk_present(monkeypatch)
    _clear_rerouting(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "http://proxy")
    result = runner.invoke(app, ["doctor", str(graph)])
    assert result.exit_code == 0, result.output
    line = _sub_line(result.output)
    assert line.startswith("[warn]")
    assert "ANTHROPIC_BASE_URL" in line and "algorithmic" in line.lower()


def _config_dir(tmp_path, monkeypatch, login: bool):
    config = tmp_path / "claude-config"
    config.mkdir()
    if login:
        (config / ".credentials.json").write_text('{"claudeAiOauth": {}}', encoding="utf-8")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(config))
    return config


def test_oracle_11_no_rerouting_variable_is_ok_and_says_login_unchecked(tmp_path, monkeypatch):
    graph = _healthy(tmp_path)
    _sdk_present(monkeypatch)
    _clear_rerouting(monkeypatch)
    _config_dir(tmp_path, monkeypatch, login=True)
    result = runner.invoke(app, ["doctor", str(graph)])
    line = _sub_line(result.output)
    assert line.startswith("[ok]")
    assert "not checked" in line


def test_oracle_12_doctor_and_runner_share_one_condition(tmp_path, monkeypatch):
    import reqlite.review as R

    graph = _healthy(tmp_path)
    _sdk_present(monkeypatch)
    for var in R._SUBSCRIPTION_REROUTING_VARS:
        _clear_rerouting(monkeypatch)
        monkeypatch.setenv(var, "1")
        reason = R.subscription_refusal()
        assert reason and var in reason
        line = _sub_line(runner.invoke(app, ["doctor", str(graph)]).output)
        assert line.startswith("[warn]") and reason in line, var


SECRET = "sk-ant-api03-SECRET-doctor"


def _key_line(output):
    return next(l for l in output.splitlines() if "key review" in l)


def test_oracle_13_key_line_reports_presence_never_the_value(tmp_path, monkeypatch):
    graph = _healthy(tmp_path)
    _sdk_present(monkeypatch)
    _clear_rerouting(monkeypatch)
    monkeypatch.setenv("REQLITE_API_KEY", SECRET)
    result = runner.invoke(app, ["doctor", str(graph)])
    assert result.exit_code == 0, result.output
    line = _key_line(result.output)
    assert line.startswith("[ok]")
    assert "REQLITE_API_KEY" in line and "not checked" in line
    for fragment in (SECRET, SECRET[:12], SECRET[-6:]):
        assert fragment not in result.output


def test_oracle_14_unset_key_variable_warns_and_names_the_ways_on(tmp_path, monkeypatch):
    graph = _healthy(tmp_path)
    _sdk_present(monkeypatch)
    _clear_rerouting(monkeypatch)
    result = runner.invoke(app, ["doctor", str(graph)])
    assert result.exit_code == 0, result.output
    line = _key_line(result.output)
    assert line.startswith("[warn]")
    for name in ("REQLITE_API_KEY", "--api-key-env", "--subscription"):
        assert name in line


def test_oracle_15_api_key_env_makes_doctor_check_that_variable(tmp_path, monkeypatch):
    graph = _healthy(tmp_path)
    _sdk_present(monkeypatch)
    _clear_rerouting(monkeypatch)
    monkeypatch.setenv("MY_KEY", SECRET)
    result = runner.invoke(app, ["doctor", str(graph), "--api-key-env", "MY_KEY"])
    line = _key_line(result.output)
    assert line.startswith("[ok]") and "MY_KEY" in line


def test_oracle_16_key_rerouting_warns_with_the_runners_reason(tmp_path, monkeypatch):
    import reqlite.review as R

    graph = _healthy(tmp_path)
    _sdk_present(monkeypatch)
    monkeypatch.setenv("REQLITE_API_KEY", SECRET)
    for var in R._KEY_REROUTING_VARS:
        _clear_rerouting(monkeypatch)
        monkeypatch.setenv(var, "1")
        reason = R.key_refusal()
        assert reason and var in reason
        line = _key_line(runner.invoke(app, ["doctor", str(graph)]).output)
        assert line.startswith("[warn]") and reason in line, var


def test_oracle_17_no_stored_login_file_warns(tmp_path, monkeypatch):
    import sys

    graph = _healthy(tmp_path)
    _sdk_present(monkeypatch)
    _clear_rerouting(monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")
    config = _config_dir(tmp_path, monkeypatch, login=False)
    result = runner.invoke(app, ["doctor", str(graph)])
    assert result.exit_code == 0, result.output
    line = _sub_line(result.output)
    assert line.startswith("[warn]")
    assert str(config / ".credentials.json") in line and "/login" in line


@pytest.mark.parametrize("content, marker", [
    ('{"mcpOAuth": {"srv": {"accessToken": "MCP-SECRET"}}}', "[warn]"),
    ('{"claudeAiOauth": {"accessToken": "CLAUDE-SECRET"}}', "[ok]"),
    ("not json", "[ok]"),
])
def test_oracle_17b_the_file_must_hold_a_claude_login(tmp_path, monkeypatch, content, marker):
    import sys

    graph = _healthy(tmp_path)
    _sdk_present(monkeypatch)
    _clear_rerouting(monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")
    config = _config_dir(tmp_path, monkeypatch, login=False)
    (config / ".credentials.json").write_text(content, encoding="utf-8")
    out = runner.invoke(app, ["doctor", str(graph)]).output
    assert _sub_line(out).startswith(marker), out
    assert "SECRET" not in out


def test_oracle_17_on_macos_the_line_stays_as_11(tmp_path, monkeypatch):
    import sys

    graph = _healthy(tmp_path)
    _sdk_present(monkeypatch)
    _clear_rerouting(monkeypatch)
    monkeypatch.setattr(sys, "platform", "darwin")
    _config_dir(tmp_path, monkeypatch, login=False)
    line = _sub_line(runner.invoke(app, ["doctor", str(graph)]).output)
    assert line.startswith("[ok]") and "not checked" in line


GW_SECRET = "pk-GATEWAY-SECRET-doctor"
GW_URL = "https://gateway.example.test/v1"


def _gw_line(output):
    return next(l for l in output.splitlines() if "gateway review" in l)


def test_oracle_19_configured_gateway_names_kind_and_model(tmp_path, monkeypatch):
    graph = _healthy(tmp_path)
    _sdk_present(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", GW_URL)
    monkeypatch.setenv("ANTHROPIC_CUSTOM_HEADERS", f"x-portkey-api-key: {GW_SECRET}")
    monkeypatch.setenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "us.anthropic.gw-sonnet")
    result = runner.invoke(app, ["doctor", str(graph)])
    assert result.exit_code == 0, result.output
    line = _gw_line(result.output)
    assert line.startswith("[ok]")
    assert "http" in line and "us.anthropic.gw-sonnet" in line
    assert GW_URL not in result.output
    for fragment in (GW_SECRET, GW_SECRET[:12], GW_SECRET[-6:]):
        assert fragment not in result.output


def test_oracle_20_no_gateway_warns_and_names_the_way_on(tmp_path, monkeypatch):
    graph = _healthy(tmp_path)
    _sdk_present(monkeypatch)
    result = runner.invoke(app, ["doctor", str(graph)])
    assert result.exit_code == 0, result.output
    line = _gw_line(result.output)
    assert line.startswith("[warn]") and "--gateway-url" in line


def test_oracle_21_refused_gateway_warns_with_the_runners_reason(tmp_path, monkeypatch):
    import reqlite.review as R

    graph = _healthy(tmp_path)
    _sdk_present(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", GW_URL)
    monkeypatch.setenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "m")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "tok")
    with pytest.raises(R.ReviewError) as e:
        R.gateway_from_env()
    line = _gw_line(runner.invoke(app, ["doctor", str(graph)]).output)
    assert line.startswith("[warn]") and str(e.value) in line


def test_oracle_21_gateway_without_a_model_is_ok_and_names_model(tmp_path, monkeypatch):
    graph = _healthy(tmp_path)
    _sdk_present(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", GW_URL)
    line = _gw_line(runner.invoke(app, ["doctor", str(graph)]).output)
    assert line.startswith("[ok]") and "--model" in line


@pytest.mark.parametrize("value", [GW_SECRET, None])
def test_oracle_22_gateway_key_env_checks_presence_only(tmp_path, monkeypatch, value):
    graph = _healthy(tmp_path)
    _sdk_present(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_DEFAULT_SONNET_MODEL", "m")
    if value is None:
        monkeypatch.delenv("GW", raising=False)
    else:
        monkeypatch.setenv("GW", value)
    result = runner.invoke(app, ["doctor", str(graph), "--gateway-url", GW_URL,
                                 "--gateway-key-env", "GW"])
    assert result.exit_code == 0, result.output
    line = _gw_line(result.output)
    assert "GW" in line
    assert line.startswith("[ok]" if value else "[warn]")
    assert GW_SECRET not in result.output
