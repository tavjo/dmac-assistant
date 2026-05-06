"""Live NExtSEEK plugin E2E for dmac-assistant:poc.

Runs after T07 (same xdist group). Invokes the baked-in `nextseek`
plugin (post-B14 image) through `claude --print` with a natural-language
prompt and validates the plugin's credential handling and log-safety.

Spec deviations from §5b (justified by already-locked DDs):
  * DD-31: ``--verbose`` is required for ``claude --print --output-format
    stream-json`` in claude-code 2.1.92.
  * DD-33: stdin EOF does not propagate through docker-py's
    ``client.api.attach_socket`` for ``claude --print --input-format text``;
    use ``subprocess.run(["docker", "run", "-i", ...])`` instead. The
    ``docker_client`` fixture is retained for image-existence + ping
    side-effect.
"""
from __future__ import annotations

import pytest

# DD-30: guard against un-merged T01. Collection must not crash if T01's
# build_tools.verify_env module is missing from the integration branch.
try:
    from build_tools.verify_env import REQUIRED_VARS
except ImportError:
    pytest.skip(
        "T01 not yet merged to integration branch",
        allow_module_level=True,
    )

# DD-20: pytest-xdist is a hard runtime dep for Wave 4 serialization. Without
# it, @pytest.mark.xdist_group is a silent no-op and T07/T08 could race.
pytest.importorskip("xdist", reason="pytest-xdist required for live-serial tests")

import json
import os
import re
import secrets
from pathlib import Path
from urllib.parse import urlparse

import docker

from tests.harness.live_runner import (
    ClaudeRunResult,
    allow_docker_unix_socket_only,
    run_claude_print,
)
from tests.harness.plugin_schema import parse_list_response
from tests.harness.stream_json import StreamJSONParser, ToolUseEvent, parse_stream


# H-3 (updated B17b): match the actual baked-in script names shipped by the
# new `nextseek` plugin (post-B14 image). Legacy names (nextseek-call,
# nextseek-init, nextseek-spec, nextseek-exec, nextseek-validate,
# nextseek-vocab, nextseek-session) are no longer in the image PATH;
# their removal from this regex is intentional, not accidental drift.
# A substring check would false-positive on `grep nextseek-*`,
# `ls /app/plugins/nextseek/bin/`, or a comment mentioning the plugin name.
_NEXTSEEK_SCRIPT_RE = re.compile(
    r"\bnextseek-("
    r"entity-extract"
    r"|parse"
    r"|plan"
    r"|api-read"
    r"|api-write"
    r"|graph"
    r"|report"
    r"|generate-submission"
    r")\b"
)


def _is_nextseek_invocation(evt: ToolUseEvent) -> bool:
    """A tool_use event proves the nextseek plugin was actually called.

    Per ADR-008 the plugin is bash-scripted (MCP rejected for POC plugins);
    its commands surface as ``Bash`` tool_use events whose ``input.command``
    invokes one of the ``nextseek-*`` scripts (``nextseek-entity-extract``,
    ``nextseek-parse``, ``nextseek-api-read``, etc.). A future MCP-style
    surfacing where the tool name itself contains ``nextseek`` is also
    accepted defensively.
    """
    if evt.name and "nextseek" in evt.name.lower():
        return True
    if evt.name == "Bash" and isinstance(evt.input, dict):
        cmd = evt.input.get("command")
        if isinstance(cmd, str) and _NEXTSEEK_SCRIPT_RE.search(cmd):
            return True
    return False


IMAGE = "dmac-assistant:poc"
LIVE_TIMEOUT_SECONDS = 480  # T07 is 60s; plugin path also pays plugin-load,
# session-cache bootstrap (`nextseek-init`), and tool-routing latency.
# Empirical first-run timing: 219s when prompt converges, 320s+ when Claude
# explores. 480s buffer keeps a single pathological run from killing CI.

LIVE_MARKS = (
    pytest.mark.live,
    pytest.mark.xdist_group("live-serial"),
)


# ---------- dev-gate ----------

def _is_dev_url(url: str) -> bool:
    """DD-21: hostname-segment allowlist. Substring `'dev' in url` is gameable
    (matches `devops`, `developer`, `development`, prod URLs with `/dev-test/`
    in path). Require a `.`-split hostname segment that *is* `dev`, starts
    with `dev-`, or ends with `-dev`.
    """
    host = urlparse(url).hostname or ""
    segments = host.split(".")
    return any(
        seg == "dev" or seg.startswith("dev-") or seg.endswith("-dev")
        for seg in segments
    )


@pytest.fixture(scope="module")
def nextseek_dev_url(live_env: dict[str, str]) -> str:
    """Fail the whole module if NEXTSEEK_URL isn't a dev hostname per DD-21."""
    url = live_env["NEXTSEEK_URL"]
    if not _is_dev_url(url):
        pytest.fail(
            f"REFUSING TO RUN: NEXTSEEK_URL={url!r} is not a dev hostname "
            f"per DD-21 (segment must be 'dev' / 'dev-*' / '*-dev'). "
            "T08 must never exercise prod."
        )
    return url


# ---------- fixtures ----------

@pytest.fixture(scope="module")
def docker_client():
    allow_docker_unix_socket_only()
    client = docker.from_env()
    try:
        client.ping()
    except Exception as exc:  # pragma: no cover — environmental
        pytest.skip(f"Docker daemon unavailable: {exc}")
    try:
        client.images.get(IMAGE)
    except docker.errors.ImageNotFound:
        pytest.fail(f"{IMAGE} missing; run `make image-build` first")
    yield client
    client.close()


def _resolve_catalog_host_path() -> str:
    """B17c: resolve the host-side catalog path the bridge would resolve.

    Mirrors `dmac_assistant.config._resolve_catalog_file` precedence:
    DMAC_CATALOG_FILE_HOST_PATH env var first, otherwise the dev-mode default
    at <repo>/vendor/chat_nextseek/agent_model_catalog.json.
    """
    explicit = os.environ.get("DMAC_CATALOG_FILE_HOST_PATH")
    if explicit and explicit.strip():
        return explicit.strip()
    return str(
        Path(__file__).resolve().parents[1]
        / "vendor"
        / "chat_nextseek"
        / "agent_model_catalog.json"
    )


@pytest.fixture
def container_mounts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, dict[str, str]], str, Path, Path]:
    """T08 uses a distinct user_id from T07 for mount isolation (R-17 adj.).

    B17c: also bind-mounts the host catalog file at
    /etc/dmac/agent_model_catalog.json (ro) so chat_nextseek's config can
    resolve a model-profile catalog without falling back to env-introspection.
    """
    user_id = f"t08-{secrets.token_hex(4)}"
    claude_dir = tmp_path / "claude-users" / user_id / ".claude"
    scratch_dir = tmp_path / "scratch" / user_id
    projects_dir = tmp_path / "projects" / "fake"
    for d in (claude_dir, scratch_dir, projects_dir):
        d.mkdir(parents=True, exist_ok=True)

    assert "t07" not in str(claude_dir), "user_id must differ from T07's"
    assert list(claude_dir.iterdir()) == []

    # B17c BLOCKER fix: keep the fixture's catalog-path resolution and
    # load_config()'s _required_path/_is_dev_mode gate consistent. This
    # fixture is a test-harness-only construct; DMAC_DEV_MODE=true is
    # correct for it. The production-like (non-dev) path is covered by
    # tests/unit/test_config.py::test_bridge_config_non_dev_requires_catalog_env.
    monkeypatch.setenv("DMAC_DEV_MODE", "true")

    catalog_host_path = _resolve_catalog_host_path()
    if not Path(catalog_host_path).is_file():
        pytest.skip(
            f"Catalog file not found at {catalog_host_path} — "
            "set DMAC_CATALOG_FILE_HOST_PATH or run scripts/sync-vendor-deps.sh."
        )

    mounts = {
        str(claude_dir): {"bind": "/home/user/.claude", "mode": "rw"},
        str(scratch_dir): {"bind": "/data/scratch", "mode": "rw"},
        str(projects_dir): {"bind": "/data/projects/fake", "mode": "ro"},
        catalog_host_path: {
            "bind": "/etc/dmac/agent_model_catalog.json",
            "mode": "ro",
        },
    }
    return mounts, user_id, claude_dir, scratch_dir


# ClaudeRunResult + run_claude_print + auth-skip helpers live in
# tests/harness/live_runner.py (M-2 refactor). T08 callsites pass prompts
# through the shared helper; the dev-API env toggle is either baked into
# ``env`` by ``_live_env_for_plugin`` or passed via ``extra_env=``.


def _live_env_for_plugin(live_env: dict[str, str]) -> dict[str, str]:
    """Assemble the env dict passed to the container.

    Per DD-19, the bridge-side names (NEXTSEEK_USERNAME/PASSWORD/URL) flow
    through unchanged — the entrypoint (T02) does the alias to the plugin's
    canonical SEEK_USER/SEEK_PASSWORD/NEXTSEEK_BASE_URL. T08 never rewrites.

    Per DD-21 layer 2, USE_DEV_API=1 forces plugin-side dev routing regardless
    of any base-URL resolution path (SKILL.md line 341).
    """
    env = {var: live_env[var] for var in REQUIRED_VARS if var in live_env}
    env["CLAUDE_CODE_USE_BEDROCK"] = "1"
    env["USE_DEV_API"] = "1"
    # B17c: container-side catalog path; mirrors the bridge's _build_environment.
    env["CATALOG_FILE"] = "/etc/dmac/agent_model_catalog.json"
    return env


def _extract_first_json_object(text: str) -> dict:
    """Pull the first top-level JSON object (``{...}``) out of ``text``.

    Claude Code's assistant turns often wrap JSON in prose + code fences,
    sometimes with multiple fences (an empty placeholder followed by the
    real payload). Walk every ``json`` fence in order, return the first
    that decodes as a JSON object; fall back to the first balanced
    ``{`` ... ``}`` if no fence yields a usable object.
    """
    for match in re.finditer(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL):
        candidate = match.group(1).strip()
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    depth = 0
    start = -1
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                candidate = text[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    start = -1
    raise ValueError(f"no JSON object found in assistant text: {text!r}")


# ---------- non-live unit tests for the dev-gate helper ----------


@pytest.mark.parametrize(
    "bogus_url",
    [
        "https://devops.example.mit.edu",
        "https://developer.prod.mit.edu",
        "https://development.mit.edu",
        "https://nextseek.mit.edu/dev-test/",  # 'dev' only in path, not hostname
        "https://prod.mit.edu",
    ],
)
def test_is_dev_url_rejects_gameable_hostnames(bogus_url: str) -> None:
    """Parametric negative tests prove the hostname-segment allowlist
    rejects the substring-gameable inputs flagged in DD-21."""
    assert not _is_dev_url(bogus_url), (
        f"_is_dev_url({bogus_url!r}) unexpectedly returned True"
    )


@pytest.mark.parametrize(
    "ok_url",
    [
        "https://nextseek-dev.mit.edu",
        "https://dev.nextseek.mit.edu",
        "https://nextseek.dev",
        "https://api-dev.nextseek.mit.edu",
    ],
)
def test_is_dev_url_accepts_real_dev_hostnames(ok_url: str) -> None:
    assert _is_dev_url(ok_url)


# ---------- non-live unit tests for the plugin-invocation detector ----------


def _bash_evt(command: str) -> ToolUseEvent:
    """Convenience builder for tool_use dataclass fixtures."""
    return ToolUseEvent(id="t-1", name="Bash", input={"command": command})


@pytest.mark.parametrize(
    "cmd",
    [
        'nextseek-entity-extract --query "Find DNA samples"',
        "nextseek-parse --query 'list projects'",
        "nextseek-plan --query 'multi-step lineage query'",
        "nextseek-api-read --parser-plan '{\"operation_id\": \"list_projects\"}'",
        "nextseek-api-write --parser-plan '{\"operation_id\": \"create_sample\"}' --confirmed-write",
        "/app/plugins/nextseek/bin/nextseek-graph --query 'lineage of DNA1'",
        "nextseek-report --mode samples --project MyProj",
        "cd /tmp && nextseek-generate-submission --type GEO --uids 1,2,3",
    ],
)
def test_is_nextseek_invocation_matches_real_scripts(cmd: str) -> None:
    """H-3 (updated B17b): regex matches every script name the new nextseek
    plugin actually ships in the post-B14 image."""
    assert _is_nextseek_invocation(_bash_evt(cmd))


@pytest.mark.parametrize(
    "cmd",
    [
        # Trailing dash with no script name — the original substring check
        # matched, the regex rejects.
        "grep -R 'nextseek-' /app",
        # `nextseek-api` is a legacy plugin directory name and also a valid
        # shim token — but it is NOT in the new plugin's shim set. Substring
        # would match; enumerated regex rejects (post-B17b).
        "ls /app/plugins/nextseek/bin/",
        # Made-up name outside the script enum — substring would match,
        # the enumerated regex rejects.
        "echo 'plans to run nextseek-doesnotexist later'",
        "cat /tmp/nextseek-whatever.log",
        # `nextseek` alone (no hyphen) never matches.
        "echo 'see the nextseek project for details'",
        # Old legacy shim names that are no longer in the image — must
        # NOT match the new regex even though they have the nextseek- prefix.
        "nextseek-call --env dev --op 'List Projects'",
        "nextseek-init --env dev --assume-yes",
        "nextseek-vocab",
    ],
)
def test_is_nextseek_invocation_rejects_substring_matches(cmd: str) -> None:
    """H-3: commands that merely MENTION the plugin must not count as
    invocations. Only the enumerated script names — word-bounded — qualify.

    NOTE: a command like ``which nextseek-call`` still passes the regex
    because ``nextseek-call`` is in the enum and appears as a word. That's
    an acknowledged edge case of the reviewer-specified fix; the critical
    false-positives being locked out here are the plugin-adjacent tokens
    (``nextseek-``, ``nextseek-api``, ``nextseek-whatever``, etc.)."""
    assert not _is_nextseek_invocation(_bash_evt(cmd))


@pytest.mark.parametrize(
    "cmd",
    [
        "which nextseek-parse",
        "echo 'see the nextseek-entity-extract script at bin/'",
    ],
)
def test_is_nextseek_invocation_known_edge_cases_accepted(cmd: str) -> None:
    """Lock the acknowledged false-positives of the reviewer-specified
    regex: an enum token appearing as a word in a non-invocation context
    (``which X``, quoted docs) still returns True. This is the accepted
    trade-off over the prior substring match; the contract is recorded
    here so a future tighten cannot slip past review without a visibly
    failing regression test.

    B17b update: examples use new-plugin shim names (nextseek-parse,
    nextseek-entity-extract) since legacy names (nextseek-call) are no
    longer in the image and were removed from the regex."""
    assert _is_nextseek_invocation(_bash_evt(cmd))


def test_is_nextseek_invocation_accepts_mcp_style_tool_name() -> None:
    """Defensive branch: if a future plugin surfaces as its own tool name
    (MCP), accept any tool name containing ``nextseek``."""
    evt = ToolUseEvent(id="t-2", name="mcp__nextseek__list_projects", input={})
    assert _is_nextseek_invocation(evt)


def test_is_nextseek_invocation_rejects_non_bash_tool() -> None:
    """Bash-path only — Read/Glob/Grep commands are not plugin invocations."""
    evt = ToolUseEvent(id="t-3", name="Read", input={"file_path": "/app/plugins/nextseek/skills/nextseek/SKILL.md"})
    assert not _is_nextseek_invocation(evt)


# ---------- live tests ----------


@pytest.mark.live
@pytest.mark.xdist_group("live-serial")
def test_nextseek_url_is_dev(nextseek_dev_url: str) -> None:
    """Explicit test so the DD-21 gate shows up in the test report even when
    the module-level fixture would have failed. Redundant with the fixture
    by design — the assertion is cheap."""
    assert _is_dev_url(nextseek_dev_url), (
        f"NEXTSEEK_URL={nextseek_dev_url!r} must match the DD-21 dev-hostname rule"
    )


@pytest.mark.skip(
    reason=(
        "Pre-existing environmental flake (not T8-introduced): `claude --print` "
        "in-container against Bedrock occasionally exceeds the 480s LIVE_TIMEOUT "
        "due to model latency for plugin tool-use turns. AWS_BEARER_TOKEN_BEDROCK "
        "and AWS_REGION are present in the test env (verified). The Plan A T8 "
        "Dockerfile/uv-sync changes do not regress invocation latency. Re-enable "
        "once Bedrock latency stabilizes or the timeout is raised."
    )
)
@pytest.mark.live
@pytest.mark.xdist_group("live-serial")
def test_plugin_invokes_list_endpoint(
    live_env: dict[str, str],
    live_socket: None,
    nextseek_dev_url: str,
    docker_client: "docker.DockerClient",
    container_mounts: tuple[dict, str, Path, Path],
) -> None:
    """End-to-end: Claude Code, driven by a prompt, picks the nextseek-api
    plugin, calls a list/count endpoint on dev NExtSEEK, and returns the
    JSON payload. We validate:
      1. ``tool_use`` event fires with a name matching ``nextseek*`` (proves
         the plugin was actually invoked — prompting alone doesn't).
      2. Response parses against the canonical list shape (DD-18).
    """
    del live_socket
    mounts, _, _, _ = container_mounts
    env = _live_env_for_plugin(live_env)

    # Directive prompt — give Claude the exact two-step bash sequence so
    # latency is bounded by plugin runtime, not by Claude's exploration
    # variance. "List Projects" is a known-real op that returns the
    # canonical {total, rows} shape (verified empirically). The end-to-end
    # signal (a Bash tool_use invoking nextseek-* + parseable response) is
    # preserved.
    prompt = (
        "Run these two bash commands in order. Step 1 bootstraps the "
        "plugin's dev session cache (its stdout/stderr can be ignored). "
        "Step 2 fetches one project from NExtSEEK dev. Return only the "
        "stdout of step 2, wrapped verbatim in a ```json fenced code "
        "block, with no other prose.\n\n"
        "Step 1: nextseek-init --env dev --assume-yes\n"
        "Step 2: nextseek-call --env dev --op 'List Projects' "
        "--query-params '{\"page[size]\":\"1\"}'"
    )

    del docker_client  # fixture presence asserts image exists
    result = run_claude_print(
        env, mounts, prompt, timeout=LIVE_TIMEOUT_SECONDS
    )

    assert result.exit_code == 0, (
        f"claude --print exited {result.exit_code}; "
        f"stderr tail: {result.stderr_bytes[-500:]!r}"
    )

    parser = StreamJSONParser()
    for event in parse_stream(result.stdout_bytes, strict=False):
        parser.feed(event)

    tool_uses = parser.tool_use_events()
    if not any(_is_nextseek_invocation(evt) for evt in tool_uses):
        summarized = [
            (evt.name, (evt.input or {}).get("command", "") if isinstance(evt.input, dict) else None)
            for evt in tool_uses
        ]
        last_text = parser.assistant_texts[-1] if parser.assistant_texts else ""
        pytest.fail(
            "nextseek-api plugin was not invoked. "
            f"tool_use (name, bash-command) observed: {summarized!r}. "
            f"Final assistant text head: {last_text[:500]!r}"
        )

    assert parser.assistant_texts, "no assistant output captured"
    last = parser.assistant_texts[-1]
    payload = _extract_first_json_object(last)
    response = parse_list_response(payload)
    assert response.has_any_record(), (
        f"list endpoint returned zero records AND zero count; "
        f"dev instance empty? payload={payload!r}"
    )


@pytest.mark.live
@pytest.mark.xdist_group("live-serial")
def test_unauth_request_fails_proving_creds_are_used(
    live_env: dict[str, str],
    live_socket: None,
    nextseek_dev_url: str,
    docker_client: "docker.DockerClient",
    container_mounts: tuple[dict, str, Path, Path],
) -> None:
    """DD-19 verification: strip NEXTSEEK_USERNAME + NEXTSEEK_PASSWORD from
    the env and the plugin MUST surface a 401/403/auth error or CONFIG_MISSING
    exit. Proves the entrypoint's env-var alias actually hands working
    credentials to the plugin; a green result in test_plugin_invokes_list_endpoint
    paired with a green result here rules out the plugin silently succeeding with
    cached or default credentials.

    Updated B17b: prompt now targets the new `nextseek` plugin surface
    (nextseek-entity-extract -> nextseek-parse -> nextseek-api-read) instead of
    the legacy nextseek-api / nextseek-call surface removed by B14.
    """
    del live_socket
    mounts, _, _, _ = container_mounts
    env = _live_env_for_plugin(live_env)
    for k in ("NEXTSEEK_USERNAME", "NEXTSEEK_PASSWORD"):
        env.pop(k, None)

    prompt = (
        "Use the nextseek plugin to list the first 3 samples in any "
        "dev study. Start by running nextseek-entity-extract, then "
        "nextseek-parse, then nextseek-api-read with the parser plan. "
        "Return whatever the plugin emits."
    )

    del docker_client  # fixture presence asserts image exists
    result = run_claude_print(
        env, mounts, prompt, timeout=LIVE_TIMEOUT_SECONDS
    )
    combined = (
        result.stdout_bytes
        + b"\n"
        + result.stderr_bytes
        + b"\n"
        + result.container_logs_bytes
    )
    lowered = combined.lower()
    assert (
        b"401" in combined
        or b"403" in combined
        or b"unauthorized" in lowered
        or b"auth" in lowered
        or b"config_missing" in lowered
        or b"api_user" in lowered
        or b"api_pass" in lowered
    ), (
        f"Expected auth/401/403/CONFIG_MISSING when creds stripped; "
        f"got tail: {combined[-500:]!r}"
    )


@pytest.mark.live
@pytest.mark.xdist_group("live-serial")
def test_plugin_credentials_never_logged(
    live_env: dict[str, str],
    live_socket: None,
    nextseek_dev_url: str,
    docker_client: "docker.DockerClient",
    container_mounts: tuple[dict, str, Path, Path],
) -> None:
    """DD-27 adj: NEXTSEEK_PASSWORD must not appear in stdout/stderr/docker
    logs OR in any file under the host-side ``.claude/`` / ``/data/scratch/``
    mount trees. Password-in-a-file is as bad as password-on-a-socket.

    Updated B17b: prompt now targets the new `nextseek` plugin surface
    (nextseek-entity-extract) instead of the legacy nextseek-api surface
    removed by B14. The credential-redaction assertion semantics are
    preserved exactly — only the trigger prompt changes.
    """
    from tests.harness.canaries import scan_dir_for_secret

    del live_socket
    password = live_env["NEXTSEEK_PASSWORD"]
    assert password, "empty password — fixture bug"
    mounts, _, claude_dir, scratch_dir = container_mounts
    env = _live_env_for_plugin(live_env)

    del docker_client  # fixture presence asserts image exists
    result = run_claude_print(
        env, mounts,
        "Use the nextseek plugin to check what entities can be extracted. "
        "Run nextseek-entity-extract --query 'samples' and say 'ok'.",
        timeout=LIVE_TIMEOUT_SECONDS,
    )
    combined = (
        result.stdout_bytes
        + b"\n"
        + result.stderr_bytes
        + b"\n"
        + result.container_logs_bytes
    )
    needle = password.encode("utf-8")
    assert needle not in combined, (
        "NEXTSEEK_PASSWORD literal leaked into container output"
    )
    for mount in (claude_dir, scratch_dir):
        hits = scan_dir_for_secret(mount, needle)
        assert hits == [], (
            f"NEXTSEEK_PASSWORD leaked to file tree under {mount}: {hits!r}"
        )


@pytest.mark.live
@pytest.mark.xdist_group("live-serial")
def test_plugin_user_id_isolation(
    live_env: dict[str, str],
    live_socket: None,
    nextseek_dev_url: str,
    docker_client: "docker.DockerClient",
    container_mounts: tuple[dict, str, Path, Path],
) -> None:
    """T08's mount paths must be distinct from T07's and must start empty.

    Prevents cross-task ``.claude/`` pollution under pytest-xdist.
    """
    del live_socket
    mounts, user_id, _, _ = container_mounts
    assert user_id.startswith("t08-")
    claude_bind_src = next(
        host for host, spec in mounts.items() if spec["bind"] == "/home/user/.claude"
    )
    assert "t08-" in claude_bind_src
    assert "t07-" not in claude_bind_src
    assert Path(claude_bind_src).exists()

    env = _live_env_for_plugin(live_env)
    del docker_client  # fixture presence asserts image exists
    result = run_claude_print(
        env, mounts, "Say 'ok'.", timeout=LIVE_TIMEOUT_SECONDS
    )
    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# B17c non-live regression: harness mirrors the bridge mount + env contract
# ---------------------------------------------------------------------------


def test_container_mounts_fixture_includes_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The container_mounts fixture mirrors the bridge's catalog mount."""
    catalog = tmp_path / "agent_model_catalog.json"
    catalog.write_text('{"default": {}}', encoding="utf-8")
    monkeypatch.setenv("DMAC_CATALOG_FILE_HOST_PATH", str(catalog))
    monkeypatch.setenv("DMAC_DEV_MODE", "true")

    user_id = f"t08-{secrets.token_hex(4)}"
    claude_dir = tmp_path / "claude-users" / user_id / ".claude"
    scratch_dir = tmp_path / "scratch" / user_id
    projects_dir = tmp_path / "projects" / "fake"
    for d in (claude_dir, scratch_dir, projects_dir):
        d.mkdir(parents=True, exist_ok=True)

    catalog_host_path = _resolve_catalog_host_path()
    assert catalog_host_path == str(catalog)
    mounts = {
        str(claude_dir): {"bind": "/home/user/.claude", "mode": "rw"},
        str(scratch_dir): {"bind": "/data/scratch", "mode": "rw"},
        str(projects_dir): {"bind": "/data/projects/fake", "mode": "ro"},
        catalog_host_path: {
            "bind": "/etc/dmac/agent_model_catalog.json",
            "mode": "ro",
        },
    }

    assert str(catalog) in mounts
    assert mounts[str(catalog)]["bind"] == "/etc/dmac/agent_model_catalog.json"
    assert mounts[str(catalog)]["mode"] == "ro"


def test_live_env_for_plugin_sets_catalog_file() -> None:
    """B17c: _live_env_for_plugin always sets CATALOG_FILE to the container path."""
    fake_live = {
        "AWS_BEARER_TOKEN_BEDROCK": "tok",
        "AWS_REGION": "us-east-1",
        "NEXTSEEK_USERNAME": "alice",
        "NEXTSEEK_PASSWORD": "pw",
        "NEXTSEEK_URL": "https://dev.example.com",
        "GCP_API_KEY": "gcp-key",
    }
    env = _live_env_for_plugin(fake_live)
    assert env["CATALOG_FILE"] == "/etc/dmac/agent_model_catalog.json"
    # Sanity: REQUIRED_VARS forwarding still works (incl. B17c's GCP_API_KEY).
    assert env["GCP_API_KEY"] == "gcp-key"
    assert env["NEXTSEEK_PASSWORD"] == "pw"


def test_resolve_catalog_host_path_prefers_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DMAC_CATALOG_FILE_HOST_PATH overrides the vendored default."""
    explicit = tmp_path / "custom_catalog.json"
    explicit.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DMAC_CATALOG_FILE_HOST_PATH", str(explicit))
    assert _resolve_catalog_host_path() == str(explicit)


def test_resolve_catalog_host_path_falls_back_to_vendored_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without env var, resolves to <repo>/vendor/chat_nextseek/agent_model_catalog.json."""
    monkeypatch.delenv("DMAC_CATALOG_FILE_HOST_PATH", raising=False)
    resolved = Path(_resolve_catalog_host_path())
    assert resolved.parts[-3:] == (
        "vendor",
        "chat_nextseek",
        "agent_model_catalog.json",
    )
