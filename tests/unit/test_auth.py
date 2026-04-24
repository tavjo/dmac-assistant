"""T02 auth tests: token issuance, verification, and login route behavior."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from dmac_assistant.auth import (
    AuthenticatedIdentity,
    AuthenticationError,
    TokenStore,
    get_config,
    get_token_store,
    router,
    verify_token_dependency,
)
from dmac_assistant.config import BridgeConfig, UserRecord


@pytest.fixture
def allow_unix_socket_only():
    """Permit local TestClient socketpairs for the duration of a test."""
    try:
        import pytest_socket
    except ImportError:
        yield
        return

    pytest_socket.enable_socket()
    pytest_socket.disable_socket(allow_unix_socket=True)
    try:
        yield
    finally:
        pytest_socket.disable_socket()


@pytest.fixture
def bridge_config() -> BridgeConfig:
    return BridgeConfig(
        users={
            "alice": UserRecord(password="s3cret-alice", projects=["proj-a"]),
            "bob": UserRecord(password="s3cret-bob", projects=["proj-a", "proj-b"]),
        },
        claude_users_root="/tmp/claude-users",
        scratch_root="/tmp/scratch",
        dropbox_root="/tmp/dropbox",
        bridge_host="127.0.0.1",
        bridge_port=8000,
    )


def test_issue_returns_urlsafe_token_and_expiry(bridge_config: BridgeConfig) -> None:
    store = TokenStore()

    issued = store.issue(
        user_id="alice",
        password="s3cret-alice",
        config=bridge_config,
        now=datetime(2026, 4, 23, tzinfo=UTC),
    )

    assert len(issued.token) == 43
    assert issued.expires_at == datetime(2026, 4, 23, 12, tzinfo=UTC)


def test_issue_rejects_unknown_user(bridge_config: BridgeConfig) -> None:
    store = TokenStore()

    with pytest.raises(AuthenticationError, match="invalid credentials"):
        store.issue(user_id="carol", password="x", config=bridge_config)


def test_issue_rejects_wrong_password(bridge_config: BridgeConfig) -> None:
    store = TokenStore()

    with pytest.raises(AuthenticationError, match="invalid credentials"):
        store.issue(user_id="alice", password="wrong", config=bridge_config)


def test_issue_is_unique_over_many_calls(bridge_config: BridgeConfig) -> None:
    store = TokenStore()
    tokens = {
        store.issue(user_id="alice", password="s3cret-alice", config=bridge_config).token
        for _ in range(1000)
    }
    assert len(tokens) == 1000


def test_verify_returns_authenticated_identity(bridge_config: BridgeConfig) -> None:
    store = TokenStore()
    issued = store.issue(
        user_id="bob",
        password="s3cret-bob",
        config=bridge_config,
        now=datetime(2026, 4, 23, tzinfo=UTC),
    )

    identity = store.verify(issued.token, now=datetime(2026, 4, 23, 1, tzinfo=UTC))

    assert isinstance(identity, AuthenticatedIdentity)
    assert identity.user_id == "bob"
    assert identity.projects == ["proj-a", "proj-b"]
    assert identity.password.get_secret_value() == "s3cret-bob"


def test_verify_rejects_missing_token() -> None:
    store = TokenStore()

    with pytest.raises(AuthenticationError, match="invalid token"):
        store.verify("missing")


def test_verify_rejects_expired_token(bridge_config: BridgeConfig) -> None:
    store = TokenStore(ttl=timedelta(seconds=1))
    issued = store.issue(
        user_id="alice",
        password="s3cret-alice",
        config=bridge_config,
        now=datetime(2026, 4, 23, tzinfo=UTC),
    )

    with pytest.raises(AuthenticationError, match="expired token"):
        store.verify(issued.token, now=datetime(2026, 4, 23, 0, 0, 2, tzinfo=UTC))


def test_revoke_removes_token(bridge_config: BridgeConfig) -> None:
    store = TokenStore()
    issued = store.issue(
        user_id="alice",
        password="s3cret-alice",
        config=bridge_config,
    )

    store.revoke(issued.token)

    with pytest.raises(AuthenticationError, match="invalid token"):
        store.verify(issued.token)


def test_get_config_loads_from_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "DMAC_USERS",
        '{"alice": {"password": "s3cret-alice", "projects": ["proj-a"]}}',
    )
    monkeypatch.setenv("DMAC_CLAUDE_USERS_ROOT", "./var/claude-users")
    monkeypatch.setenv("DMAC_SCRATCH_ROOT", "./var/scratch")
    monkeypatch.setenv("DMAC_DROPBOX_ROOT", "./dropbox")

    loaded = get_config()

    assert loaded.users["alice"].projects == ["proj-a"]


def test_get_token_store_returns_singleton() -> None:
    assert get_token_store() is get_token_store()


def test_verify_token_dependency_rejects_missing_header() -> None:
    store = TokenStore()

    with pytest.raises(Exception) as exc_info:
        verify_token_dependency(authorization=None, token_store=store)
    exc = exc_info.value
    assert getattr(exc, "status_code", None) == 401


def test_verify_token_dependency_rejects_bad_scheme() -> None:
    store = TokenStore()

    with pytest.raises(Exception) as exc_info:
        verify_token_dependency(authorization="Basic nope", token_store=store)
    assert getattr(exc_info.value, "status_code", None) == 401


def test_verify_token_dependency_accepts_bearer_token(bridge_config: BridgeConfig) -> None:
    store = TokenStore()
    issued = store.issue(
        user_id="alice",
        password="s3cret-alice",
        config=bridge_config,
    )

    identity = verify_token_dependency(
        authorization=f"Bearer {issued.token}",
        token_store=store,
    )

    assert identity.user_id == "alice"
    assert identity.password.get_secret_value() == "s3cret-alice"


def test_verify_token_dependency_rejects_invalid_bearer_token() -> None:
    store = TokenStore()

    with pytest.raises(Exception) as exc_info:
        verify_token_dependency(authorization="Bearer missing", token_store=store)
    assert getattr(exc_info.value, "status_code", None) == 401
    assert getattr(exc_info.value, "detail", None) == "invalid token"


def test_login_route_returns_token(
    bridge_config: BridgeConfig,
    allow_unix_socket_only,
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_config] = lambda: bridge_config
    app.dependency_overrides[get_token_store] = lambda: TokenStore()

    with TestClient(app) as client:
        response = client.post(
            "/auth/login",
            json={"user_id": "alice", "password": "s3cret-alice"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["token"]) == 43
    assert payload["expires_at"].startswith("202")


def test_login_route_rejects_bad_credentials(
    bridge_config: BridgeConfig,
    allow_unix_socket_only,
) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_config] = lambda: bridge_config
    app.dependency_overrides[get_token_store] = lambda: TokenStore()

    with TestClient(app) as client:
        response = client.post(
            "/auth/login",
            json={"user_id": "alice", "password": "wrong"},
        )

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid credentials"
