"""agent/agents/log_agent.py — 로그 담당 에이전트(LangGraph 서브그래프): 최근 로그를 MCP로 조회한다.

서브그래프:  fetch → END
"""
import asyncio
from functools import partial
from typing import TypedDict

from langgraph.graph import END, StateGraph
from langsmith import traceable

from ..retry import with_retry


class LogState(TypedDict, total=False):
    systems: list[str]
    limit: int              # 시스템당 가져올 로그 줄 수
    items: list[dict]       # 출력: [{"source": "log", "data": {...}}]
    retries: int


async def fetch_node(state: LogState, deps) -> dict:
    async def one(name: str):
        data, retries = await with_retry(deps.mcp.call_tool, "get_recent_logs",
                                         {"system_name": name, "limit": state["limit"]})
        return {"source": "log", "data": data}, retries
    results = await asyncio.gather(*(one(s) for s in state["systems"]))
    return {"items": [r for r, _ in results], "retries": sum(n for _, n in results)}


def build_log_graph(deps):
    g = StateGraph(LogState)
    g.add_node("fetch", partial(fetch_node, deps=deps))
    g.set_entry_point("fetch")
    g.add_edge("fetch", END)
    return g.compile()


@traceable(name="log_agent")
async def run(systems: list[str], deps, limit: int = 5) -> tuple[list[dict], int]:
    out = await build_log_graph(deps).ainvoke({"systems": systems, "limit": limit})
    return out["items"], out["retries"]
