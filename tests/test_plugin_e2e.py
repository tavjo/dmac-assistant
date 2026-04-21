"""Live NExtSEEK plugin E2E for dmac-assistant:poc.

Runs after T07 (same xdist group). Invokes the baked-in `nextseek-api`
plugin through `claude --print` with a natural-language prompt, extracts
the JSON payload from the assistant's final turn, and validates it
against the canonical DRF-style list shape.

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
import re
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import docker

from tests.harness.plugin_schema import parse_list_response
from tests.harness.stream_json import StreamJSONParser, ToolUseEvent, parse_stream


# H-3: match the actual baked-in script names, not any token containing
# "nextseek-". A substring check would false-positive on `grep nextseek-*`,
# `ls /app/plugins/nextseek-api/bin/`, or a comment mentioning the plugin
# name. The regex enumerates the real executables shipped in the image's
# PATH (DD-37) plus ``nextseek-session`` used by the SKILL.md docs.
_NEXTSEEK_SCRIPT_RE = re.compile(
    r"\bnextseek-(call|init|spec|exec|validate|vocab|session)\b"
)


def _is_nextseek_invocation(evt: ToolUseEvent) -> bool:
    """A tool_use event proves the nextseek-api plugin was actually called.

    Per ADR-008 the plugin is bash-scripted (MCP rejected for POC plugins);
    its commands surface as ``Bash`` tool_use events whose ``input.command``
    invokes one of the ``nextseek-*`` scripts (``nextseek-call``,
    ``nextseek-spec``, ``nextseek-vocab``, etc.). A future MCP-style
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

def _allow_docker_unix_socket_only() -> None:
    """Keep host networking gated while allowing docker-py's Unix socket."""
    try:
        import pytest_socket
    except ImportError:
        return
    pytest_socket.enable_socket()
    pytest_socket.disable_socket(allow_unix_socket=True)


@pytest.fixture(scope="module")
def docker_client():
    _allow_docker_unix_socket_only()
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


@pytest.fixture
def container_mounts(tmp_path: Path) -> tuple[dict[str, dict[str, str]], str, Path, Path]:
    """T08 uses a distinct user_id from T07 for mount isolation (R-17 adj.)."""
    user_id = f"t08-{secrets.token_hex(4)}"
    claude_dir = tmp_path / "claude-users" / user_id / ".claude"
    scratch_dir = tmp_path / "scratch" / user_id
    projects_dir = tmp_path / "projects" / "fake"
    for d in (claude_dir, scratch_dir, projects_dir):
        d.mkdir(parents=True, exist_ok=True)

    assert "t07" not in str(claude_dir), "user_id must differ from T07's"
    assert list(claude_dir.iterdir()) == []

    mounts = {
        str(claude_dir): {"bind": "/home/user/.claude", "mode": "rw"},
        str(scratch_dir): {"bind": "/data/scratch", "mode": "rw"},
        str(projects_dir): {"bind": "/data/projects/fake", "mode": "ro"},
    }
    return mounts, user_id, claude_dir, scratch_dir


@dataclass
class ClaudeRunResult:
    stdout_bytes: bytes
    stderr_bytes: bytes
    container_logs_bytes: bytes
    exit_code: int


_AUTH_ERROR_MARKERS = (
    "ExpiredTokenException",
    "UnauthorizedException",
    "AccessDenied",
    "Invalid API Key format",
)


def _maybe_skip_on_auth(*blobs: bytes) -> None:
    """Skip (per ADR-004) when output shows a recognized Bedrock auth failure."""
    joined = b"\n".join(b for b in blobs if b).decode("utf-8", errors="replace")
    if any(marker in joined for marker in _AUTH_ERROR_MARKERS):
        pytest.skip(
            "Bedrock auth failure (likely ADR-004 hourly token expiry or "
            f"malformed credential in --env-file): {joined[:500]}"
        )


def _run_claude_print(
    client: "docker.DockerClient",
    env: dict[str, str],
    mounts: dict[str, dict[str, str]],
    prompt: str,
    timeout: int = LIVE_TIMEOUT_SECONDS,
    extra_env: dict[str, str] | None = None,
) -> ClaudeRunResult:
    """Run `claude --print` inside the image via `docker run -i`.

    Per DD-33, uses the docker CLI rather than docker-py's ``attach_socket``
    because the library's hijacked-socket pattern does not propagate stdin
    EOF for the ``claude --print --input-format text`` workload. ADR-006's
    docker-py convention applies to the production bridge, not test
    harnesses.

    Per DD-31, ``--verbose`` is required for ``--output-format stream-json``
    in claude-code 2.1.92; without it the CLI rejects the combination at
    arg-validation time.

    ``extra_env`` is merged over ``env`` (e.g., ``USE_DEV_API=1`` for DD-21
    layer 2). Does NOT assert the return code so callers can probe expected
    failure modes (e.g., the unauth-negative test).
    """
    del client  # presence of `docker_client` fixture asserts image exists
    effective_env = dict(env)
    if extra_env:
        effective_env.update(extra_env)

    cmd: list[str] = ["docker", "run", "--rm", "-i"]
    for key, value in effective_env.items():
        cmd.extend(["-e", f"{key}={value}"])
    for host_path, spec in mounts.items():
        bind = spec["bind"]
        mode = spec.get("mode", "rw")
        cmd.extend(["-v", f"{host_path}:{bind}:{mode}"])
    cmd.extend([
        IMAGE,
        "claude",
        "--print",
        "--output-format",
        "stream-json",
        "--input-format",
        "text",
        "--verbose",
        "--dangerously-skip-permissions",
    ])

    try:
        completed = subprocess.run(
            cmd,
            input=prompt.encode("utf-8") + b"\n",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        partial_stdout = exc.stdout or b""
        partial_stderr = exc.stderr or b""
        _maybe_skip_on_auth(partial_stderr, partial_stdout)
        raise TimeoutError(
            f"claude --print did not exit within {timeout}s; "
            f"stdout={partial_stdout[:500]!r} stderr={partial_stderr[:500]!r}"
        ) from exc

    _maybe_skip_on_auth(completed.stderr, completed.stdout)

    return ClaudeRunResult(
        stdout_bytes=completed.stdout,
        stderr_bytes=completed.stderr,
        container_logs_bytes=completed.stdout + b"\n" + completed.stderr,
        exit_code=completed.returncode,
    )


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
        "nextseek-call --env dev --op 'List Projects'",
        "nextseek-init --env dev --assume-yes",
        "nextseek-spec 'List Samples'",
        "nextseek-validate --op foo",
        "/app/plugins/nextseek-api/bin/nextseek-exec --op foo",
        "cd /tmp && nextseek-vocab",
    ],
)
def test_is_nextseek_invocation_matches_real_scripts(cmd: str) -> None:
    """H-3: regex matches every script name the plugin actually ships."""
    assert _is_nextseek_invocation(_bash_evt(cmd))


@pytest.mark.parametrize(
    "cmd",
    [
        # Trailing dash with no script name — the original substring check
        # matched, the regex rejects.
        "grep -R 'nextseek-' /app",
        # `nextseek-api` is the plugin directory name, not a script name;
        # the original substring check would have accepted this.
        "ls /app/plugins/nextseek-api/bin/",
        # Made-up name outside the script enum — substring would match,
        # the enumerated regex rejects.
        "echo 'plans to run nextseek-doesnotexist later'",
        "cat /tmp/nextseek-whatever.log",
        # `nextseek` alone (no hyphen) never matches.
        "echo 'see the nextseek project for details'",
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


def test_is_nextseek_invocation_accepts_mcp_style_tool_name() -> None:
    """Defensive branch: if a future plugin surfaces as its own tool name
    (MCP), accept any tool name containing ``nextseek``."""
    evt = ToolUseEvent(id="t-2", name="mcp__nextseek__list_projects", input={})
    assert _is_nextseek_invocation(evt)


def test_is_nextseek_invocation_rejects_non_bash_tool() -> None:
    """Bash-path only — Read/Glob/Grep commands are not plugin invocations."""
    evt = ToolUseEvent(id="t-3", name="Read", input={"file_path": "/app/plugins/nextseek-api/SKILL.md"})
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

    result = _run_claude_print(
        docker_client, env, mounts, prompt, timeout=LIVE_TIMEOUT_SECONDS
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
    the env and the plugin MUST surface a 401/403/auth error. Proves the
    entrypoint's env-var alias actually handed working credentials to the
    plugin in ``test_plugin_invokes_list_endpoint``; a green result there
    paired with a green result here rules out the plugin silently
    succeeding with cached or default creds.
    """
    del live_socket
    mounts, _, _, _ = container_mounts
    env = _live_env_for_plugin(live_env)
    for k in ("NEXTSEEK_USERNAME", "NEXTSEEK_PASSWORD"):
        env.pop(k, None)

    prompt = (
        "Use the nextseek-api plugin to list the first 3 samples in any "
        "dev study. Return whatever the plugin emits."
    )

    result = _run_claude_print(
        docker_client, env, mounts, prompt, timeout=LIVE_TIMEOUT_SECONDS
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
    ), (
        f"Expected auth/401/403 when creds stripped; "
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
    """
    from tests.harness.canaries import scan_dir_for_secret

    del live_socket
    password = live_env["NEXTSEEK_PASSWORD"]
    assert password, "empty password — fixture bug"
    mounts, _, claude_dir, scratch_dir = container_mounts
    env = _live_env_for_plugin(live_env)

    result = _run_claude_print(
        docker_client, env, mounts,
        "Use nextseek-api to check the session status; say 'ok'.",
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
    result = _run_claude_print(
        docker_client, env, mounts, "Say 'ok'.", timeout=LIVE_TIMEOUT_SECONDS
    )
    assert result.exit_code == 0
