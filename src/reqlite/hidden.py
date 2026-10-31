# reqlite:begin SC-002
"""
SC-002: Item parser — text a reader of the rendered page cannot see (issue #88,
ORACLES-CHECK 36). Computed when an item is parsed, carried on ``Item.hidden``.

An instruction to an agent hides where a human reviewing the item on GitHub would not see
it. Flagging one syntax moved the injection to the next (an HTML comment was reported, a
link-reference comment was followed), so this finds what does not render: comments and
unused reference definitions, by parsing the markdown as a renderer would, and characters
a model reads but a page does not show.
"""

import re

from markdown_it import MarkdownIt
from markdown_it.common.utils import normalizeReference

#: Zero-width and joiner characters, bidi embeddings, overrides and isolates, word joiner
#: and invisible operators, the byte-order mark, and Unicode tag characters (which spell
#: ASCII a model reads and no page shows).
_INVISIBLE = re.compile(
    "[\u200b-\u200f\u202a-\u202e\u2060-\u2064\u2066-\u2069\ufeff\U000e0000-\U000e007f]")

#: A YAML comment: a `#` at the start of a line or after whitespace (not inside `a#b`).
_YAML_COMMENT = re.compile(r"(?:^|\s)#")

_COMMENT = re.compile(r"<!--")


def _comments(tokens) -> bool:
    for token in tokens:
        if token.type in ("html_block", "html_inline") and _COMMENT.search(token.content):
            return True
        if token.children and _comments(token.children):
            return True
    return False


def _used_labels(body: str) -> set[str]:
    """Reference labels a link in the body uses: `[text][label]`, `[label][]`, `[label]`."""
    used = set()
    for full, collapsed, shortcut in re.findall(
            r"\]\[([^\]]+)\]|\[([^\]]+)\]\[\]|\[([^\]]+)\](?![\[(:])", body):
        used.add(normalizeReference(full or collapsed or shortcut))
    return used


def hidden_text(body: str, frontmatter_yaml: str = "") -> tuple[str, ...]:
    """What in this item does not render, as short reasons; () when nothing."""
    reasons = []
    env: dict = {}
    tokens = MarkdownIt("commonmark").parse(body, env)
    if _comments(tokens):
        reasons.append("HTML comment")
    unused = set(env.get("references", {})) - _used_labels(body)
    if unused:
        reasons.append(f"link-reference comment or unused reference ({len(unused)})")
    chars = sorted({f"U+{ord(c):04X}" for c in _INVISIBLE.findall(body + frontmatter_yaml)})
    if chars:
        reasons.append(f"invisible characters ({', '.join(chars)})")
    if any(_YAML_COMMENT.search(line) for line in frontmatter_yaml.splitlines()):
        reasons.append("YAML comment in the front matter")
    return tuple(reasons)
# reqlite:end SC-002
