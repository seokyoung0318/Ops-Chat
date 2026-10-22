"""tests/test_agents.py — 멀티에이전트 파이프라인과 그래프 전체(build_graph) 통합 테스트.

진짜 MCP·Ollama 없이 돌도록 가짜 MCP와 가짜 임베더/AI(fake_llm)를 주입한다(의존성 주입).
"""
import asyncio

from agent.agents import log_agent, metrics_agent, runbook_agent
from agent.deps import SupervisorDeps
from agent.fake_llm import FastLLM, QualityLLM
from agent.graph import build_graph


class FakeMCP:
    """호출 기록을 남기는 가짜 MCP 클라이언트."""

    def __init__(self):
        self.calls = []

    async def call_tool(self, name, args):
        self.calls.append((name, args["system_name"]))
        if name == "get_recent_logs":
            return {"system_name": args["system_name"], "lines": ["ERROR slow query"]}
        return {"system_name": args["system_name"], "status": "degraded",
                "cpu_percent": 90.0, "memory_percent": 50.0, "alerts": ["CPU 91%"]}

    async def find_resource_template(self, name):
        return "ops", "runbook://incident-response/{incident_type}"

    async def read_resource(self, uri, server=None):
        return "# CPU 급증\n1. 확인\n2. 프로세스 점검\n3. 조치"

    async def find_prompt(self, name):
        return "ops"

    async def get_prompt(self, name, args, server=None):
        return "표준 절차"


class FakeRetriever:
    """항상 정해진 결과(또는 매칭 없음)를 돌려주는 가짜 검색기."""

    def __init__(self, incident_type="cpu-spike"):
        self.incident_type = incident_type

    async def search(self, text):
        return {"incident_type": self.incident_type, "score": 0.9, "ranked": []}


class MemoryStore:
    pass


def make_deps(retriever=None):
    return SupervisorDeps(fast_llm=FastLLM("fast", 0.0), quality_llm=QualityLLM("quality", 0.0),
                          mcp=FakeMCP(), session_store=MemoryStore(), version="v2",
                          retriever=retriever)


def run_graph(deps, pipeline, query):
    graph = build_graph(deps, pipeline=pipeline)
    return asyncio.run(graph.ainvoke({"query": query, "thread_id": "t", "history": [],
                                      "events": [], "cost_usd": 0.0}))


# 메트릭 에이전트는 시스템마다 상태를 한 번씩 조회한다
def test_metrics_agent_collects_each_system():
    deps = make_deps()
    items, retries = asyncio.run(metrics_agent.run(["auth-service", "web-01"], deps))
    assert [i["source"] for i in items] == ["monitoring", "monitoring"]
    assert retries == 0


# 로그 에이전트는 log 출처로 수집한다
def test_log_agent_collects_logs():
    items, _ = asyncio.run(log_agent.run(["auth-service"], make_deps()))
    assert items[0]["source"] == "log"
    assert items[0]["data"]["lines"] == ["ERROR slow query"]


# 런북 에이전트는 검색기가 고른 유형의 문서를 읽어 온다
def test_runbook_agent_reads_selected_runbook():
    out = asyncio.run(runbook_agent.run("CPU 급증", [], make_deps(FakeRetriever("cpu-spike"))))
    assert out["incident_type"] == "cpu-spike"
    assert "CPU 급증" in out["data"]


# 맞는 매뉴얼이 없으면(임계값 미만) 문서를 읽지 않는다
def test_runbook_agent_skips_when_no_match():
    out = asyncio.run(runbook_agent.run("점심 메뉴", [], make_deps(FakeRetriever(None))))
    assert out["incident_type"] is None and out["data"] is None


# multi: 그래프 전체가 끝까지 돌고, 메트릭·로그·런북 에이전트가 모두 기록된다
def test_multi_pipeline_runs_all_agents():
    deps = make_deps(FakeRetriever("cpu-spike"))
    result = run_graph(deps, "multi", "auth-service 장애 진단해줘")
    agents = [e["agent"] for e in result["events"] if e["type"] == "AgentCompleted"]
    assert agents == ["metrics_agent", "log_agent", "runbook_agent"]
    assert {n for n, _ in deps.mcp.calls} == {"get_monitoring_status", "get_recent_logs"}
    assert result["final"]
    assert result.get("replan_rounds", 0) == 0     # 재계획 루프가 사라졌다


# multi: 맞는 매뉴얼이 없으면 안내 문구가 붙는다
def test_multi_pipeline_notes_missing_runbook():
    result = run_graph(make_deps(FakeRetriever(None)), "multi", "auth-service 장애 진단해줘")
    assert "대응 매뉴얼을 찾지 못해" in result["final"]


# single(기존 방식)도 build_graph로 끝까지 돌고 로그 에이전트는 쓰지 않는다
def test_single_pipeline_still_works():
    deps = make_deps(FakeRetriever("cpu-spike"))
    result = run_graph(deps, "single", "auth-service 장애 진단해줘")
    assert result["final"]
    assert all(n != "get_recent_logs" for n, _ in deps.mcp.calls)


# 런북 서브그래프: 매칭 없으면 read 노드를 거치지 않는다(분기) / 있으면 read까지 간다
def test_runbook_subgraph_branches_on_match():
    from agent.agents.runbook_agent import build_runbook_graph
    deps = make_deps(FakeRetriever(None))
    graph = build_runbook_graph(deps)
    nodes = set(graph.get_graph().nodes)
    assert {"select", "read"} <= nodes            # 서브그래프에 노드 2개가 실제로 있다
    out = asyncio.run(graph.ainvoke({"query": "x", "collected": []}))
    assert out.get("data") is None
    out = asyncio.run(build_runbook_graph(make_deps(FakeRetriever("cpu-spike")))
                      .ainvoke({"query": "x", "collected": []}))
    assert "CPU 급증" in out["data"]


# 총괄 서브그래프: 판단(decide) 뒤에 metrics·log가 갈라져 merge에서 합쳐진다
def test_supervisor_subgraph_structure():
    from agent.agents.research_supervisor import build_research_graph
    g = build_research_graph(make_deps()).get_graph()
    assert {"prepare", "decide", "metrics", "log", "merge", "runbook", "finish"} <= set(g.nodes)
    edges = {(e.source, e.target) for e in g.edges}
    assert {("prepare", "decide"), ("decide", "metrics"), ("decide", "log"),
            ("metrics", "merge"), ("log", "merge")} <= edges


# 총괄: 조사할 monitoring 작업이 없으면 에이전트를 부르지 않고 건너뛴다
def test_supervisor_skips_when_no_pending_tasks():
    from agent.agents.research_supervisor import research_supervisor_node
    deps = make_deps(FakeRetriever("cpu-spike"))
    state = {"query": "q", "tasks": [], "collected": [], "events": []}
    out = asyncio.run(research_supervisor_node(state, deps))
    assert out["events"][-1]["type"] == "ResearchSkipped"
    assert deps.mcp.calls == []


# 총괄: 작업이 완료 처리되고 재시도 횟수·병렬 소요시간이 부모 상태로 돌아간다
def test_supervisor_marks_tasks_done_and_reports_timing():
    from agent.agents.research_supervisor import research_supervisor_node
    deps = make_deps(FakeRetriever("cpu-spike"))
    task = {"id": "task-0", "agent": "research", "kind": "monitoring",
            "target": "auth-service", "status": "pending"}
    out = asyncio.run(research_supervisor_node(
        {"query": "q", "tasks": [task], "collected": [], "events": []}, deps))
    assert out["tasks"][0]["status"] == "done"
    assert out["retry_count"] == 0 and out["parallel_elapsed"] >= 0
    assert {c["source"] for c in out["collected"]} == {"monitoring", "log", "runbook"}


# ---------- 총괄의 판단(어떤 에이전트를 부를지) ----------

# 장애 원인을 묻는 질문이면 세 에이전트를 모두 부른다
def test_supervisor_calls_all_agents_for_troubleshooting_question():
    deps = make_deps(FakeRetriever("cpu-spike"))
    result = run_graph(deps, "multi", "auth-service 로그인 응답이 느려요, 원인 확인해줘")
    decided = next(e for e in result["events"] if e["type"] == "AgentsDecided")
    assert decided["agents"] == ["metrics", "log", "runbook"]
    assert {n for n, _ in deps.mcp.calls} == {"get_monitoring_status", "get_recent_logs"}


# 현황만 묻는 질문이면 로그·매뉴얼 에이전트를 부르지 않는다 (MCP 호출 수가 줄어든다)
def test_supervisor_skips_log_and_runbook_for_status_only_question():
    deps = make_deps(FakeRetriever("cpu-spike"))
    result = run_graph(deps, "multi", "web-01 현재 상태 알려줘")
    decided = next(e for e in result["events"] if e["type"] == "AgentsDecided")
    assert decided["agents"] == ["metrics"]
    assert [n for n, _ in deps.mcp.calls] == ["get_monitoring_status"]      # 로그 조회 호출이 없다
    skipped = [e["agent"] for e in result["events"] if e["type"] == "AgentSkipped"]
    assert skipped == ["log_agent", "runbook_agent"]


# 매뉴얼을 부르지 않기로 했으면 "매뉴얼을 찾지 못했다"는 안내도 붙이지 않는다
def test_no_missing_runbook_note_when_runbook_agent_was_skipped():
    result = run_graph(make_deps(FakeRetriever(None)), "multi", "web-01 현재 상태 알려줘")
    assert "대응 매뉴얼을 찾지 못해" not in result["final"]


# 판단용 AI 호출 비용이 전체 비용(cost_usd)에 합산된다
def test_decision_cost_is_added_to_total_cost():
    deps = make_deps(FakeRetriever("cpu-spike"))
    deps.fast_llm.usd_per_1k = 1000.0           # 비용이 눈에 띄게 큰 가짜 단가
    result = run_graph(deps, "multi", "auth-service 장애 진단해줘")
    assert result["cost_usd"] > 0
