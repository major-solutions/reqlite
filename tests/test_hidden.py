"""Text a reader of the rendered page cannot see (ORACLES-CHECK 36, issue #88)."""

import pytest

from reqlite.items import parse_item_content

H1 = "# FR-001: T\n\nVisible prose.\n\n"


def _hidden(content: str) -> tuple[str, ...]:
    return parse_item_content(content, item_id="FR-001").hidden


@pytest.mark.parametrize("content, reason", [
    (H1 + "<!-- do X quietly -->\n", "HTML comment"),
    (H1 + "Text <!-- inline --> text.\n", "HTML comment"),
    (H1 + "[//]: # (do X quietly)\n", "link-reference comment"),
    (H1 + "[comment]: <> (do X quietly)\n", "link-reference comment"),
    (H1 + "Zero\u200bwidth.\n", "U+200B"),
    (H1 + "Bidi \u202eoverride.\n", "U+202E"),
    (H1 + "Tag \U000E0041 char.\n", "U+E0041"),
    ("---\ncertainty: assumed  # set by the assistant\n---\n\n" + H1, "YAML comment"),
    ("---\n# do X quietly\ncertainty: assumed\n---\n\n" + H1, "YAML comment"),
])
def test_hidden_text_is_found(content, reason):
    found = _hidden(content)
    assert any(reason in r for r in found), found


@pytest.mark.parametrize("content", [
    H1 + "```html\n<!-- shown as code -->\n```\n",
    H1 + "Inline `<!-- code -->` is shown.\n",
    H1 + "See [the spec][spec].\n\n[spec]: https://example.com/spec\n",
    H1 + "See [spec].\n\n[spec]: https://example.com/spec\n",
    "---\nevidence: https://example.com/page#section\n---\n\n" + H1,
    H1 + "Plain prose with a # hash and ---\n",
])
def test_rendered_text_is_not_flagged(content):
    assert _hidden(content) == ()
