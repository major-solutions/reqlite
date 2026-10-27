"""
Tests for SC-002: Item parser.
Derived from test oracles (tests/ORACLES-SC002.md) and FR-008 parsing rules.
"""

import pytest
from pathlib import Path

from reqlite.items import parse_item_content, parse_all, Item, ParseError


VALID_ITEM = """\
---
id: SRC-099
title: Test item
certainty: assumed
negotiability: constrained
status: active
evidence: null
---

# SRC-099: Test item

This is the body. It references [SRC-001](SRC-001-dag-assumption.md).
"""


# --- Oracle 1: Valid item with all required fields ---

def test_valid_item_all_required_fields():
    item = parse_item_content(VALID_ITEM)
    assert item.id == "SRC-099"
    assert item.title == "Test item"
    assert item.certainty == "assumed"
    assert item.negotiability == "constrained"
    assert "This is the body" in item.body
    assert "[SRC-001](SRC-001-dag-assumption.md)" in item.body


def test_unmodelled_frontmatter_kept_in_file_order():
    # Fields a ruleset declares (SRC `source`, ...) are not the engine's to drop (ADR-016).
    content = """\
---
source: stakeholder interview
certainty: assumed
tags: [a, b]
status: active
---

# SRC-099: Test item
"""
    item = parse_item_content(content, "SRC-099")
    assert list(item.extra.items()) == [("source", "stakeholder interview"),
                                        ("tags", ["a", "b"]), ("status", "active")]


def test_modelled_fields_not_duplicated_in_extra():
    item = parse_item_content(VALID_ITEM)
    assert set(item.extra) == {"status"}


# --- Oracle 2: Optional evidence field ---

def test_optional_evidence_present():
    content = """\
---
id: SRC-099
title: Test
certainty: assumed
negotiability: constrained
status: active
evidence: "https://example.com"
---

Body.
"""
    item = parse_item_content(content)
    assert item.evidence == "https://example.com"


# --- Oracle 3: Optional actor field ---

def test_optional_actor_present():
    content = """\
---
id: UC-001
title: Capture an item
certainty: verified
negotiability: immovable
status: active
evidence: null
actor: Tamás
---

Body.
"""
    item = parse_item_content(content)
    assert item.actor == "Tamás"


# --- Oracle 4: Optional fields absent ---

def test_optional_fields_absent():
    item = parse_item_content(VALID_ITEM)
    assert item.evidence is None
    assert item.actor is None


# --- Oracles 5–9: Missing required fields ---

def _without(field):
    return "".join(
        line for line in VALID_ITEM.splitlines(keepends=True)
        if not line.startswith(f"{field}:")
    )


def test_missing_id_raises_without_filename():
    # id must come from the filename or the frontmatter; absent both, it's an error
    with pytest.raises(ParseError, match="id"):
        parse_item_content(_without("id"))


def test_id_from_filename_when_frontmatter_absent():
    item = parse_item_content(_without("id"), item_id="SRC-077")
    assert item.id == "SRC-077"


@pytest.mark.parametrize("missing_field, attr, expected", [
    ("title", "title", "Test item"),  # lifted from the H1 now; id only when no H1        # defaults to the id
    ("certainty", "certainty", None),
    ("negotiability", "negotiability", None),
])
def test_optional_fields_default_when_absent(missing_field, attr, expected):
    item = parse_item_content(_without(missing_field))
    assert getattr(item, attr) == expected


# --- Oracle 10: Invalid certainty value ---

def test_invalid_certainty():
    content = VALID_ITEM.replace("certainty: assumed", "certainty: maybe")
    with pytest.raises(ParseError, match="certainty"):
        parse_item_content(content)


# --- Oracle 11: Invalid negotiability value ---

def test_invalid_negotiability():
    content = VALID_ITEM.replace("negotiability: constrained", "negotiability: flexible")
    with pytest.raises(ParseError, match="negotiability"):
        parse_item_content(content)
# --- Oracle 13: No frontmatter at all ---

def test_no_frontmatter():
    content = "# Just a heading\n\nSome text.\n"
    with pytest.raises(ParseError, match="frontmatter"):
        parse_item_content(content)


# --- Oracle 14: Malformed YAML ---

def test_malformed_yaml():
    content = """\
---
id: SRC-099
title: "unclosed quote
certainty: assumed
---

Body.
"""
    with pytest.raises(ParseError, match="[Yy][Aa][Mm][Ll]"):
        parse_item_content(content)


# --- Oracle 15: Body preserved verbatim ---

def test_body_preserved_verbatim():
    body_text = """# Heading with [link](SRC-001-dag.md)

Special chars: á é ö ü ő ű — "curly quotes"

    indented block

* list item
"""
    content = f"""\
---
id: SRC-099
title: Test
certainty: assumed
negotiability: constrained
status: active
evidence: null
---
{body_text}"""
    item = parse_item_content(content)
    assert item.body == body_text


# --- Oracle 16: Body with horizontal rule (---) ---

def test_body_horizontal_rule_not_confused_with_frontmatter():
    content = """\
---
id: SRC-099
title: Test
certainty: assumed
negotiability: constrained
status: active
evidence: null
---

# Title

Some text.

---

More text after the horizontal rule.
"""
    item = parse_item_content(content)
    assert "---" in item.body
    assert "More text after the horizontal rule." in item.body


# --- Oracle 17: Empty body ---

def test_empty_body():
    content = """\
---
id: SRC-099
title: Test
certainty: assumed
negotiability: constrained
status: active
evidence: null
---
"""
    item = parse_item_content(content)
    assert item.body.strip() == ""


# --- Oracle 18: Extra unknown fields ignored ---

def test_extra_unknown_fields_ignored():
    content = """\
---
id: SRC-099
title: Test
certainty: assumed
negotiability: constrained
status: active
evidence: null
topic: tourism
custom_field: whatever
---

Body.
"""
    item = parse_item_content(content)
    assert item.id == "SRC-099"
    # No error, unknown fields silently ignored


# --- Oracle 19: Determinism ---

def test_determinism():
    item1 = parse_item_content(VALID_ITEM)
    item2 = parse_item_content(VALID_ITEM)
    assert item1 == item2


# --- Oracle 20: Optional effort field ---

def test_optional_effort_present():
    content = """\
---
id: SC-001
title: Test component
certainty: verified
negotiability: constrained
status: active
evidence: null
effort: 3
---

Body.
"""
    item = parse_item_content(content)
    assert item.effort == 3


def test_optional_effort_absent():
    item = parse_item_content(VALID_ITEM)
    assert item.effort is None


# --- Oracle 20: parse_all sorted by filename ---

def test_parse_all_sorted_by_filename(tmp_path):
    # Create files in non-alphabetical order
    for name, item_id in [
        ("UC-001-capture.md", "UC-001"),
        ("FR-002-extraction.md", "FR-002"),
        ("SRC-001-dag.md", "SRC-001"),
    ]:
        (tmp_path / name).write_text(f"""\
---
id: {item_id}
title: {item_id}
certainty: assumed
negotiability: constrained
status: active
evidence: null
---

Body.
""")
    items = parse_all(tmp_path)
    assert [item.id for item in items] == ["FR-002", "SRC-001", "UC-001"]


# --- Oracle 21: parse_all skips non-matching filenames ---

def test_parse_all_skips_non_item_files(tmp_path):
    # One valid item
    (tmp_path / "SRC-001-dag.md").write_text("""\
---
id: SRC-001
title: DAG
certainty: assumed
negotiability: constrained
status: active
evidence: null
---

Body.
""")
    # Non-matching files
    (tmp_path / "README.md").write_text("# Readme\n")
    (tmp_path / "notes.txt").write_text("some notes\n")

    items = parse_all(tmp_path)
    assert len(items) == 1
    assert items[0].id == "SRC-001"


# --- Oracle 22: parse_all empty directory ---

def test_parse_all_empty_directory(tmp_path):
    items = parse_all(tmp_path)
    assert items == []


# --- Frontmatter-optional parsing and H1 title derivation (consolidation, 2026-06-11) ---


def test_no_frontmatter_block_parses():
    """A file with no frontmatter at all is a valid minimum item: body only."""
    item = parse_item_content("# SRC-900: Bare item\n\nJust a body.\n", item_id="SRC-900")
    assert item.id == "SRC-900"
    assert item.body.startswith("# SRC-900")


def test_empty_frontmatter_block_parses():
    """An empty ---/--- block parses as no metadata."""
    item = parse_item_content("---\n---\n\n# SRC-901: Empty fm\n\nBody.\n", item_id="SRC-901")
    assert item.id == "SRC-901"


def test_title_lifted_from_h1_with_id_prefix():
    """Without a frontmatter title, the first H1 supplies it; a leading 'ID:' is stripped."""
    item = parse_item_content("# SRC-902: The lifted title\n\nBody.\n", item_id="SRC-902")
    assert item.title == "The lifted title"


def test_title_lifted_from_h1_without_id_prefix():
    item = parse_item_content("# A plain heading\n\nBody.\n", item_id="SRC-903")
    assert item.title == "A plain heading"


def test_title_defaults_to_id_when_no_h1():
    item = parse_item_content("---\ncertainty: assumed\n---\n\nNo heading here.\n", item_id="SRC-904")
    assert item.title == "SRC-904"


def test_frontmatter_title_wins_over_h1():
    content = "---\ntitle: Authored title\n---\n\n# SRC-905: Different heading\n\nBody.\n"
    item = parse_item_content(content, item_id="SRC-905")
    assert item.title == "Authored title"


# --- Oracle 23: parse_all records each item's filename ---

def test_parse_all_records_the_filename(tmp_path):
    (tmp_path / "SRC-001-dag.md").write_text("# SRC-001: DAG\n\nBody.\n", encoding="utf-8")
    [item] = parse_all(tmp_path)
    assert item.filename == "SRC-001-dag.md"


def test_content_alone_has_no_filename():
    item = parse_item_content("# SRC-001: DAG\n\nBody.\n", item_id="SRC-001")
    assert item.filename is None
