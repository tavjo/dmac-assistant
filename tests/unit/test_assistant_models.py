import pathlib
import sys

import pytest

_BIN = pathlib.Path(__file__).resolve().parents[2] / "build_context/plugins/nextseek/bin"
sys.path.insert(0, str(_BIN))
import _assistant_models as m


def test_query_request_mode_required_and_extra_forbidden():
    r = m.QueryRequest(query="hi", mode="standard")
    assert r.mode == "standard" and r.force_new is False and r.use_prod is False
    with pytest.raises(ValueError):
        m.QueryRequest(query="hi")
    with pytest.raises(ValueError):
        m.QueryRequest(query="hi", mode="standard", junk=1)


def test_query_complete_event_artifacts_union():
    e = m.QueryCompleteEvent(reply="r", artifacts=[
        {"artifact_type": "table", "key": "k", "label": "L", "columns": ["a"], "data": [{"a": 1}]},
        {"artifact_type": "file", "key": "g", "label": "G", "file_format": "xlsx"},
    ])
    assert e.artifacts[0].artifact_type == "table"
    assert e.artifacts[1].artifact_type == "file"


def test_turn_and_session_detail_with_turns():
    sd = m.SessionDetailResponse(session_id="11111111-1111-4111-8111-111111111111",
                                 created_at="2026-06-09T00:00:00Z", query_count=1, has_results=True,
                                 title="t", turns=[{"bundle_id": 1, "user_query": "q", "reply": "a", "mode": "standard"}])
    assert sd.turns[0].bundle_id == 1


def test_task_progress_and_async():
    a = m.AsyncQueryResponse(task_id="11111111-1111-4111-8111-111111111111",
                             session_id="22222222-2222-4222-8222-222222222222")
    tp = m.TaskProgressResponse(task_id=a.task_id, session_id=a.session_id, status="running",
                                progress=[{"event": "agent_started", "data": {"agent": "entity"}}])
    assert tp.result is None
