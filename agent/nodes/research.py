"""agent/nodes/research.py — 조사 노드 (MCP로 자료 수집).

research_node: 계획(tasks)에 적힌 조사 작업을 실제로 실행한다. 시스템 상태는 MCP Tool로,
runbook 문서는 MCP Resource로 가져오며, 작업들은 동시에(병렬) 실행한다.
graph.py에 있던 것을 분리했다(동작은 그대로).
"""
import asyncio                                   # 여러 작업을 동시에 실행
import time                                      # 걸린 시간 측정

from langsmith import traceable                  # LangSmith 기록용 장식자

from ..deps import SupervisorDeps                # 도구 상자 형식
from ..retry import with_retry                   # 일시적 실패 시 재시도하는 도우미
from ..state import AgentState                   # 공용 메모장 양식


@traceable(name="research_node")
async def research_node(state: AgentState, deps: SupervisorDeps) -> dict:
    """Wave 15 가드 + Wave 10b 병렬 + Wave 9 재시도 + Wave 2 Tool/Resource 실호출."""
    tasks = state["tasks"]                       # plan_node/replan_check_node가 만든 작업 목록
    # ① 지금 해야 할 조사 작업의 번호만 고른다 (research 담당이고 아직 pending인 것)
    research_indices = [i for i, t in enumerate(tasks)
                        if t["agent"] == "research" and t["status"] == "pending"]
    # Wave 15 — 객체가 아니라 '실행할 목록'을 검사한다 (not research_agent 버그의 수정판)
    if not research_indices:                     # 할 일이 하나도 없으면 조사 없이 기록만 남기고 끝
        return {"events": state["events"] +
                [{"type": "ResearchSkipped", "reason": "pending research task 0개"}]}

    retry_total = state.get("retry_count", 0)    # 지금까지 누적된 재시도 횟수

    # ② runbook을 읽을 작업이 있으면, 먼저 MCP에서 "어느 서버가 runbook을 제공하고 주소 형식이
    #    무엇인지" 찾는다. URI를 코드에 박아 두지 않고, 연결된 서버들을 조회해서 찾은 뒤에만 요청한다.
    needs_runbook = any(tasks[i]["kind"] != "monitoring" for i in research_indices)
    runbook_server = runbook_uri_template = None
    if needs_runbook:
        runbook_server, runbook_uri_template = await deps.mcp.find_resource_template(
            "get_incident_runbook")

    # ③ 작업 하나를 실행하는 내부 함수 (아래에서 여러 개를 동시에 돌림)
    async def run_one(idx: int) -> dict:
        task = tasks[idx]
        await asyncio.sleep(0.35)   # 태스크당 고정 지연 — 병렬 효과를 실측하기 위함
        if task["kind"] == "monitoring":         # 시스템 상태 조회 작업이면 → MCP Tool
            data, retries = await with_retry(    # 실패하면 다시 시도
                deps.mcp.call_tool, "get_monitoring_status",
                {"system_name": task["target"]})
            return {"idx": idx, "source": "monitoring", "data": data, "retries": retries}
        # 그 외(runbook 읽기) → MCP Resource. 주소 형식에 장애유형 이름을 끼워 완성
        uri = runbook_uri_template.format(incident_type=task["target"])
        data = await deps.mcp.read_resource(uri, server=runbook_server)
        return {"idx": idx, "source": "runbook", "data": data, "retries": 0}

    started = time.perf_counter()                # 시계 시작
    results = await asyncio.gather(*(run_one(i) for i in research_indices))   # 모든 작업을 동시에 실행
    elapsed = round(time.perf_counter() - started, 2)                         # 전체에 걸린 시간

    # ④ 결과를 메모장 형식으로 정리한다
    new_tasks = [dict(t) for t in tasks]         # 원본을 건드리지 않게 복사
    collected = list(state.get("collected", [])) # 지금까지 모은 자료
    events = list(state["events"])               # 지금까지의 기록
    for r in results:
        new_tasks[r["idx"]]["status"] = "done"                   # 이 작업은 끝났다고 표시
        collected.append({"source": r["source"], "data": r["data"]})   # 가져온 자료 추가
        retry_total += r["retries"]                              # 재시도 횟수 합산
        events.append({"type": "TaskCompleted", "id": new_tasks[r["idx"]]["id"],
                       "source": r["source"], "target": new_tasks[r["idx"]]["target"],
                       "retries": r["retries"]})                 # 화면의 "조회" 줄이 되는 기록
    return {"tasks": new_tasks, "collected": collected, "retry_count": retry_total,
            "parallel_elapsed": elapsed, "events": events}
