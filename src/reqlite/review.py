# reqlite:begin SC-014
"""
SC-014: Review runner — isolated inferential review (DD-030, DD-031).

Runs one item's quality review in a process whose context holds the review prompt and the
item and nothing else. That isolation is the requirement — SRC-057 needs both *no authoring
history* and *no inherited doctrine*, and the measured leak is the second one: a process
that loads filesystem configuration picks up the project's instruction file and the
operator's personal profile (SRC-073). `setting_sources=[]` is what closes it, so this
module sets it explicitly rather than relying on a default that loads all three scopes.

Shipped in the ``reqlite[review]`` extra (DD-031): the agent SDK is imported lazily, inside
``_load_sdk``, so ``import reqlite.review`` works — and every error below is raisable —
with the extra absent. The engine itself stays free of any LLM vendor dependency, which is
what keeps SC-010's delegated path satisfying FR-004.

The model call is injected as ``transport``, so the contract is testable without network
access. Finding *content* is not asserted anywhere: measured variance is ±1 finding per
item on identical input.
"""

from dataclasses import dataclass, field
from pathlib import Path
import json

from reqlite.compile import compile_item
from reqlite.graph import build_graph
from reqlite.items import ParseError, parse_all
from reqlite.parse import parse_findings


class ReviewError(Exception):
    """Review could not be performed. Never raised to mean 'no findings'."""


class MissingExtraError(ReviewError):
    """The reqlite[review] extra is not installed."""


class MissingCredentialError(ReviewError):
    """No API key was supplied."""


@dataclass(frozen=True)
class Gateway:
    """The provider an environment already routes Claude through (#86), as the review
    process gets it. Built by ``gateway_from_env``. ``kind`` is ``http``, ``bedrock`` or
    ``vertex``; ``env`` overlays the inherited environment in the child; ``secrets`` are
    the credential values scrubbed from every error."""

    kind: str
    env: dict = field(default_factory=dict)
    secrets: tuple = ()


#: Tools removed from the reviewer's context. A reviewer that can read the repository can
#: reach the very instruction files ``setting_sources=[]`` excludes, and can load item
#: bodies that SRC-058's cost model assumes stay out.
#: A second layer only: the base toolset is already empty (``tools=[]`` in ``_options``).
#: ``Agent`` is the subagent tool; ``Task`` is its older name.
BLOCKED_TOOLS = (
    "Read", "Glob", "Grep", "Bash", "Write", "Edit", "WebSearch", "WebFetch",
    "Agent", "Task", "TodoWrite", "Skill", "NotebookEdit",
)

#: The reviewer's whole standing instruction. Deliberately thin: the per-type quality
#: prompt from the ruleset carries the actual review criteria, and this must not compete
#: with it. It says only how to behave, never what good looks like.
SYSTEM_PROMPT = (
    "You are a requirements reviewer running in isolation. The message you receive is a "
    "complete review instruction followed by the single item to review. Treat that message "
    "as your only input and follow its output format exactly. Emit one valid JSON object "
    "and nothing else — no prose, no markdown fences. Include every field the instruction's "
    "schema requires on every finding. If you find no problems, emit an empty findings list "
    "rather than commentary."
)

DEFAULT_MODEL = "claude-sonnet-4-6"

#: The variable the command line reads a key from unless told another name (DD-037). Not
#: ``ANTHROPIC_API_KEY``: that one outranks the user's login for every Claude tool on the
#: machine, so asking users to set it would change how their own sessions authenticate.
DEFAULT_KEY_ENV = "REQLITE_API_KEY"

#: Wall-clock ceiling for one review. A hung child otherwise stalls until the calling tool
#: kills it, and then none of the command's exit codes apply (ORACLES-REVIEW 35).
REVIEW_TIMEOUT_S = 300

#: How to get the extra. Not ``pip install "reqlite[review]"``: reqlite is not on PyPI, so
#: that installs nothing today, or whoever registers the name later.
INSTALL_HINT = ('run reqlite through uvx --from "<reqlite directory>[review]", or '
                'pip install -e ".[review]" in a clone')


@dataclass(frozen=True)
class ReviewRequest:
    """One review. ``api_key`` is explicit by design (SRC-072): a published component must
    require its own credential and must never fall through to whatever subscription happens
    to be logged in, so there is no environment-variable default here. The operator's own
    subscription is an explicit local override — ``use_subscription=True`` — never a
    fallback; so is the gateway the environment routes through (``gateway``, #86).
    Exactly one of the three must be given."""

    graph_dir: str
    item_id: str
    api_key: str | None
    model: str = DEFAULT_MODEL
    max_tokens: int = 16384
    use_subscription: bool = False
    gateway: Gateway | None = None


@dataclass
class _Compiled:
    prompt: str
    item_id: str


def _load_sdk():
    """Import the agent SDK, or explain how to install it (DD-031).

    Lazy and in its own function so the module imports without the extra, and so tests can
    substitute it.
    """
    try:
        from claude_agent_sdk import ClaudeAgentOptions, query  # noqa: F401
    except ImportError as e:  # pragma: no cover - exercised via substitution
        raise MissingExtraError(
            "the review extra is not installed. Inferential review needs it: "
            f"{INSTALL_HINT}\n"
            "Algorithmic analysis (report, integrity, check) does not."
        ) from e
    return ClaudeAgentOptions, query


def sdk_versions() -> tuple[str, str]:
    """(agent SDK version, bundled CLI version). The isolation and credential guarantees
    were measured against one such pair, so ``doctor`` shows it (ORACLES-DOCTOR 8)."""
    from claude_agent_sdk._cli_version import __cli_version__
    from claude_agent_sdk._version import __version__
    return __version__, __cli_version__


def bundled_cli_present() -> bool:
    """Whether the SDK ships its own CLI binary here. Without one it falls back to
    ``claude`` on PATH, and the measured SDK/CLI pair is no longer what runs."""
    import claude_agent_sdk
    bundled = Path(claude_agent_sdk.__file__).parent / "_bundled"
    return any((bundled / name).is_file() for name in ("claude", "claude.exe"))


def _ruleset_path(graph_dir: str) -> Path:
    """The ruleset sits in a ``ruleset/`` directory beside the graph (ADR-016)."""
    return Path(graph_dir).resolve().parent / "ruleset" / "ruleset.json"


def _load_ruleset(graph_dir: str) -> dict:
    path = _ruleset_path(graph_dir)
    if not path.is_file():
        raise ReviewError(
            f"no ruleset found at {path}. Review needs the project's type definitions "
            "and per-type quality prompts."
        )
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ReviewError(f"ruleset at {path} is not valid JSON: {e}") from e


def _quality_prompt(graph_dir: str, ruleset: dict, item_id: str) -> str:
    # Only reached for an id already present in the graph, and the parser derives ids from
    # `{PREFIX}-{NUM}-{slug}.md`, so a prefix always exists here. An id with no prefix is
    # refused earlier, by the not-found check in _compile.
    prefix = item_id.split("-")[0]

    types = ruleset.get("types", {})
    rel = (types.get(prefix) or {}).get("quality_prompt")
    if not rel:
        with_prompts = sorted(t for t, d in types.items() if (d or {}).get("quality_prompt"))
        raise ReviewError(
            f"no quality prompt defined for type '{prefix}' in the ruleset, so this item "
            f"cannot be quality-reviewed. Types that can be: {with_prompts or 'none'}."
        )

    return _read_ruleset_prompt(graph_dir, rel, f"the quality prompt for {prefix}")


def _read_ruleset_prompt(graph_dir: str, rel: str, what: str) -> str:
    """A prompt file the ruleset declares, read only from inside the ruleset directory."""
    root = _ruleset_path(graph_dir).parent.resolve()
    path = (root / rel).resolve()
    # The ruleset belongs to the repository under analysis, which may be someone else's.
    # An absolute or `..` path would send any readable file to the model as the "prompt".
    if not path.is_relative_to(root):
        raise ReviewError(
            f"the ruleset declares '{rel}' as {what}, which "
            f"escapes the ruleset directory {root}. Prompt paths must stay inside it."
        )
    if not path.is_file():
        raise ReviewError(
            f"the ruleset declares '{rel}' as {what}, "
            f"but {path} does not exist."
        )
    return path.read_text(encoding="utf-8")


def _load_graph(graph_dir: str, item_id: str):
    """The parsed graph, refusing when it cannot be read or does not hold ``item_id``."""
    graph_path = Path(graph_dir)
    if not graph_path.is_dir():
        raise ReviewError(f"{graph_path} is not a directory")

    try:
        items = parse_all(graph_path)
    except ParseError as e:
        raise ReviewError(f"could not parse the graph: {e}") from e

    G, _ = build_graph(items)
    if item_id not in G or G.nodes[item_id].get("item") is None:
        raise ReviewError(f"item {item_id} not found in {graph_path}")
    return G


def _compile(request: ReviewRequest) -> _Compiled:
    """Assemble the reviewer's input from an item id.

    The runner compiles for itself rather than accepting pre-compiled text (FR-011): text
    handed in by a caller depends on that caller to frame it faithfully, and puts the item
    body in the caller's context, defeating SRC-057 and SRC-058 at once.
    """
    G = _load_graph(request.graph_dir, request.item_id)

    ruleset = _load_ruleset(request.graph_dir)
    prompt_text = _quality_prompt(request.graph_dir, ruleset, request.item_id)

    # Item-only: quality review is item-scoped (SRC-046). The dependency chain is the
    # consistency check, a different analysis with a different prompt.
    compiled = compile_item(G, request.item_id, prompt_text)
    if compiled is None:
        raise ReviewError(f"compile failed for {request.item_id}")
    return _Compiled(prompt=compiled, item_id=request.item_id)


def _options(request, system_prompt: str = SYSTEM_PROMPT) -> dict:
    """The options the reviewer demands. Every isolation-bearing value is set explicitly;
    none of them is left to a platform default. ``request`` is anything carrying ``model``
    and ``max_tokens``; the ruleset check passes its own system prompt (SC-018)."""
    return {
        "system_prompt": system_prompt,
        "setting_sources": [],            # SRC-073: the leak this closes
        "tools": [],                      # empty base toolset; allowed_tools only auto-approves
        "strict_mcp_config": True,        # no MCP server from any configuration file
        "mcp_servers": {},
        "disallowed_tools": list(BLOCKED_TOOLS),
        "max_turns": 1,
        "model": request.model,
        # The runner's own wall-clock ceiling, popped before the SDK sees the options.
        "timeout_s": getattr(request, "timeout_s", None) or REVIEW_TIMEOUT_S,
        # The CLI's own output ceiling; the SDK has no max_tokens option (ORACLES-REVIEW 34).
        "env": {"CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(request.max_tokens)},
        # Otherwise the child writes a transcript, prompt and item included, into the
        # config directory: the user's own in key and subscription mode (ORACLES-REVIEW 57).
        "extra_args": {"no-session-persistence": None},
    }


#: Credential variables blanked in the child for subscription mode. The SDK builds the child
#: environment as the parent's overlaid with ``options.env`` and never removes a variable,
#: so an inherited key would otherwise beat the subscription the caller asked for. An empty
#: value counts as unset (measured 2026-10-18, ORACLES-REVIEW 26).
_API_CREDENTIAL_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

#: Variables that, inherited by the child, would make "subscription" mean a cloud provider,
#: a proxy, or another account's token. Blanking is measured only for the two above, so for
#: these subscription mode refuses instead (ORACLES-REVIEW 33).
_SUBSCRIPTION_REROUTING_VARS = (
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
    "ANTHROPIC_BASE_URL", "CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_CUSTOM_HEADERS",
)


#: Variables that, inherited by the child, would make a key-mode review go unused (a cloud
#: provider outranks the key) or send the key itself to another endpoint. The subscription
#: set minus ``CLAUDE_CODE_OAUTH_TOKEN``, which the key outranks (measured 2026-10-19).
#: ``ANTHROPIC_CUSTOM_HEADERS`` holds a gateway's key in gateway setups; without a base URL
#: the child would send it to the Anthropic API (ORACLES-REVIEW 63).
_KEY_REROUTING_VARS = (
    "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
    "ANTHROPIC_BASE_URL", "ANTHROPIC_CUSTOM_HEADERS",
)

#: What the child's init message must report as ``apiKeySource`` for each mode. Gateway
#: mode reports ``none`` like subscription mode (measured 2026-10-26 through Portkey), so
#: there the throwaway config directory is what rules out the stored login.
_EXPECTED_KEY_SOURCE = {"key": "ANTHROPIC_API_KEY", "subscription": "none", "gateway": "none"}

#: The variable that selects each gateway kind. ``http`` is also selected by an explicit URL.
_GATEWAY_SELECTORS = {
    "http": "ANTHROPIC_BASE_URL",
    "bedrock": "CLAUDE_CODE_USE_BEDROCK",
    "vertex": "CLAUDE_CODE_USE_VERTEX",
}

#: Variables gateway mode refuses on: Foundry is out of scope, and an OAuth token pays
#: without any config directory, so the throwaway one would not stop it (ORACLES-REVIEW 54).
_GATEWAY_REFUSING_VARS = ("CLAUDE_CODE_USE_FOUNDRY", "CLAUDE_CODE_OAUTH_TOKEN")

#: Credential values in the environment, scrubbed from errors in gateway mode.
_GATEWAY_SECRET_VARS = (
    "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_API_KEY",
    "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_BEARER_TOKEN_BEDROCK",
)

#: Everything that decides what ``--gateway`` passes on; the test suite clears them.
_GATEWAY_VARS = (
    *_GATEWAY_SELECTORS.values(), *_GATEWAY_REFUSING_VARS, *_GATEWAY_SECRET_VARS,
    "ANTHROPIC_CUSTOM_HEADERS", "ANTHROPIC_DEFAULT_SONNET_MODEL",
)

#: The bearer token the child gets when the gateway key rides in a custom header: the
#: client needs some credential set, and the measured setup had a placeholder.
_GATEWAY_PLACEHOLDER_TOKEN = "gateway"

#: Gateway-mode config directories: their name prefix, the age after which a later run
#: removes one a killed run left, and the child's retry ceiling (CLI 2.1.294 reads the
#: variable as an integer from 0 up).
_CONFIG_DIR_PREFIX = "reqlite-review-"
_STALE_CONFIG_DIR_S = 86400
_GATEWAY_MAX_RETRIES = 2

#: Shorter values are not scrubbed: they are routing values, not secrets, and replacing a
#: common short string would garble the error around it.
_MIN_SECRET_LEN = 8


def _refusal(variables, consequence: str) -> str | None:
    import os
    set_vars = [v for v in variables if os.environ.get(v)]
    if not set_vars:
        return None
    verb = "is" if len(set_vars) == 1 else "are"
    return f"{', '.join(set_vars)} {verb} set in this environment, so {consequence}"


def stored_login_path() -> Path | None:
    """Where the CLI keeps a subscription login on this platform, or None on macOS, where
    it is in the Keychain. Presence says a login was stored, not that it is still valid
    (ORACLES-DOCTOR 17)."""
    import os
    import sys

    if sys.platform == "darwin":
        return None
    config = os.environ.get("CLAUDE_CONFIG_DIR") or str(Path.home() / ".claude")
    return Path(config) / ".credentials.json"


def holds_claude_login(path: Path) -> bool | None:
    """Whether the credentials file holds a Claude login: True, False, or None when it
    cannot be read as JSON. Only the key's presence is read, never a value. MCP servers
    with OAuth store their tokens in the same file (ORACLES-DOCTOR 17b); `claudeAiOauth`
    is the CLI's own format, not a documented contract."""
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return isinstance(data, dict) and "claudeAiOauth" in data


def subscription_refusal() -> str | None:
    """Why subscription mode would be refused in this environment, or None. The one
    condition both ``_dispatch`` and ``doctor`` use (ORACLES-DOCTOR 12)."""
    return _refusal(_SUBSCRIPTION_REROUTING_VARS,
                    "the review would go to a different provider, endpoint or account than "
                    "the stored Claude login")


def key_refusal() -> str | None:
    """Why key mode would be refused in this environment, or None. Shared with ``doctor``
    (ORACLES-DOCTOR 16)."""
    return _refusal(_KEY_REROUTING_VARS,
                    "the review would either not use the key or send it to an endpoint other "
                    "than the Anthropic API")


def gateway_refusal() -> str | None:
    """Why gateway mode would be refused in this environment whatever the gateway, or
    None. Shared by ``gateway_from_env``, ``_dispatch`` and ``doctor``."""
    import sys
    if sys.platform == "darwin":
        return ("gateway mode is not available on macOS: the stored Claude login is in the "
                "Keychain there, and whether an empty config directory keeps it out of "
                "reach is unmeasured, so a misrouted review could be billed to it")
    return _refusal(_GATEWAY_REFUSING_VARS,
                    "the review could be billed to a credential other than the gateway "
                    "(Foundry is not supported; an OAuth token pays without a stored login)")


def _header_values(headers: str) -> list[str]:
    """The values in ``ANTHROPIC_CUSTOM_HEADERS``, one ``Name: value`` per line."""
    return [line.partition(":")[2].strip() for line in headers.splitlines() if ":" in line]


def gateway_from_env(url: str | None = None, key_env: str | None = None,
                     header: str | None = None) -> Gateway:
    """The gateway this environment routes Claude through, or one given explicitly.

    With no arguments, passes on what the environment has: ``ANTHROPIC_BASE_URL`` with its
    token and headers, or the Bedrock or Vertex selection. ``url`` names an HTTP gateway
    instead; ``key_env`` names the variable holding its key, sent as ``header`` (default
    ``Authorization``, i.e. as the bearer token), and the child then gets that gateway
    only. Refuses, as ``ReviewError``, what it cannot pass on unambiguously
    (ORACLES-REVIEW 51–54).
    """
    import os

    reason = gateway_refusal()
    if reason:
        raise ReviewError(f"gateway mode refused: {reason}.")
    selected = [kind for kind, var in _GATEWAY_SELECTORS.items() if os.environ.get(var)]
    if url and "http" not in selected:
        selected.append("http")
    if not selected:
        raise ReviewError(
            f"no gateway in this environment: none of {', '.join(_GATEWAY_SELECTORS.values())} "
            "is set. Outside an environment that routes Claude through a gateway, name one "
            "with --gateway-url."
        )
    if len(selected) > 1:
        names = [_GATEWAY_SELECTORS[k] for k in selected if k != "http" or not url]
        names += ["--gateway-url"] if url else []
        raise ReviewError(
            f"{' and '.join(names)} each select a provider, so it is unclear which one "
            "should carry and pay for this review."
        )
    kind = selected[0]
    if kind != "http" and (key_env or header):
        flag = "--gateway-key-env" if key_env else "--gateway-header"
        raise ReviewError(f"{flag} applies to an HTTP gateway only; {kind} takes its "
                          "credentials from the environment as it is.")
    if header and not key_env:
        raise ReviewError("--gateway-header names the header for the key in "
                          "--gateway-key-env, which was not given.")
    inherited_url = (os.environ.get("ANTHROPIC_BASE_URL") or "").rstrip("/")
    if url and not key_env and url.rstrip("/") != inherited_url:
        # The inherited token and headers are the inherited gateway's key; sending them
        # to another URL hands that key to whoever wrote the URL (ORACLES-REVIEW 54).
        raise ReviewError("--gateway-url names a gateway other than this environment's, "
                          "so its credentials are not passed on; name that gateway's key "
                          "with --gateway-key-env.")

    if kind != "http":
        env = {"ANTHROPIC_API_KEY": "", "ANTHROPIC_AUTH_TOKEN": ""}
        secrets = [os.environ.get(v, "") for v in _GATEWAY_SECRET_VARS]
    elif key_env:
        value = key_from_env(key_env)
        env = {"ANTHROPIC_BASE_URL": url or os.environ["ANTHROPIC_BASE_URL"],
               "ANTHROPIC_API_KEY": ""}
        if (header or "Authorization").lower() == "authorization":
            env.update({"ANTHROPIC_AUTH_TOKEN": value, "ANTHROPIC_CUSTOM_HEADERS": ""})
        else:
            env.update({"ANTHROPIC_AUTH_TOKEN": _GATEWAY_PLACEHOLDER_TOKEN,
                        "ANTHROPIC_CUSTOM_HEADERS": f"{header}: {value}"})
        secrets = [value]
    else:
        token = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
        headers = os.environ.get("ANTHROPIC_CUSTOM_HEADERS", "")
        env = {"ANTHROPIC_BASE_URL": url or os.environ["ANTHROPIC_BASE_URL"],
               "ANTHROPIC_AUTH_TOKEN": token or _GATEWAY_PLACEHOLDER_TOKEN,
               "ANTHROPIC_CUSTOM_HEADERS": headers,
               "ANTHROPIC_API_KEY": ""}
        secrets = [token, *_header_values(headers)]
    return Gateway(kind=kind, env=env,
                   secrets=tuple(s for s in secrets if len(s) >= _MIN_SECRET_LEN))


def key_from_env(name: str) -> str:
    """The key held in environment variable ``name``, stripped. Refuses, naming only the
    variable, when it is unset or blank (ORACLES-REVIEW 46, 50)."""
    import os
    value = (os.environ.get(name) or "").strip()
    if not value:
        raise MissingCredentialError(
            f"no API key in the environment variable {name}. Set it in your own shell or "
            "system settings, never by pasting the key into a chat. A process only sees "
            "variables that were set before it started, so restart the terminal or editor "
            "that runs this command afterwards."
        )
    return value


def _remove_stale_config_dirs() -> None:
    """Remove gateway config directories older than a day: a run killed hard never
    reaches its own cleanup. Younger ones may belong to a review still running
    (ORACLES-REVIEW 56b)."""
    import shutil
    import tempfile
    import time

    cutoff = time.time() - _STALE_CONFIG_DIR_S
    for path in Path(tempfile.gettempdir()).glob(f"{_CONFIG_DIR_PREFIX}*"):
        try:
            if path.is_dir() and path.stat().st_mtime < cutoff:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


def _redact(text: str, secrets) -> str:
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        text = text.replace(secret, "<credential>")
    return text


def _sdk_transport(*, prompt: str, options: dict, api_key: str | None,
                   gateway: Gateway | None = None) -> str:
    """Default transport: one isolated agent turn, returning its text.

    Imported lazily and run to completion synchronously — a review is one request/response,
    so the caller should not have to be async to ask for one. ``api_key=None`` means
    subscription mode, or gateway mode when ``gateway`` is given; ``review_item`` passes
    either only when it was explicitly requested.
    """
    import asyncio
    import shutil
    import tempfile

    ClaudeAgentOptions, query = _load_sdk()
    # The key goes to the spawned process only, via `env`. Setting it in *this* process
    # would shadow the operator's sign-in for every other tool on the machine, since it
    # wins the credential race (SRC-072); omitting it entirely would let the child fall
    # back to whatever login happens to exist, which is the thing a published component
    # must not do.
    options = dict(options)
    env = dict(options.pop("env", {}))
    timeout_s = options.pop("timeout_s", REVIEW_TIMEOUT_S)
    config_dir = None
    if gateway is not None:
        # An empty config directory puts the stored login out of reach, so a gateway
        # setting the child ignores fails as "Not logged in" instead of billing the
        # subscription (measured 2026-10-26, ORACLES-REVIEW 56).
        _remove_stale_config_dirs()
        config_dir = tempfile.mkdtemp(prefix=_CONFIG_DIR_PREFIX)
        env.update(gateway.env)
        env["CLAUDE_CONFIG_DIR"] = config_dir
        # A misconfigured gateway otherwise fails only after minutes of retries
        # (ORACLES-REVIEW 56c).
        env["CLAUDE_CODE_MAX_RETRIES"] = str(_GATEWAY_MAX_RETRIES)
        expected = _EXPECTED_KEY_SOURCE["gateway"]
    elif api_key is None:
        env.update({var: "" for var in _API_CREDENTIAL_VARS})
        expected = _EXPECTED_KEY_SOURCE["subscription"]
    else:
        # A bearer token is documented to outrank the key; blanking it is measured safe.
        env.update({"ANTHROPIC_API_KEY": api_key, "ANTHROPIC_AUTH_TOKEN": ""})
        expected = _EXPECTED_KEY_SOURCE["key"]
    opts = ClaudeAgentOptions(**options, env=env)

    async def _run() -> str:
        chunks: list[str] = []
        source_seen = False
        async for message in query(prompt=prompt, options=opts):
            kind = type(message).__name__
            if kind == "SystemMessage" and getattr(message, "subtype", None) == "init":
                # What the child says it authenticated with, not what it was handed: the
                # check one level past the seam (ORACLES-REVIEW 42).
                source = (getattr(message, "data", None) or {}).get("apiKeySource")
                if source != expected:
                    raise ReviewError(
                        f"the review process reported credential source {source!r} where "
                        f"{expected!r} was required, so it is not billed to the credential "
                        "that was asked for. Its result is discarded."
                    )
                source_seen = True
            elif kind == "AssistantMessage":
                if not source_seen:
                    raise ReviewError(
                        "the review process did not report which credential it used, so "
                        "its result is discarded."
                    )
                chunks.extend(
                    b.text for b in message.content if hasattr(b, "text")
                )
        if not source_seen:
            raise ReviewError(
                "the review process did not report which credential it used, so its "
                "result is discarded."
            )
        return "".join(chunks)

    try:
        return asyncio.run(asyncio.wait_for(_run(), timeout_s))
    except asyncio.TimeoutError:
        raise ReviewError(f"the review timed out after {timeout_s} s")
    finally:
        if config_dir is not None:
            shutil.rmtree(config_dir, ignore_errors=True)


def review_item(request: ReviewRequest, transport=None) -> dict:
    """Review one item in an isolated context. Returns parsed findings.

    On a response that cannot be parsed, returns ``{"warning", "raw_response"}`` and
    **no** ``findings`` key: an empty findings list would read as "this item is clean",
    and a response the runner could not read is not evidence of that (SRC-058).
    """
    compiled = _compile(request)
    raw = _dispatch(compiled.prompt, request, transport)

    parsed = parse_findings(raw or "")
    if parsed is None:
        return {
            "warning": "the model's response could not be parsed as findings JSON. The "
                       'engine requires {"target": "<id>", "findings": [...]}; check that '
                       "the type's quality prompt asks for that envelope.",
            "raw_response": (raw or "")[:2000],
            "target": compiled.item_id,
        }

    # The envelope is the engine's; a reviewer that names a different item is reported,
    # not silently relabelled (ORACLES-REVIEW 36).
    if parsed.get("target") != compiled.item_id:
        parsed["target_mismatch"] = parsed.get("target")
    parsed["target"] = compiled.item_id
    return parsed


def _dispatch(prompt: str, request, transport=None, system_prompt: str = SYSTEM_PROMPT) -> str:
    """Check the credential choice, then run one isolated turn and return its raw text.

    Shared by every inferential check, so the credential and isolation rules cannot differ
    between them. ``request`` carries ``api_key``, ``use_subscription``, ``gateway``,
    ``model`` and ``max_tokens``.
    """
    gateway = request.gateway
    given = [name for name, on in (("an API key", request.api_key),
                                   ("subscription mode", request.use_subscription),
                                   ("a gateway", gateway is not None)) if on]
    if len(given) > 1:
        raise ReviewError(
            f"{' and '.join(given)} were given together, so it is unclear which credential "
            "should pay for this review. Pass exactly one."
        )
    if not given:
        raise MissingCredentialError(
            "an API key is required for inferential review. Pass api_key; the command "
            f"line reads it from {DEFAULT_KEY_ENV} (key_from_env). It is deliberately not "
            "read from ANTHROPIC_API_KEY: that variable wins the credential race for every "
            "tool on the machine, so setting it would shadow your interactive sign-in. "
            "To use your own logged-in subscription instead, ask for it "
            "explicitly with use_subscription=True; for the gateway this environment "
            "routes through, gateway=gateway_from_env()."
        )

    if gateway is not None:
        mode, reason = "gateway", gateway_refusal()
    elif request.use_subscription:
        mode, reason = "subscription", subscription_refusal()
    else:
        mode, reason = "key", key_refusal()
    if reason:
        raise ReviewError(
            f"{mode} mode refused: {reason}. That routing is the user's choice; "
            f"{mode}-billed review is not available in this environment."
        )

    if transport is None:
        _load_sdk()                      # fail on the missing extra before dispatching
        transport = _sdk_transport

    # Error text reaches stderr and from there the calling agent's transcript, so every
    # credential is scrubbed from every message that leaves here (ORACLES-REVIEW 43, 59).
    key = request.api_key if mode == "key" else None
    secrets = gateway.secrets if gateway is not None else (key,)
    try:
        return transport(
            prompt=prompt,
            options=_options(request, system_prompt),
            api_key=key,
            gateway=gateway,
        )
    except ReviewError as e:
        # `from None`: a chained cause would carry the unredacted text into any traceback.
        raise type(e)(_redact(str(e), secrets)) from None
    except Exception as e:
        raise ReviewError(_redact(f"the review call failed: {e}", secrets)) from None
# reqlite:end SC-014
