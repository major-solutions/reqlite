# reqlite:begin SC-016
"""
SC-016: Next-id allocator.

Next free item id — computed from history, because retirement deletes (DD-011) and ids are
never reused (SRC-038). The live graph alone cannot show which numbers were used.
"""

import re
import subprocess
from pathlib import Path


class NextIdError(Exception):
    """The next id cannot be determined safely. Never answered with a guess."""


def _git(graph_dir: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=graph_dir, capture_output=True,
                       text=True, encoding="utf-8")
    if r.returncode != 0:
        raise NextIdError(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    return r.stdout


def next_id(prefix: str, graph_dir: Path) -> str:
    """The id after the highest number ever used for ``prefix``, live or retired."""
    graph_dir = Path(graph_dir)
    try:
        inside = _git(graph_dir, "rev-parse", "--is-inside-work-tree").strip()
    except (NextIdError, FileNotFoundError):
        inside = "false"
    if inside != "true":
        raise NextIdError(
            f"{graph_dir} is not inside a git work tree, so retired ids cannot be "
            "recovered and the next id could reuse one."
        )
    if _git(graph_dir, "rev-parse", "--is-shallow-repository").strip() == "true":
        raise NextIdError(
            "this is a shallow clone, so retired ids may be missing from the history and "
            "the next id could reuse one. Run `git fetch --unshallow` first."
        )

    pattern = re.compile(rf"(?:^|/){re.escape(prefix)}-(\d+)-[^/]*\.md$")
    names = [p.name for p in graph_dir.iterdir()]
    names += _git(graph_dir, "log", "--all", "--diff-filter=D", "--name-only",
                  "--format=", "--", ".").splitlines()
    used = [int(m.group(1)) for n in names if (m := pattern.search(n.strip()))]
    return f"{prefix}-{max(used, default=0) + 1:03d}"
# reqlite:end SC-016
