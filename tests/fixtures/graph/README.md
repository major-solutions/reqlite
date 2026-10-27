# Test Fixture Graph

11 items, purpose-built for testing. Every structural pattern
reqlite needs to handle is represented in this small graph.

## Structure

Each line is one item and the items it links (its foundations):

```
UC-001  -> FR-001
SC-001  -> FR-001
SC-002  -> FR-001
FR-001  -> SRC-002, SRC-003
SRC-001 -> SRC-002
SRC-002 -> SRC-003, SRC-004
SRC-003 -> SRC-004, SRC-005
SRC-004 -> SRC-005
SRC-005    (leaf)
SRC-006    (orphan — no connections)
SRC-009 -> SRC-009 (self-cycle)
```

## Structural properties

| Property | Items |
|---|---|
| Source (in-degree 0) | SRC-001, UC-001, SC-001, SC-002; also the orphan SRC-006 |
| Leaf (out-degree 0) | SRC-005 |
| Diamond (convergence) | SRC-003 → SRC-005 ← SRC-004 |
| Orphan | SRC-006 |
| Self-cycle | SRC-009 |
| Cross-prefix refs | UC-001 → FR-001 → SRC-002 |
| SC with effort | SC-001 (effort=5), SC-002 (effort=1) |
| Three-layer chain | UC-001 → FR-001 → SRC-002 |

## Expected integrity findings

- **orphan**: SRC-006
- **cycle**: SRC-009 (self-reference)
