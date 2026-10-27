# reqlite methodology

What is true for every reqlite project. Everything project-specific — item types, their
definitions, field vocabularies, conventions — lives in that project's `ruleset/`. Do not
assume any type system from prior knowledge of reqlite.

## Why it is shaped this way

The generative principle is YAGNI, applied to requirements rather than code: an item that
nothing justifies is speculative scope, and speculative scope is cut. Justification is
therefore the primary *structure*. Each item links to the items beneath it that justify
it, and that DAG turns "is this needed, and what needs it?" into a fact you can check
instead of a judgement call.

Everything that might read as a quirk follows from that:

- **No status field or workflow.** That is speculative machinery; membership in the graph
  already marks an item as live.
- **Retirement is deletion, not archival.** Git already keeps history, so hoarding retired
  items in the tree adds nothing.
- **The engine adjudicates only structural integrity.** Every evaluative call — risk,
  coverage, severity, the type system itself — is per-project configuration, because
  baking in methodology a project might not need is the speculative generality YAGNI
  rejects.

If you carry Jira or DOORS priors — work tracking, forward traceability, lifecycle
metadata — drop them. This is a smaller, stricter idea.

## Core concepts

- **Item.** A markdown file named `{PREFIX}-{NUM}-{slug}.md`; its id is `{PREFIX}-{NUM}`,
  taken from the filename and nowhere else. Frontmatter is optional. A frontmatter `id`
  that disagrees with the filename is a hard parse error. The title is the first H1, with
  a leading `ID:` stripped.
- **Prefix.** Classifies what kind of thinking an item records. Defined per project in the
  ruleset; there is no fixed set.
- **Reference.** A standard markdown link to another item's filename, e.g.
  `[ABC-001](ABC-001-title.md)`. It means "I depend on / derive from / am justified by
  this". References point at foundations, never at dependents, and form a DAG. The
  project's `reference_conventions` in the ruleset are authoritative.
- **Ruleset.** `ruleset/ruleset.json` beside the graph directory: type definitions, field
  scales, declared analyses, prompt paths, and optionally a `readme`. A `prompts/`
  directory holds the per-type review prompts.
- **Project readme.** Optional prose orientation for one project — its domain and the
  intent behind its type boundaries. It deliberately carries no enumerable facts; those
  live in the ruleset.
- **Layer.** All items sharing a prefix.
- **Retirement.** Absorption then deletion. Salvage remaining value into living items,
  remove every inbound link, delete the file. The commit message names the retired id and
  where its value went. Retired ids are never reused.

## Authored versus derived

Two notions of confidence coexist and must not be confused:

- **Authored**, e.g. `certainty` and `negotiability` — the writer's judgement about an
  item's own claim. An opinion someone writes down. Never invent or change these values;
  propose them to the owner visibly.
- **Derived**, e.g. foundation risk — computed by the engine from the graph. A property
  you read off, never one you write.

Quality review consumes the authored values; declared analyses compute derived ones.
Which fields exist, and the scale behind each, are ruleset facts.

## Starting a new project

Run `reqlite init [dir]`. It creates a flat `graph/` and copies a shipped ruleset into
`ruleset/` beside it: by default `reqlite`, this tool's own; `--ruleset <name>` picks
another from the library, and `--ruleset <path>` copies a ruleset directory the user
already has. An error on an unknown name lists the library.

**Rulesets are shipped, not drafted.** Formulating one takes understanding and
experience, and a ruleset drafted in a conversation looks complete when it is not: vague
type boundaries make every later finding meaningless, and nothing reports it. Do not offer
to draft types, descriptions or quality prompts. If the user asks, say that reqlite
supports starting from a shipped ruleset, and that writing their own is possible at their
own risk. The copied ruleset is the project's own; changing it is the user's call.

One thing is the engine's, not the project's: a quality prompt must ask the reviewer for
the envelope `{"target": "<id>", "findings": [ ... ]}`. A response without it is reported
as unreadable.

## Changing the ruleset

Gaps in a type system are found by use, not by inference: an item that fits no type, or
a review that lets through something the type should catch. When that happens, with the
user's agreement:

1. Add the missing type, or the missing criterion to the type's quality prompt. The
   quality prompt is the norm items are judged against.
2. Rewrite the type's `description` from its quality prompt. The description is what
   authors read first; if it no longer matches the prompt, items get written to one rule
   and reviewed against another, and nothing reports it.
3. Run `reqlite check-ruleset` to harden the changed boundary against the existing
   types. Findings on pairs the change did not touch are usually pre-existing.

A tightened ruleset does not re-check existing items. Say so, and let the user decide
which items to revisit.
