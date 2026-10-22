"""eval/decision_eval.py — 조사 총괄의 판단(어떤 에이전트를 부를지)이 맞는지 평가한다.

질문 두 묶음으로 fast 모델의 decide_agents를 호출해 본다.
  현황 질문 (eval/status_queries.json, 8개): 사람이 보기에 '수치만 보면 되는' 질문 → 기대: metrics만
  장애 질문 (eval/queries.json 중 조사 경로를 타는 21개)                          → 기대: metrics + log + runbook 전부
답변 작성이나 MCP 호출은 하지 않고 판단만 보므로 몇 초~1분이면 끝난다.

실행:  .venv/bin/python eval/decision_eval.py ollama     # qwen3:0.6b (무료)
       .venv/bin/python eval/decision_eval.py openai     # gpt-4o-mini (과금, 센트 미만)
주의: 현황 질문 8개는 이 평가를 위해 새로 쓴 소표본이다. '기대'는 사람(작성자)이 정했다.
"""
import json
import os
import sys
import time
from pathlib import Path

os.environ["LANGCHAIN_TRACING_V2"] = "false"
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
from dotenv import load_dotenv      # noqa: E402
load_dotenv(ROOT / ".env")
os.environ["LANGCHAIN_TRACING_V2"] = "false"

from agent.agents.decision import rule_decide   # noqa: E402


def make_fast(backend: str):
    if backend == "ollama":
        from agent.ollama_llm import OllamaFastLLM
        return OllamaFastLLM("qwen3:0.6b", usd_per_1k_tokens=0.00015)
    from agent.openai_llm import OpenAIFastLLM
    return OpenAIFastLLM("gpt-4o-mini", usd_per_1k_tokens=0.00015)


def main(backend: str) -> None:
    status = json.loads((ROOT / "eval" / "status_queries.json").read_text(encoding="utf-8"))
    trouble = [q for q in json.loads((ROOT / "eval" / "queries.json").read_text(encoding="utf-8"))
               if q["id"] not in (18, 19) and "none" not in q["expect"] and "chat" not in q["expect"]]
    fast = make_fast(backend)
    fast.decide_agents("워밍업")      # 모델을 메모리에 올리는 첫 호출 시간이 결과에 섞이지 않게

    rows = []
    for kind, items in (("status", status), ("trouble", trouble)):
        for q in items:
            t = time.perf_counter()
            decision, _ = fast.decide_agents(q["query"])
            rows.append({"kind": kind, "id": q["id"], "query": q["query"], "agents": decision["agents"],
                         "source": decision["source"], "reason": decision["reason"],
                         "ms": round((time.perf_counter() - t) * 1000)})
            print(f"[{kind[:3]} {q['id']:>3}] {q['query'][:30]:<30} -> {decision['agents']} ({decision['source']}, {rows[-1]['ms']}ms)", flush=True)
    (ROOT / "eval" / f"results_decision_{backend}.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    st = [r for r in rows if r["kind"] == "status"]
    tr = [r for r in rows if r["kind"] == "trouble"]
    st_ok = sum(r["agents"] == ["metrics"] for r in st)
    tr_all = sum(r["agents"] == ["metrics", "log", "runbook"] for r in tr)
    tr_log = sum("log" in r["agents"] for r in tr)
    rule_st = sum(rule_decide(r["query"])["agents"] == ["metrics"] for r in st)
    rule_tr = sum(rule_decide(r["query"])["agents"] == ["metrics", "log", "runbook"] for r in tr)
    print(f"\n## 조사 총괄 판단 평가 — {backend} (fast 모델, 질문당 1회)")
    print("| 지표 | AI 판단 | 코드 규칙만(참고) |")
    print("|---|---|---|")
    print(f"| 현황 질문에서 metrics만 고름 | {st_ok}/{len(st)} | {rule_st}/{len(st)} |")
    print(f"| 장애 질문에서 세 에이전트 모두 고름 | {tr_all}/{len(tr)} | {rule_tr}/{len(tr)} |")
    print(f"| 장애 질문에서 log 포함 | {tr_log}/{len(tr)} | - |")
    print(f"| 장애 질문에서 runbook 포함(코드가 보장) | {sum('runbook' in r['agents'] for r in tr)}/{len(tr)} | - |")
    print(f"| 형식 오류로 규칙으로 대체된 횟수 | {sum(r['source'] == 'fallback' for r in rows)}/{len(rows)} | - |")
    print(f"| 판단 1회 평균 지연 | {sum(r['ms'] for r in rows) / len(rows):.0f}ms | 0ms |")
    print("\n현황 질문인데 metrics만 고르지 않은 것:", [(r["id"], r["agents"]) for r in st if r["agents"] != ["metrics"]] or "없음")
    print("장애 질문인데 log를 뺀 것:", [(r["id"], r["agents"]) for r in tr if "log" not in r["agents"]] or "없음")


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in ("ollama", "openai"):
        sys.exit("사용법: .venv/bin/python eval/decision_eval.py [ollama|openai]")
    main(sys.argv[1])
