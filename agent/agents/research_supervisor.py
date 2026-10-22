"""agent/agents/research_supervisor.py — 조사 총괄(LangGraph 서브그래프): 질문을 보고 필요한 에이전트만 골라 지휘한다.

서브그래프 구조:
    prepare ──(할 일 없음)──▶ END
       └──▶ decide ← 총괄의 판단: 이 질문에 metrics / log / runbook 중 무엇이 필요한가 (AI가 고름)
              ├──▶ metrics ─┐   ← 병렬 분기(서로 기다리지 않음). 고르지 않은 에이전트는 아무것도 하지 않고 지나간다
              └──▶ log ─────┴─▶ merge ─▶ runbook ─▶ finish ─▶ END
metrics/log/runbook 노드는 각각 자기 서브그래프(metrics_agent 등)를 실행한다 → 그래프 안의 그래프.
runbook은 수치를 본 뒤 고르므로 기존 '재계획 루프(replan_check)'가 필요 없다.
PIPELINE=multi일 때 research+replan_check 대신 부모 그래프에 꽂힌다.

병렬 노드(metrics, log)는 서로 다른 키에만 쓴다 → 값을 합치는 규칙(reducer) 없이도 충돌하지 않는다.
"""
import time
from functools import partial
from typing import TypedDict

from langgraph.graph import END, StateGraph
from langsmith import traceable

from . import log_agent, metrics_agent, runbook_agent
from ..deps import SupervisorDeps
from ..state import AgentState, _cost


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
    agents: list[str]            # 총괄이 고른 에이전트 (decide 노드가 채움)
    decision_usage: dict         # decide의 AI 호출 비용 (부모가 cost_usd에 합산)
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
    return END if state["skipped"] else "decide"


async def decide_node(state: ResearchState, deps) -> dict:
    """총괄의 판단: AI(fast 모델)가 질문을 보고 부를 에이전트를 고른다. 이후 노드는 고른 것만 실행한다."""
    decision, usage = deps.fast_llm.decide_agents(state["query"])
    event = {"type": "AgentsDecided", "agents": decision["agents"],
             "reason": decision["reason"], "source": decision["source"]}
    return {"agents": decision["agents"], "decision_usage": usage,
            "events": state["events"] + [event]}


async def metrics_node(state: ResearchState, deps) -> dict:
    if "metrics" not in state["agents"]:        # 고르지 않았으면 그냥 지나간다 (합류 지점이 기다리지 않게)
        return {"metrics_items": [], "metrics_retries": 0}
    items, retries = await metrics_agent.run(state["systems"], deps)
    return {"metrics_items": items, "metrics_retries": retries}


async def log_node(state: ResearchState, deps) -> dict:
    if "log" not in state["agents"]:
        return {"log_items": [], "log_retries": 0}
    items, retries = await log_agent.run(state["systems"], deps)
    return {"log_items": items, "log_retries": retries}


async def merge_node(state: ResearchState) -> dict:
    """병렬로 끝난 두 결과를 합치고 기록을 남긴다 (metrics·log 둘 다 지나가야 실행됨)."""
    elapsed = round(time.perf_counter() - state["started"], 2)
    events = list(state["events"])
    for t in state["tasks"]:
        if t["agent"] == "research" and t["status"] == "pending" and t["kind"] == "monitoring":
            events.append({"type": "TaskCompleted", "id": t["id"], "source": "monitoring",
                           "target": t["target"], "retries": 0})
    for name, items in (("metrics", state["metrics_items"]), ("log", state["log_items"])):
        if name in state["agents"]:
            events.append({"type": "AgentCompleted", "agent": f"{name}_agent", "items": len(items)})
        else:
            events.append({"type": "AgentSkipped", "agent": f"{name}_agent"})
    return {"collected": list(state.get("collected", [])) + state["metrics_items"] + state["log_items"],
            "parallel_elapsed": elapsed, "events": events}


async def runbook_node(state: ResearchState, deps) -> dict:
    if "runbook" not in state["agents"]:
        return {"runbook": {"skipped": True}}
    return {"runbook": await runbook_agent.run(state["query"], state["collected"], deps)}


async def finish_node(state: ResearchState) -> dict:
    """runbook 결과를 반영하고 작업을 완료 처리한다."""
    rb = state["runbook"]
    collected, events = list(state["collected"]), list(state["events"])
    if rb.get("skipped"):                       # 총괄이 매뉴얼을 부르지 않기로 했다 → '매뉴얼 없음' 안내도 붙이지 않는다
        events.append({"type": "AgentSkipped", "agent": "runbook_agent"})
    else:
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
    g.add_node("decide", partial(decide_node, deps=deps))
    g.add_node("metrics", partial(metrics_node, deps=deps))
    g.add_node("log", partial(log_node, deps=deps))
    g.add_node("merge", merge_node)
    g.add_node("runbook", partial(runbook_node, deps=deps))
    g.add_node("finish", finish_node)
    g.set_entry_point("prepare")
    g.add_conditional_edges("prepare", _after_prepare, ["decide", END])   # 도착지를 알려야 그림에도 표시됨
    g.add_edge("decide", "metrics")           # 판단 뒤 metrics와 log를 동시에 시작
    g.add_edge("decide", "log")
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
            "cost_usd": _cost(state, out["decision_usage"]),
            "parallel_elapsed": out["parallel_elapsed"]}
