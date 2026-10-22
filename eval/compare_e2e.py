"""eval/compare_e2e.py — 답변 작성까지 전부 돌린 single vs multi 전체 응답 비교 (백엔드별).

compare_pipelines.py는 '조사 단계'만 쟀다. 이 스크립트는 route → ... → write → validate → finalize 까지 그래프 전체를
같은 질문으로 single/multi 각각 돌려, 사용자가 실제로 기다리는 시간과 retry·재계획·검수 횟수를 잰다.

실행:  .venv/bin/python eval/compare_e2e.py ollama     # 로컬 qwen3 (무료, 느림)
       .venv/bin/python eval/compare_e2e.py openai     # OpenAI API (과금, 빠름)
결과는 eval/results_e2e_<백엔드>.json 에 저장된다.

주의
- LangSmith 전송은 이 스크립트에서 끈다(40여 번의 기록이 프로젝트에 쌓이지 않게).
- 시스템 첫 호출이 일부러 한 번 실패하는 데모 장치가 있어 측정 전에 예열한다.
- single의 research_node에는 시연용 0.35초 지연이 있다 — 실제 앱과 같은 조건으로 그대로 두었다(전체 응답 수 초~수십 초 대비 작음).
- cost_usd는 글자 수로 어림한 추정치이며 실제 과금이 아니다.
- 질문마다 1회씩 측정한 값이다. LLM 출력은 매번 달라 일반화에는 한계가 있다.
"""
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

os.environ["LANGCHAIN_TRACING_V2"] = "false"   # 이 측정은 LangSmith로 보내지 않는다 (.env보다 먼저 지정)
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from dotenv import load_dotenv                              # noqa: E402
load_dotenv(ROOT / ".env")                                  # 이미 지정된 값은 덮어쓰지 않는다 (override=False)
os.environ["LANGCHAIN_TRACING_V2"] = "false"

from agent.deps import SupervisorDeps                       # noqa: E402
from agent.graph import build_graph                         # noqa: E402
from agent.mcp_client import MCPClient                      # noqa: E402
from agent.rag import OllamaEmbedder, RunbookRetriever      # noqa: E402
from agent.retry import with_retry                          # noqa: E402

# 같은 입력: eval/queries.json의 문항 번호 (장애 질문 8 + 모르는 시스템 1 + 장애와 무관 1)
QUERY_IDS = [1, 3, 4, 6, 9, 13, 14, 16, 18, 21]
WARMUP_ID = 3


def build_llms(backend: str):
    if backend == "ollama":
        from agent.ollama_llm import OllamaFastLLM, OllamaQualityLLM
        return (OllamaFastLLM("qwen3:0.6b", usd_per_1k_tokens=0.00015),
                OllamaQualityLLM("qwen3:8b", usd_per_1k_tokens=0.005))
    from agent.openai_llm import OpenAIFastLLM, OpenAIQualityLLM
    return (OpenAIFastLLM("gpt-4o-mini", usd_per_1k_tokens=0.00015),
            OpenAIQualityLLM("gpt-4o", usd_per_1k_tokens=0.005))


async def run_once(graph, query: str) -> dict:
    started = time.perf_counter()
    out = await graph.ainvoke({"query": query, "thread_id": "e2e", "history": [],
                               "events": [], "cost_usd": 0.0})
    seconds = round(time.perf_counter() - started, 2)
    runbook = next((e["target"] for e in out["events"]
                    if e.get("type") == "ReplanCheck" and e.get("target")), "none")
    return {"seconds": seconds, "route": out.get("route"),
            "retry_count": out.get("retry_count", 0),
            "replan_rounds": out.get("replan_rounds", 0),
            "validation_attempts": out.get("validation_attempts", 0),
            "cost_usd_est": out.get("cost_usd", 0.0), "runbook": runbook,
            "log_collected": any(c.get("source") == "log" for c in out.get("collected", [])),
            "final_len": len(out.get("final", ""))}


async def main(backend: str) -> None:
    items = {i["id"]: i for i in json.loads((ROOT / "eval" / "queries.json").read_text(encoding="utf-8"))}
    mcp = MCPClient()
    await mcp.start()
    try:
        await with_retry(mcp.call_tool, "get_monitoring_status", {"system_name": "web-01"})   # 첫 호출 실패 데모 예열
        retriever = RunbookRetriever(OllamaEmbedder("bge-m3"), threshold=0.5)
        await retriever.build()
        fast, quality = build_llms(backend)
        deps = SupervisorDeps(fast_llm=fast, quality_llm=quality, mcp=mcp, session_store=None,
                              version="v2", retriever=retriever)
        graphs = {p: build_graph(deps, pipeline=p) for p in ("single", "multi")}

        print(f"[{backend}] 예열 중 (결과에 포함하지 않음)...", flush=True)
        await run_once(graphs["single"], items[WARMUP_ID]["query"])

        results = []
        for qid in QUERY_IDS:
            q = items[qid]["query"]
            row = {"id": qid, "query": q, "group": items[qid]["group"]}
            for p in ("single", "multi"):               # 질문마다 번갈아 실행
                row[p] = await run_once(graphs[p], q)
            results.append(row)
            print(f"[{qid:>2}] {q[:30]:<30} single {row['single']['seconds']:>6}s "
                  f"| multi {row['multi']['seconds']:>6}s | runbook {row['single']['runbook']}/{row['multi']['runbook']}",
                  flush=True)
    finally:
        await mcp.stop()

    out = ROOT / "eval" / f"results_e2e_{backend}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    inc = [r for r in results if r["id"] not in (18, 21)]      # 장애 질문(조사·매뉴얼 경로)만 집계
    print(f"\n## {backend} — 장애 질문 {len(inc)}개 (질문당 1회 측정)")
    print("| 지표 | single | multi |")
    print("|---|---|---|")
    for label, key, fmt in (("평균 전체 응답 시간(초)", "seconds", "{:.1f}"),
                            ("중앙값 응답 시간(초)", None, "{:.1f}"),
                            ("평균 retry 횟수", "retry_count", "{:.2f}"),
                            ("평균 replan 횟수", "replan_rounds", "{:.2f}"),
                            ("평균 검수 시도 횟수", "validation_attempts", "{:.2f}"),
                            ("평균 추정 비용 cost_usd (추정치)", "cost_usd_est", "{:.5f}")):
        cells = []
        for p in ("single", "multi"):
            vals = [r[p][key or "seconds"] for r in inc]
            cells.append(fmt.format(statistics.median(vals) if key is None else statistics.mean(vals)))
        print(f"| {label} | {cells[0]} | {cells[1]} |")
    print(f"| 로그를 수집한 질문 수 | {sum(r['single']['log_collected'] for r in inc)}/{len(inc)} "
          f"| {sum(r['multi']['log_collected'] for r in inc)}/{len(inc)} |")
    diff = [r["id"] for r in inc if r["single"]["runbook"] != r["multi"]["runbook"]]
    print(f"\n두 방식이 서로 다른 매뉴얼을 고른 질문: {diff or '없음'}")
    for qid in (18, 21):
        r = next(x for x in results if x["id"] == qid)
        print(f"#{qid} {r['query'][:24]} → single {r['single']['seconds']}s / multi {r['multi']['seconds']}s "
              f"(route={r['single']['route']})")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("ollama", "openai"):
        sys.exit("사용법: .venv/bin/python eval/compare_e2e.py [ollama|openai]")
    asyncio.run(main(sys.argv[1]))
