"""v2 Supervisor — 실제 langgraph.StateGraph (Wave 4·5·6·7·8·10b·15 통합).

route → (chat 직행 | incident 파이프라인)
incident: plan(MCP Prompt 절차 반영) → gate(권위 게이트) → research(가드+병렬+재시도)
          → replan_check(부족 시 gap task 후 재조사) → analysis(needs_analysis=True일 때만
          실제 실행) → write → validate(반려 시 재작성) → finalize

모든 노드는 SupervisorDeps를 functools.partial로 주입받는 순수 함수다(Wave 13).
각 노드는 @traceable로 LangSmith에 계층 트리로 기록된다.
"""
import asyncio
import json
import os
import re
import time
from functools import partial
from pathlib import Path
from typing import Any, TypedDict

from langgraph.config import get_stream_writer
from langgraph.graph import END, StateGraph
from langsmith import traceable

from .deps import SupervisorDeps
from .retry import with_retry


def _load_known_systems() -> set[str]:
    """ollama_llm.py/openai_llm.py와 동일한 소스(data/monitoring.json)에서
    시스템 목록을 읽는다 — plan_node가 MCP Prompt에 넘길 system_name을
    쿼리에서 멤버십 매칭으로 뽑아낼 때 쓴다."""
    path = Path(__file__).resolve().parent.parent / "data" / "monitoring.json"
    try:
        return set(json.loads(path.read_text()).keys())
    except (OSError, json.JSONDecodeError):
        return {"auth-service", "web-01"}


KNOWN_SYSTEMS = _load_known_systems()

# 개선 2 — '이름-service' 또는 '이름-숫자'(예: web-01) 모양의 글자를 시스템 이름 후보로 본다.
# 앞의 (?<!...)는 한글 바로 뒤에 붙은 영어 이름(예: '의billing-service')도 잡기 위한 장치.
_SYSTEM_RE = re.compile(
    r"(?<![A-Za-z0-9-])[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*-(?:service|\d+)", re.I)


def _mentioned_systems(query: str) -> list[str]:
    """질문에 언급된 시스템 이름 후보를 뽑는다 (예: 'billing-service', 'web-01').
    'auth service'처럼 하이픈 대신 공백으로 쓴 경우도 'auth-service'로 정규화한다."""
    normalized = re.sub(r"([A-Za-z0-9]+)\s+service", r"\1-service", query, flags=re.I)
    found = [m.group(0).lower() for m in _SYSTEM_RE.finditer(normalized)]
    return list(dict.fromkeys(found))   # 중복 제거, 순서 유지


def _split_systems(query: str) -> tuple[list[str], list[str]]:
    """질문에 언급된 시스템을 (아는 시스템, 모르는 시스템)으로 나눈다."""
    mentioned = _mentioned_systems(query)
    known = [s for s in mentioned if s in KNOWN_SYSTEMS]
    unknown = [s for s in mentioned if s not in KNOWN_SYSTEMS]
    return known, unknown


def _extract_system_name(query: str) -> str:
    """정규식 대신 실제 KNOWN_SYSTEMS 멤버십 매칭 — MCP Prompt(incident_analysis_
    prompt)의 system_name은 "시스템: X" 한 줄짜리 컨텍스트라 항상 정해진 이름
    중 하나로만 고정한다(여러 개 언급돼도 join하지 않음 — 실제 조사 대상 목록은
    이후 plan()의 tasks가 별도로 결정). 쿼리에서 가장 먼저 등장하는 시스템을
    고르고, 하나도 안 걸리면 가장 흔한 사례인 auth-service로 폴백."""
    matches = [(query.index(s), s) for s in KNOWN_SYSTEMS if s in query]
    return min(matches)[1] if matches else "auth-service"


class AgentState(TypedDict, total=False):
    query: str
    thread_id: str
    history: list[dict]
    route: str
    needs_analysis: bool
    tasks: list[dict]
    gate_removed: int
    collected: list[dict]
    replan_rounds: int
    retry_count: int
    parallel_elapsed: float
    draft: str
    validation_attempts: int
    validation_feedback: str
    final: str
    last_prompt: str
    cost_usd: float
    events: list[dict]


def _cost(state: AgentState, usage: dict) -> float:
    return round(state.get("cost_usd", 0.0) + usage["usd"], 6)


@traceable(name="route_node")
async def route_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """Wave 5 — 모든 쿼리가 무거운 파이프라인을 탈 필요는 없다.

    개선 — 작은 모델이 시스템 이름이 있는 장애 질문을 '잡담'으로 잘못 분류하는 경우
    (예: 'shipping-service 응답이 느려요')를 코드가 보정한다(W6 정신: 모델 판단을 그대로
    믿지 않는다). 시스템 이름이 있으면 장애 경로로 보내야 '모르는 시스템 안내'도 작동한다."""
    result, usage = deps.fast_llm.route(state["query"])
    route, corrected = result["route"], False
    if route == "chat" and _mentioned_systems(state["query"]):
        route, corrected = "incident", True
    event = {"type": "RouteDecided", "route": route}
    if corrected:
        event["corrected"] = True   # 모델은 chat이라 했지만 코드가 incident로 바로잡음
    return {"route": route, "needs_analysis": result["needs_analysis"],
            "cost_usd": _cost(state, usage),
            "events": state.get("events", []) + [event]}


@traceable(name="chat_answer_node")
async def chat_answer_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """Wave 5 direct 경로 — 히스토리 기반 응답 (Wave 12 세션 증명 지점).

    토큰 단위 스트리밍 — get_stream_writer()는 /chat/stream처럼 custom 모드로 소비될
    때만 실제로 전송되고, /chat(ainvoke)처럼 스트리밍하지 않는 호출에서는 자동으로
    no-op이 된다."""
    writer = get_stream_writer()
    reply, usage = await deps.fast_llm.chat(
        state["query"], state.get("history", []),
        on_token=lambda piece: writer({"type": "AnswerToken", "delta": piece}))
    return {"final": reply, "last_prompt": usage.get("prompt"),
            "cost_usd": _cost(state, usage),
            "events": state["events"] + [{"type": "Finalize", "pipeline": "chat-direct"}]}


@traceable(name="plan_node")
async def plan_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """Wave 4 — Plan/Task 분해. Wave 2의 MCP Prompt가 표준 절차를 깔아준다.

    resource와 마찬가지로 이름을 어느 서버가 들고 있는지 미리 가정하지 않고,
    find_prompt()로 연결된 서버들을 먼저 조회해 찾은 뒤에만 get_prompt를 보낸다."""
    prompt_server = await deps.mcp.find_prompt("incident_analysis_prompt")
    procedure = await deps.mcp.get_prompt(
        "incident_analysis_prompt",
        {"system_name": _extract_system_name(state["query"]), "symptom": state["query"]},
        server=prompt_server,
    )
    result, usage = deps.fast_llm.plan(state["query"], procedure)
    targets = [t["target"] for t in result["tasks"]
               if t["agent"] == "research" and t.get("target")]
    event = {"type": "PlanCreated", "task_count": len(result["tasks"]),
             "targets": targets}
    return {"tasks": result["tasks"], "needs_analysis": result["needs_analysis"],
            "cost_usd": _cost(state, usage), "events": state["events"] + [event]}


@traceable(name="gate_node")
async def gate_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """Wave 6 — 권위 게이트. needs_analysis=False인데 섞여 들어온 analysis task를
    프롬프트가 아니라 코드로 강제 제거한다."""
    tasks = state["tasks"]
    if not state.get("needs_analysis", False):
        kept = [t for t in tasks if t["agent"] != "analysis"]
        removed = len(tasks) - len(kept)
    else:
        kept, removed = tasks, 0
    event = {"type": "GateApplied", "removed_analysis_tasks": removed}
    return {"tasks": kept, "gate_removed": removed,
            "events": state["events"] + [event]}


@traceable(name="research_node")
async def research_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """Wave 15 가드 + Wave 10b 병렬 + Wave 9 재시도 + Wave 2 Tool/Resource 실호출."""
    tasks = state["tasks"]
    research_indices = [i for i, t in enumerate(tasks)
                        if t["agent"] == "research" and t["status"] == "pending"]
    # Wave 15 — 객체가 아니라 '실행할 목록'을 검사한다 (not research_agent 버그의 수정판)
    if not research_indices:
        return {"events": state["events"] +
                [{"type": "ResearchSkipped", "reason": "pending research task 0개"}]}

    retry_total = state.get("retry_count", 0)

    # URI를 코드에 하드코딩하지 않는다. 여러 MCP 서버가 연결돼 있고 그중 어느 서버가
    # "get_incident_runbook" resource를 제공하는지 모른다고 가정하고, 먼저 연결된
    # 서버들을 조회(list)해 유효한 서버를 찾은 뒤에만 그 서버로 요청한다.
    needs_runbook = any(tasks[i]["kind"] != "monitoring" for i in research_indices)
    runbook_server = runbook_uri_template = None
    if needs_runbook:
        runbook_server, runbook_uri_template = await deps.mcp.find_resource_template(
            "get_incident_runbook")

    async def run_one(idx: int) -> dict:
        task = tasks[idx]
        await asyncio.sleep(0.35)   # 태스크당 고정 지연 — 병렬 효과를 실측하기 위함
        if task["kind"] == "monitoring":
            data, retries = await with_retry(
                deps.mcp.call_tool, "get_monitoring_status",
                {"system_name": task["target"]})
            return {"idx": idx, "source": "monitoring", "data": data, "retries": retries}
        uri = runbook_uri_template.format(incident_type=task["target"])
        data = await deps.mcp.read_resource(uri, server=runbook_server)
        return {"idx": idx, "source": "runbook", "data": data, "retries": 0}

    started = time.perf_counter()
    results = await asyncio.gather(*(run_one(i) for i in research_indices))
    elapsed = round(time.perf_counter() - started, 2)

    new_tasks = [dict(t) for t in tasks]
    collected = list(state.get("collected", []))
    events = list(state["events"])
    for r in results:
        new_tasks[r["idx"]]["status"] = "done"
        collected.append({"source": r["source"], "data": r["data"]})
        retry_total += r["retries"]
        events.append({"type": "TaskCompleted", "id": new_tasks[r["idx"]]["id"],
                       "source": r["source"], "target": new_tasks[r["idx"]]["target"],
                       "retries": r["retries"]})
    return {"tasks": new_tasks, "collected": collected, "retry_count": retry_total,
            "parallel_elapsed": elapsed, "events": events}


# 수집된 모니터링 결과(상태·알림 문구)를 보고 어떤 runbook이 맞는지 고른다. LLM에게
# 다시 묻는 대신 코드 레벨 규칙으로 판단한다 — gate(Wave 6)·replan(Wave 7)과 같은 설계
# 원칙: 모델의 판단을 그대로 믿지 않고, 실측 데이터로 검증 가능한 결정은 코드가 내린다.
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
    text = " ".join(
        f"{c['data'].get('status', '')} " + " ".join(c["data"].get("alerts", []))
        for c in collected if c.get("source") == "monitoring"
    ).lower()
    for keyword, incident_type in _INCIDENT_TYPE_RULES:
        if keyword in text:
            return incident_type
    return "db-down"   # 매칭되는 증상이 없으면 가장 일반적인 장애 대응 절차로 폴백


# 개선 1 — RAG 검색 입력 (eval/run_eval.py 23문항 비교 결과로 기본값 결정).
#   'auto'(기본)    : 질문에 아는 시스템이 명시된 때만 질문 + 그 시스템의 알림, 아니면 질문만 (19/23)
#   'query'         : 질문만 (17/23)
#   'query+alerts'  : 항상 질문 + 알림 (14/23) — 시스템을 안 밝힌 질문에서 기본 조회 대상
#                     (auth-service)의 알림이 검색을 high-latency 쪽으로 오염시킴
RAG_INPUT = os.environ.get("RAG_INPUT", "auto")


def _search_text(state: AgentState) -> str:
    if RAG_INPUT == "query":
        return state["query"]
    if RAG_INPUT == "auto":   # 질문에 아는 시스템이 명시된 경우에만 그 시스템의 알림을 함께 검색
        known, _ = _split_systems(state["query"])
        if not known:   # 시스템을 안 밝혔다면 기본 조회 대상(auth-service)의 알림이 검색을 오염시킴
            return state["query"]
    monitoring = " ".join(
        f"{c['data'].get('status', '')} " + " ".join(c["data"].get("alerts", []))
        for c in state.get("collected", []) if c.get("source") == "monitoring")
    return f"{state['query']} {monitoring}".strip()


@traceable(name="replan_check_node")
async def replan_check_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """Wave 7 — 1차 수집 결과 평가. runbook이 없으면 gap task만 추가해 재조사.

    개선 1 — 어떤 runbook을 가져올지를 키워드 규칙 대신 의미 검색(RAG)으로 고른다.
    deps.retriever가 None이면(CLASSIFIER=rules) 기존 키워드 규칙으로 동작한다.
    select_ms — runbook 선택에 걸린 시간(밀리초). 규칙/RAG 비용 비교용."""
    has_runbook = any(c["source"] == "runbook" for c in state.get("collected", []))
    rounds = state.get("replan_rounds", 0)
    if has_runbook or rounds >= 1:
        verdict = {"type": "ReplanCheck", "round": rounds, "is_sufficient": True}
        return {"events": state["events"] + [verdict]}

    started = time.perf_counter()   # 선택 시간 측정 시작
    if deps.retriever is not None:
        match = await deps.retriever.search(_search_text(state))
        incident_type, score, method = match["incident_type"], match["score"], "rag"
    else:
        incident_type = _classify_incident_type(state.get("collected", []))
        score, method = None, "rules"
    select_ms = round((time.perf_counter() - started) * 1000, 1)

    if incident_type is None:   # 임계값 미만 — 맞는 runbook이 없다. 억지로 고르지 않는다
        verdict = {"type": "ReplanCheck", "round": rounds, "is_sufficient": True,
                   "method": method, "score": score, "matched": None,
                   "select_ms": select_ms}
        return {"events": state["events"] + [verdict]}

    gap_task = {"id": "task-gap-runbook", "agent": "research", "kind": "runbook",
                "target": incident_type, "status": "pending"}
    verdict = {"type": "ReplanCheck", "round": rounds, "is_sufficient": False,
               "gap_task": gap_task["id"], "target": incident_type,
               "method": method, "score": score, "select_ms": select_ms}
    return {"tasks": state["tasks"] + [gap_task], "replan_rounds": rounds + 1,
            "events": state["events"] + [verdict]}




@traceable(name="analysis_node")
async def analysis_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """Wave 6 보완 — needs_analysis=True가 정당한 경우(모델의 자기모순이 아니라
    실제로 패턴 비교가 필요하다고 판단한 경우)를 위한 실행 경로. gate가 살려둔
    agent=='analysis' task가 있을 때만 수집된 monitoring 결과들을 비교 분석한다."""
    tasks = state["tasks"]
    pending = [t for t in tasks if t["agent"] == "analysis" and t["status"] == "pending"]
    if not pending:
        return {"events": state["events"] +
                [{"type": "AnalysisSkipped", "reason": "analysis task 0개"}]}
    summary, usage = deps.fast_llm.analyze(state.get("collected", []))
    new_tasks = [dict(t) for t in tasks]
    for t in new_tasks:
        if t["agent"] == "analysis" and t["status"] == "pending":
            t["status"] = "done"
    collected = state.get("collected", []) + [{"source": "analysis", "data": summary}]
    event = {"type": "AnalysisCompleted", "length": len(summary)}
    return {"tasks": new_tasks, "collected": collected,
            "cost_usd": _cost(state, usage), "events": state["events"] + [event]}


@traceable(name="write_node")
async def write_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """Wave 8/10a — 고품질 모델로 초안 작성 (1차는 의도적 저품질).

    토큰마다 attempt 번호를 같이 실어 보낸다 — validate가 반려해 재작성(attempt 증가)
    될 때 프론트가 새 말풍선으로 끊어서 보여줄 수 있게 하기 위함(Wave 8 재작성 루프를
    그대로 노출)."""
    attempt = state.get("validation_attempts", 0) + 1
    writer = get_stream_writer()
    draft, usage = await deps.quality_llm.write(
        state["query"], state.get("collected", []),
        attempt, state.get("validation_feedback"),
        on_token=lambda piece: writer(
            {"type": "AnswerToken", "attempt": attempt, "delta": piece}))
    return {"draft": draft, "last_prompt": usage.get("prompt"),
            "cost_usd": _cost(state, usage),
            "events": state["events"] + [{"type": "DraftWritten", "attempt": attempt,
                                          "length": len(draft)}]}


@traceable(name="validate_node")
async def validate_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """Wave 8 — 코드 기준 검증: 30자 이상 + 절차 번호 포함이어야 합격."""
    draft = state["draft"]
    attempts = state.get("validation_attempts", 0) + 1
    ok = len(draft) >= 30 and "1)" in draft
    verdict = "합격" if ok else "불합격"
    if not ok and attempts >= 3:   # 실모델 무한 재작성 방지 — 최대 3회 후 통과 처리
        ok, verdict = True, "합격(최대 시도 도달 — 통과 처리)"
    feedback = None if ok else (
        f"응답이 너무 짧습니다({len(draft)}자, 최소 30자). 절차를 1) 2) 3) 번호로 "
        f"구체적으로 설명하세요.")
    event = {"type": "Validation", "attempt": attempts, "verdict": verdict}
    return {"validation_attempts": attempts, "validation_feedback": feedback,
            "events": state["events"] + [event]}


@traceable(name="unknown_system_node")
async def unknown_system_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """개선 2 — 질문에 '모르는 시스템'만 있으면 auth-service 등으로 몰래 바꿔 조사하지
    않고, 조회할 수 없다고 솔직히 안내한다. LLM·MCP를 호출하지 않으므로 지연·비용이 거의 0."""
    _, unknown = _split_systems(state["query"])
    final = (f"{', '.join(unknown)}은(는) 모니터링 대상 목록에 없어 조회할 수 없습니다.\n"
             f"조회 가능한 시스템: {', '.join(sorted(KNOWN_SYSTEMS))}\n"
             "시스템 이름을 확인한 뒤 다시 질문해 주세요.")
    events = state["events"] + [{"type": "UnknownSystem", "systems": unknown},
                                {"type": "Finalize", "pipeline": "unknown-system"}]
    return {"final": final, "events": events}


@traceable(name="finalize_node")
async def finalize_node(state: AgentState, deps: SupervisorDeps) -> dict:
    final = state["draft"]
    _, unknown = _split_systems(state["query"])
    if unknown:   # 아는 시스템과 모르는 시스템이 섞인 질문 — 모르는 쪽은 조회하지 않았음을 밝힌다
        final += f"\n\n※ {', '.join(unknown)}은(는) 모니터링 대상 목록에 없어 조회하지 않았습니다."
    if any(e.get("type") == "ReplanCheck" and "matched" in e for e in state["events"]):
        final += "\n\n※ 질문과 일치하는 대응 매뉴얼을 찾지 못해, 조회된 수치만으로 안내했습니다."
    return {"final": final,
            "events": state["events"] + [{"type": "Finalize", "pipeline": "incident-v2"}]}


def _after_route(state: AgentState) -> str:
    if state["route"] == "chat":
        return "chat_answer"
    known, unknown = _split_systems(state["query"])
    if unknown and not known:   # 개선 2 — 아는 시스템이 하나도 없으면 바꿔치기하지 않고 안내
        return "unknown_system"
    return "plan"


def _after_replan_check(state: AgentState) -> str:
    last = state["events"][-1]
    return "analysis" if last.get("is_sufficient") else "research"


def _after_validate(state: AgentState) -> str:
    return "finalize" if state.get("validation_feedback") is None else "write"


def build_graph(deps: SupervisorDeps):
    g = StateGraph(AgentState)
    node = lambda fn: partial(fn, deps=deps)   # Wave 13 — 명시적 의존성 주입
    g.add_node("route", node(route_node))
    g.add_node("chat_answer", node(chat_answer_node))
    g.add_node("unknown_system", node(unknown_system_node))   # 개선 2
    g.add_node("plan", node(plan_node))
    g.add_node("gate", node(gate_node))
    g.add_node("research", node(research_node))
    g.add_node("replan_check", node(replan_check_node))
    g.add_node("analysis", node(analysis_node))
    g.add_node("write", node(write_node))
    g.add_node("validate", node(validate_node))
    g.add_node("finalize", node(finalize_node))

    g.set_entry_point("route")
    g.add_conditional_edges("route", _after_route,
                            {"chat_answer": "chat_answer", "plan": "plan",
                             "unknown_system": "unknown_system"})
    g.add_edge("chat_answer", END)
    g.add_edge("unknown_system", END)
    g.add_edge("plan", "gate")
    g.add_edge("gate", "research")
    g.add_edge("research", "replan_check")
    g.add_conditional_edges("replan_check", _after_replan_check,
                            {"analysis": "analysis", "research": "research"})
    g.add_edge("analysis", "write")
    g.add_edge("write", "validate")
    g.add_conditional_edges("validate", _after_validate,
                            {"finalize": "finalize", "write": "write"})
    g.add_edge("finalize", END)
    return g.compile()
