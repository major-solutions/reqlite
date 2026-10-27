# Commands and their output

`reqlite <command>` means the invocation given in SKILL.md. Every command takes an
optional `graph_dir` (default `graph`); the ruleset is read from `ruleset/` beside it.
`reqlite <command> --help` is authoritative for flags.

## Orientation and health

| Command | What it returns |
|---|---|
| `init [dir] [--ruleset NAME\|PATH]` | Creates `graph/` and copies a shipped ruleset into `ruleset/` (default `reqlite`). Never overwrites a ruleset; keeps an existing graph. Exit 0 done; 1 refused, nothing written (stderr; an unknown name lists the library); 4 copied, but the ruleset has algorithmic findings (printed). |
| `doctor [graph_dir] [--api-key-env NAME]` | One checklist line per runtime: engine, graph, ruleset, review extra, whether the key variable (`REQLITE_API_KEY` by default) is set, and whether this environment lets key and subscription review run. Never prints any part of the key. `[fail]` means stop; `[warn]` on the review extra or a credential line only removes inferential checks in that mode — algorithmic analysis still runs. |
| `report [graph_dir]` | Markdown: a `Hidden text` section first when any item holds text the rendered page does not show (comments, unused reference definitions, YAML comments, invisible characters), then the integrity gate, then descriptive topology and orphans, then every analysis the ruleset declares, each with its declared severity. The primary analysis. |
| `integrity [graph_dir]` | The self-integrity findings: duplicate ids, unknown references, cycles, and orphans (descriptive, not failures; the other three are what `report` gates on). Exit 0 even when findings exist; read the output. |
| `check [graph_dir] [--staged\|--changed]` | Integrity over the whole graph plus write conventions per item, as `error:`/`warning:` lines; a `hidden_text` warning names each item holding text that does not render, and what it is, a `frontmatter_position` error a front-matter block after the first line (its fields are lost), and with `--changed`/`--staged` a `judgement_fields` warning lists the fields each new item sets. No flag checks every item. `--changed` checks only items changed against HEAD in the working tree; `--staged` checks only items in the index. Exit 1 on any error, or if the check could not run. |
| `check-ruleset [graph_dir] --algorithmic` | JSON: `formal` findings on the ruleset itself — missing or escaping prompt files, a type without a quality prompt, an invalid `id_pattern`, declared analyses the algebra cannot run. Free; no model call. Exit 0 clean, 4 findings, 1 could not run. The graph directory need not exist yet. The semantic half (a model call, billed to a key or `--subscription`) belongs to the `review` skill. |
| `next-id <PREFIX> [graph_dir]` | The next unused id for a prefix, counting retired ids from git history. Refuses (exit 1) in a shallow clone or outside git rather than guess. |

## Navigation

| Command | What it returns |
|---|---|
| `connections <ID> [graph_dir]` | Direct foundations and dependents of one item, as text. |
| `connections <ID> --mermaid --direction foundations\|dependents\|both --depth N` | A mermaid subgraph without bodies. `--depth 0` is the full transitive closure. Arrows point at foundations. |
| `compile <ID> [graph_dir]` | The item plus its transitive foundations as one markdown document, between `[reqlite: repository content follows …]` and `[reqlite: end of repository content]` lines; the opening line names any item holding text that does not render. `--item-only` for the item alone. Useful for reading a chain; large for deep items. The size of this document is the size of a consistency check's input (`review` skill); `connections --mermaid --direction foundations --depth 0` counts the chain without bodies. |
| `parse` | Reads a model's response on stdin, strips fences and surrounding prose, and prints the findings JSON (`target`, `findings`) once it validates. Exit 1 if no valid findings are found. With `compile <ID> --prompt "<prompt text>"` it is the path for running a check with a model and provider of your own choice; the `review` skill is the isolated, Anthropic-only path. |
| `topology`, `orphans` | Source/middle/leaf classification; items with no links either way. Descriptive, not failures. |

## Project analyses

Analyses are **declared in the ruleset**, not built into the engine. `report` runs all of
them. The convenience commands `coverage`, `assumptions`, `justification`, and `effort`
run one analysis by a fixed name and fail if this project's ruleset does not declare it.
Read `ruleset.json` → `analyses` to see what a project declares and what each means.

Each analysis row carries the item id, the term values that produced it, and a `result`.
A `null` result means **incomplete inputs** — a reached item lacks the scored field — not
an error and not zero. The engine reports the project's declared `severity` but never
decides pass or fail; that judgement is the user's.

### Declared-analysis query shape (to read or write one)

A declared analysis is `{start, terms[], combine?}`:

- `start`: a type prefix or `"*"` — one row per matching item.
- each term: `{name, direction, reduce, dimension?, target?, include_self?}`
  - `direction`: `down` follows links to transitive foundations; `up` walks to transitive
    dependents; `self` is the start item only.
  - `target`: keep only reached items of this prefix. Reachability is transitive with no
    hop limit and no "via type" constraint, so route shape is not expressible.
  - `reduce`: `min` | `max` | `sum` | `count` | `value` over the reached items' `dimension`.
- `combine`: `+ - * /`, one comparison (`< <= > >= ==`), unary minus, literals, and names.
  No `and`/`or`, no chained comparisons, no `!=`. Two conditions means two analyses.
- `scales.<dimension>` in the ruleset maps labels to numbers; `min`/`max` and `combine`
  work on the numbers.
- Beside `query`: `severity` (reported, never acted on), `sort: "desc"` (rank by result),
  and `show: "flagged"` (`report` lists only rows with a non-zero result, after a
  "N of M items flagged" line).

The algebra is frozen deliberately. Needing more is a signal to load the graph into a
real graph database for that question, not to extend the algebra.

## Code traceability

`impl-scan [src_dir]` and `impl-list` report how implementation code traces back to the
spec, for projects that annotate their code that way.
