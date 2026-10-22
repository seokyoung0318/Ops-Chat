"""eval/compare_pipelines.py — single(기존) vs multi(멀티에이전트) 조사 단계 비교.

route → plan → gate 는 질문당 한 번만 실행해 두 방식이 공유한다. 그다음 '조사 단계'만 두 방식으로 각각 돌려 비교한다.
    single : research → replan_check → (runbook 없으면) research → replan_check   (기존 그래프 흐름)
    multi  : research_supervisor (metrics ∥ log → runbook)                        (새 그래프 흐름)
답변 작성·검수는 두 방식이 같은 코드를 쓰므로 제외한다 (LLM 호출이 없어 질문당 수 초면 끝난다).

공정성: 기존 research_node에는 작업당 0.35초의 인위적 지연(병렬 효과 시연용)이 있고 새 에이전트에는 없다.
이 지연이 시간 비교를 왜곡하지 않도록 이 스크립트에서는 research_node의 지연을 제거한다.

측정: runbook 선택 정확도(expect 기준), 조사 단계 시간, 조사 라운드 수, replan 횟수, MCP 호출 수.
실행:  .venv/bin/python eval/compare_pipelines.py [질문 파일]     (Ollama 필요: qwen3:0.6b, bge-m3)
"""
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from agent.agents.research_supervisor import research_supervisor_node   # noqa: E402
from agent.deps import SupervisorDeps                                   # noqa: E402
from agent.mcp_client import MCPClient                                  # noqa: E402
from agent.nodes import research as research_module                    # noqa: E402
from agent.nodes.planning import gate_node, plan_node                   # noqa: E402
from agent.nodes.replan import replan_check_node                        # noqa: E402
from agent.nodes.research import research_node                          # noqa: E402
from agent.nodes.routing import _after_route, route_node                # noqa: E402
from agent.ollama_llm import OllamaFastLLM                              # noqa: E402
from agent.rag import OllamaEmbedder, RunbookRetriever                  # noqa: E402
from agent.retry import with_retry                                      # noqa: E402


async def _no_sleep(_):
    """인위적 지연 제거용 (research_node가 쓰는 asyncio.sleep 대체)."""


# research_node 안의 asyncio.sleep(0.35)만 없앤다. with_retry 등 다른 곳의 asyncio는 그대로.
research_module.asyncio = SimpleNamespace(sleep=_no_sleep, gather=asyncio.gather)


def selected_target(events: list[dict]) -> str:
    """이벤트에서 최종 선택된 runbook 유형을 읽는다 (없으면 'none')."""
    for e in events:
        if e.get("type") == "ReplanCheck" and e.get("target"):
            return e["target"]
    return "none"


async def run_single(base: dict, deps) -> dict:
    state, rounds_research = dict(base), 0
    state.update(await research_node(state, deps=deps)); rounds_research += 1
    state.update(await replan_check_node(state, deps=deps))
    if not state["events"][-1].get("is_sufficient"):      # runbook이 아직 없으면 한 번 더 조사
        state.update(await research_node(state, deps=deps)); rounds_research += 1
        state.update(await replan_check_node(state, deps=deps))
    return {"target": selected_target(state["events"]), "research_rounds": rounds_research,
            "replan_rounds": state.get("replan_rounds", 0)}


async def run_multi(base: dict, deps) -> dict:
    state = dict(base)
    state.update(await research_supervisor_node(state, deps=deps))
    return {"target": selected_target(state["events"]), "research_rounds": 1,
            "replan_rounds": state.get("replan_rounds", 0)}


async def main() -> None:
    mcp = MCPClient()
    await mcp.start()
    try:
        await _run(mcp)
    finally:
        await mcp.stop()


async def _run(mcp) -> None:
    qpath = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "eval" / "queries.json"
    items = json.loads(qpath.read_text(encoding="utf-8"))
    calls = {"n": 0}                                   # MCP 호출 수 세기
    for name in ("call_tool", "read_resource"):
        orig = getattr(mcp, name)
        async def counted(*a, _orig=orig, **k):
            calls["n"] += 1
            return await _orig(*a, **k)
        setattr(mcp, name, counted)
    # 첫 호출 한 번이 일부러 실패하는 데모 장치가 있다 → 미리 한 번 불러 첫 질문이 불리해지지 않게 한다
    await with_retry(mcp.call_tool, "get_monitoring_status", {"system_name": "web-01"})

    fast = OllamaFastLLM(os.environ.get("OLLAMA_FAST_MODEL", "qwen3:0.6b"), usd_per_1k_tokens=0.00015)
    retriever = RunbookRetriever(OllamaEmbedder("bge-m3"), threshold=0.5)
    await retriever.build()
    deps = SupervisorDeps(fast_llm=fast, quality_llm=None, mcp=mcp, session_store=None,
                          version="v2", retriever=retriever)

    results = []
    for item in items:
        base = {"query": item["query"], "thread_id": f"cmp-{item['id']}", "history": [],
                "events": [], "cost_usd": 0.0}
        base.update(await route_node(base, deps=deps))
        path = _after_route(base)
        if path != "plan":      # chat/unknown_system: 두 방식이 같은 경로 → 조사 단계가 없다
            label = "chat" if path == "chat_answer" else path
            results.append({**item, "path": label})
            print(f"[{item['id']:>2}] (조사 없음: {label})")
            continue
        base.update(await plan_node(base, deps=deps))
        base.update(await gate_node(base, deps=deps))
        row = {**item, "path": "plan"}
        for name, fn in (("single", run_single), ("multi", run_multi)):
            calls["n"] = 0
            started = time.perf_counter()
            out = await fn(base, deps)
            out["ms"] = round((time.perf_counter() - started) * 1000, 1)
            out["mcp_calls"] = calls["n"]
            row[name] = out
        results.append(row)
        print(f"[{item['id']:>2}] single={row['single']['target']:<16} {row['single']['ms']:>7}ms "
              f"| multi={row['multi']['target']:<16} {row['multi']['ms']:>7}ms")

    (ROOT / "eval" / f"results_pipeline_{qpath.stem}.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    plan_rows = [r for r in results if r["path"] == "plan"]
    other_rows = [r for r in results if r["path"] != "plan"]
    ok = lambda r, k: r[k]["target"] in r["expect"]
    print(f"\n총 {len(results)}문항 (조사 단계 실행 {len(plan_rows)}, 조사 없이 종료 {len(other_rows)})")
    print("\n## 조사 단계 비교 (인위적 지연 제거, 질문당 1회 측정)")
    print("| 지표 | single | multi |")
    print("|---|---|---|")
    n = len(plan_rows)
    print(f"| runbook 선택 정확도 (조사 실행 문항 기준) | {sum(ok(r,'single') for r in plan_rows)}/{n} "
          f"| {sum(ok(r,'multi') for r in plan_rows)}/{n} |")
    for label, key, fmt in (("평균 조사 단계 시간(ms)", "ms", "{:.1f}"),
                            ("평균 조사 라운드 수", "research_rounds", "{:.2f}"),
                            ("평균 replan 횟수", "replan_rounds", "{:.2f}"),
                            ("평균 MCP 호출 수", "mcp_calls", "{:.2f}")):
        vals = {k: [r[k][key] for r in plan_rows] for k in ("single", "multi")}
        print(f"| {label} | {fmt.format(statistics.mean(vals['single']))} | {fmt.format(statistics.mean(vals['multi']))} |")
    diff = [(r["id"], r["single"]["target"], r["multi"]["target"]) for r in plan_rows
            if r["single"]["target"] != r["multi"]["target"]]
    print(f"\n두 방식의 선택이 다른 질문: {diff or '없음'}")
    print(f"single만 오답: {[r['id'] for r in plan_rows if ok(r,'multi') and not ok(r,'single')]}"
          f" / multi만 오답: {[r['id'] for r in plan_rows if ok(r,'single') and not ok(r,'multi')]}")


if __name__ == "__main__":
    asyncio.run(main())
