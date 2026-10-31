"""
Every plugin invocation of the engine resolves under a dependency cooldown (DD-032).

``uvx --from <plugin root>`` ignores the project's ``uv.lock`` and its
``[tool.uv] exclude-newer``, so the command-line flag is the only setting an installer's
resolve obeys. One invocation without it resolves whatever was uploaded a minute ago.

The cutoff is an absolute date, set when a release is cut: uv before 0.9.17 rejects a
relative one ("7 days") with exit 2, the hook protocol's block code, which denied every
agent commit, and in VS Code every tool call (issue #109).
"""

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FLAG = re.compile(r"--exclude-newer (\d{4}-\d{2}-\d{2})(?=\s)")


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


def _guide_cooldowns():
    """The user guide's lines that set a cooldown (its pre-commit hook for humans)."""
    text = (ROOT / "docs" / "user-guide.md").read_text(encoding="utf-8")
    return [line.strip() for line in text.splitlines() if "--exclude-newer" in line]


def test_every_skill_invocation_carries_the_cooldown():
    found = list(_skill_invocations())
    assert len(found) >= 4, "test premise: the skills' invocations are found"
    missing = [f"{p}: {line}" for p, line in found if not FLAG.search(line)]
    assert missing == []


def test_every_hook_invocation_carries_the_cooldown():
    found = list(_hook_invocations())
    assert found, "test premise: the commit-gate hook is found"
    for command in found:
        assert FLAG.search(command), command


def test_every_invocation_shares_one_cutoff_date():
    """Skills, hooks and the guide's pre-commit line resolve the same dependency set; a
    release bumps the date in all of them at once."""
    guide = _guide_cooldowns()
    assert guide, "test premise: the guide's pre-commit hook is found"
    lines = [line for _, line in _skill_invocations()] + list(_hook_invocations()) + guide
    assert [line for line in lines if not FLAG.search(line)] == []
    dates = {date for line in lines for date in FLAG.findall(line)}
    assert len(dates) == 1, dates


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


GATE = "reqlite commit-gate"
EXIT_SUFFIX = "; exit $LASTEXITCODE"


def test_the_gate_command_passes_its_exit_code_through_powershell():
    """VS Code's Copilot agent on Windows runs a hook through `powershell.exe -Command`,
    which turns a native exit 2 into 1, and VS Code reads 1 as a non-blocking error: the
    gate found the errors and the commit went through (issue #105)."""
    for command in _hook_invocations():
        assert command.endswith(GATE + EXIT_SUFFIX), command


def _shells():
    """Shells that run a command. On Windows `bash` can be the WSL launcher, which fails
    every command when no distribution is installed (#125), so each candidate is probed."""
    import shutil
    import subprocess

    def works(argv):
        return subprocess.run([*argv, "exit 3"], capture_output=True).returncode == 3

    for name in ("sh", "bash"):
        if shutil.which(name) and works([shutil.which(name), "-c"]):
            yield name, [shutil.which(name), "-c"], False
    for name in ("powershell", "pwsh"):
        if shutil.which(name):
            # The arguments VS Code passes (issue #105).
            yield name, [shutil.which(name), "-ExecutionPolicy", "Bypass", "-NoProfile",
                         "-NoLogo", "-Command"], True


@pytest.mark.parametrize("code", [0, 2])
def test_the_exit_suffix_keeps_the_gate_status_in_every_available_shell(code):
    """The suffix is PowerShell; in a POSIX shell `$LASTEXITCODE` is unset and the bare
    `exit` returns the last command's status. Measured with the gate replaced by a process
    exiting `code`, under each shell on the machine (dash on CI, PowerShell on Windows)."""
    import subprocess
    import sys

    command = next(_hook_invocations())
    suffix = command[command.index(GATE) + len(GATE):]
    found = list(_shells())
    assert found, "test premise: at least one shell is available"
    for name, argv, powershell in found:
        exe = sys.executable.replace("\\", "/")
        stub = (f"& '{exe}'" if powershell else f"'{exe}'") + f" -c 'import sys; sys.exit({code})'"
        if powershell and code:
            bare = subprocess.run([*argv, stub], capture_output=True).returncode
            assert bare == 1, f"{name}: test premise, -Command flattens the exit code"
        got = subprocess.run([*argv, stub + suffix], capture_output=True).returncode
        assert got == code, name


def test_marketplace_manifest_parses_on_older_clients():
    """Claude Code 2.1.76 rejects `"source": "."` and a root `description` (issue #85;
    `claude plugin validate`, measured 2026-10-24). `./` and `metadata.description` pass
    on 2.1.76 and on current versions."""
    manifest = json.loads((ROOT / ".claude-plugin" / "marketplace.json")
                          .read_text(encoding="utf-8"))
    assert "description" not in manifest
    assert all(p["source"] == "./" for p in manifest["plugins"])
