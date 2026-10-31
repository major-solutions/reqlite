<p align="center">
  <img src="docs/assets/banner.svg" alt="reqlite: a cairn of stacked stones at dusk, each resting on the ones below" width="100%">
</p>

# reqlite

Requirements management for the LLM era: a graph of plain markdown files in your git
repository, checked by deterministic analysis and reviewed by a language model in an
isolated process.

No database, no stored edges, no status fields. The files are the system.

> **Status: early (0.1).** The core works and is used to build reqlite itself. Expect rough
> edges. Feedback and issues are welcome.

## Why

Traditional requirements engineering decomposes deeply, partly because no human can hold
hundreds of items in mind at once. A language model with a large context window can read
a whole justification chain in one pass. reqlite takes advantage of that: graphs stay
shallow, every item says what it rests on, and the expensive judgment work goes to a
model only where the structure says it matters.

## How it works

An **item** is one markdown file. The filename is its identity, the first heading is its
title, and the optional frontmatter holds judgments such as how certain the claim is:

```markdown
---
certainty: assumed
negotiability: negotiable
---

# FR-012: The system must reject payloads over the configured limit

Users upload exports from [UC-004](UC-004-import-export.md); the limit protects the
parser described in [DD-007](DD-007-streaming-parser.md).
```

- **Links are ordinary markdown links** and always point at what justifies an item, never
  at what depends on it. Together they form a directed acyclic graph. Nothing is stored:
  the edges are parsed from the text every time an analysis runs.
- **Types are yours.** The prefix (`FR`, `UC`, …) is the type, and a per-project
  *ruleset* defines the types, their fields, the analyses to run and the review prompts.
  The engine itself has no opinion about any of it.
- **Retiring an item means deleting it**, after moving whatever is still valuable into
  the items that should carry it. Git history is the archive.

It analyses the graph in two ways, and never lets one stand in for the other:

| | Algorithmic | Inferential |
|---|---|---|
| Run by | the engine, deterministically | a language model, in an isolated process |
| Reads | links and frontmatter | the meaning of the text |
| Cost | free, milliseconds | one model call per item |
| Examples | integrity, coverage, assumption risk, commit check | quality review, consistency against foundations, ruleset coherence |

The structural analysis produces a reading list: which items carry the most risk and
where a defect would cost the most. The model then reviews those items one at a time, in
a fresh process with no tools and no access to your conversation, so its findings are
independent of whoever wrote the item.

## Install

reqlite is a [Claude Code](https://claude.com/claude-code) plugin. You need Claude Code
and [uv](https://docs.astral.sh/uv/) 0.4 or later. It is developed and tested on current Claude Code
(2.1.310). Versions from 2.1.76 install it; before 2.1.85 the commit check runs ahead of
every shell command rather than only commits, adding about half a second to each.

```bash
claude plugin marketplace add major-solutions/reqlite
claude plugin install reqlite@reqlite
```

It also works as an agent plugin in VS Code with GitHub Copilot (tested on Windows); the
[user guide](docs/user-guide.md#in-vs-code-with-github-copilot) has the setup and the
differences.

Then, in a repository, ask Claude to *"set up reqlite here"* (it runs `reqlite init`), or
to *"run the reqlite report"*. The plugin brings two skills: `reqlite` for the method,
authoring and structural analysis, and `review` for LLM review.

**LLM review** is billed to an Anthropic API key in the `REQLITE_API_KEY` environment
variable by default, or to your company's gateway with `--gateway`. Claude asks which one
before the first review. The [user guide](docs/user-guide.md#setting-up-a-key) explains
how to set up a key safely.

**What leaves your machine:** only the review commands send anything, and they send the
item (or, for a consistency check, the item and its foundations) plus your ruleset's
prompt, to Anthropic. Everything else runs locally.

## Documentation

- **[User guide](docs/user-guide.md)**: the model, the daily loop, how to read the
  report, quality review, the commit check and current limits.
- `skills/reqlite/references/`: every command, authoring guidance and the method.

## Repository layout

reqlite is specified in reqlite: its own requirements are a reqlite graph, developed
privately. This repository is the released plugin.

```text
.claude-plugin/              plugin manifest and single-plugin marketplace
skills/                      the plugin's skills: reqlite (method, analysis), review (LLM review)
hooks/                       the commit check for agent commits
src/reqlite/                 the engine
src/reqlite/rulesets/        the ruleset library `reqlite init` copies from
tests/                       the test suite
docs/                        user guide
```

## Running the tests

```bash
git clone https://github.com/major-solutions/reqlite.git
cd reqlite
uv run --extra dev pytest
```

Python 3.11+. Issues are welcome; for security problems, see [SECURITY.md](SECURITY.md).
Changes are made in the private development repository and arrive here with each
release, so a pull request is read as a proposal rather than merged directly.

## License

[Apache License 2.0](LICENSE). Copyright 2026 Tamás Majoros.
