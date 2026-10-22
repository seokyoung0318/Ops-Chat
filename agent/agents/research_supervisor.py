"""agent/agents/research_supervisor.py — 조사 총괄(LangGraph 서브그래프): 하위 에이전트들을 지휘한다.

서브그래프 구조:
    prepare ──(할 일 없음)──▶ END
       ├──▶ metrics ─┐   ← 병렬 분기(서로 기다리지 않음)
       └──▶ log ─────┴─▶ merge ─▶ runbook ─▶ finish ─▶ END
metrics/log/runbook 노드는 각각 자기 서브그래프(metrics_agent 등)를 실행한다 → 그래프 안의 그래프.
runbook은 수치를 본 뒤 고르므로 기존 '재계획 루프(replan_check)'가 필요 없다.
PIPELINE=multi일 때 research+replan_check 대신 부모 그래프에 꽂힌다.

병렬 노드(metrics, log)는 서로 다른 키에만 쓴다 → 값을 합치는 규칙(reducer) 없이도 충돌하지 않는다.
"""
import time
from functools import partial
from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph
from langsmith import traceable

from . import log_agent, metrics_agent, runbook_agent
from ..deps import SupervisorDeps
from ..state import AgentState


class ResearchState(TypedDict, total=False):
    # 입력(부모 AgentState에서 복사)
    query: str
    tasks: list[dict]
    collected: list[dict]
    events: list[dict]
    retry_count: int
    # 내부 작업용
    systems: list[str]
    started: float
    skipped: bool
    metrics_items: list[dict]
    metrics_retries: int
    log_items: list[dict]
    log_retries: int
    runbook: dict
    # 출력
    parallel_elapsed: float


async def prepare_node(state: ResearchState) -> dict:
    """아직 조사 안 한 monitoring 작업에서 조사 대상 시스템을 뽑는다. 없으면 건너뛴다."""
    pending = [t for t in state["tasks"] if t["agent"] == "research"
               and t["status"] == "pending" and t["kind"] == "monitoring"]
    if not pending:
        return {"skipped": True, "events": state["events"] +
                [{"type": "ResearchSkipped", "reason": "pending research task 0개"}]}
    return {"skipped": False, "started": time.perf_counter(),
            "systems": list(dict.fromkeys(t["target"] for t in pending))}


def _after_prepare(state: ResearchState):
    # 갈림길: 건너뛰면 END, 아니면 metrics와 log를 동시에 시작(리스트 = 병렬 분기)
    return END if state["skipped"] else ["metrics", "log"]


async def metrics_node(state: ResearchState, deps) -> dict:
    items, retries = await metrics_agent.run(state["systems"], deps)
    return {"metrics_items": items, "metrics_retries": retries}


async def log_node(state: ResearchState, deps) -> dict:
    items, retries = await log_agent.run(state["systems"], deps)
    return {"log_items": items, "log_retries": retries}


async def merge_node(state: ResearchState) -> dict:
    """병렬로 끝난 두 결과를 합치고 기록을 남긴다 (metrics·log 둘 다 끝나야 실행됨)."""
    elapsed = round(time.perf_counter() - state["started"], 2)
    events = list(state["events"])
    for t in state["tasks"]:
        if t["agent"] == "research" and t["status"] == "pending" and t["kind"] == "monitoring":
            events.append({"type": "TaskCompleted", "id": t["id"], "source": "monitoring",
                           "target": t["target"], "retries": 0})
    events.append({"type": "AgentCompleted", "agent": "metrics_agent",
                   "items": len(state["metrics_items"])})
    events.append({"type": "AgentCompleted", "agent": "log_agent",
                   "items": len(state["log_items"])})
    return {"collected": list(state.get("collected", [])) + state["metrics_items"] + state["log_items"],
            "parallel_elapsed": elapsed, "events": events}


async def runbook_node(state: ResearchState, deps) -> dict:
    return {"runbook": await runbook_agent.run(state["query"], state["collected"], deps)}


async def finish_node(state: ResearchState) -> dict:
    """runbook 결과를 반영하고 작업을 완료 처리한다."""
    rb = state["runbook"]
    collected, events = list(state["collected"]), list(state["events"])
    verdict = {"type": "ReplanCheck", "round": 0, "is_sufficient": True,
               "method": rb["method"], "score": rb["score"], "select_ms": rb["select_ms"]}
    if rb["incident_type"] is None:
        verdict["matched"] = None   # finalize_node가 "맞는 매뉴얼 없음" 문구를 붙이는 신호
    else:
        collected.append({"source": "runbook", "data": rb["data"]})
        verdict["target"] = rb["incident_type"]
        events.append({"type": "TaskCompleted", "id": "task-runbook", "source": "runbook",
                       "target": rb["incident_type"], "retries": 0})
    events.append({"type": "AgentCompleted", "agent": "runbook_agent",
                   "items": 1 if rb["data"] else 0})
    events.append(verdict)
    tasks = [dict(t, status="done") if (t["agent"] == "research" and t["status"] == "pending"
                                        and t["kind"] == "monitoring") else dict(t)
             for t in state["tasks"]]
    return {"tasks": tasks, "collected": collected, "events": events}


def build_research_graph(deps):
    g = StateGraph(ResearchState)
    g.add_node("prepare", prepare_node)
    g.add_node("metrics", partial(metrics_node, deps=deps))
    g.add_node("log", partial(log_node, deps=deps))
    g.add_node("merge", merge_node)
    g.add_node("runbook", partial(runbook_node, deps=deps))
    g.add_node("finish", finish_node)
    g.set_entry_point("prepare")
    g.add_conditional_edges("prepare", _after_prepare, ["metrics", "log", END])   # 도착지를 알려야 그림에도 표시됨
    g.add_edge(["metrics", "log"], "merge")   # 둘 다 끝나야 merge 실행(합류)
    g.add_edge("merge", "runbook")
    g.add_edge("runbook", "finish")
    g.add_edge("finish", END)
    return g.compile()


@traceable(name="research_supervisor")
async def research_supervisor_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """부모 그래프용 어댑터: 부모 상태 → 총괄 서브그래프 입력, 결과 → 부모 상태 갱신."""
    out = await build_research_graph(deps).ainvoke({
        "query": state["query"], "tasks": state["tasks"],
        "collected": state.get("collected", []), "events": state["events"],
        "retry_count": state.get("retry_count", 0)})
    if out.get("skipped"):
        return {"events": out["events"]}
    return {"tasks": out["tasks"], "collected": out["collected"], "events": out["events"],
            "retry_count": state.get("retry_count", 0)
                           + out["metrics_retries"] + out["log_retries"],
            "parallel_elapsed": out["parallel_elapsed"]}
