"""
Tests for SC-001: Reference extractor.
Derived from test oracles (tests/ORACLES.md) and FR-002 extraction rules.

All tests call extract_references(content) -> set[str].
"""

from reqlite.references import extract_references


# --- Oracle 1: Basic link extraction ---

def test_basic_link_extraction():
    content = """---
id: SRC-099
title: Test
certainty: assumed
negotiability: constrained
status: active
evidence: null
---

# Test item

This references [SRC-022](SRC-022-impact-assessment.md).
"""
    assert extract_references(content) == {"SRC-022"}


# --- Oracle 2: Multiple distinct references ---

def test_multiple_distinct_references():
    content = """---
id: SRC-099
title: Test
certainty: assumed
negotiability: constrained
status: active
evidence: null
---

# Test item

Depends on [SRC-001](SRC-001-dag-assumption.md).
Also related to [FR-003](FR-003-analysis-runner.md).
See [UC-005](UC-005-impact-assessment.md) for context.
"""
    assert extract_references(content) == {"SRC-001", "FR-003", "UC-005"}


# --- Oracle 3: Deduplication ---

def test_duplicate_references_deduplicated():
    content = """---
id: SRC-099
title: Test
certainty: assumed
negotiability: constrained
status: active
evidence: null
---

# Test item

First mention of [SRC-022](SRC-022-impact-assessment.md).

Second mention of [SRC-022](SRC-022-impact-assessment.md) in another paragraph.

Third mention of [SRC-022](SRC-022-impact-assessment.md) again.
"""
    assert extract_references(content) == {"SRC-022"}


# --- Oracle 4: Descriptive link text ---

def test_descriptive_link_text():
    content = """---
id: SRC-099
title: Test
certainty: assumed
negotiability: constrained
status: active
evidence: null
---

# Test item

As we established in [the DAG assumption](SRC-001-dag-assumption.md), cycles are harmless.
"""
    assert extract_references(content) == {"SRC-001"}


# --- Oracle 5: Fenced code block ignored ---

def test_fenced_code_block_ignored():
    content = """---
id: SRC-099
title: Test
certainty: assumed
negotiability: constrained
status: active
evidence: null
---

# Test item

Some text.

```python
link = "[SRC-022](SRC-022-impact-assessment.md)"
```

More text with [FR-003](FR-003-analysis-runner.md).
"""
    assert extract_references(content) == {"FR-003"}


# --- Oracle 6: Inline code span ignored ---

def test_inline_code_span_ignored():
    content = """---
id: SRC-099
title: Test
certainty: assumed
negotiability: constrained
status: active
evidence: null
---

# Test item

Use `[SRC-022](SRC-022-impact-assessment.md)` as an example.
"""
    assert extract_references(content) == set()


# --- Oracle 7: External links ignored ---

def test_external_links_ignored():
    content = """---
id: SRC-099
title: Test
certainty: assumed
negotiability: constrained
status: active
evidence: null
---

# Test item

See [example](https://example.com) for background.
Also see [SRC-001](SRC-001-dag-assumption.md).
And [docs](http://docs.example.com/page).
"""
    assert extract_references(content) == {"SRC-001"}


# --- Oracle 8: Frontmatter excluded ---

def test_frontmatter_excluded():
    content = """---
id: SRC-099
title: Test item
certainty: assumed
negotiability: constrained
status: active
evidence: "[SRC-001](SRC-001-dag-assumption.md)"
---

# SRC-099: Test item

This references [FR-002](FR-002-reference-extraction.md).
"""
    assert extract_references(content) == {"FR-002"}


# --- Oracle 9: Case sensitivity ---

def test_case_sensitivity_lowercase_not_recognised():
    content = """---
id: SRC-099
title: Test
certainty: assumed
negotiability: constrained
status: active
evidence: null
---

# Test item

This links to [src-001](src-001-dag-assumption.md).
"""
    assert extract_references(content) == set()


# --- Oracle 10: Prefix agnosticism ---

def test_prefix_agnosticism():
    content = """---
id: SRC-099
title: Test
certainty: assumed
negotiability: constrained
status: active
evidence: null
---

# Test item

Links to [SRC-001](SRC-001-dag-assumption.md), [FR-002](FR-002-ref.md),
[UC-005](UC-005-impact.md), [DD-003](DD-003-refs.md),
[SC-001](SC-001-extractor.md), and [RSK-001](RSK-001-content-exposure.md).
"""
    assert extract_references(content) == {
        "SRC-001", "FR-002", "UC-005", "DD-003", "SC-001", "RSK-001"
    }


# --- Oracle 11: Non-item links ignored ---

def test_non_item_links_ignored():
    content = """---
id: SRC-099
title: Test
certainty: assumed
negotiability: constrained
status: active
evidence: null
---

# Test item

See [README](README.md) and [conventions](../agent/conventions.md).
"""
    assert extract_references(content) == set()


# --- Oracle 12: No .md extension ---

def test_no_md_extension_not_extracted():
    content = """---
id: SRC-099
title: Test
certainty: assumed
negotiability: constrained
status: active
evidence: null
---

# Test item

Link without extension: [SRC-001](SRC-001-dag-assumption).
Link with extension: [FR-002](FR-002-reference-extraction.md).
"""
    assert extract_references(content) == {"FR-002"}


# --- Oracle 13: Determinism ---

def test_determinism():
    content = """---
id: SRC-099
title: Test
certainty: assumed
negotiability: constrained
status: active
evidence: null
---

# Test item

References [SRC-001](SRC-001-dag.md) and [FR-003](FR-003-runner.md).
"""
    result1 = extract_references(content)
    result2 = extract_references(content)
    assert result1 == result2
    assert result1 == {"SRC-001", "FR-003"}


# --- Oracle 14: Empty body ---

def test_empty_body():
    content = """---
id: SRC-099
title: Test
certainty: assumed
negotiability: constrained
status: active
evidence: null
---

"""
    assert extract_references(content) == set()


# --- Oracle 15: Punctuation after link ---

def test_punctuation_after_link():
    content = """---
id: SRC-099
title: Test
certainty: assumed
negotiability: constrained
status: active
evidence: null
---

# Test item

See [SRC-022](SRC-022-impact-assessment.md).
Also [FR-003](FR-003-analysis-runner.md), which is important.
And ([UC-001](UC-001-capture-item.md)).
"""
    assert extract_references(content) == {"SRC-022", "FR-003", "UC-001"}


# --- Oracle 16: Nested markdown ---

def test_link_inside_bold():
    content = """---
id: SRC-099
title: Test
certainty: assumed
negotiability: constrained
status: active
evidence: null
---

# Test item

**See [SRC-022](SRC-022-impact-assessment.md) for details.**
"""
    assert extract_references(content) == {"SRC-022"}


# --- Oracle 17: Reference-style links ---

def test_reference_style_links():
    content = """---
id: SRC-099
title: Test
certainty: assumed
negotiability: constrained
status: active
evidence: null
---

# Test item

This references [SRC-001][dag] and [FR-002][ref].

[dag]: SRC-001-dag-assumption.md
[ref]: FR-002-reference-extraction.md
"""
    assert extract_references(content) == {"SRC-001", "FR-002"}
