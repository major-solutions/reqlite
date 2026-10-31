Toy project for `reqlite trace-compare`, with one planted case per finding. Its own
`graph/` and `ruleset/` make it a nested project, so a fence scan of the repository above
skips it. `observed.json` was written by `examples/adapters/pytest_observed.py` from a real
run of this project's tests; `tests/test_trace.py::test_oracle_18_the_example_adapter_writes_format_1`
shows the steps.
