import hashlib
import sys
import types

import pytest

from sidecar.app import sessions
from sidecar.app.contract import NsLogin


@pytest.fixture
def fake_mss(monkeypatch):
    captured = {}

    class FakeMSS:
        def __init__(self, db_config, session_id):
            captured["db_config"] = db_config
            captured["session_id"] = session_id

    mod = types.ModuleType("chat_nextseek.session")
    mod.MySQLSessionState = FakeMSS
    monkeypatch.setitem(sys.modules, "chat_nextseek.session", mod)
    return captured


class _Cfg:
    session_db = {"host": "h", "port": 3306, "user": "u", "password": "p", "database": "d"}


def test_session_key_is_hashed_user(fake_mss):
    login = NsLogin(api_user="alice@mit.edu", api_pass="x")
    sessions.make_session(login, config=object(), sidecar_cfg=_Cfg())
    expected = "ns:" + hashlib.sha256(b"alice@mit.edu").hexdigest()
    assert fake_mss["session_id"] == expected
    assert fake_mss["db_config"]["host"] == "h"
    # 2R1 item 3b: first-class never-raw-user assertion — the plaintext api_user must
    # never appear in the session_id (only its sha256 digest does).
    assert login.api_user not in fake_mss["session_id"]


def test_distinct_users_distinct_keys(fake_mss):
    a = sessions._session_key("alice")
    b = sessions._session_key("bob")
    assert a != b and a.startswith("ns:")


def test_no_normalization_distinct_case_distinct_keys(fake_mss):
    # 2R1 item 3a: keying is intentionally NOT case-normalized. Normalizing would risk
    # merging distinct authenticated identities onto one session; fragmentation is the
    # safe direction, so distinct case must yield distinct keys.
    assert sessions._session_key("Alice") != sessions._session_key("alice")


def test_assistant_session_id_preserved_when_present(fake_mss):
    login = NsLogin(api_user="alice", api_pass="x")
    sessions.make_session(
        login, config=object(), sidecar_cfg=_Cfg(), assistant_session_id="conv-123"
    )
    assert fake_mss["session_id"] == "ns:" + hashlib.sha256(b"alice").hexdigest() + ":conv-123"
