"""
Every plugin invocation of the engine resolves under a dependency cooldown (DD-032).

``uvx --from <plugin root>`` ignores the project's ``uv.lock`` and its
``[tool.uv] exclude-newer``, so the command-line flag is the only setting an installer's
resolve obeys. One invocation without it resolves whatever was uploaded a minute ago.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FLAG = '--exclude-newer "7 days"'


def _skill_invocations():
    for path in sorted((ROOT / "skills").rglob("*.md")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if re.match(r"\s*uvx\s", line):
                yield path.relative_to(ROOT), line.strip()


def _hooks():
    hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    for entries in hooks["hooks"].values():
        for entry in entries:
            yield from entry["hooks"]


def _hook_invocations():
    for hook in _hooks():
        if hook.get("command", "").startswith("uvx "):
            yield hook["command"]


def test_every_skill_invocation_carries_the_cooldown():
    found = list(_skill_invocations())
    assert len(found) >= 4, "test premise: the skills' invocations are found"
    missing = [f"{p}: {line}" for p, line in found if FLAG not in line]
    assert missing == []


def test_every_hook_invocation_carries_the_cooldown():
    found = list(_hook_invocations())
    assert found, "test premise: the commit-gate hook is found"
    for command in found:
        assert FLAG in command


def test_hooks_are_shell_form_with_the_plugin_root_quoted():
    """Clients older than Claude Code 2.1.139, and VS Code's agents, drop exec-form `args`
    and ran bare `uvx`, whose exit 2 blocked every Bash call (issues #78, #85). A shell-form
    command survives every parser; the root is quoted because it can hold spaces."""
    for hook in _hooks():
        assert "args" not in hook
        assert '"${CLAUDE_PLUGIN_ROOT}"' in hook["command"]


def test_the_gate_also_fires_on_git_dash_c():
    """`git -C <dir> commit` does not match `Bash(git commit*)` (#89 named it as a bypass).
    `if` holds one rule, so a second handler runs the same gate; the gate itself ignores
    every `git -C` command that is not a commit."""
    gates = {h.get("if"): h["command"] for h in _hooks()}
    assert set(gates) == {"Bash(git commit*)", "Bash(git -C *)"}
    assert len(set(gates.values())) == 1


def test_marketplace_manifest_parses_on_older_clients():
    """Claude Code 2.1.76 rejects `"source": "."` and a root `description` (issue #85;
    `claude plugin validate`, measured 2026-10-24). `./` and `metadata.description` pass
    on 2.1.76 and on current versions."""
    manifest = json.loads((ROOT / ".claude-plugin" / "marketplace.json")
                          .read_text(encoding="utf-8"))
    assert "description" not in manifest
    assert all(p["source"] == "./" for p in manifest["plugins"])
