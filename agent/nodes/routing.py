"""agent/nodes/routing.py — 질문 분류와 갈래 처리 노드.

route_node(질문 분류와 모델 오분류 보정), chat_answer_node(잡담 응답),
unknown_system_node(모르는 시스템 안내), _after_route(다음 노드를 고르는 갈림길 함수).
graph.py에 있던 것을 분리했다(동작은 그대로).
"""
from langgraph.config import get_stream_writer
from langsmith import traceable

from ..deps import SupervisorDeps
from ..state import AgentState, _cost
from ..systems import KNOWN_SYSTEMS, _mentioned_systems, _split_systems


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


def _after_route(state: AgentState) -> str:
    if state["route"] == "chat":
        return "chat_answer"
    known, unknown = _split_systems(state["query"])
    if unknown and not known:   # 개선 2 — 아는 시스템이 하나도 없으면 바꿔치기하지 않고 안내
        return "unknown_system"
    return "plan"
