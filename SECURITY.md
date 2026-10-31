# Security policy

## Reporting a vulnerability

Please report security problems privately, through GitHub's
[Report a vulnerability](https://github.com/major-solutions/reqlite/security/advisories/new)
form, not as a public issue.

reqlite is maintained by one person. You can expect an acknowledgement within 7 days;
after that, fixes are best effort. Once a fix is released, the advisory is published
with credit to you, unless you prefer otherwise.

## Supported versions

reqlite is in beta. Only the latest release receives fixes.

## In scope

reqlite runs code on your machine on every agent commit, passes the text of your
requirements to a language model, and handles an API key. Reports about any of these
are welcome:

- **Prompt injection.** Item, ruleset or prompt content that makes an agent act outside
  the item being authored: writing other files, running commands, committing, or
  changing what it reports. This includes hidden text that `reqlite check` does not flag.
  Defences against injection are mitigations, not guarantees, so a reproducible path is
  worth reporting even when the fix can only reduce it.
- **Data leaving your machine** other than through the review commands, to the billing
  route you chose (an API key or a gateway).
- **Credential exposure.** The API key or gateway credentials appearing in output, logs,
  error messages or `doctor`, or reaching a process that does not need them.
- **Content that crashes, hangs or locks out the engine**, such as a ruleset pattern
  with catastrophic backtracking, or an item that makes the commit check block every
  command.

## Not vulnerabilities

These are known limitations. Gaps in them are bugs, and welcome as ordinary issues:

- **Getting a commit past the commit check.** The check catches mistakes, not intent:
  `--no-verify`, another command form, or committing outside the agent all skip it, and
  the [user guide](docs/user-guide.md#7-the-commit-check) lists the forms it does not
  follow. Enforcement that cannot be skipped needs branch protection on your remote.
- **The commit check passing when it cannot judge**, for example outside a reqlite
  project, or when a `cd` target cannot be resolved. It fails open by design.
