"""tests/test_nodes.py — 새로 만든 노드 동작(모르는 시스템 안내, 마무리 문구, 검색어 구성)의 단위 테스트.

이 노드들은 AI·MCP를 부르지 않으므로 상태(dict)만 만들어 넣으면 된다.
"""
import asyncio

from agent.graph import finalize_node, unknown_system_node
from agent.nodes import replan


def run(node, state):
    """async 노드를 실행해 결과를 받는다 (deps는 이 노드들이 쓰지 않으므로 None)."""
    return asyncio.run(node(state, deps=None))


# ---------- unknown_system_node ----------

# 모르는 시스템 이름과 조회 가능한 시스템 목록을 안내한다
def test_unknown_system_node_explains_and_lists_known_systems():
    out = run(unknown_system_node, {"query": "billing-service 응답이 느려요", "events": []})
    assert "billing-service" in out["final"]
    assert "조회할 수 없습니다" in out["final"]
    assert "auth-service" in out["final"]          # 조회 가능한 시스템 목록에 포함


# UnknownSystem 이벤트와 Finalize 이벤트를 남긴다
def test_unknown_system_node_records_events():
    out = run(unknown_system_node, {"query": "billing-service 응답이 느려요", "events": []})
    assert out["events"][-2] == {"type": "UnknownSystem", "systems": ["billing-service"]}
    assert out["events"][-1] == {"type": "Finalize", "pipeline": "unknown-system"}


# ---------- finalize_node ----------

# 문구를 붙일 이유가 없으면 초안 그대로 최종 답변이 된다
def test_finalize_keeps_draft_when_nothing_to_add():
    state = {"query": "web-01 CPU 급증", "draft": "1) 정상 범위입니다.", "events": []}
    out = run(finalize_node, state)
    assert out["final"] == "1) 정상 범위입니다."
    assert out["events"][-1] == {"type": "Finalize", "pipeline": "incident-v2"}


# 아는 시스템과 모르는 시스템이 섞였으면 모르는 쪽은 조회하지 않았다고 덧붙인다
def test_finalize_notes_unknown_system_in_mixed_query():
    state = {"query": "payments-service랑 billing-service 둘 다 느려요", "draft": "1) 조사 결과", "events": []}
    out = run(finalize_node, state)
    assert out["final"].startswith("1) 조사 결과")
    assert "billing-service" in out["final"]
    assert "조회하지 않았습니다" in out["final"]


# 맞는 runbook이 없다고 판단했으면(matched 키가 있는 ReplanCheck) 그 사실을 덧붙인다
def test_finalize_notes_when_no_runbook_matched():
    events = [{"type": "ReplanCheck", "round": 0, "is_sufficient": True, "matched": None}]
    out = run(finalize_node, {"query": "web-01 CPU 급증", "draft": "1) 수치만 안내", "events": events})
    assert "대응 매뉴얼을 찾지 못해" in out["final"]


# runbook을 정상적으로 골랐으면(matched 키가 없는 ReplanCheck) 안내 문구를 붙이지 않는다
def test_finalize_adds_no_note_when_runbook_was_selected():
    events = [{"type": "ReplanCheck", "round": 0, "is_sufficient": False, "target": "cpu-spike"}]
    out = run(finalize_node, {"query": "web-01 CPU 급증", "draft": "1) 매뉴얼 기반 답변", "events": events})
    assert out["final"] == "1) 매뉴얼 기반 답변"


# ---------- _search_text (RAG 검색어 구성) ----------

MONITORING = [{"source": "monitoring",
               "data": {"status": "degraded", "alerts": ["p95 latency 2.4s", "connection pool 92% used"]}}]


# 'query' 방식은 알림을 섞지 않고 질문만 쓴다
def test_search_text_query_mode_uses_question_only(monkeypatch):
    monkeypatch.setattr(replan, "RAG_INPUT", "query")
    state = {"query": "web-01 CPU 급증", "collected": MONITORING}
    assert replan._search_text(state) == "web-01 CPU 급증"


# 'query+alerts' 방식은 항상 알림을 함께 쓴다
def test_search_text_query_plus_alerts_mode_always_adds_alerts(monkeypatch):
    monkeypatch.setattr(replan, "RAG_INPUT", "query+alerts")
    state = {"query": "인증서가 만료됐다는 경고", "collected": MONITORING}
    text = replan._search_text(state)
    assert "인증서가 만료됐다는 경고" in text
    assert "p95 latency 2.4s" in text


# 'auto' 방식: 질문에 아는 시스템이 있으면 그 알림을 함께 쓴다
def test_search_text_auto_adds_alerts_when_known_system_named(monkeypatch):
    monkeypatch.setattr(replan, "RAG_INPUT", "auto")
    state = {"query": "auth-service 응답이 느려요", "collected": MONITORING}
    assert "p95 latency 2.4s" in replan._search_text(state)


# 'auto' 방식: 시스템을 안 밝혔으면 (기본 조회 대상의 알림이 검색을 오염시키므로) 질문만 쓴다
def test_search_text_auto_uses_question_only_when_no_system_named(monkeypatch):
    monkeypatch.setattr(replan, "RAG_INPUT", "auto")
    state = {"query": "인증서가 만료됐다는 경고", "collected": MONITORING}
    assert replan._search_text(state) == "인증서가 만료됐다는 경고"
