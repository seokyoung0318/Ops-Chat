"""eval/run_eval.py — 개선 전/후 비교 평가 (미니프로젝트에서 새로 추가한 파일).

질문 세트(eval/queries.json)를 실제 그래프 노드로 돌려, '어떤 runbook(장애유형)을 골랐는가'를
세 방식으로 비교한다.
    rules       : 기존 키워드 규칙 (Before)
    rag_query   : RAG, 검색 입력 = 질문만
    rag_alerts  : RAG, 검색 입력 = 질문 + 조회된 알림
    rag_auto    : RAG, 질문에 아는 시스템이 명시된 경우에만 질문 + 그 시스템 알림, 아니면 질문만

route → plan → gate → research 는 질문당 한 번만 실행하고(세 방식이 공유), replan_check_node만
방식을 바꿔 세 번 실행한다. 답변 작성(qwen3:8b)과 검수는 건너뛰므로 질문당 수 초면 끝난다.
RAG 임계값은 0으로 두고 1위 점수를 기록한 뒤, 임계값별 정확도를 사후에 계산한다.

실행:  .venv/bin/python eval/run_eval.py                       # 튜닝에 쓴 23문항(eval/queries.json)
       .venv/bin/python eval/run_eval.py eval/queries_heldout.json   # 설계 후 새로 쓴 검증용 질문(과적합 확인)
"""
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from agent import graph                                  # noqa: E402
from agent.nodes import replan                           # noqa: E402
from agent.deps import SupervisorDeps                    # noqa: E402
from agent.mcp_client import MCPClient                   # noqa: E402
from agent.ollama_llm import OllamaFastLLM               # noqa: E402
from agent.rag import OllamaEmbedder, RunbookRetriever   # noqa: E402

RAG_MODES = ["rag_query", "rag_alerts", "rag_auto"]
MODES = ["rules"] + RAG_MODES
RAG_INPUT_OF = {"rules": "query+alerts", "rag_query": "query",
                "rag_alerts": "query+alerts", "rag_auto": "auto"}
THRESHOLDS = [0.50, 0.55, 0.60, 0.65, 0.70]


async def run_query(item: dict, deps_rules, deps_rag) -> dict:
    q = item["query"]
    state = {"query": q, "thread_id": f"eval-{item['id']}", "history": [],
             "events": [], "cost_usd": 0.0}
    state.update(await graph.route_node(state, deps=deps_rules))
    path = graph._after_route(state)
    if path != "plan":   # chat 이거나 unknown_system — 모든 방식이 동일하게 이 경로로 감
        label = "chat" if path == "chat_answer" else path
        return {"path": label, "modes": {m: {"target": label, "score": None, "select_ms": 0.0}
                                         for m in MODES}}
    state.update(await graph.plan_node(state, deps=deps_rules))
    state.update(await graph.gate_node(state, deps=deps_rules))
    state.update(await graph.research_node(state, deps=deps_rules))
    systems = [t["target"] for t in state["tasks"] if t["agent"] == "research"]

    modes = {}
    for m in MODES:
        replan.RAG_INPUT = RAG_INPUT_OF[m]
        deps = deps_rules if m == "rules" else deps_rag
        out = await graph.replan_check_node(dict(state), deps=deps)
        ev = out["events"][-1]
        modes[m] = {"target": ev.get("target"), "score": ev.get("score"),
                    "select_ms": ev.get("select_ms", 0.0)}
    return {"path": "plan", "systems": systems, "modes": modes}


def predict(mode: str, res: dict, t: float) -> str:
    """임계값 t를 적용한 최종 예측. rules는 임계값과 무관."""
    r = res["modes"][mode]
    if res["path"] != "plan" or mode == "rules":
        return r["target"]
    return r["target"] if (r["score"] or 0) >= t else "none"


async def main() -> None:
    qpath = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "eval" / "queries.json"
    items = json.loads(qpath.read_text(encoding="utf-8"))
    mcp = MCPClient()
    await mcp.start()
    fast = OllamaFastLLM(os.environ.get("OLLAMA_FAST_MODEL", "qwen3:0.6b"), usd_per_1k_tokens=0.00015)
    retriever = RunbookRetriever(OllamaEmbedder("bge-m3"), threshold=0.0)
    await retriever.build()
    deps_rules = SupervisorDeps(fast_llm=fast, quality_llm=None, mcp=mcp, session_store=None,
                                version="v2", retriever=None)
    deps_rag = SupervisorDeps(fast_llm=fast, quality_llm=None, mcp=mcp, session_store=None,
                              version="v2", retriever=retriever)
    results = []
    started = time.perf_counter()
    for item in items:
        try:
            res = await run_query(item, deps_rules, deps_rag)
        except Exception as e:   # 한 질문이 실패해도 나머지는 계속
            res = {"path": "error", "error": repr(e),
                   "modes": {m: {"target": "error", "score": None, "select_ms": 0.0} for m in MODES}}
        results.append({**item, **res})
        print(f"[{item['id']:>2}] {item['query'][:34]:<34} -> "
              + " | ".join(f"{m}={res['modes'][m]['target']}" for m in MODES), flush=True)
    await mcp.stop()
    elapsed = round(time.perf_counter() - started, 1)

    out_name = "results.json" if qpath.name == "queries.json" else f"results_{qpath.stem}.json"
    (ROOT / "eval" / out_name).write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    def correct(mode, r, t):
        return predict(mode, r, t) in r["expect"]

    print(f"\n총 {len(results)}문항, 소요 {elapsed}s\n")
    print("## 질문별 결과 (임계값 0.5 기준, 점수 병기)")
    print("| # | 질문 | 정답(허용) | " + " | ".join(MODES) + " |")
    print("|---|---|---|" + "---|" * len(MODES))
    for r in results:
        cells = []
        for m in MODES:
            p = predict(m, r, 0.5)
            sc = r["modes"][m]["score"]
            mark = "✅" if p in r["expect"] else "❌"
            cells.append(f"{mark} {p}" + (f" ({sc})" if sc is not None and m != "rules" else ""))
        print(f"| {r['id']} | {r['query'][:30]} | {'/'.join(r['expect'])} | " + " | ".join(cells) + " |")

    print("\n## 방식별 정확도 (임계값 0.5)")
    print("| 방식 | 정답 수 | 정확도 | 평균 select_ms |")
    print("|---|---|---|---|")
    for m in MODES:
        n = sum(correct(m, r, 0.5) for r in results)
        ms = [r["modes"][m]["select_ms"] for r in results if r["path"] == "plan"]
        print(f"| {m} | {n}/{len(results)} | {n / len(results):.0%} | {statistics.mean(ms) if ms else 0:.1f} |")

    print("\n## 그룹별 정확도 (임계값 0.5)")
    groups = list(dict.fromkeys(r["group"] for r in results))
    print("| 그룹 | 문항 | " + " | ".join(MODES) + " |")
    print("|---|---|" + "---|" * len(MODES))
    for g in groups:
        rs = [r for r in results if r["group"] == g]
        print(f"| {g} | {len(rs)} | " + " | ".join(
            f"{sum(correct(m, r, 0.5) for r in rs)}/{len(rs)}" for m in MODES) + " |")

    print("\n## 임계값별 정확도 (RAG, 정답 수 / 전체)")
    print("| 임계값 | " + " | ".join(RAG_MODES) + " |")
    print("|---|" + "---|" * len(RAG_MODES))
    for t in THRESHOLDS:
        print(f"| {t:.2f} | " + " | ".join(
            f"{sum(correct(m, r, t) for r in results)}/{len(results)}" for m in RAG_MODES) + " |")

    print("\n## 방식별 1위 점수 분포와 오답")
    for m in RAG_MODES:
        ok = [r["modes"][m]["score"] for r in results
              if r["path"] == "plan" and r["modes"][m]["target"] in r["expect"]]
        oos = [r["modes"][m]["score"] for r in results
               if r["path"] == "plan" and "none" in r["expect"]]
        wrong = [(r["id"], r["modes"][m]["target"], r["modes"][m]["score"]) for r in results
                 if r["path"] == "plan" and r["modes"][m]["target"] not in r["expect"]]
        print(f"[{m}] 정답 일치 질문 1위 점수 최소 {min(ok) if ok else '-'} / 평균 "
              f"{round(statistics.mean(ok), 3) if ok else '-'} | 범위 밖 질문 1위 점수 {oos} | 오답 {wrong}")
    nroute = [r["id"] for r in results if r["path"] == "chat" and "chat" not in r["expect"]]
    print(f"route가 chat으로 보낸(장애 질문인데) 질문: {nroute}")

if __name__ == "__main__":
    asyncio.run(main())
