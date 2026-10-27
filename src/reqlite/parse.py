"""
SC-010: Inference client (response parsing).

LLM response parsing: fence stripping, JSON extraction, schema validation.
"""

import json
import re


def parse_findings(raw: str, require_target: bool = True) -> dict | None:
    """Parse and validate LLM findings output.

    Handles: markdown fences, preamble text, trailing commentary.
    Returns validated dict or None if parsing/validation fails. ``require_target=False``
    accepts a bare ``{"findings": [...]}``, for checks with no single target item (SC-018).
    """
    if not raw or not raw.strip():
        return None

    text = raw.strip()

    # Try to extract JSON from markdown fences first
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1).strip()
    else:
        # Try to find JSON object by locating first { and last }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]
        else:
            return None

    # Parse JSON
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None

    # Validate schema
    if not isinstance(data, dict):
        return None
    if require_target and "target" not in data:
        return None
    if "findings" not in data:
        return None
    if not isinstance(data["findings"], list):
        return None

    return data
