"""agent/agents/runbook_agent.py — 매뉴얼 담당 에이전트(LangGraph 서브그래프).

서브그래프:  select ──(매뉴얼 있음)──▶ read → END
                  └──(없음: 임계값 미만)──▶ END      ← 억지로 읽지 않는 분기

select: RAG(deps.retriever)로 유형 선택, 없으면 예전 키워드 규칙(replan.py 로직 재사용).
read:   MCP Resource로 해당 runbook 본문을 읽는다.
메트릭·로그가 먼저 모여야 하므로 research_supervisor가 마지막에 부른다.
"""
import time
from functools import partial
from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph
from langsmith import traceable
from langsmith.run_helpers import get_current_run_tree

from ..nodes.replan import _classify_incident_type, _search_text


class RunbookState(TypedDict, total=False):
    query: str
    collected: list[dict]
    incident_type: Optional[str]
    score: Optional[float]
    method: str
    select_ms: float
    data: Optional[str]


async def select_node(state: RunbookState, deps) -> dict:
    started = time.perf_counter()
    if deps.retriever is not None:
        match = await deps.retriever.search(_search_text(state))
        incident_type, score, method = match["incident_type"], match["score"], "rag"
    else:
        incident_type = _classify_incident_type(state["collected"])
        score, method = None, "rules"
    return {"incident_type": incident_type, "score": score, "method": method,
            "select_ms": round((time.perf_counter() - started) * 1000, 1)}


async def read_node(state: RunbookState, deps) -> dict:
    server, template = await deps.mcp.find_resource_template("get_incident_runbook")
    data = await deps.mcp.read_resource(
        template.format(incident_type=state["incident_type"]), server=server)
    return {"data": data}


def _after_select(state: RunbookState) -> str:
    return "read" if state.get("incident_type") else "end"


def build_runbook_graph(deps):
    g = StateGraph(RunbookState)
    g.add_node("select", partial(select_node, deps=deps))
    g.add_node("read", partial(read_node, deps=deps))
    g.set_entry_point("select")
    g.add_conditional_edges("select", _after_select, {"read": "read", "end": END})
    g.add_edge("read", END)
    return g.compile()


@traceable(name="runbook_agent")
async def run(query: str, collected: list[dict], deps) -> dict:
    """결과: {"incident_type", "data", "method", "score", "select_ms"} (매칭 없으면 type·data는 None)."""
    out = await build_runbook_graph(deps).ainvoke({"query": query, "collected": collected})
    rt = get_current_run_tree()   # LangSmith 기록에 '무엇을 몇 점으로 골랐는지' 남기기
    if rt is not None:
        rt.metadata.update({"selected_runbook": out.get("incident_type") or "none",
                            "score": out["score"], "select_ms": out["select_ms"],
                            "method": out["method"]})
    return {"incident_type": out.get("incident_type"), "data": out.get("data"),
            "method": out["method"], "score": out["score"], "select_ms": out["select_ms"]}
