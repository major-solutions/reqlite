"""
Combine expressions are numeric only (SC-011's frozen operator set, issue #77 finding 5).

A ruleset is data from whoever wrote the repository. If a string reached ``*``, Python's
sequence repetition would turn a combine into an allocation the ruleset's author sizes:
``"x" * 999999999999`` exhausts memory when ``report`` runs on someone else's repository.
Strings can arrive two ways, as a literal in the expression or as a scale value, so the
evaluator checks every operand, not only the literals.
"""

import ast

import pytest

from reqlite.query import QuerySpec, _eval, run_query


def _run(expr, env):
    return _eval(ast.parse(expr, mode="eval"), env)


@pytest.mark.parametrize("expr", ['a * "x"', '"x" * a', "a * b'x'", "a == None"])
def test_non_numeric_literal_is_refused(expr):
    with pytest.raises(ValueError):
        _run(expr, {"a": 3})


def test_string_from_a_scale_is_refused_before_it_is_multiplied(fixture_graph):
    G, _ = fixture_graph
    scales = {"certainty": {"verified": "x", "assumed": "x", "speculative": "x"}}
    spec = QuerySpec(start="SRC", terms=[], combine="self_certainty * 3")
    with pytest.raises(ValueError):
        run_query(G, spec, scales)


@pytest.mark.parametrize("expr,env,expected", [
    ("a * 1.5", {"a": 2}, 3.0),
    ("-a + 1", {"a": 2}, -1),
    ("(a >= 1) * 2", {"a": 1}, 2),
    ("a * 2", {"a": None}, None),
])
def test_numeric_expressions_still_evaluate(expr, env, expected):
    assert _run(expr, env) == expected
