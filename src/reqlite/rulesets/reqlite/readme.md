# Project orientation

This project's requirements are a reqlite graph: items are plain markdown files in a repository, references between them form a DAG, and analyses run over that DAG.

Read this before classifying or authoring. It explains why the type system is shaped the way it is. The enumerable facts — which types exist, their fields, their quality criteria — are in `ruleset.json` and the prompts; do not duplicate them here, and do not infer them from general requirements-engineering training. Several conventions below run against that training on purpose.

## The frame

An item is one unit of thinking, recorded once. Its identity is its filename — `SRC-001-slug.md` is `SRC-001`, full stop. There is no `id` field, no `status` field, no `title` field; the title is the first H1. Frontmatter is optional and carries only editorial judgment (`certainty`, `negotiability`) and the occasional `effort` or `evidence`. If you find yourself reaching for a status or a lifecycle field, stop — the graph itself is the state. An item is current because it is in the graph.

A reference points at what justifies you, never at what you justify. An FR links the UC it serves; the UC does not link back. Dependencies flow toward foundations. There are no see-also links and no reverse links.

## Why these types

The boundaries between types are drawn on *authority and perspective*, not on a conventional requirements taxonomy. This is the part most likely to fight your priors:

The SRC/DD line is **agency**. An SRC is reality the team cannot change by itself — a law, a constraint, a stakeholder request. A DD is a choice inside the team's own authority, something it can decide and later revise alone. The signal is deliberation: if two live options were weighed, it was the team's choice and it is a DD, even when the option chosen is an externally mandated standard. The constraint that bounded the choice stays a separate SRC. "We adopted X" is not automatically a decision; "we weighed X against Y and chose X" is.

The UC/FR line is **perspective, not level**. A UC is what the user walks through; an FR is what the system must do. Neither sits above the other — one UC can spawn many FRs and one FR can serve many UCs. The binding test for a UC is the presence of user steps; an actor only reinforces it. A system obligation with no user steps is an FR even if it names a role.

The FR/TC line is **obligation versus check**. An FR states what must hold ("the system must reject payloads over the limit"). A TC states how you verify it — inputs, an invocation, an observable outcome. A TC derives from its FR, and must stay independent of the SC that implements the same FR: the test checks the capability, not the implementation, so the two siblings share an upstream but never reference each other.

The DD/SC line is **rationale versus artifact**. A DD is a choice with a why and a trade-off. An SC is a concrete thing that gets built and costs effort. A named artifact with an effort estimate is an SC; a choice with rationale and no artifact is a DD. One decision often spawns a DD plus the SCs that realize it.

## Retirement

There is no archive and no graveyard. An item leaves the graph by **absorption then deletion**: salvage its remaining value into the living items that should carry it, de-link inbound references, delete the file. Git history is the archive; the deletion commit names the id and where the value went. Retired ids are never reused. When a check recommends retiring an item, this is what it means — not flagging it, not setting a field.

## Authored versus derived

Two different notions of confidence coexist and must not be confused. `certainty` and `negotiability` are *authored* — the writer's judgment about an item's own claim. Foundation risk is *derived* — the engine computes how much trust an item inherits from the SRC foundations beneath it. The first is an opinion you write down; the second is a property of the graph the engine reads off. Quality checks consume the authored values; risk analyses compute the derived one.
