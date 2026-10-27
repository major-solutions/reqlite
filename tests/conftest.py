"""
Shared pytest fixtures for reqlite tests.
"""

from pathlib import Path

import pytest

from reqlite.items import parse_all
from reqlite.graph import build_graph


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "graph"


@pytest.fixture
def fixture_items():
    """Load the standard fixture graph items."""
    return parse_all(FIXTURES_DIR)


@pytest.fixture
def fixture_graph():
    """Build graph from the standard fixture items.
    Returns (DiGraph, findings)."""
    items = parse_all(FIXTURES_DIR)
    return build_graph(items)


@pytest.fixture
def fixture_graph_dir():
    """Return the path to the fixture graph directory."""
    return FIXTURES_DIR


@pytest.fixture(autouse=True)
def _no_inherited_routing(monkeypatch):
    """Hermetic: the review runner refuses subscription mode when these are set, and a
    developer machine or cloud session often sets one (ANTHROPIC_BASE_URL for a gateway).
    Tests that need one set it themselves. The same holds for the default key variable:
    a developer who set it would otherwise turn every refusal test into a key-mode run.
    Gateway variables likewise: an inherited one would decide what `--gateway` passes on."""
    from reqlite.review import _GATEWAY_VARS, _SUBSCRIPTION_REROUTING_VARS, DEFAULT_KEY_ENV
    for var in (*_SUBSCRIPTION_REROUTING_VARS, *_GATEWAY_VARS, DEFAULT_KEY_ENV):
        monkeypatch.delenv(var, raising=False)
