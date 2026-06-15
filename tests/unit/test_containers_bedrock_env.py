"""OI-3 (T4): de-credentialing proof for the agent-container env builders.

After T4 the per-user agent container is pointed at the Bedrock auth-proxy
sidecar and told to emit UNSIGNED Bedrock requests; the institutional
``AWS_BEARER_TOKEN_BEDROCK`` lives ONLY in the proxy's compose env_file and is
never forwarded into the agent. These tests pin that contract on BOTH the
base builder (``_build_environment``) and the per-exec builder
(``_build_exec_environment``), and make the absence assertion NON-VACUOUS by
supplying a token-bearing ``bridge_env`` input and proving it does not survive
into the output env.
"""
from __future__ import annotations

import pytest
from pydantic import SecretStr

from dmac_assistant.auth import AuthenticatedIdentity
from dmac_assistant.containers import (
    _build_environment,
    _build_exec_environment,
)

PROXY_URL = "http://bedrock-proxy:8080"

# Mirror tests/unit/test_containers.py: the bearer token is an INPUT the de-cred
# guard must filter — keeping it in the input is what makes the OUTPUT-absence
# assertions non-vacuous.
_BRIDGE_ENV_WITH_TOKEN = {
    "AWS_REGION": "us-east-1",
    "AWS_BEARER_TOKEN_BEDROCK": "bearer-abc",
}


def _identity() -> AuthenticatedIdentity:
    return AuthenticatedIdentity(
        user_id="alice",
        password=SecretStr("s3cret"),
        projects=["proj-a", "proj-b"],
    )


# --------------------------------------------------------------- base builder


def test_build_environment_drops_bearer_and_points_at_proxy() -> None:
    """Non-vacuous: bridge_env CARRIES the token; the output must NOT."""
    bridge_env = dict(_BRIDGE_ENV_WITH_TOKEN)
    assert "AWS_BEARER_TOKEN_BEDROCK" in bridge_env  # input carries it
    env = _build_environment(_identity(), bridge_env, bedrock_proxy_url=PROXY_URL)

    assert "AWS_BEARER_TOKEN_BEDROCK" not in env
    assert env["ANTHROPIC_BEDROCK_BASE_URL"] == PROXY_URL
    assert env["CLAUDE_CODE_SKIP_BEDROCK_AUTH"] == "1"
    assert env["CLAUDE_CODE_USE_BEDROCK"] == "1"
    # the canary VALUE never appears in any output value either (catches re-keying)
    assert "bearer-abc" not in "".join(env.values())


def test_build_environment_proxy_url_is_the_configured_value() -> None:
    """ANTHROPIC_BEDROCK_BASE_URL is exactly the threaded proxy url, not a default."""
    custom = "http://proxy.internal:9999"
    env = _build_environment(
        _identity(), dict(_BRIDGE_ENV_WITH_TOKEN), bedrock_proxy_url=custom
    )
    assert env["ANTHROPIC_BEDROCK_BASE_URL"] == custom


def test_build_environment_requires_bedrock_proxy_url() -> None:
    """A missed thread of bedrock_proxy_url must fail loudly (no silent default)."""
    with pytest.raises(TypeError):
        _build_environment(  # type: ignore[call-arg]
            _identity(), dict(_BRIDGE_ENV_WITH_TOKEN)
        )


# ----------------------------------------------------- per-exec builder (both routes)


@pytest.mark.parametrize("route", ["cc", "ns"])
def test_build_exec_environment_drops_bearer_on_both_routes(route: str) -> None:
    """Non-vacuous: the token is an INPUT but is ABSENT from the exec env on
    BOTH the cc and ns routes, which is the surface docker exec actually runs."""
    bridge_env = dict(_BRIDGE_ENV_WITH_TOKEN, NEXTSEEK_BASE_URL="http://ns.example")
    assert "AWS_BEARER_TOKEN_BEDROCK" in bridge_env  # input carries it
    env = _build_exec_environment(
        _identity(),
        bridge_env,
        route=route,
        bedrock_proxy_url=PROXY_URL,
        ns_session_id="sess-1" if route == "ns" else None,
    )

    assert "AWS_BEARER_TOKEN_BEDROCK" not in env
    assert env["ANTHROPIC_BEDROCK_BASE_URL"] == PROXY_URL
    assert env["CLAUDE_CODE_SKIP_BEDROCK_AUTH"] == "1"
    assert env["CLAUDE_CODE_USE_BEDROCK"] == "1"
    assert "bearer-abc" not in "".join(env.values())
