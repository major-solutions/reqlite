"""
SC-001: Reference extractor.

Pure function: item content -> set of referenced item IDs.
Satisfies FR-002. See tests/ORACLES.md for the behavioural spec.
"""

import re
from markdown_it import MarkdownIt

# Matches filenames like SRC-022-impact-assessment.md
# Captures the ID portion (SRC-022) as group 1
_ITEM_FILENAME = re.compile(r"^([A-Z]+-\d+)-.+\.md$")


def _split_frontmatter(content: str) -> str:
    """Return the body text after YAML frontmatter, or the full content
    if no frontmatter is found."""
    if not content.startswith("---"):
        return content
    # Find closing --- (must be on its own line after the opening ---)
    end = content.find("\n---", 3)
    if end == -1:
        return content
    # Skip past the closing --- and the newline after it
    body_start = end + 4
    if body_start < len(content) and content[body_start] == "\n":
        body_start += 1
    return content[body_start:]


def extract_references(content: str) -> set[str]:
    """Extract item IDs referenced via markdown links in the body text.

    Args:
        content: Full item file content, including frontmatter.

    Returns:
        Deduplicated set of item IDs (e.g. {"SRC-022", "FR-003"}).
    """
    return set(extract_link_targets(content))


def extract_link_targets(content: str) -> dict[str, set[str]]:
    """Map each referenced item ID to the link targets (filenames) naming it.

    The ID is the connection key; the full target is what existence is
    validated against (FR-002 rule 4, DD-003).
    """
    body = _split_frontmatter(content)

    md = MarkdownIt()
    tokens = md.parse(body)

    targets: dict[str, set[str]] = {}

    for token in tokens:
        if token.children is None:
            continue
        for child in token.children:
            if child.type == "link_open" and child.attrs:
                href = child.attrs.get("href", "")
                match = _ITEM_FILENAME.match(href)
                if match:
                    targets.setdefault(match.group(1), set()).add(href)

    return targets
