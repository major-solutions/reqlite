"""
Tests for the parse command — LLM response cleaning and validation.
"""

import json

from reqlite.parse import parse_findings


# --- Clean JSON passes through ---

def test_clean_json_passthrough():
    raw = '{"target": "SC-001", "findings": []}'
    result = parse_findings(raw)
    assert result == {"target": "SC-001", "findings": []}


# --- Strips markdown fences ---

def test_strips_json_fences():
    raw = '```json\n{"target": "SC-001", "findings": []}\n```'
    result = parse_findings(raw)
    assert result == {"target": "SC-001", "findings": []}


def test_strips_plain_fences():
    raw = '```\n{"target": "SC-001", "findings": []}\n```'
    result = parse_findings(raw)
    assert result == {"target": "SC-001", "findings": []}


# --- Strips preamble text ---

def test_strips_preamble():
    raw = 'Here is my analysis:\n\n{"target": "SC-001", "findings": []}'
    result = parse_findings(raw)
    assert result == {"target": "SC-001", "findings": []}


def test_strips_preamble_with_fences():
    raw = 'Here is the result:\n\n```json\n{"target": "SC-001", "findings": []}\n```'
    result = parse_findings(raw)
    assert result == {"target": "SC-001", "findings": []}


# --- Strips trailing commentary ---

def test_strips_trailing_text():
    raw = '{"target": "SC-001", "findings": []}\n\nLet me know if you need more detail.'
    result = parse_findings(raw)
    assert result == {"target": "SC-001", "findings": []}


# --- Validates schema ---

def test_validates_target_field():
    raw = '{"findings": []}'
    result = parse_findings(raw)
    assert result is None


def test_validates_findings_field():
    raw = '{"target": "SC-001"}'
    result = parse_findings(raw)
    assert result is None


def test_validates_findings_is_list():
    raw = '{"target": "SC-001", "findings": "none"}'
    result = parse_findings(raw)
    assert result is None


# --- Handles real findings ---

def test_preserves_findings():
    data = {
        "target": "SC-201",
        "findings": [
            {
                "category": "ambiguity",
                "items": ["SRC-003", "FR-015"],
                "summary": "Coefficient format unspecified.",
                "severity": "medium"
            }
        ]
    }
    raw = json.dumps(data)
    result = parse_findings(raw)
    assert result == data
    assert len(result["findings"]) == 1
    assert result["findings"][0]["category"] == "ambiguity"


# --- Returns None on garbage ---

def test_garbage_input():
    result = parse_findings("This is not JSON at all.")
    assert result is None


def test_empty_input():
    result = parse_findings("")
    assert result is None
