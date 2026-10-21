"""agent/nodes/replan.py — 재판단 노드: 어떤 runbook을 읽을지 고르고 필요하면 조사를 한 번 더.

replan_check_node(1차 조사 결과를 보고 runbook이 없으면 RAG로 골라 읽기 작업을 추가),
_search_text(RAG 검색어 구성), _classify_incident_type(예전 키워드 규칙, Before 비교용으로 보존),
_after_replan_check(다음 노드를 고르는 갈림길). graph.py에 있던 것을 분리했다(동작은 그대로).
"""
import os                                        # 환경변수(RAG_INPUT) 읽기
import time                                      # runbook 선택 시간 측정

from langsmith import traceable                  # LangSmith 기록용 장식자

from ..deps import SupervisorDeps                # 도구 상자 형식
from ..state import AgentState                   # 공용 메모장 양식
from ..systems import _split_systems             # 질문 속 시스템을 아는 것/모르는 것으로 나누기


# 개선 1 — RAG 검색 입력 (eval/run_eval.py 23문항 비교 결과로 기본값 결정).
#   'auto'(기본)    : 질문에 아는 시스템이 명시된 때만 질문 + 그 시스템의 알림, 아니면 질문만 (19/23)
#   'query'         : 질문만 (17/23)
#   'query+alerts'  : 항상 질문 + 알림 (14/23) — 시스템을 안 밝힌 질문에서 기본 조회 대상
#                     (auth-service)의 알림이 검색을 high-latency 쪽으로 오염시킴
RAG_INPUT = os.environ.get("RAG_INPUT", "auto")


def _search_text(state: AgentState) -> str:
    """RAG에 넣을 검색어를 만든다 (RAG_INPUT 설정에 따라 질문만 또는 질문 + 알림)."""
    if RAG_INPUT == "query":                     # 질문만 쓰는 방식
        return state["query"]
    if RAG_INPUT == "auto":   # 질문에 아는 시스템이 명시된 경우에만 그 시스템의 알림을 함께 검색
        known, _ = _split_systems(state["query"])
        if not known:   # 시스템을 안 밝혔다면 기본 조회 대상(auth-service)의 알림이 검색을 오염시킴
            return state["query"]
    # 조회된 모니터링 결과(상태, 알림)를 글자로 이어 붙인다
    monitoring = " ".join(
        f"{c['data'].get('status', '')} " + " ".join(c["data"].get("alerts", []))
        for c in state.get("collected", []) if c.get("source") == "monitoring")
    return f"{state['query']} {monitoring}".strip()


# 예전 키워드 규칙(Before). CLASSIFIER=rules로 서버를 켰을 때만 쓰이며 비교용으로 남겨 둔 것이다.
# 수집된 모니터링 결과(상태·알림 문구)를 보고 어떤 runbook이 맞는지 코드 규칙으로 고른다.
_INCIDENT_TYPE_RULES = [
    ("latency", "high-latency"),
    ("pool", "high-latency"),
    ("cpu", "cpu-spike"),
    ("memory", "memory-leak"),
    ("heap", "memory-leak"),
    ("timeout", "network-timeout"),
    ("network", "network-timeout"),
    ("disk", "disk-full"),
    ("down", "db-down"),
]


def _classify_incident_type(collected: list[dict]) -> str:
    text = " ".join(                             # 알림 글자만 모아 하나의 문자열로
        f"{c['data'].get('status', '')} " + " ".join(c["data"].get("alerts", []))
        for c in collected if c.get("source") == "monitoring"
    ).lower()
    for keyword, incident_type in _INCIDENT_TYPE_RULES:   # 위에서부터 처음 맞는 키워드가 승리
        if keyword in text:
            return incident_type
    return "db-down"   # 매칭되는 증상이 없으면 가장 일반적인 장애 대응 절차로 폴백


@traceable(name="replan_check_node")
async def replan_check_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """Wave 7 — 1차 수집 결과 평가. runbook이 없으면 gap task만 추가해 재조사.

    개선 1 — 어떤 runbook을 가져올지를 키워드 규칙 대신 의미 검색(RAG)으로 고른다.
    deps.retriever가 None이면(CLASSIFIER=rules) 기존 키워드 규칙으로 동작한다.
    select_ms — runbook 선택에 걸린 시간(밀리초). 규칙/RAG 비용 비교용."""
    # 지금까지 가져온 자료 중에 runbook이 있는가 (md 파일 존재 여부가 아니라 "이번에 읽어 왔는가")
    has_runbook = any(c["source"] == "runbook" for c in state.get("collected", []))
    rounds = state.get("replan_rounds", 0)       # 지금까지 재조사한 횟수
    if has_runbook or rounds >= 1:               # 이미 읽었거나, 이미 한 번 재조사했으면 (무한 반복 방지)
        verdict = {"type": "ReplanCheck", "round": rounds, "is_sufficient": True}
        return {"events": state["events"] + [verdict]}

    started = time.perf_counter()   # 선택 시간 측정 시작
    if deps.retriever is not None:               # 검색기가 있으면 → RAG (After)
        match = await deps.retriever.search(_search_text(state))
        incident_type, score, method = match["incident_type"], match["score"], "rag"
    else:                                        # 없으면 → 예전 키워드 규칙 (Before)
        incident_type = _classify_incident_type(state.get("collected", []))
        score, method = None, "rules"
    select_ms = round((time.perf_counter() - started) * 1000, 1)

    if incident_type is None:   # 임계값 미만 — 맞는 runbook이 없다. 억지로 고르지 않는다
        verdict = {"type": "ReplanCheck", "round": rounds, "is_sufficient": True,
                   "method": method, "score": score, "matched": None,
                   "select_ms": select_ms}
        return {"events": state["events"] + [verdict]}

    # 고른 runbook을 읽어 오라는 새 작업을 추가한다 (research_node가 다음에 실행)
    gap_task = {"id": "task-gap-runbook", "agent": "research", "kind": "runbook",
                "target": incident_type, "status": "pending"}
    verdict = {"type": "ReplanCheck", "round": rounds, "is_sufficient": False,
               "gap_task": gap_task["id"], "target": incident_type,
               "method": method, "score": score, "select_ms": select_ms}
    return {"tasks": state["tasks"] + [gap_task], "replan_rounds": rounds + 1,
            "events": state["events"] + [verdict]}


def _after_replan_check(state: AgentState) -> str:
    """갈림길: 충분하면 analysis로, 아니면 research로 되돌아가 runbook을 읽는다."""
    last = state["events"][-1]
    return "analysis" if last.get("is_sufficient") else "research"
