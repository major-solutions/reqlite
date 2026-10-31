# reqlite:begin SC-020
"""
SC-020: Project scaffold and ruleset library (DD-036).

Rulesets are shipped, not drafted. The package carries a library of named rulesets under
``rulesets/<name>/``; ``init`` copies one, unmodified, as the project's own ``ruleset/``
beside an empty ``graph/``. A ruleset directory on disk is accepted the same way, so custom
and contributed rulesets need no packaging to be used.

``reqlite`` is this repository's own ruleset, kept byte-identical to ``ruleset/`` by a
test (ORACLES-INIT 1).
"""

from importlib.resources import files
from pathlib import Path
import shutil

DEFAULT = "reqlite"


class ScaffoldError(Exception):
    """The scaffold was refused. Nothing has been written."""


def library_root() -> Path:
    return Path(str(files("reqlite") / "rulesets"))


def library() -> list[str]:
    root = library_root()
    if not root.is_dir():
        return []
    return sorted(d.name for d in root.iterdir()
                  if (d / "ruleset.json").is_file() and not d.name.startswith("_"))


def resolve(source: str) -> Path:
    """A library name, or a path to a ruleset directory."""
    if source in library():
        return library_root() / source
    path = Path(source)
    if path.is_dir():
        if not (path / "ruleset.json").is_file():
            raise ScaffoldError(f"{path} is not a ruleset directory: it has no ruleset.json")
        return path
    raise ScaffoldError(
        f"no ruleset named '{source}'. Library: {', '.join(library()) or 'empty'}. "
        "A path to a ruleset directory also works.")


def scaffold(project_dir: str, source: str = DEFAULT) -> Path:
    """Copy a ruleset into ``project_dir/ruleset`` and ensure ``project_dir/graph``.

    Refuses, writing nothing, when the project directory is missing, a ruleset already
    exists, the source is not a ruleset, or the source contains a symlink. An existing
    ``graph/`` is kept. Returns the source copied from.
    """
    project = Path(project_dir)
    if not project.is_dir():
        raise ScaffoldError(f"{project} is not a directory; create it first")
    target = project / "ruleset"
    if target.exists():
        raise ScaffoldError(
            f"{target} already exists; init never overwrites a ruleset")
    src = resolve(source)
    # A copy follows links, so a ruleset from someone else could bring any readable file
    # into the project, where review would send it to a model (as ORACLES-REVIEW 32).
    links = [p for p in [src, *src.rglob("*")] if p.is_symlink()]
    if links:
        raise ScaffoldError(
            f"{src} contains symlinks ({', '.join(p.name for p in links)}); copy a "
            "ruleset of plain files")
    shutil.copytree(src, target, ignore=shutil.ignore_patterns("__pycache__"))
    (project / "graph").mkdir(exist_ok=True)
    return src
# reqlite:end SC-020
