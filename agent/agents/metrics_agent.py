"""agent/agents/metrics_agent.py — 메트릭 담당 에이전트(LangGraph 서브그래프): 시스템 상태를 MCP로 조회한다.

서브그래프:  fetch → END   (상태 양식 MetricsState는 부모 AgentState와 별개)
"""
import asyncio
from functools import partial
from typing import TypedDict

from langgraph.graph import END, StateGraph
from langsmith import traceable

from ..retry import with_retry


class MetricsState(TypedDict, total=False):
    systems: list[str]      # 입력: 조회할 시스템 이름들
    items: list[dict]       # 출력: 수집 결과 [{"source": "monitoring", "data": ...}]
    retries: int            # 출력: 재시도 횟수 합


async def fetch_node(state: MetricsState, deps) -> dict:
    async def one(name: str):
        data, retries = await with_retry(deps.mcp.call_tool, "get_monitoring_status",
                                         {"system_name": name})
        return {"source": "monitoring", "data": data}, retries
    results = await asyncio.gather(*(one(s) for s in state["systems"]))
    return {"items": [r for r, _ in results], "retries": sum(n for _, n in results)}


def build_metrics_graph(deps):
    g = StateGraph(MetricsState)
    g.add_node("fetch", partial(fetch_node, deps=deps))   # 의존성 주입(부모와 같은 방식)
    g.set_entry_point("fetch")
    g.add_edge("fetch", END)
    return g.compile()


@traceable(name="metrics_agent")
async def run(systems: list[str], deps) -> tuple[list[dict], int]:
    """서브그래프를 실행해 (수집 결과 목록, 재시도 횟수 합)을 돌려준다."""
    out = await build_metrics_graph(deps).ainvoke({"systems": systems})
    return out["items"], out["retries"]
