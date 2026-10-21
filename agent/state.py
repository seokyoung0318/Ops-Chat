"""agent/state.py — 그래프의 모든 노드가 주고받는 상태(AgentState)와 비용 누적 도우미.

graph.py에 있던 것을 분리했다(동작은 그대로). 노드가 여러 파일로 나뉘어도
모두 이 파일에서 상태 양식을 가져다 쓴다.
"""
from typing import TypedDict


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
